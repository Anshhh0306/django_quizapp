import random
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib.auth.models import User
from .models import Question, Choice, UserQuiz, Category, UserAnswer
from .forms import RegisterForm
from .ratelimit import rate_limit
from django.contrib.auth import login as auth_login
from django.db.models import Count, Avg
from .models import UserStatistics

PRAISES = ["Well done!", "Good job!", "Smarty!", "Legend!", "Bingo!"]
ROASTS = ["Oh come on!", "Not quite...", "Oh well", "Try harder!", "*sighs in disappointment*"]

def random_message(correct=True):
    return random.choice(PRAISES if correct else ROASTS)

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.urls import reverse
from .tokens import email_verification_token
from django.conf import settings

def _send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    verification_url = request.build_absolute_uri(reverse('verify_email', args=[uid, token]))
    message = render_to_string('quiz/email/verification_email.txt', {
        'user': user,
        'verification_url': verification_url,
    })
    send_mail(
        'Verify your SRMIST email address',
        message,
        'noreply@quizplatform.com',
        [user.email],
        fail_silently=False,
    )

@rate_limit('register', 10, 3600)
def register(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            _send_verification_email(request, user)
            return render(request, 'quiz/verification_sent.html', {'email': user.email})
    else:
        form = RegisterForm()
    return render(request, 'quiz/register.html', {'form': form})

def verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and email_verification_token.check_token(user, token):
        user.is_active = True
        user.save()
        return render(request, 'quiz/verification_success.html')
    else:
        return render(request, 'quiz/verification_failed.html')

@rate_limit('resend', 5, 3600, field='email')
def resend_verification(request):
    if request.method == 'POST':
        user = User.objects.filter(email__iexact=request.POST.get('email', ''), is_active=False).first()
        if user:
            _send_verification_email(request, user)
            return render(request, 'quiz/verification_sent.html', {'email': user.email})
    return redirect('register')

def home(request):
    context = {}
    if request.user.is_authenticated:
        categories = Category.objects.all()
        # Add user progress for each category
        for category in categories:
            try:
                quiz = UserQuiz.objects.get(user=request.user, category=category)
                category.completed = quiz.completed
                category.score = quiz.score
                category.total_questions = quiz.total_questions
            except UserQuiz.DoesNotExist:
                category.completed = False
        context['categories'] = categories
    return render(request, 'quiz/home.html', context)

@login_required
def anti_cheat_warning(request, category_id):
    """Show anti-cheat warning before starting quiz"""
    category = get_object_or_404(Category, pk=category_id)
    
    # Check if already taken this category
    userquiz = UserQuiz.objects.filter(user=request.user, category=category).first()
    if userquiz and userquiz.completed:
        return redirect('already_taken')
    
    return render(request, 'quiz/anti_cheat_warning.html', {
        'category': category
    })

QUESTIONS_PER_QUIZ = 10
GRACE_SECONDS = 3  # slack for network latency on the server-side timer

def _finish(userquiz):
    userquiz.total_questions = len(userquiz.question_ids)
    userquiz.total_points = sum(
        Question.objects.filter(id__in=userquiz.question_ids).values_list('points', flat=True)
    )
    userquiz.completed = True
    userquiz.taken_on = timezone.now()
    userquiz.save()

def _record_answer(userquiz, question, choice, elapsed):
    """Save an answer (choice=None means timed out), score it, advance to the next question."""
    correct = bool(choice and choice.is_correct and elapsed <= question.time_limit + GRACE_SECONDS)
    UserAnswer.objects.update_or_create(
        user_quiz=userquiz,
        question=question,
        defaults={
            'selected_choice': choice,
            'is_correct': correct,
            'time_taken': round(min(elapsed, question.time_limit), 1),
        },
    )
    userquiz.score += correct
    userquiz.current_index += 1
    userquiz.question_started_at = None
    userquiz.save()
    return correct

@login_required
def start_quiz(request, category_id):
    category = get_object_or_404(Category, pk=category_id)
    userquiz, _ = UserQuiz.objects.get_or_create(user=request.user, category=category)
    if userquiz.completed:
        return redirect('already_taken')

    # Only pick questions once; restarting resumes instead of resetting progress
    if not userquiz.question_ids:
        ids = list(Question.objects.filter(category=category).values_list('id', flat=True))
        if not ids:
            return render(request, 'quiz/error.html',
                          {'message': 'No questions available in this category.'})
        random.shuffle(ids)
        userquiz.question_ids = ids[:QUESTIONS_PER_QUIZ]
        userquiz.save()

    request.session['category_id'] = category_id
    return redirect('question')

@login_required
def question_view(request):
    category_id = request.session.get('category_id')
    if not category_id:
        return redirect('home')

    userquiz = get_object_or_404(UserQuiz, user=request.user, category_id=category_id)
    if userquiz.completed:
        return redirect('already_taken')
    if not userquiz.question_ids:
        return redirect('start_quiz', category_id=category_id)

    idx = userquiz.current_index
    total = len(userquiz.question_ids)
    if idx >= total:
        return redirect('result')

    question = get_object_or_404(Question, pk=userquiz.question_ids[idx])

    # The clock starts when the question is first served and survives reloads
    if userquiz.question_started_at is None:
        userquiz.question_started_at = timezone.now()
        userquiz.save()
    elapsed = (timezone.now() - userquiz.question_started_at).total_seconds()
    limit = question.time_limit

    if elapsed > limit + GRACE_SECONDS:  # left and came back after time was up
        _record_answer(userquiz, question, None, elapsed)
        return redirect('question')

    def question_page(error=None):
        choices = list(question.choices.all())
        random.shuffle(choices)  # Randomize choice order
        return render(request, 'quiz/question.html', {
            'question': {'text': question.text, 'time_limit': max(1, round(limit - elapsed))},
            'choices': [{'id': c.id, 'text': c.text} for c in choices],  # no correct-answer info
            'error': error,
            'progress_percentage': (idx / total) * 100,
            'current_question': idx + 1,
            'total_questions': total,
        })

    if request.method != 'POST':
        return question_page()

    choice_id = request.POST.get('choice', '')
    choice = None
    if choice_id.isdigit():  # must belong to this question
        choice = Choice.objects.filter(pk=choice_id, question=question).first()
    correct_choice = question.choices.filter(is_correct=True).first()

    # Anti-cheat early submission: score what was answered and end the quiz
    if request.POST.get('early_submission') == 'true':
        if choice:
            _record_answer(userquiz, question, choice, elapsed)
        _finish(userquiz)
        request.session['anti_cheat_violation'] = True
        return redirect('result')

    if choice is None:
        if elapsed < limit - GRACE_SECONDS:
            return question_page('Pick an option!')
        _record_answer(userquiz, question, None, elapsed)  # client timer ran out
        return render(request, 'quiz/feedback_anticheat.html', {
            'question': question,
            'correct': False,
            'message': "Time's up!",
            'correct_choice': correct_choice,
            'is_last': idx == total - 1,
            'timed_out': True,
        })

    correct = _record_answer(userquiz, question, choice, elapsed)
    return render(request, 'quiz/feedback_anticheat.html', {
        'question': question,
        'choice': choice,
        'correct': correct,
        'message': random_message(correct=correct),
        'correct_choice': correct_choice,
        'explanation': choice.explanation,
        'is_last': idx == total - 1,
        'time_taken': round(elapsed),
        'time_limit': limit,
    })

@login_required
def result(request):
    category_id = request.session.get('category_id')
    if not category_id:
        return redirect('home')

    category = get_object_or_404(Category, pk=category_id)
    userquiz = get_object_or_404(UserQuiz, user=request.user, category=category)

    if not userquiz.completed:
        if not userquiz.question_ids:
            return redirect('home')
        done = userquiz.current_index >= len(userquiz.question_ids)
        # Mid-quiz, only an anti-cheat redirect (?violation=...) may end the quiz early
        if not (done or request.GET.get('violation')):
            return redirect('question')
        _finish(userquiz)
        if not done:
            request.session['anti_cheat_violation'] = True

    anti_cheat_violation = request.session.pop('anti_cheat_violation', False)
    total_questions = userquiz.total_questions
    total_points = userquiz.total_points
    score = userquiz.score
    attempted_questions = userquiz.user_answers.count()

    return render(request, 'quiz/result.html', {
        'category': category,
        'score': score,
        'total_points': total_points,
        'total_questions': total_questions,
        'attempted_questions': attempted_questions,
        'unattempted_questions': total_questions - attempted_questions,
        'wrong_answers': attempted_questions - score,  # Wrong from attempted
        'passing_score': total_points // 2,
        'correct_percentage': round(score / total_questions * 100, 1) if total_questions else 0,
        'points_percentage': round(score / total_points * 100, 1) if total_points else 0,
        'taken_on': userquiz.taken_on,
        'anti_cheat_violation': anti_cheat_violation,
    })


@login_required
def already_taken(request):
    return render(request, 'quiz/already_taken.html')

@login_required
def leaderboard(request):
    # Get overall leaderboard
    top_users = UserStatistics.objects.select_related('user').order_by('-total_points')[:10]
    
    # Get category-specific stats with calculated percentages and tie handling
    category_leaders = {}
    for category in Category.objects.all():
        all_leaders = UserQuiz.objects.filter(category=category, completed=True) \
            .select_related('user') \
            .order_by('-score')
        
        if not all_leaders.exists():
            category_leaders[category] = []
            continue
            
        # Group leaders by score to handle ties
        score_groups = {}
        for quiz in all_leaders:
            score = quiz.score
            if score not in score_groups:
                score_groups[score] = []
            percentage = round((quiz.score / quiz.total_questions * 100), 1) if quiz.total_questions > 0 else 0
            score_groups[score].append({
                'quiz': quiz,
                'percentage': percentage
            })
        
        # Build ranked list with tie handling
        leaders = []
        current_rank = 1
        
        # Sort scores in descending order
        sorted_scores = sorted(score_groups.keys(), reverse=True)
        
        for score in sorted_scores:
            tied_users = score_groups[score]
            
            if len(tied_users) == 1:
                # Single user at this rank
                leaders.append({
                    'rank': current_rank,
                    'is_tie': False,
                    'users': tied_users,
                    'score': score
                })
            else:
                # Multiple users tied at this rank
                leaders.append({
                    'rank': current_rank,
                    'is_tie': True,
                    'users': tied_users,
                    'score': score,
                    'tie_count': len(tied_users)
                })
            
            current_rank += len(tied_users)
            
            # Stop after we have enough ranks to show top 5 positions
            if current_rank > 5:
                break
        
        category_leaders[category] = leaders
    
    # Get user's stats and rank
    try:
        user_stats = UserStatistics.objects.get(user=request.user)
    except UserStatistics.DoesNotExist:
        user_stats = None
    
    # Calculate some global statistics
    total_quizzes = UserQuiz.objects.filter(completed=True).count()
    
    # Calculate proper average score as percentage
    completed_quizzes = UserQuiz.objects.filter(completed=True)
    total_scores = sum(quiz.score for quiz in completed_quizzes)
    total_questions = sum(quiz.total_questions for quiz in completed_quizzes)
    avg_score = (total_scores / total_questions * 100) if total_questions > 0 else 0
    
    context = {
        'top_users': top_users,
        'category_leaders': category_leaders,
        'user_stats': user_stats,
        'total_quizzes': total_quizzes,
        'avg_score': round(avg_score, 1)  # Round to 1 decimal place
    }
    
    return render(request, 'quiz/leaderboard.html', context)

@login_required
def user_profile(request):
    try:
        stats = UserStatistics.objects.get(user=request.user)
    except UserStatistics.DoesNotExist:
        stats = None
        
    # Get user's quiz history
    quiz_history = UserQuiz.objects.filter(
        user=request.user,
        completed=True
    ).select_related('category').order_by('-taken_on')
    
    # Calculate performance by category
    category_performance = {}
    for category in Category.objects.all():
        quizzes = UserQuiz.objects.filter(
            user=request.user,
            category=category,
            completed=True
        )
        if quizzes.exists():
            # Calculate the average score as a percentage
            quiz_scores = []
            for quiz in quizzes:
                score_percentage = (quiz.score / quiz.total_questions * 100) if quiz.total_questions > 0 else 0
                quiz_scores.append(score_percentage)
            
            avg_score = round(sum(quiz_scores) / len(quiz_scores), 1)
            best_quiz = quizzes.order_by('-score').first()
            best_score = round((best_quiz.score / best_quiz.total_questions * 100), 1) if best_quiz.total_questions > 0 else 0
            
            category_performance[category] = {
                'attempts': quizzes.count(),
                'avg_score': avg_score,
                'best_score': best_score
            }
    
    context = {
        'stats': stats,
        'quiz_history': quiz_history,
        'category_performance': category_performance
    }
    
    return render(request, 'quiz/user_profile.html', context)

@login_required
def view_results(request, category_id):
    category = get_object_or_404(Category, pk=category_id)
    userquiz = get_object_or_404(UserQuiz, user=request.user, category=category)
    
    # Calculate percentages and wrong answers for consistency with result view
    correct_percentage = (userquiz.score / userquiz.total_questions) * 100 if userquiz.total_questions else 0
    points_percentage = (userquiz.score / userquiz.total_points) * 100 if userquiz.total_points else 0
    wrong_answers = userquiz.total_questions - userquiz.score
    
    return render(request, 'quiz/result.html', {
        'category': category,
        'score': userquiz.score,
        'total_questions': userquiz.total_questions,
        'attempted_questions': userquiz.total_questions,  # For completed quizzes
        'unattempted_questions': 0,  # For completed quizzes
        'total_points': userquiz.total_points,
        'wrong_answers': wrong_answers,
        'passing_score': userquiz.total_points // 2,
        'taken_on': userquiz.taken_on,
        'correct_percentage': correct_percentage,
        'points_percentage': points_percentage,
        'anti_cheat_violation': False  # No violation for completed quizzes
    })

@login_required
def quiz_review(request, category_id):
    """View to review questions and answers from a completed quiz"""
    category = get_object_or_404(Category, pk=category_id)
    
    # Get the user's quiz attempt
    try:
        userquiz = UserQuiz.objects.get(user=request.user, category=category, completed=True)
    except UserQuiz.DoesNotExist:
        return redirect('home')
    
    # Get all user answers for this quiz with related question and choice data
    user_answers = userquiz.user_answers.select_related(
        'question', 'selected_choice'
    ).order_by('question__id')
    
    # If no user answers exist (old quiz), get questions and show them without user answers
    if not user_answers.exists():
        questions = Question.objects.filter(category=category).prefetch_related('choices')
        review_data = []
        for question in questions:
            choices = question.choices.all()
            correct_choice = choices.filter(is_correct=True).first()
            
            review_data.append({
                'question': question,
                'choices': choices,
                'correct_choice': correct_choice,
                'user_choice': None,
                'is_correct': None,
                'time_taken': 0,
            })
    else:
        # Build review data from user answers
        review_data = []
        for user_answer in user_answers:
            question = user_answer.question
            choices = question.choices.all()
            correct_choice = choices.filter(is_correct=True).first()
            
            review_data.append({
                'question': question,
                'choices': choices,
                'correct_choice': correct_choice,
                'user_choice': user_answer.selected_choice,
                'is_correct': user_answer.is_correct,
                'time_taken': user_answer.time_taken,
            })
    
    context = {
        'category': category,
        'userquiz': userquiz,
        'review_data': review_data,
        'total_questions': len(review_data),
    }
    
    return render(request, 'quiz/quiz_review.html', context)

# Custom Password Reset Views using SRMIST verification
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator

@rate_limit('pwreset', 5, 3600, field='email')
def custom_password_reset(request):
    """Custom password reset that integrates with SRMIST email verification"""
    if request.method == 'POST':
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            
            # Check if user exists and has SRMIST email
            try:
                user = User.objects.get(email=email)
                
                # Verify it's a SRMIST email
                if not email.endswith('@srmist.edu.in'):
                    return render(request, 'quiz/password_reset.html', {
                        'form': form,
                        'error': 'Password reset is only available for SRMIST email addresses (@srmist.edu.in)'
                    })
                
                # Check if user is verified
                if not user.is_active:
                    return render(request, 'quiz/password_reset.html', {
                        'form': form,
                        'error': 'Your email address is not verified. Please verify your email first.'
                    })
                
                # Generate password reset token using our verification system
                mail_subject = 'Password Reset - SRMIST Quiz Platform'
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_url = request.build_absolute_uri(
                    reverse('password_reset_confirm', args=[uid, token]))
                
                message = render_to_string('quiz/email/password_reset_email.txt', {
                    'user': user,
                    'reset_url': reset_url,
                    'site_name': 'SRMIST Quiz Platform',
                })
                
                # Send password reset email using our system
                send_mail(
                    mail_subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                
                return render(request, 'quiz/password_reset_done.html', {
                    'email': user.email
                })
                
            except User.DoesNotExist:
                # Don't reveal if email exists or not for security
                return render(request, 'quiz/password_reset_done.html', {
                    'email': email
                })
                
    else:
        form = PasswordResetForm()
    
    return render(request, 'quiz/password_reset.html', {'form': form})

def custom_password_reset_confirm(request, uidb64, token):
    """Custom password reset confirm using our verification token"""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        # Valid token, show password reset form
        if request.method == 'POST':
            from django.contrib.auth.forms import SetPasswordForm
            form = SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                return redirect('password_reset_complete')
        else:
            from django.contrib.auth.forms import SetPasswordForm
            form = SetPasswordForm(user)
        
        return render(request, 'quiz/password_reset_confirm.html', {
            'form': form,
            'validlink': True
        })
    else:
        # Invalid token
        return render(request, 'quiz/password_reset_confirm.html', {
            'validlink': False
        })

def password_reset_complete(request):
    """Password reset complete view"""
    return render(request, 'quiz/password_reset_complete.html')
