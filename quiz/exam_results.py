"""Results for the teacher: per-student rows, class summary, and the table used for CSV / Excel download."""
from django.db.models import Count, Q

from .exam_run import finalize, finalize_expired, is_closed, scores_visible

HEADER = ['Student', 'Email', 'Status', 'Questions', 'Answered', 'Correct', 'Wrong', 'Unanswered',
          'Score', 'Out of', 'Percent', 'Time taken (m:ss)', 'Reconnects', 'Strikes', 'Left the window', 'Auto-submitted']
KEYS = ('name', 'email', 'status', 'questions', 'answered', 'right', 'wrong', 'unanswered',
        'score', 'total', 'percent', 'minutes', 'rejoins', 'strikes', 'leaves', 'auto')
FROZEN = 'Frozen: needs teacher'
STATUS_ORDER = {'Submitted': 0, FROZEN: 1, 'In progress': 2, 'Joined, did not start': 3, 'Did not join': 4}


def result_rows(exam, now=None):
    """One dict per student, best score first. Also submits anyone who ran out of time."""
    finalize_expired(exam, now)
    attempts = exam.attempts.select_related('user').annotate(
        answered=Count('answers'),
        right=Count('answers', filter=Q(answers__choice__is_correct=True)),
    )
    rows = []
    for a in attempts:
        total_q = len(a.question_ids)
        status = ('Submitted' if a.submitted_at else FROZEN if a.frozen_at else 'In progress' if a.started_at
                  else 'Joined, did not start')
        seconds = int((a.submitted_at - a.started_at).total_seconds()) if a.submitted_at and a.started_at else None
        rows.append({
            'attempt': a, 'name': a.user.username, 'email': a.user.email.lower(), 'status': status,
            'questions': total_q if a.started_at else None,
            'answered': a.answered if a.started_at else None,
            'right': a.right if a.started_at else None,
            'wrong': a.answered - a.right if a.started_at else None,
            'unanswered': max(total_q - a.answered, 0) if a.started_at else None,
            'score': a.score, 'total': a.total_points if a.submitted_at else None,
            'percent': round(a.score * 100 / a.total_points) if a.submitted_at and a.total_points else None,
            'minutes': f'{seconds // 60}:{seconds % 60:02d}' if seconds is not None else '',
            'rejoins': a.rejoins, 'strikes': a.strikes, 'leaves': a.leaves,
            'auto': 'Yes (strikes)' if a.submit_reason == 'strikes' else '',
        })
    rows.sort(key=lambda r: (STATUS_ORDER[r['status']], -(r['score'] or 0), r['name']))

    joined = {r['email'] for r in rows}
    for email in exam.allowed.order_by('email').values_list('email', flat=True):  # class list: who never came
        if email.lower() not in joined:
            rows.append({'attempt': None, 'name': email.split('@')[0], 'email': email.lower(), 'status': 'Did not join',
                         'questions': None, 'answered': None, 'right': None, 'wrong': None, 'unanswered': None,
                         'score': None, 'total': None, 'percent': None, 'minutes': '', 'rejoins': 0,
                         'strikes': 0, 'leaves': 0, 'auto': ''})
    return rows


def result_summary(rows):
    done = [r for r in rows if r['status'] == 'Submitted']
    percents = [r['percent'] for r in done if r['percent'] is not None]
    count = lambda status: sum(r['status'] == status for r in rows)
    return {
        'class_size': len(rows),
        'submitted': len(done),
        'in_progress': count('In progress'),
        'frozen': count(FROZEN),
        'not_started': count('Joined, did not start'),
        'absent': count('Did not join'),
        'average': round(sum(percents) / len(percents)) if percents else None,
        'highest': max(percents) if percents else None,
        'lowest': min(percents) if percents else None,
    }


def _safe(value):
    """Text that starts with = + - @ is run as a formula by Excel: make it plain text."""
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@'):
        return "'" + value
    return value


def result_table(rows):
    """Header + rows as plain lists, for the CSV / Excel download."""
    return [HEADER] + [['' if r[k] is None else _safe(r[k]) for k in KEYS] for r in rows]


def my_exam_cards(user):
    """The student's own exams for the home page: where each one stands and where to click next."""
    from django.urls import reverse
    cards = []
    for a in user.exam_attempts.select_related('exam').order_by('-created_at'):
        e = a.exam
        if a.started_at and not a.submitted_at and is_closed(a):  # ran out of time without pressing Submit
            a = finalize(a)
            a.exam = e
        phase = e.phase()
        score_visible = bool(a.submitted_at) and scores_visible(e)
        if a.submitted_at:
            state, page = 'Submitted', 'exam_done'
        elif phase == 'ended':
            state, page = ('Ended (not submitted)' if a.started_at else 'Ended (you did not start)'), 'exam_done'
        elif phase == 'running':
            state, page = ('In progress' if a.started_at else 'Open: start now'), 'exam_take'
        else:
            state, page = 'Waiting for the teacher to start', 'exam_lobby'
        cards.append({'title': e.title, 'state': state, 'url': reverse(page, args=[e.token]),
                      'score': a.score if score_visible else None, 'total': a.total_points,
                      'waiting_for_scores': bool(a.submitted_at) and not score_visible})
    return cards
