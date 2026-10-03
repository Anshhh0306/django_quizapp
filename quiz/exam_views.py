import re

from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db import transaction
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .exam_device import bind_device
from .models import Exam, ExamAttempt, ExamDenied
from .roles import is_student

MOBILE_RE = re.compile(r'Mobi|Android|iPhone|iPad|iPod', re.I)

MESSAGES = {
    'mobile': ('Use a laptop or desktop', 'Scheduled exams need a laptop or desktop computer with a full browser. Open the link there.'),
    'not_student': ('Students only', 'Only student accounts can take exams.'),
    'draft': ('Not open yet', 'This exam is not open yet. Try again when your teacher says it is open.'),
    'ended': ('Exam ended', 'This exam has ended.'),
    'not_listed': ('Not on the list', 'You are not on the class list for this exam. Contact your teacher if this is a mistake.'),
    'full': ('No seats left', 'All seats for this exam are taken. Contact your teacher.'),
}


def _notice(request, reason):
    title, message = MESSAGES[reason]
    return render(request, 'quiz/exam/notice.html', {'title': title, 'message': message})


def mobile_blocked(request, exam):
    """Scheduled exams are laptop/desktop only (phones can't hold fullscreen). A soft check: the user agent can be faked."""
    return exam.mode == Exam.SCHEDULED and bool(MOBILE_RE.search(request.META.get('HTTP_USER_AGENT', '')))


def admission_problem(exam, user):
    """Why this student cannot take a NEW seat right now, or None. Does not claim anything."""
    if not is_student(user):
        return 'not_student'
    phase = exam.phase()
    if phase == Exam.DRAFT:
        return 'draft'
    if phase == Exam.ENDED:
        return 'ended'
    if exam.allowed.exists():  # class list: every listed student has a seat, no counting
        if not exam.allowed.filter(email=user.email.lower()).exists():
            return 'not_listed'
    elif exam.attempts.count() >= exam.seat_limit:  # no list: plain seat counter
        return 'full'
    return None


def _deny(request, exam, reason):
    """Show the notice; turned-away students (not listed / full) are also logged for the teacher."""
    if reason in ('not_listed', 'full'):
        _log_denied(request.user, exam, reason)
    return _notice(request, reason)


def _log_denied(user, exam, reason):
    row, created = ExamDenied.objects.get_or_create(exam=exam, user=user, defaults={'reason': reason})
    if not created:
        ExamDenied.objects.filter(pk=row.pk).update(reason=reason, tries=F('tries') + 1)


def claim_seat(exam, user):
    """Atomically take a seat. Returns (attempt, None) or (None, 'full'). Safe against the last-seat race."""
    with transaction.atomic():
        exam = Exam.objects.select_for_update().get(pk=exam.pk)  # serialises seat claims per exam
        existing = ExamAttempt.objects.filter(exam=exam, user=user).first()
        if existing:
            return existing, None
        if not exam.allowed.exists() and exam.attempts.count() >= exam.seat_limit:
            return None, 'full'
        return ExamAttempt.objects.create(exam=exam, user=user, consented_at=timezone.now()), None


def _attempt(exam, user):
    return ExamAttempt.objects.filter(exam=exam, user=user).first()


@never_cache
@login_required
def exam_entry(request, token):
    exam = get_object_or_404(Exam, token=token)
    if not is_student(request.user):
        return _notice(request, 'not_student')
    if mobile_blocked(request, exam):
        return _notice(request, 'mobile')
    attempt = _attempt(exam, request.user)
    if attempt:  # already has a seat: let them straight back in and flag it for the teacher
        if attempt.device_id in ('', request.device_id):  # another browser is no reconnect: the device lock deals with it
            ExamAttempt.objects.filter(pk=attempt.pk).update(rejoins=F('rejoins') + 1, last_rejoin_at=timezone.now())
        return redirect('exam_lobby', token=token)
    problem = admission_problem(exam, request.user)
    if problem:
        return _deny(request, exam, problem)
    return redirect('exam_consent', token=token)


@never_cache
@login_required
def exam_consent(request, token):
    exam = get_object_or_404(Exam, token=token)
    if not is_student(request.user):
        return _notice(request, 'not_student')
    if mobile_blocked(request, exam):
        return _notice(request, 'mobile')
    if _attempt(exam, request.user):
        return redirect('exam_lobby', token=token)
    problem = admission_problem(exam, request.user)
    if problem:
        return _deny(request, exam, problem)
    if request.method == 'POST':
        if request.POST.get('agree') != 'on':
            return render(request, 'quiz/exam/consent.html', {'exam': exam, 'error': 'Tick the box to continue.'})
        attempt, problem = claim_seat(exam, request.user)
        if problem:
            return _deny(request, exam, problem)
        return redirect('exam_lobby', token=token)
    return render(request, 'quiz/exam/consent.html', {'exam': exam})


@never_cache
@login_required
def exam_lobby(request, token):
    exam = get_object_or_404(Exam, token=token)
    attempt = _attempt(exam, request.user)
    if not attempt:
        return redirect('exam_entry', token=token)
    if attempt.submitted_at:
        return redirect('exam_done', token=token)
    if not attempt.started_at:
        bind_device(request, attempt)  # in the lobby the newest browser wins; the lock starts with the exam
    return render(request, 'quiz/exam/lobby.html', {'exam': exam})


def _ms(dt):
    return int(dt.timestamp() * 1000)


@never_cache
@login_required
def exam_status(request, token):
    """Polled by the lobby every few seconds. Deliberately tiny: one exam lookup, one attempt check.

    Sends the server's own clock ('now') so the countdown never trusts the student's computer clock.
    """
    exam = get_object_or_404(Exam, token=token)
    if not _attempt(exam, request.user):
        raise Http404
    now = timezone.now()
    return JsonResponse({
        'status': exam.status,
        'phase': exam.phase(now),
        'now': _ms(now),
        'starts_at': _ms(exam.starts_at) if exam.starts_at else None,
    })
