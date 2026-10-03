"""What the teacher can do about frozen seats and running out of time. Every action is written to the audit log."""
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .exam_device import log_event
from .exam_run import finalize, is_closed
from .models import Exam, ExamAttempt

EXTRA_MINUTES = (0, 5, 10, 15, 20, 30)
EXTEND_ALL_MINUTES = (5, 10, 15, 20, 30)


def _locked(attempt):
    return ExamAttempt.objects.select_for_update().select_related('exam', 'user').get(pk=attempt.pk)


def unfreeze(attempt, keep, minutes, actor):
    """Let one device back in. keep: 'original' or 'new'. The other device is turned away for good.
    minutes: extra time to grant at the same time (0 for none). Returns True if it was frozen."""
    with transaction.atomic():
        a = _locked(attempt)
        if not a.frozen_at or a.submitted_at:  # a stale page may offer this for someone already submitted
            return False
        blocked = set(a.blocked_devices)
        if keep == 'new' and a.challenger_id:
            blocked.add(a.device_id)  # the old browser is now the one turned away
            a.device_id, a.device_label, a.device_ip = a.challenger_id, a.challenger_label, a.challenger_ip
            a.device_seen_at = timezone.now()
            chosen = f'switched to {a.device_label}'
        else:
            if a.challenger_id:
                blocked.add(a.challenger_id)
            chosen = f'kept {a.device_label}'
        a.blocked_devices = sorted(blocked)
        a.challenger_id = a.challenger_label = ''
        a.challenger_ip = None
        a.frozen_at = None
        extra = ''
        if minutes and a.ends_at:
            a.ends_at += timedelta(minutes=minutes)
            a.extra_seconds += minutes * 60
            extra = f', +{minutes} min'
        a.save()
        log_event(a.exam, 'unfreeze', f'{a.user.username}: {chosen}{extra}', a, actor)
        return True


def reset_device(attempt, actor):
    """The student's device is gone for good (or a wrong choice turned the right device away): forget every device
    for this seat so the next browser to open the exam is accepted. Returns an error message, or None."""
    with transaction.atomic():
        a = _locked(attempt)
        if a.submitted_at or a.exam.status == Exam.ENDED:
            return 'This student has already been submitted.'
        a.device_id = a.device_label = a.challenger_id = a.challenger_label = ''
        a.device_ip = a.challenger_ip = a.device_seen_at = a.frozen_at = None
        a.blocked_devices = []
        a.save()
        log_event(a.exam, 'reset_device', f'{a.user.username}: device lock cleared; the next device to open the exam '
                                          f'is accepted', a, actor)
        return None


def grant_extra(attempt, minutes, actor):
    """Extra time for one student. Returns an error message, or None when it worked."""
    with transaction.atomic():
        a = _locked(attempt)
        if minutes not in EXTRA_MINUTES or minutes == 0:
            return 'Choose how many minutes to add.'
        if a.submitted_at or a.exam.status == Exam.ENDED:
            return 'This student has already been submitted, so time cannot be added.'
        if not a.ends_at:
            return 'This exam has no timer.'
        if is_closed(a):  # their time was already up and nobody had scored it yet: do not bring it back to life
            finalize(a)
            return 'This student\'s time was already up and their exam has been submitted.'
        a.ends_at += timedelta(minutes=minutes)
        a.extra_seconds += minutes * 60
        a.save(update_fields=['ends_at', 'extra_seconds'])
        log_event(a.exam, 'extra_time', f'{a.user.username}: +{minutes} min', a, actor)
        return None


def reopen(attempt, minutes, actor):
    """Undo an automatic submission (three strikes): the student carries on with their answers kept, strikes back to
    zero, plus optional extra minutes. Only while the exam is still running, so nobody has seen a score yet.
    Returns an error message, or None when it worked."""
    with transaction.atomic():
        a = _locked(attempt)
        if minutes not in EXTRA_MINUTES:
            return 'Choose how many extra minutes to give (0 for none).'
        if not a.submitted_at or a.submit_reason != 'strikes':
            return 'This student was not submitted automatically.'
        if a.exam.phase() != 'running':
            return 'The exam is over, so this student cannot be reopened.'
        now = timezone.now()
        a.ends_at = max(a.ends_at or now, now) + timedelta(minutes=minutes)
        a.extra_seconds += minutes * 60
        a.submitted_at = a.score = a.away_since = None
        a.total_points, a.strikes, a.submit_reason = 0, 0, ''
        a.save()
        extra = f', +{minutes} min' if minutes else ''
        log_event(a.exam, 'reopen', f'{a.user.username}: reopened after the automatic submission, strikes cleared{extra}', a, actor)
        return None


def set_strikes_off(attempt, off, actor):
    """Switch strikes (and the fullscreen rule) off or on for one student, e.g. for assistive technology."""
    with transaction.atomic():
        a = _locked(attempt)
        a.strikes_off = off
        # switched ON: the student gets a fresh clock to go fullscreen; switched OFF: nothing is owed any more
        a.away_since = None if off else (None if a.submitted_at else timezone.now())
        a.save(update_fields=['strikes_off', 'away_since'])
        log_event(a.exam, 'strikes_off' if off else 'strikes_on',
                  f'{a.user.username}: strikes and the fullscreen rule turned {"off" if off else "on"}', a, actor)


def extend_all(exam, minutes, actor):
    """Everyone still taking the exam gets more time (power cut, network trouble). Returns an error message or None."""
    if minutes not in EXTEND_ALL_MINUTES:
        return 'Choose how many minutes to add.'
    delta = timedelta(minutes=minutes)
    with transaction.atomic():
        locked = Exam.objects.select_for_update().get(pk=exam.pk)  # two quick clicks must not overwrite each other
        if locked.mode != Exam.SCHEDULED or locked.phase() != 'running':
            return 'Time can only be added while a scheduled exam is running.'
        Exam.objects.filter(pk=exam.pk).update(ends_at=F('ends_at') + delta)
        exam.attempts.filter(started_at__isnull=False, submitted_at__isnull=True, ends_at__isnull=False).update(
            ends_at=F('ends_at') + delta, extra_seconds=F('extra_seconds') + minutes * 60)
        log_event(exam, 'extend_all', f'Everyone: +{minutes} min', actor=actor)
    exam.refresh_from_db(fields=['ends_at'])
    return None
