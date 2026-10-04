"""The student side of an exam in progress: the question page, autosave, submit, and the finished page."""
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .exam_device import bind_device, check_device
from .exam_integrity import (CLIENT_KINDS, ENTER_SECONDS, MAX_STRIKES, STRIKES,
                             applies, enforce, record_back, record_leave, start_watching)
from .exam_run import begin_attempt, finalize, is_closed, scores_visible, shuffled_choices
from .ratelimit import user_rate_limit
from .util import to_int
from .exam_views import _attempt, _ms, _notice, mobile_blocked
from .models import DEVICE_TAG, Choice, Exam, ExamAnswer, ExamAttempt, Question
from .roles import is_student


def _guard(request, token):
    """(exam, attempt, early_response). Only students who joined (consented) may continue."""
    exam = get_object_or_404(Exam, token=token)
    if not is_student(request.user):
        return exam, None, _notice(request, 'not_student')
    attempt = _attempt(exam, request.user)
    if not attempt:
        return exam, None, redirect('exam_entry', token=token)
    return exam, attempt, None


@never_cache
@login_required
def exam_take(request, token):
    exam, attempt, early = _guard(request, token)
    if early:
        return early
    if attempt.submitted_at:
        return redirect('exam_done', token=token)
    phase = exam.phase()
    if phase in (Exam.DRAFT, Exam.LOBBY, 'countdown'):
        return redirect('exam_lobby', token=token)  # no peeking before the start
    if mobile_blocked(request, exam):
        return _notice(request, 'mobile')
    # The exam may be over for everyone else while this student still has extra time (or a frozen seat to resolve).
    if phase == Exam.ENDED and not (attempt.started_at and not is_closed(attempt)):
        if attempt.started_at:
            finalize(attempt)
        return redirect('exam_done', token=token)

    if not attempt.started_at:
        bind_device(request, attempt)  # before the clock starts, the newest browser wins
    attempt = begin_attempt(attempt)
    if is_closed(attempt):
        finalize(attempt)
        return redirect('exam_done', token=token)
    state = check_device(request, attempt)
    if state != 'ok':  # a second browser: nothing is shown, not even the questions
        return render(request, 'quiz/exam/frozen.html', {
            'exam': exam, 'blocked': state == 'blocked', 'device_tag': request.device_id[:DEVICE_TAG],
            'ping_url': reverse('exam_ping', args=[token]), 'done_url': reverse('exam_done', args=[token])})

    attempt = enforce(attempt)  # an overdue absence counts even if the page is reloaded to hide it
    if attempt.submitted_at:
        return redirect('exam_done', token=token)
    start_watching(attempt)  # from now the server's own clock for "go fullscreen" runs, whatever the page does

    questions = Question.objects.filter(pk__in=attempt.question_ids).prefetch_related('choices')
    by_id = {q.pk: q for q in questions}
    payload_questions = []
    for qid in attempt.question_ids:  # this student's order
        q = by_id.get(qid)
        if q:  # the teacher may have deleted it meanwhile
            options = shuffled_choices(attempt.pk, q.pk, q.choices.all())
            payload_questions.append({'id': q.pk, 'text': q.text, 'points': q.points,
                                      'options': [{'id': c.pk, 'text': c.text} for c in options]})  # never is_correct
    return render(request, 'quiz/exam/take.html', {
        'exam': exam, 'device_tag': request.device_id[:DEVICE_TAG],
        'payload': {
            'questions': payload_questions,
            'scheduled': exam.mode == Exam.SCHEDULED,  # leaving the window is reported (open exams: never)
            'enter_seconds': ENTER_SECONDS,
            'anti_cheat': applies(exam, attempt), 'strikes': attempt.strikes, 'max_strikes': MAX_STRIKES,
            'event_url': reverse('exam_event', args=[token]),
            'low_seconds': min(300, (exam.duration_minutes or 0) * 6),  # the timer turns red in the last 10% (at most 5 minutes)
            'answers': {str(a.question_id): a.choice_id for a in attempt.answers.all()},
            'deadline_ms': _ms(attempt.ends_at) if attempt.ends_at else None,
            'now_ms': _ms(timezone.now()),
            'ping_url': reverse('exam_ping', args=[token]),
            'answer_url': reverse('exam_answer', args=[token]),
            'submit_url': reverse('exam_submit', args=[token]),
            'done_url': reverse('exam_done', args=[token]),
        },
    })


@never_cache
@login_required
@require_POST
@user_rate_limit('answer', 180, 60)  # the page saves one answer per click; a person cannot click this fast
def exam_answer(request, token):
    """Autosave one answer. The browser calls this on every click and retries if the wifi drops."""
    exam = get_object_or_404(Exam, token=token)
    attempt = ExamAttempt.objects.filter(exam=exam, user=request.user).select_related('exam').first()
    if not attempt or not attempt.started_at:
        return JsonResponse({'ok': False, 'reason': 'not_started'}, status=409)
    if is_closed(attempt):
        finalize(attempt)
        return JsonResponse({'ok': False, 'reason': 'closed'}, status=409)
    state = check_device(request, attempt)
    if state != 'ok':  # frozen (423) or turned away (403): nothing is saved from this browser
        return JsonResponse({'ok': False, 'reason': state}, status=423 if state == 'frozen' else 403)
    attempt = enforce(attempt)  # saving answers is a check-in too: a page that never pings still gets counted
    if attempt.submitted_at:
        return JsonResponse({'ok': False, 'reason': 'closed'}, status=409)

    qid, raw_choice = to_int(request.POST.get('question', '')), request.POST.get('choice', '')
    if qid is None or qid not in attempt.question_ids:
        return JsonResponse({'ok': False, 'reason': 'bad_question'}, status=400)
    cid = None
    if raw_choice != '':  # an empty choice means the student cleared their answer
        cid = to_int(raw_choice)
        if cid is None or not Choice.objects.filter(pk=cid, question_id=qid).exists():
            return JsonResponse({'ok': False, 'reason': 'bad_choice'}, status=400)

    # Lock the attempt while writing so a Submit arriving at the same moment cannot score the exam first
    # and leave this answer behind as one the score does not count.
    with transaction.atomic():
        locked = ExamAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.submitted_at:
            return JsonResponse({'ok': False, 'reason': 'closed'}, status=409)
        if cid is None:
            ExamAnswer.objects.filter(attempt=locked, question_id=qid).delete()
        else:
            ExamAnswer.objects.update_or_create(attempt=locked, question_id=qid, defaults={'choice_id': cid})
    return JsonResponse({'ok': True})


@never_cache
@login_required
@require_POST
def exam_submit(request, token):
    exam, attempt, early = _guard(request, token)
    if early:
        return early
    if attempt.submitted_at or not attempt.started_at:
        return redirect('exam_done', token=token)  # nothing to submit (and no device alarm for a finished exam)
    if check_device(request, attempt) != 'ok':  # a frozen or turned-away browser cannot submit
        return redirect('exam_take', token=token)
    finalize(attempt)
    return redirect('exam_done', token=token)


@never_cache
@login_required
@user_rate_limit('ping', 30, 60)  # the page asks every 8 seconds
def exam_ping(request, token):
    """The exam page asks every few seconds: still ok? frozen? new deadline? Also how a frozen page learns it was released."""
    exam = get_object_or_404(Exam, token=token)
    attempt = ExamAttempt.objects.filter(exam=exam, user=request.user).select_related('exam').first()
    if not attempt or not attempt.started_at:
        return JsonResponse({'state': 'closed'}, status=404)
    now = timezone.now()
    if is_closed(attempt, now):
        finalize(attempt, now)
        return JsonResponse({'state': 'closed'})
    state = check_device(request, attempt, now)
    if state == 'ok':  # only the seat's own browser can make the server count anything against the student
        attempt = enforce(attempt, now)
        if attempt.submitted_at:
            return JsonResponse({'state': 'closed'})
    return JsonResponse({'state': state, 'now_ms': _ms(now),
                         'deadline_ms': _ms(attempt.ends_at) if attempt.ends_at else None,
                         'anti_cheat': applies(exam, attempt), 'strikes': attempt.strikes, 'max_strikes': MAX_STRIKES})


@never_cache
@login_required
@require_POST
@user_rate_limit('event', 60, 60)  # one report per leave or return, de-duplicated by the server anyway
def exam_event(request, token):
    """The exam page reports that the exam window was left ('hidden', 'blur', 'fullscreen') or that the student is back."""
    exam = get_object_or_404(Exam, token=token)
    attempt = ExamAttempt.objects.filter(exam=exam, user=request.user).select_related('exam').first()
    if not attempt or not attempt.started_at:
        return JsonResponse({'ok': False, 'reason': 'not_started'}, status=409)
    if is_closed(attempt):
        finalize(attempt)
        return JsonResponse({'ok': False, 'reason': 'closed', 'closed': True}, status=409)
    if check_device(request, attempt) == 'blocked':  # another browser cannot add or remove strikes
        return JsonResponse({'ok': False, 'reason': 'blocked'}, status=403)
    kind, counted = request.POST.get('kind', ''), False
    if kind in CLIENT_KINDS:
        attempt, counted = record_leave(attempt, kind)
    elif kind == 'back':
        attempt = record_back(attempt, to_int(request.POST.get('away', ''), 10**6) or 0)  # clamped to what the server saw
    else:
        return JsonResponse({'ok': False, 'reason': 'bad_kind'}, status=400)
    return JsonResponse({'ok': True, 'counted': counted, 'closed': bool(attempt.submitted_at),
                         'anti_cheat': applies(exam, attempt), 'strikes': attempt.strikes, 'max_strikes': MAX_STRIKES})


@never_cache
@login_required
def exam_done(request, token):
    exam, attempt, early = _guard(request, token)
    if early:
        return early
    if attempt.started_at and not attempt.submitted_at:
        if not is_closed(attempt):
            return redirect('exam_take', token=token)  # still in progress
        attempt = finalize(attempt)

    context = {'exam': exam, 'attempt': attempt, 'started': bool(attempt.started_at),
               'by_strikes': attempt.submit_reason == STRIKES, 'max_strikes': MAX_STRIKES,
               'ping_url': reverse('exam_ping', args=[token])}
    # Scheduled exams reveal the score only once nobody is still working (extra time included),
    # so early finishers can't pass anything on.
    if attempt.submitted_at and scores_visible(exam):
        order = {qid: i for i, qid in enumerate(attempt.question_ids)}
        answers = sorted(attempt.answers.select_related('question', 'choice'), key=lambda a: order.get(a.question_id, 0))
        context.update(show_score=True, selections=[(a.question.text, a.choice.text) for a in answers])
    return render(request, 'quiz/exam/done.html', context)
