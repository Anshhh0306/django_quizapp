from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .exam_control import EXTEND_ALL_MINUTES, EXTRA_MINUTES, extend_all, grant_extra, reset_device, unfreeze
from .util import to_int
from .exam_results import result_rows, result_summary, result_table
from .exam_run import COUNTDOWN_SECONDS, end_exam, finalize_expired, start_exam
from .exams import (QUESTION_ROWS, STUDENT_ROWS, create_questions, parse_allowed, parse_questions, read_student_list,
                    read_upload, template_bytes)
from .forms import ExamForm
from .models import Exam, ExamAllowed, ExamAttempt, Question
from .roles import role_of


def teacher_required(view):
    """Approved teachers (and superadmins) only; everyone else is sent home."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if role_of(request.user) not in ('teacher', 'admin'):
            return redirect('home')
        return view(request, *args, **kwargs)
    return login_required(wrapper)


@teacher_required
def teach_home(request):
    return render(request, 'quiz/teacher/home.html', {'exams': request.user.exams.order_by('-created_at')})


@teacher_required
def question_bank(request):
    if request.method == 'POST':
        upload = request.FILES.get('file')
        if not upload:
            messages.error(request, 'Choose a CSV file first.')
        else:
            try:
                rows, errors = parse_questions(read_upload(upload), upload.name)
            except ValueError as e:
                rows, errors = [], [str(e)]
            if errors:  # all-or-nothing: fix the file and upload again
                return render(request, 'quiz/teacher/questions.html', {
                    'errors': errors, 'count': request.user.question_bank.count()})
            with transaction.atomic():
                added = create_questions(request.user, rows)
            messages.success(request, f'{added} question(s) added to your bank.')
            return redirect('question_bank')
    return render(request, 'quiz/teacher/questions.html', {'count': request.user.question_bank.count()})


@teacher_required
def exam_new(request):
    form = ExamForm(request.POST or None, request.FILES or None, owner=request.user)
    if request.method == 'POST' and form.is_valid():
        exam = form.save(commit=False)
        exam.owner = request.user
        with transaction.atomic():
            exam.save()
            form.save_m2m()
            ExamAllowed.objects.bulk_create(
                ExamAllowed(exam=exam, email=e) for e in form.cleaned_data['allowed_emails'])
        return redirect('exam_detail', pk=exam.pk)
    return render(request, 'quiz/teacher/exam_form.html', {'form': form, 'has_questions': request.user.question_bank.exists()})


@teacher_required
def exam_detail(request, pk):
    exam = get_object_or_404(Exam, pk=pk, owner=request.user)  # only your own exams
    if request.method == 'POST':
        action = request.POST.get('action')
        if action in ('seats', 'allow') and exam.phase() == Exam.ENDED:
            messages.error(request, 'This exam has ended, so the class list and seats are locked.')
        elif action == 'seats' and exam.allowed.exists():
            messages.error(request, 'This exam has a class list, so seats follow the list automatically.')
        elif action == 'seats':
            new = to_int(request.POST.get('seat_limit', ''))
            if new is not None and new > exam.seat_limit:  # raise only
                exam.seat_limit = new
                exam.save(update_fields=['seat_limit'])
                messages.success(request, f'Seat limit raised to {exam.seat_limit}.')
            else:
                messages.error(request, f'Enter a number higher than the current limit ({exam.seat_limit}).')
        elif action == 'open' and exam.status == Exam.DRAFT:
            if not exam.questions.exists():
                messages.error(request, 'This exam has no questions.')
            else:
                exam.status = Exam.LOBBY if exam.mode == Exam.SCHEDULED else Exam.RUNNING
                exam.save(update_fields=['status'])
                messages.success(request, 'Exam is now open for students.')
        elif action == 'start' and exam.mode == Exam.SCHEDULED and exam.status == Exam.LOBBY:
            start_exam(exam)
            messages.success(request, f'Starting in {COUNTDOWN_SECONDS} seconds for everyone in the lobby.')
        elif action == 'end' and exam.status in (Exam.LOBBY, Exam.RUNNING):
            end_exam(exam)
            messages.success(request, 'Exam ended. All answers so far were submitted.')
        elif action in ('unfreeze', 'extra_time', 'reset_device'):
            attempt_id = to_int(request.POST.get('attempt', ''))
            attempt = exam.attempts.filter(pk=attempt_id).select_related('user').first() if attempt_id is not None else None
            minutes = to_int(request.POST.get('minutes', ''))
            minutes = -1 if minutes is None else minutes
            if not attempt:
                messages.error(request, 'Student not found.')
            elif action == 'reset_device':
                error = reset_device(attempt, request.user)
                messages.error(request, error) if error else messages.success(
                    request, f'{attempt.user.username}: the next device they open the exam on will be accepted.')
            elif action == 'unfreeze':
                if minutes not in EXTRA_MINUTES:
                    messages.error(request, 'Choose how many extra minutes to give (0 for none).')
                elif unfreeze(attempt, 'new' if request.POST.get('device') == 'new' else 'original', minutes, request.user):
                    messages.success(request, f'{attempt.user.username} can continue.')
                else:
                    messages.error(request, f'{attempt.user.username} is not frozen.')
            else:
                error = grant_extra(attempt, minutes, request.user)
                messages.error(request, error) if error else messages.success(
                    request, f'{attempt.user.username} got {minutes} extra minutes.')
        elif action == 'extend_all':
            minutes = to_int(request.POST.get('minutes', ''))
            error = extend_all(exam, -1 if minutes is None else minutes, request.user)
            messages.error(request, error) if error else messages.success(request, f'Everyone got {minutes} extra minutes.')
        elif action == 'allow':
            text, error = request.POST.get('students', ''), None
            if request.FILES.get('students_file'):
                try:
                    text += '\n' + read_student_list(read_upload(request.FILES['students_file']), request.FILES['students_file'].name)
                except ValueError as e:
                    error = str(e)
            emails, bad = parse_allowed(text)
            if error:
                messages.error(request, error)
            elif bad:
                messages.error(request, f'Not valid student IDs: {", ".join(bad[:10])}. Nothing was added.')
            elif emails:
                have = set(exam.allowed.values_list('email', flat=True))
                ExamAllowed.objects.bulk_create(ExamAllowed(exam=exam, email=e) for e in emails if e not in have)
                exam.seat_limit = exam.allowed.count()  # seats follow the class list
                exam.save(update_fields=['seat_limit'])
                messages.success(request, f'{len(set(emails) - have)} student(s) added to the class list.')
        return redirect('exam_detail', pk=exam.pk)
    return render(request, 'quiz/teacher/exam_detail.html', {
        'exam': exam,
        'link': request.build_absolute_uri(reverse('exam_entry', args=[exam.token])),
        'question_count': exam.questions.count(),
        'allowed': exam.allowed.order_by('email'),
        'controls': _controls_context(exam),
        **_live_context(exam),
    })


ROSTER_LIMIT = 300  # keeps the 5-second refresh light for big classes


def _state(started_at, submitted_at, frozen_at=None):
    return 'submitted' if submitted_at else 'frozen' if frozen_at else 'answering' if started_at else 'lobby'


def _roster(exam):
    """[(name, state)] with state: absent / lobby / answering / submitted.

    The class list when there is one, otherwise the students who have joined, in join order.
    """
    rows = exam.attempts.values_list('user__email', 'user__username', 'started_at', 'submitted_at', 'frozen_at').order_by('created_at')
    if exam.allowed.exists():
        state = {email.lower(): _state(s, d, f) for email, _, s, d, f in rows}
        emails = exam.allowed.order_by('email').values_list('email', flat=True)[:ROSTER_LIMIT]
        return [(e.split('@')[0], state.get(e.lower(), 'absent')) for e in emails]
    return [(name, _state(s, d, f)) for _, name, s, d, f in rows[:ROSTER_LIMIT]]


def _live_context(exam):
    finalize_expired(exam)  # anyone who ran out of time without pressing Submit is submitted now
    attempts = exam.attempts
    return {
        'roster': _roster(exam),
        'exam': exam,
        'phase': exam.phase(),
        'started_count': attempts.filter(started_at__isnull=False).count(),
        'submitted_count': attempts.filter(submitted_at__isnull=False).count(),
        'has_list': exam.allowed.exists(),
        'seats_used': exam.attempts.count(),
        # still turned away = tried but never got a seat
        'denied': exam.denied.exclude(user__in=exam.attempts.values('user')).select_related('user').order_by('-last_at'),
        # reconnected = came back through the link after already joining (wifi drop etc.)
        'reconnected': exam.attempts.filter(rejoins__gt=0).select_related('user').order_by('-last_rejoin_at')[:100],
        # other browsers turned away while the student's own browser was working (to look into later)
        'intruders': exam.attempts.filter(intrusions__gt=0).select_related('user').order_by('-last_intrusion_at')[:50],
        'events': exam.events.select_related('actor')[:30],  # the audit log, newest first
    }


def _controls_context(exam):
    """Frozen seats and the extra-time boxes. Rendered on its own so typing in a dropdown is never wiped by a refresh."""
    frozen = list(exam.attempts.filter(frozen_at__isnull=False, submitted_at__isnull=True)
                  .select_related('user').order_by('frozen_at'))
    taking = list(exam.attempts.filter(started_at__isnull=False, submitted_at__isnull=True)
                  .select_related('user').order_by('user__username'))
    return {
        'exam': exam, 'frozen': frozen, 'taking': taking,
        'minutes': EXTRA_MINUTES, 'extend_minutes': EXTEND_ALL_MINUTES,
        'can_extend_all': exam.mode == Exam.SCHEDULED and exam.phase() == 'running',
        # the page only swaps this panel in when the sig changes (someone froze / unfroze / joined)
        'sig': '|'.join(f'{a.pk}:{a.freezes}' for a in frozen) + '#' + ','.join(str(a.pk) for a in taking),
    }


@teacher_required
def exam_controls(request, pk):
    exam = get_object_or_404(Exam, pk=pk, owner=request.user)
    return render(request, 'quiz/teacher/_exam_controls.html', _controls_context(exam))


@teacher_required
def exam_live(request, pk):
    """HTML fragment the exam page refreshes every few seconds."""
    exam = get_object_or_404(Exam, pk=pk, owner=request.user)
    return render(request, 'quiz/teacher/_exam_live.html', _live_context(exam))


def _download(request, rows, basename):
    data, content_type, ext = template_bytes(rows, request.GET.get('format'))
    response = HttpResponse(data, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{basename}.{ext}"'
    return response


@teacher_required
def question_template(request):
    return _download(request, QUESTION_ROWS, 'question_template')


@teacher_required
def student_template(request):
    return _download(request, STUDENT_ROWS, 'student_list_template')


@teacher_required
def exam_results(request, pk):
    exam = get_object_or_404(Exam, pk=pk, owner=request.user)
    rows = result_rows(exam)
    fmt = request.GET.get('format')
    if fmt in ('csv', 'xlsx'):
        data, content_type, ext = template_bytes(result_table(rows), fmt)
        response = HttpResponse(data, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="results_{exam.pk}.{ext}"'
        return response
    return render(request, 'quiz/teacher/results.html', {
        'exam': exam, 'rows': rows, 'summary': result_summary(rows), 'phase': exam.phase()})


@teacher_required
def exam_result_detail(request, pk, attempt_pk):
    """One student's answers next to the correct ones, for the teacher to evaluate."""
    exam = get_object_or_404(Exam, pk=pk, owner=request.user)
    attempt = get_object_or_404(ExamAttempt, pk=attempt_pk, exam=exam)
    finalize_expired(exam)
    attempt.refresh_from_db()
    chosen = {a.question_id: a.choice_id for a in attempt.answers.all()}
    questions = {q.pk: q for q in Question.objects.filter(pk__in=attempt.question_ids).prefetch_related('choices')}
    items = []
    for qid in attempt.question_ids:
        q = questions.get(qid)
        if not q:
            continue
        choices = list(q.choices.all())
        picked = next((c for c in choices if c.pk == chosen.get(qid)), None)
        right = next((c for c in choices if c.is_correct), None)
        items.append({'question': q, 'picked': picked, 'right': right,
                      'state': 'unanswered' if picked is None else 'correct' if picked.is_correct else 'wrong'})
    sections = {}
    for item in items:  # same section order the student saw: 1-mark, 2-mark, ...
        sections.setdefault(item['question'].points, []).append(item)
    sections = [{'marks': marks, 'items': group,
                 'earned': sum(i['question'].points for i in group if i['state'] == 'correct'),
                 'possible': marks * len(group)} for marks, group in sorted(sections.items())]
    return render(request, 'quiz/teacher/result_detail.html', {
        'exam': exam, 'attempt': attempt, 'items': items, 'sections': sections})
