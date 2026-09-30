from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .exams import (QUESTION_ROWS, STUDENT_ROWS, create_questions, parse_allowed, parse_questions,
                    read_student_list, template_bytes)
from .forms import ExamForm
from .models import Exam, ExamAllowed, Question
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
            rows, errors = parse_questions(upload.read(), upload.name)
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
        if action == 'seats' and exam.allowed.exists():
            messages.error(request, 'This exam has a class list, so seats follow the list automatically.')
        elif action == 'seats':
            new = request.POST.get('seat_limit', '')
            if new.isdigit() and int(new) > exam.seat_limit:  # raise only
                exam.seat_limit = int(new)
                exam.save(update_fields=['seat_limit'])
                messages.success(request, f'Seat limit raised to {exam.seat_limit}.')
            else:
                messages.error(request, f'Enter a number higher than the current limit ({exam.seat_limit}).')
        elif action == 'open' and exam.status == Exam.DRAFT:
            exam.status = Exam.LOBBY if exam.mode == Exam.SCHEDULED else Exam.RUNNING
            exam.save(update_fields=['status'])
            messages.success(request, 'Exam is now open for students.')
        elif action == 'allow':
            text, error = request.POST.get('students', ''), None
            if request.FILES.get('students_file'):
                try:
                    text += '\n' + read_student_list(request.FILES['students_file'].read(), request.FILES['students_file'].name)
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
        **_live_context(exam),
    })


ROSTER_LIMIT = 300  # keeps the 5-second refresh light for big classes


def _roster(exam):
    """[(name, joined)]: the class list with ticks, or (without a list) the students who have joined."""
    if exam.allowed.exists():
        joined = {e.lower() for e in exam.attempts.values_list('user__email', flat=True)}
        emails = exam.allowed.order_by('email').values_list('email', flat=True)[:ROSTER_LIMIT]
        return [(e.split('@')[0], e.lower() in joined) for e in emails]
    names = exam.attempts.order_by('created_at').values_list('user__username', flat=True)[:ROSTER_LIMIT]
    return [(n, True) for n in names]


def _live_context(exam):
    return {
        'roster': _roster(exam),
        'exam': exam,
        'has_list': exam.allowed.exists(),
        'seats_used': exam.attempts.count(),
        # still turned away = tried but never got a seat
        'denied': exam.denied.exclude(user__in=exam.attempts.values('user')).select_related('user').order_by('-last_at'),
        # reconnected = came back through the link after already joining (wifi drop etc.)
        'reconnected': exam.attempts.filter(rejoins__gt=0).select_related('user').order_by('-last_rejoin_at')[:100],
    }


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
