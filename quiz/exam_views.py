from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Exam, ExamAttempt, ExamDenied
from .roles import is_student

MESSAGES = {
    'not_student': ('Students only', 'Only student accounts can take exams.'),
    'draft': ('Not open yet', 'This exam is not open yet. Try again when your teacher says it is open.'),
    'ended': ('Exam ended', 'This exam has ended.'),
    'not_listed': ('Not on the list', 'You are not on the class list for this exam. Contact your teacher if this is a mistake.'),
    'full': ('No seats left', 'All seats for this exam are taken. Contact your teacher.'),
}


def _notice(request, reason):
    title, message = MESSAGES[reason]
    return render(request, 'quiz/exam/notice.html', {'title': title, 'message': message})


def admission_problem(exam, user):
    """Why this student cannot take a NEW seat right now, or None. Does not claim anything."""
    if not is_student(user):
        return 'not_student'
    if exam.status == Exam.DRAFT:
        return 'draft'
    if exam.status == Exam.ENDED:
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


@login_required
def exam_entry(request, token):
    exam = get_object_or_404(Exam, token=token)
    if not is_student(request.user):
        return _notice(request, 'not_student')
    attempt = _attempt(exam, request.user)
    if attempt:  # already has a seat: let them straight back in and flag it for the teacher
        ExamAttempt.objects.filter(pk=attempt.pk).update(rejoins=F('rejoins') + 1, last_rejoin_at=timezone.now())
        return redirect('exam_lobby', token=token)
    problem = admission_problem(exam, request.user)
    if problem:
        return _deny(request, exam, problem)
    return redirect('exam_consent', token=token)


@login_required
def exam_consent(request, token):
    exam = get_object_or_404(Exam, token=token)
    if not is_student(request.user):
        return _notice(request, 'not_student')
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


@login_required
def exam_lobby(request, token):
    exam = get_object_or_404(Exam, token=token)
    if not _attempt(exam, request.user):
        return redirect('exam_entry', token=token)
    return render(request, 'quiz/exam/lobby.html', {'exam': exam})


@login_required
def exam_status(request, token):
    """Polled by the lobby every few seconds. Deliberately tiny: one exam lookup, one attempt check."""
    exam = get_object_or_404(Exam, token=token)
    if not _attempt(exam, request.user):
        raise Http404
    return JsonResponse({'status': exam.status})
