"""The student side of an exam in progress: the question page, autosave, submit, and the finished page."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .exam_run import begin_attempt, finalize, is_closed, shuffled_choices
from .exam_views import _attempt, _ms, _notice, mobile_blocked
from .models import Choice, Exam, ExamAnswer, ExamAttempt, Question
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
    if phase == Exam.ENDED:
        if attempt.started_at:
            finalize(attempt)
        return redirect('exam_done', token=token)

    attempt = begin_attempt(attempt)
    if is_closed(attempt):
        finalize(attempt)
        return redirect('exam_done', token=token)

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
        'exam': exam,
        'payload': {
            'questions': payload_questions,
            'answers': {str(a.question_id): a.choice_id for a in attempt.answers.all()},
            'deadline_ms': _ms(attempt.ends_at) if attempt.ends_at else None,
            'now_ms': _ms(timezone.now()),
            'answer_url': reverse('exam_answer', args=[token]),
            'submit_url': reverse('exam_submit', args=[token]),
            'done_url': reverse('exam_done', args=[token]),
        },
    })


@login_required
@require_POST
def exam_answer(request, token):
    """Autosave one answer. The browser calls this on every click and retries if the wifi drops."""
    exam = get_object_or_404(Exam, token=token)
    attempt = ExamAttempt.objects.filter(exam=exam, user=request.user).select_related('exam').first()
    if not attempt or not attempt.started_at:
        return JsonResponse({'ok': False, 'reason': 'not_started'}, status=409)
    if is_closed(attempt):
        finalize(attempt)
        return JsonResponse({'ok': False, 'reason': 'closed'}, status=409)

    qid, cid = request.POST.get('question', ''), request.POST.get('choice', '')
    if not qid.isdigit() or int(qid) not in attempt.question_ids:
        return JsonResponse({'ok': False, 'reason': 'bad_question'}, status=400)
    if cid == '':  # student cleared their answer
        ExamAnswer.objects.filter(attempt=attempt, question_id=qid).delete()
        return JsonResponse({'ok': True})
    if not cid.isdigit() or not Choice.objects.filter(pk=cid, question_id=qid).exists():
        return JsonResponse({'ok': False, 'reason': 'bad_choice'}, status=400)
    ExamAnswer.objects.update_or_create(attempt=attempt, question_id=qid, defaults={'choice_id': cid})
    return JsonResponse({'ok': True})


@login_required
@require_POST
def exam_submit(request, token):
    exam, attempt, early = _guard(request, token)
    if early:
        return early
    if attempt.started_at:
        finalize(attempt)
    return redirect('exam_done', token=token)


@login_required
def exam_done(request, token):
    exam, attempt, early = _guard(request, token)
    if early:
        return early
    if attempt.started_at and not attempt.submitted_at:
        if not is_closed(attempt):
            return redirect('exam_take', token=token)  # still in progress
        attempt = finalize(attempt)

    context = {'exam': exam, 'attempt': attempt, 'started': bool(attempt.started_at)}
    # Scheduled exams reveal the score only after everyone is done, so early finishers can't pass anything on.
    if attempt.submitted_at and (exam.mode == Exam.OPEN or exam.phase() == Exam.ENDED):
        order = {qid: i for i, qid in enumerate(attempt.question_ids)}
        answers = sorted(attempt.answers.select_related('question', 'choice'), key=lambda a: order.get(a.question_id, 0))
        context.update(show_score=True, selections=[(a.question.text, a.choice.text) for a in answers])
    return render(request, 'quiz/exam/done.html', context)
