"""Running an exam: per-student order, deadlines, scoring. Pure logic, no request handling."""
import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Exam, ExamAttempt

COUNTDOWN_SECONDS = 30  # between the teacher pressing Start and the first question
GRACE_SECONDS = 5       # slack for the last autosave / submit travelling over the network


def start_exam(exam, now=None):
    """Teacher pressed Start on a lobby exam: everyone starts together after the countdown."""
    now = now or timezone.now()
    exam.starts_at = now + timedelta(seconds=COUNTDOWN_SECONDS)
    exam.ends_at = exam.starts_at + timedelta(minutes=exam.duration_minutes)
    exam.status = Exam.RUNNING
    exam.save(update_fields=['starts_at', 'ends_at', 'status'])


def end_exam(exam, now=None):
    """Teacher ended the exam early (or closed an open exam): stop the clock, submit everyone."""
    now = now or timezone.now()
    exam.status = Exam.ENDED
    if exam.ends_at and exam.ends_at > now:
        exam.ends_at = now
    exam.save(update_fields=['status', 'ends_at'])
    finalize_expired(exam, now)


def shuffled_choices(attempt_pk, question_pk, choices):
    """Choices in this student's own stable random order (same on every reload, different per student)."""
    choices = sorted(choices, key=lambda c: c.id)
    random.Random(f'{attempt_pk}:{question_pk}').shuffle(choices)
    return choices


def sectioned_order(id_points):
    """Question ids as sections by marks (1-mark first, then 2-mark, ...), shuffled within each section."""
    sections = {}
    for qid, points in id_points:
        sections.setdefault(points, []).append(qid)
    rng = random.SystemRandom()
    ids = []
    for points in sorted(sections):
        rng.shuffle(sections[points])
        ids += sections[points]
    return ids


def begin_attempt(attempt, now=None):
    """First time the student reaches the questions: shuffle once, start their clock. Idempotent."""
    now = now or timezone.now()
    with transaction.atomic():
        a = ExamAttempt.objects.select_for_update().select_related('exam').get(pk=attempt.pk)
        if a.started_at is None:
            a.question_ids = sectioned_order(a.exam.questions.values_list('id', 'points'))
            a.started_at = now
            a.ends_at = a.exam.ends_at  # None for open exams (no timer); late joiners simply have less time
            a.save(update_fields=['question_ids', 'started_at', 'ends_at'])
        return a


def is_closed(attempt, now=None):
    """True once this student can no longer change answers (submitted, exam ended, or past their deadline)."""
    now = now or timezone.now()
    if attempt.submitted_at:
        return True
    if attempt.exam.status == Exam.ENDED:
        return True
    return bool(attempt.ends_at and now > attempt.ends_at + timedelta(seconds=GRACE_SECONDS))


def finalize(attempt, now=None):
    """Score and lock an attempt. Safe to call twice."""
    now = now or timezone.now()
    with transaction.atomic():
        a = ExamAttempt.objects.select_for_update().get(pk=attempt.pk)
        if a.submitted_at:
            return a
        questions = {q.pk: q.points for q in a.exam.questions.filter(pk__in=a.question_ids)}
        correct = set(a.answers.filter(choice__is_correct=True).values_list('question_id', flat=True))
        a.total_points = sum(questions.values())
        a.score = sum(points for qid, points in questions.items() if qid in correct)
        a.submitted_at = min(now, a.ends_at) if a.ends_at else now  # a late auto-submit is stamped at the deadline
        a.save(update_fields=['total_points', 'score', 'submitted_at'])
        return a


def finalize_expired(exam, now=None):
    """Submit every started attempt that ran out of time. Called whenever someone looks at the exam."""
    now = now or timezone.now()
    for a in exam.attempts.filter(started_at__isnull=False, submitted_at__isnull=True).select_related('exam'):
        if is_closed(a, now):
            finalize(a, now)
