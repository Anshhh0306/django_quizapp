"""Tells the owner of an account that someone has just been locked out of it for guessing its password."""
import threading

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .ratelimit import LOGIN_FREE_TRIES, key_part

ALERT_EVERY = 60 * 60  # at most one alert an hour per account, so this cannot be used to flood someone's inbox


def _send(subject, body, to):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
    except OSError:  # a mail problem must never change what the person typing sees
        pass


def mail_later(subject, body, to):
    """Send from a background thread (a page must not wait for the mail server), or straight away under test.
    The thread only sends; it never touches the database."""
    if settings.LOCK_ALERT_BACKGROUND:
        threading.Thread(target=_send, args=(subject, body, to), daemon=True).start()
    else:
        _send(subject, body, to)


def alert_owner(request, username, seconds):
    """Email the owner when the lock starts. Silent for a name that is not an active account, and sent in a
    background thread: waiting for the mail server would make the 5th wrong password slower for real accounts than for
    made-up ones, which would reveal which IDs exist. (Only the thread sends; it never touches the database.)"""
    name = (username or '').strip().lower()[:150]
    if not name or not cache.add(f'lf:alert:{key_part(name)}', 1, ALERT_EVERY):
        return
    user = User.objects.filter(username__iexact=name, is_active=True).exclude(email='').first()
    if user is None:
        return
    body = render_to_string('quiz/email/lock_alert_email.txt', {
        'user': user, 'tries': LOGIN_FREE_TRIES, 'minutes': seconds // 60, 'when': timezone.localtime(),
        'reset_url': request.build_absolute_uri(reverse('password_reset')),
    })
    mail_later('Wrong password attempts on your SRMIST Quiz account', body, user.email)
