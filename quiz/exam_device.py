"""One browser per student per exam. A second browser is turned away, or freezes the seat, depending on whether
the student's own browser is still working."""
import re
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import ExamAttempt, ExamEvent

COOKIE = 'exam_device'
ACTIVE_SECONDS = 30   # the locked browser checks in every ~8 seconds; this long without a check-in counts as silent
TOUCH_SECONDS = 5     # don't write "still here" to the database more often than this
_VALID_ID = re.compile(r'^[A-Za-z0-9_-]{16,64}$')


def new_device_id():
    return secrets.token_urlsafe(16)


def valid_device_id(value):
    return bool(value and _VALID_ID.match(value))


def describe_device(user_agent):
    """'Chrome on Windows' from a user-agent string. Good enough for a teacher to tell two devices apart."""
    ua = user_agent or ''
    browser = ('Edge' if 'Edg/' in ua else 'Opera' if 'OPR/' in ua else 'Firefox' if 'Firefox/' in ua
               else 'Chrome' if ('Chrome/' in ua or 'CriOS' in ua) else 'Safari' if 'Safari/' in ua
               else 'Unknown browser')
    system = ('iPhone/iPad' if re.search(r'iPhone|iPad', ua) else 'Android' if 'Android' in ua
              else 'Windows' if 'Windows' in ua else 'Mac' if 'Mac OS' in ua else 'Linux' if 'Linux' in ua
              else 'unknown system')
    return f'{browser} on {system}'


def log_event(exam, kind, detail='', attempt=None, actor=None):
    ExamEvent.objects.create(exam=exam, attempt=attempt, actor=actor, kind=kind, detail=detail[:300])


def _here(request):
    return (request.device_id, describe_device(request.META.get('HTTP_USER_AGENT', '')),
            request.META.get('REMOTE_ADDR') or None)


def bind_device(request, attempt, now=None):
    """Lock the attempt to this browser. Before the exam starts the newest browser simply wins
    (students often move from a phone to a laptop while waiting in the lobby)."""
    now = now or timezone.now()
    attempt.device_id, attempt.device_label, attempt.device_ip = _here(request)
    attempt.device_seen_at = now
    ExamAttempt.objects.filter(pk=attempt.pk).update(
        device_id=attempt.device_id, device_label=attempt.device_label, device_ip=attempt.device_ip,
        device_seen_at=now)


def _touch(attempt, now):
    """The locked browser is alive. Written at most every few seconds, so the database isn't hit on every request."""
    if not attempt.device_seen_at or now - attempt.device_seen_at > timedelta(seconds=TOUCH_SECONDS):
        attempt.device_seen_at = now
        ExamAttempt.objects.filter(pk=attempt.pk).update(device_seen_at=now)


def original_is_active(attempt, now):
    return bool(attempt.device_seen_at and now - attempt.device_seen_at <= timedelta(seconds=ACTIVE_SECONDS))


def _turn_away(a, device, label, ip, now):
    """Another browser showed up while the student's own is working: refuse it, leave the student alone, tell the teacher."""
    recent = a.last_intrusion_at and now - a.last_intrusion_at < timedelta(seconds=60)
    if a.last_intruder_id != device and not recent:  # not one log line per refresh, and no flood from fresh cookies
        log_event(a.exam, 'intruder',
                  f'{a.user.username}: {label} ({ip}) tried to open the exam while their own device '
                  f'({a.device_label}) was active. Turned away; the student was not interrupted.', a)
    ExamAttempt.objects.filter(pk=a.pk).update(
        intrusions=F('intrusions') + 1, last_intruder_id=device, last_intruder_label=label,
        last_intruder_ip=ip, last_intrusion_at=now)


def _note_copied_code(attempt, label, ip, now):
    """The locked device code arrived from a different KIND of browser than it was first seen on. Browsers keep their
    own cookies, so this means the code was copied to another browser. Flag only: the teacher decides what it means."""
    if not attempt.device_label or label == attempt.device_label:
        return
    if attempt.last_mismatch_at and now - attempt.last_mismatch_at < timedelta(seconds=60):  # one line a minute, not one per ping
        return
    ExamAttempt.objects.filter(pk=attempt.pk).update(mismatches=F('mismatches') + 1, last_mismatch_at=now)
    attempt.last_mismatch_at = now
    log_event(attempt.exam, 'copied_code',
              f'{attempt.user.username}: device code {attempt.device_tag} (first seen on {attempt.device_label}) is also '
              f'being used from {label} ({ip}). The exam link or browser data may have been copied.', attempt)


def _other_device(attempt, device, label, ip, now):
    """A browser that is not the locked one. Decided on a freshly locked copy of the seat, because the copy the
    request loaded may be stale (the teacher can unfreeze or turn this very browser away at the same moment)."""
    with transaction.atomic():
        a = ExamAttempt.objects.select_for_update(of=('self',)).select_related('exam', 'user').get(pk=attempt.pk)
        attempt.frozen_at = a.frozen_at
        if a.device_id == device:  # the teacher has just handed the seat to this browser
            return 'frozen' if a.frozen_at else 'ok'
        if device in a.blocked_devices:
            return 'blocked'  # the teacher already turned this browser away: no new alarm
        if a.frozen_at:
            return 'frozen'
        if original_is_active(a, now):
            _turn_away(a, device, label, ip, now)
            return 'blocked'
        a.frozen_at = now  # the student's own browser went quiet: pause the seat for the teacher
        a.freezes += 1
        a.challenger_id, a.challenger_label, a.challenger_ip = device, label, ip
        a.freeze_silent_seconds = int((now - a.device_seen_at).total_seconds()) if a.device_seen_at else None
        a.save(update_fields=['frozen_at', 'freezes', 'challenger_id', 'challenger_label', 'challenger_ip',
                              'freeze_silent_seconds'])
        attempt.frozen_at = now
        log_event(a.exam, 'freeze', f'{a.user.username} was opened on {label} ({ip}) while locked to '
                                    f'{a.device_label} ({a.device_ip}), which had gone quiet', a)
        return 'frozen'


def check_device(request, attempt, now=None):
    """'ok', 'frozen' or 'blocked' for this browser.

    The first browser locks the seat. A different browser is turned away if the locked one is still working,
    and freezes the seat for the teacher if the locked one has gone silent (a dead laptop, a dropped connection)."""
    now = now or timezone.now()
    device, label, ip = _here(request)
    if not attempt.device_id:
        bind_device(request, attempt, now)
        return 'ok'
    if attempt.device_id == device:
        _touch(attempt, now)
        _note_copied_code(attempt, label, ip, now)
        return 'frozen' if attempt.frozen_at else 'ok'
    return _other_device(attempt, device, label, ip, now)
