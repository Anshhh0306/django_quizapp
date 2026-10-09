from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from .forms import RegisterForm, pending_account
from .ratelimit import claim_send, login_succeeded, rate_limit, release_send
from .two_factor import mark_browser_known
from .exam_results import my_exam_cards
from .roles import is_student, role_of
from django.contrib.auth.forms import SetPasswordForm
from django.db import IntegrityError, transaction

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.urls import reverse
from .tokens import email_verification_token
from django.conf import settings

def _send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    verification_url = request.build_absolute_uri(reverse('verify_email', args=[uid, token]))
    message = render_to_string('quiz/email/verification_email.txt', {
        'user': user,
        'verification_url': verification_url,
        'is_staff_account': not is_student(user),
    })
    send_mail(
        'Verify your SRMIST email address',
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )

def _try_send_verification(request, user):
    """True if the email went out. A mail-server problem must not turn into a crash page."""
    try:
        _send_verification_email(request, user)
        return True
    except OSError:  # smtplib.SMTPException is an OSError too
        return False

def _try_send_already_registered(request, email):
    """The address already has an account: tell its owner by email, so the page itself never says which addresses do."""
    message = render_to_string('quiz/email/already_registered_email.txt', {
        'login_url': request.build_absolute_uri(reverse('login')),
        'reset_url': request.build_absolute_uri(reverse('password_reset')),
    })
    try:
        send_mail('Your SRMIST Quiz Platform account', message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
        return True
    except OSError:
        return False

# ponytail: 1000 an hour per address is far above one class; the real ceiling is the mail provider's daily limit.
# A few an hour per MAILBOX (the second number) is what stops one inbox being flooded. It is not tight: a first email often
# lands in Junk, so people press "send again" a few times before they look there.
@rate_limit('register', 1000, 3600, field='email', field_limit=5, repeat='verify')
def register(request):
    """New address: make the account and email the verification link. Address that already has an account: email its
    owner instead. Either way the person sees the same page, so this form cannot be used to find out who has an account.
    The button pressed again inside a minute (a double click, a nervous student) shows the same page and sends nothing more."""
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            email, user = form.cleaned_data['email'], None
            if not claim_send('verify', email):
                return render(request, 'quiz/verification_sent.html', {'email': email})
            if not form.taken:
                try:
                    with transaction.atomic():
                        user = form.save()
                except IntegrityError:  # two people registered the same address at the same moment: the second is "taken"
                    pass
            sent = _try_send_verification(request, user) if user else _try_send_already_registered(request, email)
            if sent:
                return render(request, 'quiz/verification_sent.html', {'email': email})
            release_send('verify', email)  # nothing went out: the next press must really try again
            form.add_error('email', 'We could not send the email right now. Please try again in a few minutes.')
    else:
        form = RegisterForm()
    return render(request, 'quiz/register.html', {'form': form})

def _pending_user(uidb64, token):
    """The account this link belongs to, if it is still waiting for its first password. Anything else (already
    active, or an account a superadmin deactivated, which has a password) can never be activated by a link."""
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None
    if user.is_active or user.has_usable_password():
        return None
    return user if email_verification_token.check_token(user, token) else None

def verify_email(request, uidb64, token):
    """The emailed link proves the inbox is theirs; this page is where they choose their password."""
    user = _pending_user(uidb64, token)
    if user is None:
        return render(request, 'quiz/verification_failed.html')
    form = SetPasswordForm(user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user.is_active = True
        form.save()  # sets the password and saves the account
        response = render(request, 'quiz/verification_success.html', {'pending_teacher': not is_student(user)})
        mark_browser_known(response, user)  # the browser where the password was chosen is not a "new browser" later
        return response
    return render(request, 'quiz/verification_set_password.html', {'form': form})

@rate_limit('resend', 1000, 3600, field='email', field_limit=8, repeat='verify')
def resend_verification(request):
    """Same page for every address, so this cannot be used to find out which ones are waiting for their link.
    The page says "just sent it again" (hedged: only if that address was waiting), because with no sign that the click did
    anything people press the button again and again. Pressed again inside a minute of any verification email to that
    address (this form's or the registration's), it sends nothing more and uses none of the hourly limit."""
    email = request.POST.get('email', '').strip() if request.method == 'POST' else ''
    if not email:
        return redirect('register')
    if claim_send('verify', email):  # claimed for ANY address, waiting or not, so the page and the limits behave the same for all
        user = pending_account(email)
        if user and not _try_send_verification(request, user):  # a mail problem is not shown: the page says "resend" again anyway
            release_send('verify', email)
    return render(request, 'quiz/verification_sent.html', {'email': email, 'again': True})

def home(request):
    context = {}
    if request.user.is_authenticated:
        context['role'] = role_of(request.user)
    if context.get('role') == 'student':
        context['my_exams'] = my_exam_cards(request.user)
    return render(request, 'quiz/home.html', context)

@login_required
def user_profile(request):
    return render(request, 'quiz/user_profile.html')

# Custom Password Reset Views using SRMIST verification
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator

@rate_limit('pwreset', 1000, 3600, field='email', field_limit=8, repeat='pwreset')
def custom_password_reset(request):
    """Sends a reset link to verified SRMIST accounts. The page shown is identical whether or not an email was
    sent, so it cannot be used to find out which addresses have accounts."""
    if request.method == 'POST':
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            # claimed for ANY address, with an account or not (so nothing here tells them apart); pressed again within a minute: one link is enough
            claimed = claim_send('pwreset', email)
            user = User.objects.filter(email__iexact=email, is_active=True).first() if claimed else None
            if user and user.email.lower().endswith('@srmist.edu.in'):
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_url = request.build_absolute_uri(reverse('password_reset_confirm', args=[uid, token]))
                message = render_to_string('quiz/email/password_reset_email.txt', {
                    'user': user,
                    'reset_url': reset_url,
                    'site_name': 'SRMIST Quiz Platform',
                })
                try:
                    send_mail('Password Reset - SRMIST Quiz Platform', message, settings.DEFAULT_FROM_EMAIL,
                              [user.email], fail_silently=False)
                except OSError:
                    release_send('pwreset', email)  # same page either way; the next press tries again
            return render(request, 'quiz/password_reset_done.html', {'email': email})
    else:
        form = PasswordResetForm()
    return render(request, 'quiz/password_reset.html', {'form': form})

def custom_password_reset_confirm(request, uidb64, token):
    """Custom password reset confirm using our verification token"""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and user.is_active and default_token_generator.check_token(user, token):
        # Valid token, show password reset form
        if request.method == 'POST':
            from django.contrib.auth.forms import SetPasswordForm
            form = SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                login_succeeded(user.username, None)  # the inbox owner proved themselves: any login lock ends
                return redirect('password_reset_complete')
        else:
            from django.contrib.auth.forms import SetPasswordForm
            form = SetPasswordForm(user)
        
        return render(request, 'quiz/password_reset_confirm.html', {
            'form': form,
            'validlink': True
        })
    else:
        # Invalid token
        return render(request, 'quiz/password_reset_confirm.html', {
            'validlink': False
        })

def password_reset_complete(request):
    """Password reset complete view"""
    return render(request, 'quiz/password_reset_complete.html')
