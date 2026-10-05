"""Leaving the exam window, and the evidence a teacher sees about it.

A web page cannot stop anyone from leaving, it can only notice and tell the server, and anything the page does can be
undone by a student with devtools (deleting the fullscreen overlay, say). So the SERVER keeps the count and its own clock:
from the moment the exam page is served the student is "not in the exam window yet" until the page says they are, and if
that lasts longer than ENTER_SECONDS (or an absence lasts another REPEAT_SECONDS) the server adds a strike by itself, whatever
the page reports. Reloading resets nothing. Three strikes submit the exam; the teacher can reopen it. A student who forges the
page's "I am in fullscreen" report can still evade this: that takes writing requests by hand, and it is why the teacher
also sees silent pages and copied device codes. Scheduled exams only (open exams can be taken on phones, which cannot
hold fullscreen)."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .exam_device import log_event
from .exam_run import finalize
from .models import Exam, ExamAttempt

MAX_STRIKES = 3
DEDUPE_SECONDS = 4    # losing focus, hiding the tab and leaving fullscreen arrive together: one absence, one strike
SILENT_SECONDS = 45   # a started student whose page has not checked in for this long is flagged (never a strike)
ENTER_SECONDS = 45    # after the exam page opens (or fullscreen is required again) the student has this long to go fullscreen
REPEAT_SECONDS = 60   # an absence that goes on earns another strike this often
CLIENT_KINDS = ('hidden', 'blur', 'fullscreen')  # what the page may report; the server adds 'never' and 'away' itself
LEAVE_KINDS = {'hidden': 'switched tab or minimized the window', 'blur': 'switched to another window',
               'fullscreen': 'left fullscreen', 'never': 'did not go fullscreen in time',
               'away': 'is still outside the exam window'}
STRIKES = 'strikes'   # ExamAttempt.submit_reason when the server submitted the exam for leaving it


def applies(exam, attempt=None):
    """Are strikes (and the fullscreen rule) in force? Scheduled exams only, and not for a student the teacher switched off."""
    return exam.mode == Exam.SCHEDULED and not (attempt is not None and attempt.strikes_off)


def start_watching(attempt, now=None):
    """The exam page was just served (first load, a reload, or strikes switched on): the student is not in fullscreen
    yet, so the server's clock for that starts now. Does nothing if an absence is already open (a reload must not
    give a student a fresh 45 seconds) or if strikes do not apply."""
    now = now or timezone.now()
    if attempt.away_since is None and not attempt.submitted_at and not attempt.frozen_at and applies(attempt.exam, attempt):
        ExamAttempt.objects.filter(pk=attempt.pk, away_since__isnull=True).update(away_since=now)
        attempt.away_since = now


def enforce(attempt, now=None):
    """Called on every check-in (ping, answer). If the student has been outside the exam window, or never entered it,
    for longer than allowed, the SERVER counts a strike itself, whatever the page reports. Returns the attempt, which
    is submitted if that was the third strike."""
    now = now or timezone.now()
    a = attempt
    if a.submitted_at or a.frozen_at or a.away_since is None or not applies(a.exam, a):
        return a
    reported = a.last_leave_at is not None and a.last_leave_at >= a.away_since  # a strike already came for this absence
    since = a.last_leave_at if reported else a.away_since
    if now - since < timedelta(seconds=REPEAT_SECONDS if reported else ENTER_SECONDS):
        return a
    return record_leave(a, 'away' if reported else 'never', now)[0]


def record_leave(attempt, kind, now=None):
    """The page says the exam window was left. Returns (the attempt as it is now, whether this report counted)."""
    now = now or timezone.now()
    with transaction.atomic():
        a = ExamAttempt.objects.select_for_update(of=('self',)).select_related('exam', 'user').get(pk=attempt.pk)
        if a.submitted_at or a.exam.mode != Exam.SCHEDULED:
            return a, False
        if a.last_leave_at and now - a.last_leave_at < timedelta(seconds=DEDUPE_SECONDS):
            return a, False  # the same absence, reported again
        previous = a.last_leave_at
        a.leaves += 1
        a.last_leave_at = now
        if a.away_since is None:
            a.away_since = now  # an absence is measured from its first report, however often it is repeated
        what = LEAVE_KINDS[kind]
        if a.frozen_at:  # a paused seat cannot earn strikes, but trying to leave is something the teacher should see
            log_event(a.exam, 'leave_frozen', f'{a.user.username} {what} while the seat was frozen', a)
            a.save(update_fields=['leaves', 'last_leave_at', 'away_since'])
            return a, True
        if a.strikes_off:  # counted for the teacher; one log line per burst, as assistive technology can trigger this constantly
            if previous is None or now - previous >= timedelta(seconds=60):
                log_event(a.exam, 'leave', f'{a.user.username} {what} (strikes are off for this student)', a)
            a.save(update_fields=['leaves', 'last_leave_at', 'away_since'])
            return a, True
        a.strikes += 1
        log_event(a.exam, 'strike', f'{a.user.username} {what}: strike {a.strikes} of {MAX_STRIKES}', a)
        a.save(update_fields=['leaves', 'last_leave_at', 'away_since', 'strikes'])
        if a.strikes >= MAX_STRIKES:
            log_event(a.exam, 'auto_submit',
                      f'{a.user.username}: exam submitted automatically after {MAX_STRIKES} strikes', a)
            a = finalize(a, now, reason=STRIKES)
        return a, True


def record_back(attempt, away, now=None):
    """The student came back. Adds the time they were away: their page's figure, but never more than the server saw."""
    now = now or timezone.now()
    with transaction.atomic():
        a = ExamAttempt.objects.select_for_update().get(pk=attempt.pk)
        if a.away_since is None:
            return a
        seen = int((now - a.away_since).total_seconds())
        a.away_seconds += max(0, min(away, seen, 3600))
        a.away_since = None
        a.save(update_fields=['away_seconds', 'away_since'])
        return a


def silent_seconds(a, now):
    """How long this student's page has been quiet, if long enough to flag, else None. Never a strike."""
    if not a.started_at or a.submitted_at or a.frozen_at or not a.device_seen_at:
        return None
    gap = int((now - a.device_seen_at).total_seconds())
    return gap if gap >= SILENT_SECONDS else None


def integrity_rows(exam, now=None):
    """Students worth a teacher's attention, most strikes first: [{'attempt', 'silent', 'away_now'}]."""
    now = now or timezone.now()
    watching = exam.mode == Exam.SCHEDULED and exam.phase(now) == 'running'
    flagged = (Q(strikes__gt=0) | Q(leaves__gt=0) | Q(mismatches__gt=0) | Q(intrusions__gt=0) | Q(freezes__gt=0)
               | ~Q(submit_reason=''))
    if watching:
        flagged |= Q(started_at__isnull=False, submitted_at__isnull=True, frozen_at__isnull=True,
                     device_seen_at__lt=now - timedelta(seconds=SILENT_SECONDS))
        flagged |= Q(started_at__isnull=False, submitted_at__isnull=True, frozen_at__isnull=True,
                     away_since__lt=now - timedelta(seconds=20))  # not in the exam window for a while (never entered it, or left)
    rows = []
    for a in exam.attempts.filter(flagged).select_related('user').order_by('-strikes', 'user__username')[:100]:
        rows.append({
            'attempt': a,
            'silent': silent_seconds(a, now) if watching else None,
            'away_now': int((now - a.away_since).total_seconds()) if a.away_since and not a.submitted_at else None,
        })
    return rows


def freeze_evidence(a, now=None):
    """What a teacher needs to decide about a frozen seat. `a` must carry .answered (annotate Count('answers'))."""
    now = now or timezone.now()
    original_back = None
    if a.device_seen_at and a.frozen_at and a.device_seen_at > a.frozen_at:
        original_back = int((now - a.device_seen_at).total_seconds())  # the ORIGINAL device checked in again after the freeze
    left = int((a.ends_at - now).total_seconds()) if a.ends_at else None
    return {
        'silent_before': a.freeze_silent_seconds,
        'original_back_ago': original_back,
        'same_network': (a.device_ip == a.challenger_ip) if a.device_ip and a.challenger_ip else None,
        'answered': a.answered, 'questions': len(a.question_ids),
        'time_left': 'no timer' if left is None else 'time is up' if left < 0 else f'{left // 60}:{left % 60:02d}',
        'events': list(a.events.all()[:6]),
    }
