"""Two-factor sign-in: a 6-digit code from an authenticator app, with recovery codes (django-otp underneath).

Every way of signing in (the login page, /admin/login/) ends the same way: the password makes an ordinary session,
and TwoFactorGateMiddleware (quiz/middleware.py) then keeps every page shut except the ones here until the code is
accepted. Teachers and the superadmin must have it (settings.TWO_FACTOR_REQUIRED_ROLES); anyone else may turn it on.
Wrong codes slow themselves down (2, 4, 8, ... seconds), and a code can be used only once."""
from base64 import b32encode
from datetime import timedelta
from math import ceil

import segno
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from .exam_device import describe_device, log_event
from .lock_alert import mail_later
from .models import Exam, ExamAttempt
from .roles import role_of

RECOVERY_CODES = 10
EXEMPT_PREFIXES = ('/2fa/', '/accounts/logout/', '/static/')  # reachable while signed in but not yet verified
TRUST_COOKIE = 'trusted_{}'  # "remember this browser": per account, so a shared computer can remember several people
KNOWN_COOKIE = 'kb_{}'       # "this account has used this browser before": the new-browser email is for the others
KNOWN_DAYS = 365
# django-otp doubles the wait after every wrong code and caps it at 100 YEARS, so whoever knows a password (or one
# clumsy person) could keep the owner out of the code step for days, and a restart does not undo it (it is in the
# database). After this long without a wrong try the count starts again: nobody is held out longer than this, and a
# guesser still gets only about a thousand tries a day against a million possible codes.
FORGET_WRONG_CODES_AFTER = timedelta(minutes=15)


# ---- who needs what ----

def required_for(user):
    return bool(settings.TWO_FACTOR_REQUIRED_ROLES) and role_of(user) in settings.TWO_FACTOR_REQUIRED_ROLES


def totp_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


def pending_step(request):
    """What a signed-in, not yet verified person must do before anything else: 'verify' (they have an authenticator),
    'setup' (their role requires one and they have none), or None (nothing: students who never turned it on)."""
    user = request.user
    device = totp_device(user)
    if device is None:
        return 'setup' if required_for(user) else None
    if is_trusted(request, user, device):
        otp_login(request, device)
        return None
    return 'verify'


# ---- remembered browsers ----
# The cookie is signed with a salt made from the account's password hash and its authenticator, so a password reset
# or a reset/new authenticator makes every remembered browser forget at once.

def _trust_signer(user, device):
    return signing.TimestampSigner(salt=f'trusted-browser:{user.get_session_auth_hash()}:{device.pk}')


def is_trusted(request, user, device):
    value = request.COOKIES.get(TRUST_COOKIE.format(user.pk))
    if not value:
        return False
    try:
        return _trust_signer(user, device).unsign(value, max_age=settings.TRUSTED_BROWSER_DAYS * 86400) == str(user.pk)
    except signing.BadSignature:  # tampered, someone else's, or too old
        return False


def _cookie(response, name, value, days):
    response.set_cookie(name, value, max_age=days * 86400, httponly=True, samesite='Lax', secure=not settings.DEBUG)


def trust_browser(response, user, device):
    _cookie(response, TRUST_COOKIE.format(user.pk), _trust_signer(user, device).sign(str(user.pk)),
            settings.TRUSTED_BROWSER_DAYS)


# ---- the new-browser email ----

def _known(request, user):
    try:
        return signing.Signer(salt='known-browser').unsign(request.COOKIES.get(KNOWN_COOKIE.format(user.pk), '')) == str(user.pk)
    except signing.BadSignature:
        return False


def mark_browser_known(response, user):
    _cookie(response, KNOWN_COOKIE.format(user.pk), signing.Signer(salt='known-browser').sign(str(user.pk)), KNOWN_DAYS)


def note_browser(request, response):
    """Runs for a fully signed-in person on every page: a browser this account has not used before is marked, and the
    owner gets ONE email about it (at most one an hour per account). The browser where the password was chosen counts
    as known. It tells; it cannot stop anything, and if the password reset it recommends is used, the other browser is
    signed out too (Django ends every session when the password changes)."""
    user = request.user  # the view may have signed them out (logout): then there is no one to tell
    if not user.is_authenticated or not settings.NEW_BROWSER_ALERTS or _known(request, user):
        return
    mark_browser_known(response, user)
    if user.email and cache.add(f'nb:{user.pk}', 1, 3600):
        mail_later('New sign-in to your SRMIST Quiz account', (
            f'Hello {user.username},\n\nYour account was just used from a browser it has not been used from before:\n\n'
            f'  Browser: {describe_device(request.META.get("HTTP_USER_AGENT", ""))}\n'
            f'  Address: {request.META.get("REMOTE_ADDR") or "unknown"}\n'
            f'  Time: {timezone.localtime():%d %b %Y, %H:%M} IST\n\n'
            'If that was you, there is nothing to do.\n\n'
            'If it was NOT you, reset your password now. That also signs the other browser out:\n'
            f'{request.build_absolute_uri(reverse("password_reset"))}\n\n'
            'Best regards,\nQuiz Platform Team\n'), user.email)


# ---- the code itself ----

def _forgive_old_failures(device):
    stamp = device.throttling_failure_timestamp
    if device.throttling_failure_count and stamp and timezone.now() - stamp > FORGET_WRONG_CODES_AFTER:
        device.throttle_reset()


def _wait_message(device):
    allowed, data = device.verify_is_allowed()
    if allowed:
        return ''
    until = min(data['locked_until'], device.throttling_failure_timestamp + FORGET_WRONG_CODES_AFTER) if data.get('locked_until') else None
    seconds = max(1, ceil((until - timezone.now()).total_seconds())) if until else 30
    when = f'{seconds} seconds' if seconds <= 120 else f'{ceil(seconds / 60)} minutes'
    return f'Too many wrong codes. Wait {when} and try again.'


def _try(device, code):
    """(True, '') if this device accepts the code, else (False, why). The caller holds a row lock (select_for_update)."""
    _forgive_old_failures(device)
    wait = _wait_message(device)
    if wait:
        return False, wait
    if device.verify_token(code):
        return True, ''
    return False, 'That code was not accepted. Check the clock on your phone and try again.'


def check_code(user, raw):
    """(the device that accepted it, '') or (None, why not). Six digits are tried on the authenticator, anything else
    as a recovery code (each works once, letters in any case, dashes and spaces ignored)."""
    code = ''.join(raw.split()).replace('-', '').lower()
    if not code:
        return None, 'Enter the code.'
    with transaction.atomic():
        authenticator = TOTPDevice.objects.select_for_update().filter(user=user, confirmed=True).first()
        if authenticator is None:
            return None, 'That code was not accepted.'
        if code.isdigit() and len(code) == authenticator.digits:
            device = authenticator
        else:
            device = StaticDevice.objects.select_for_update().filter(user=user).first()
            if device is None:
                return None, 'That code was not accepted. Check the clock on your phone and try again.'
        ok, message = _try(device, code)
    return (device, '') if ok else (None, message)


def new_recovery_codes(user):
    """Replace the person's recovery codes with 10 fresh ones and return them. They are shown once, on the page that
    follows; the old ones stop working."""
    device = StaticDevice.objects.get_or_create(user=user, defaults={'name': 'recovery'})[0]
    device.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(RECOVERY_CODES)]
    StaticToken.objects.bulk_create([StaticToken(device=device, token=c) for c in codes])
    return [f'{c[:4]}-{c[4:]}' for c in codes]


def _next(request):
    target = request.POST.get('next') or request.GET.get('next') or ''
    safe = url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return target if safe and not target.startswith(('/2fa/verify/', '/2fa/setup/')) else reverse('home')


def _say(user, subject, text):
    if user and user.email:
        mail_later(subject, f'Hello {user.username},\n\n{text}\n\nBest regards,\nQuiz Platform Team\n', user.email)


# ---- pages ----

@never_cache
@login_required
def verify(request):
    user = request.user
    if user.is_verified():
        return redirect(_next(request))
    authenticator = totp_device(user)
    if authenticator is None:  # nothing to verify: set one up if the role needs it
        return redirect('two_factor_setup' if required_for(user) else 'home')
    error = ''
    if request.method == 'POST':
        device, error = check_code(user, request.POST.get('code', ''))
        if device is not None:
            otp_login(request, device)
            request.session.cycle_key()  # a new session key now that the person is more trusted
            used_recovery_code = isinstance(device, StaticDevice)
            response = redirect(reverse('two_factor') if used_recovery_code else _next(request))
            if request.POST.get('remember'):
                trust_browser(response, user, authenticator)
            if used_recovery_code:
                _say(user, 'A recovery code was used on your SRMIST Quiz account',
                     f'A recovery code was just used to sign in at {timezone.localtime():%H:%M} IST. Each code works once. '
                     'If that was not you, reset your password and tell your administrator.')
            return response
    return render(request, 'quiz/two_factor/verify.html', {
        'error': error, 'next': _next(request), 'days': settings.TRUSTED_BROWSER_DAYS})


@never_cache
@login_required
def setup(request):
    user = request.user
    if totp_device(user):
        return redirect('two_factor')
    device = (TOTPDevice.objects.filter(user=user, confirmed=False).first()
              or TOTPDevice.objects.create(user=user, name='authenticator', confirmed=False))
    error = ''
    if request.method == 'POST':
        with transaction.atomic():
            locked = TOTPDevice.objects.select_for_update().get(pk=device.pk)
            ok, error = _try(locked, ''.join(request.POST.get('code', '').split()))
            if ok:
                locked.confirmed = True
                locked.save(update_fields=['confirmed'])
        if ok:
            otp_login(request, locked)
            request.session.cycle_key()
            _say(user, 'Two-factor sign-in was turned on', 'Two-factor sign-in was just turned on for your account. '
                 'From now on signing in needs a code from your authenticator app. If that was not you, reset your password '
                 'and tell your administrator.')
            return render(request, 'quiz/two_factor/recovery_codes.html', {
                'codes': new_recovery_codes(user), 'next': _next(request), 'first_time': True})
    key = b32encode(device.bin_key).decode()
    return render(request, 'quiz/two_factor/setup.html', {
        'error': error, 'next': _next(request), 'required': required_for(user),
        'qr': segno.make(device.config_url, error='m').svg_data_uri(scale=5, border=2),
        'key': ' '.join(key[i:i + 4] for i in range(0, len(key), 4))})


@never_cache
@login_required
def manage(request):
    user = request.user
    enabled = totp_device(user) is not None
    if enabled and not user.is_verified():
        return redirect(f'{reverse("two_factor_verify")}?next={reverse("two_factor")}')
    return render(request, 'quiz/two_factor/manage.html', {
        'enabled': enabled, 'required': required_for(user),
        'codes_left': StaticToken.objects.filter(device__user=user).count(), 'error': request.GET.get('error', '')})


@never_cache
@login_required
@require_POST
def new_codes(request):
    if not request.user.is_verified():
        return redirect('two_factor')
    _say(request.user, 'New recovery codes on your SRMIST Quiz account',
         'A new set of recovery codes was just created for your account; the old ones no longer work.')
    return render(request, 'quiz/two_factor/recovery_codes.html', {
        'codes': new_recovery_codes(request.user), 'next': reverse('two_factor'), 'first_time': False})


@never_cache
@login_required
@require_POST
def turn_off(request):
    """For people whose role does not require it: needs the password again, and the person is told by email."""
    user = request.user
    if not user.is_verified() or required_for(user):
        return redirect('two_factor')
    if not user.check_password(request.POST.get('password', '')):
        return redirect(f'{reverse("two_factor")}?error=password')
    for device in TOTPDevice.objects.filter(user=user):
        device.delete()  # one by one: that is what emails the owner and removes the recovery codes
    return redirect('two_factor')


# ---- signals ----

@receiver(post_delete, sender=TOTPDevice)
def _turned_off(sender, instance, **kwargs):
    """However the authenticator disappears (turned off by the owner, reset in the admin site or by the command),
    the recovery codes go with it and the owner is told."""
    if not instance.confirmed:
        return
    StaticDevice.objects.filter(user_id=instance.user_id).delete()
    _say(User.objects.filter(pk=instance.user_id).first(), 'Two-factor sign-in was turned off',
         f'Two-factor sign-in was just turned off or reset on your account at {timezone.localtime():%H:%M} IST. '
         'If you did not ask for that, reset your password and tell your administrator.')


@receiver(user_logged_in)
def _login_during_exam(sender, request, user, **kwargs):
    """The teacher's log says when a student account signed in while that student's exam was running (the password was
    accepted: the second step may not have happened). Evidence only; nothing is punished, because a sign-in can be
    someone else's doing. A sign-in made without a real request has no address, and is not logged."""
    address = request.META.get('REMOTE_ADDR') if request is not None else None
    if not address:
        return
    attempts = ExamAttempt.objects.filter(user=user, started_at__isnull=False, submitted_at__isnull=True,
                                          exam__status=Exam.RUNNING).select_related('exam')
    for attempt in attempts:
        log_event(attempt.exam, 'login', f'{user.username} signed in again (password accepted) from '
                  f'{describe_device(request.META.get("HTTP_USER_AGENT", ""))}, address {address}', attempt)
