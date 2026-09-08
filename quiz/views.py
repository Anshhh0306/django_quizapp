import random
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib.auth.models import User
from .models import Question, Choice, UserQuiz, Category, UserAnswer
from .forms import RegisterForm
from django.contrib.auth import login as auth_login
from django.db.models import Count, Avg
from .models import UserStatistics

PRAISES = ["Well done!", "Good job!", "Smarty!", "Legend!", "Bingo!"]
ROASTS = ["Oh Come on!", "Idiot!", "Ghosh... Oh well", "Try harder!", "Dumbass *sighs in disappointment*"]

def random_message(correct=True):
    return random.choice(PRAISES if correct else ROASTS)

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.sites.shortcuts import get_current_site
from .tokens import email_verification_token
from django.conf import settings

def register(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            
            # Generate verification token
            current_site = get_current_site(request)
            mail_subject = 'Verify your SRMIST email address'
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = email_verification_token.make_token(user)
            
            verification_url = f"http://{current_site.domain}/verify/{uid}/{token}/"
            
            message = render_to_string('quiz/email/verification_email.txt', {
                'user': user,
                'verification_url': verification_url,
            })
            
            # Send verification email
            send_mail(
                mail_subject,
                message,
                'noreply@quizplatform.com',
                [user.email],
                fail_silently=False,
            )
            
            return render(request, 'quiz/verification_sent.html', {
                'email': user.email
            })
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

def resend_verification(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email, is_active=False)
            
            current_site = get_current_site(request)
            mail_subject = 'Verify your SRMIST email address'
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = email_verification_token.make_token(user)
            
            verification_url = f"http://{current_site.domain}/verify/{uid}/{token}/"
            
            message = render_to_string('quiz/email/verification_email.txt', {
                'user': user,
                'verification_url': verification_url,
            })
            
            send_mail(
                mail_subject,
                message,
                'noreply@quizplatform.com',
                [user.email],
                fail_silently=False,
            )
            
            return render(request, 'quiz/verification_sent.html', {
                'email': user.email
            })
        except User.DoesNotExist:
            pass
    
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

@login_required
def start_quiz(request, category_id):
    category = get_object_or_404(Category, pk=category_id)
    
    # Check if already taken this category
    userquiz = UserQuiz.objects.filter(user=request.user, category=category).first()
    if userquiz and userquiz.completed:
        return redirect('already_taken')
    
    # Create or reset UserQuiz for this category
    userquiz, _ = UserQuiz.objects.get_or_create(user=request.user, category=category)
    if not userquiz.completed:  # Only reset if not completed
        userquiz.score = 0
        userquiz.save()

    # Check if questions are already in session
    if 'quiz_qs' in request.session:
        selected = request.session['quiz_qs']
    else:
        # Get 10 random questions from this category
        qs = list(Question.objects.filter(category=category))
        random.shuffle(qs)
        qs = qs[:10]
        selected = [q.id for q in qs]

    if not selected:
        return render(request, 'quiz/error.html', 
                     {'message': 'No questions available in this category.'})

    # save to session
    request.session['quiz_qs'] = selected
    request.session['quiz_idx'] = 0
    request.session['quiz_score'] = 0
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

    quiz_qs = request.session.get('quiz_qs')
    if not quiz_qs:
        return redirect('start_quiz', category_id=category_id)

    idx = request.session.get('quiz_idx', 0)
    if idx >= len(quiz_qs):
        return redirect('result')

    qid = quiz_qs[idx]
    question = get_object_or_404(Question, pk=qid)
    choices = list(question.choices.all())
    random.shuffle(choices)  # Randomize choice order

    if request.method == 'POST':
        choice_id = request.POST.get('choice')
        time_taken = int(request.POST.get('time_taken', question.time_limit))
        early_submission = request.POST.get('early_submission', 'false') == 'true'
        
        # Handle anti-cheat early submission
        if early_submission:
            # Mark quiz as completed with current progress
            userquiz.completed = True
            userquiz.score = request.session.get('quiz_score', 0)
            
            # Store both attempted and total questions  
            total_questions_count = len(quiz_qs)  # Total questions in quiz
            
            # Set total_questions to the actual total (not just attempted)
            userquiz.total_questions = total_questions_count
            
            # Calculate total points for ALL questions (not just attempted)
            all_questions = Question.objects.filter(id__in=quiz_qs)
            userquiz.total_points = sum(q.points for q in all_questions)
            userquiz.taken_on = timezone.now()
            userquiz.save()
            
            # Save the current answer if a choice was made
            if choice_id:
                choice = get_object_or_404(Choice, pk=choice_id)
                correct = choice.is_correct and time_taken < question.time_limit
                
                UserAnswer.objects.update_or_create(
                    user_quiz=userquiz,
                    question=question,
                    defaults={
                        'selected_choice': choice,
                        'is_correct': correct,
                        'time_taken': time_taken
                    }
                )
                
                if correct:
                    userquiz.score += 1
                    userquiz.save()
            
            # Store early submission info in session
            request.session['anti_cheat_violation'] = True
            
            # Cleanup quiz session but keep anti-cheat info
            for k in ['quiz_qs', 'quiz_idx', 'quiz_score', 'category_id']:
                request.session.pop(k, None)
            
            return redirect('result')
        
        # Store current question state
        request.session['current_question'] = {
            'id': qid,
            'idx': idx
        }
        request.session.modified = True
        
        # If time ran out and no choice was made
        if not choice_id and time_taken >= question.time_limit:
            # Save user answer as no answer (timed out)
            UserAnswer.objects.update_or_create(
                user_quiz=userquiz,
                question=question,
                defaults={
                    'selected_choice': None,
                    'is_correct': False,
                    'time_taken': time_taken
                }
            )
            
            context = {
                'question': question,
                'correct': False,
                'message': "Time's up!",
                'correct_choice': question.choices.filter(is_correct=True).first(),
                'is_last': (idx == len(quiz_qs)-1),
                'timed_out': True
            }
            request.session['quiz_idx'] = idx + 1
            return render(request, 'quiz/feedback_anticheat.html', context)
            
        if not choice_id:
            return render(request, 'quiz/question.html', {
                'question': question,
                'choices': choices,
                'error': 'Pick an option!',
                'progress_percentage': (idx / len(quiz_qs)) * 100,
                'current_question': idx + 1,
                'total_questions': len(quiz_qs)
            })

        choice = get_object_or_404(Choice, pk=choice_id)
        correct = choice.is_correct and time_taken < question.time_limit
        message = random_message(correct=correct)

        # Save user answer for review
        UserAnswer.objects.update_or_create(
            user_quiz=userquiz,
            question=question,
            defaults={
                'selected_choice': choice,
                'is_correct': correct,
                'time_taken': time_taken
            }
        )

        # update score and session
        if correct:
            request.session['quiz_score'] = request.session.get('quiz_score', 0) + 1

        # prepare context showing feedback immediately
        context = {
            'question': question,
            'choice': choice,
            'correct': correct,
            'message': message,
            'correct_choice': question.choices.filter(is_correct=True).first(),
            'explanation': choice.explanation,
            'is_last': (idx == len(quiz_qs)-1),
            'time_taken': time_taken,
            'time_limit': question.time_limit
        }

        # increment index for next visit
        request.session['quiz_idx'] = idx + 1
        return render(request, 'quiz/feedback_anticheat.html', context)

    # Create safe versions of choices without correct answer information
    safe_choices = [{
        'id': choice.id,
        'text': choice.text
    } for choice in choices]

    return render(request, 'quiz/question.html', {
        'question': {
            'text': question.text,
            'time_limit': question.time_limit
        },
        'choices': safe_choices,
        'progress_percentage': (idx / len(quiz_qs)) * 100,
        'current_question': idx + 1,
        'total_questions': len(quiz_qs)
    })

@login_required
def result(request):
    category_id = request.session.get('category_id')
    if not category_id:
        return redirect('home')
        
    category = get_object_or_404(Category, pk=category_id)
    userquiz = get_object_or_404(UserQuiz, user=request.user, category=category)
    
    if userquiz.completed and userquiz.taken_on:
        # Calculate percentages for completed quiz
        correct_percentage = (userquiz.score / userquiz.total_questions) * 100 if userquiz.total_questions else 0
        points_percentage = (userquiz.score / userquiz.total_points) * 100 if userquiz.total_points else 0
        wrong_answers = userquiz.total_questions - userquiz.score
        
        # Check for anti-cheat violation
        anti_cheat_violation = request.session.pop('anti_cheat_violation', False)
        
        # Calculate actual attempted questions from database records
        attempted_questions = UserAnswer.objects.filter(user_quiz=userquiz).count()
        unattempted_questions = userquiz.total_questions - attempted_questions
        
        return render(request, 'quiz/result.html', {
            'category': category,
            'score': userquiz.score,
            'total_points': userquiz.total_points,
            'total_questions': userquiz.total_questions,
            'attempted_questions': attempted_questions,
            'unattempted_questions': unattempted_questions,
            'wrong_answers': attempted_questions - userquiz.score,  # Wrong from attempted
            'passing_score': userquiz.total_points // 2,
            'taken_on': userquiz.taken_on,
            'correct_percentage': correct_percentage,
            'points_percentage': points_percentage,
            'anti_cheat_violation': anti_cheat_violation
        })

    # This should only run for NEW quiz completions, not existing ones
    quiz_qs = request.session.get('quiz_qs', [])
    questions = Question.objects.filter(id__in=quiz_qs)
    total_points = sum(q.points for q in questions)
    score = request.session.get('quiz_score', 0)
    total_questions = len(quiz_qs)
    
    # Calculate percentages
    correct_percentage = (score / total_questions) * 100 if total_questions else 0
    points_percentage = (score / total_points) * 100 if total_points else 0
    wrong_answers = total_questions - score
    
    # Round percentages to 1 decimal place
    correct_percentage = round(correct_percentage, 1)
    points_percentage = round(points_percentage, 1)
    
    # mark user as completed (no retake for this category)
    userquiz.score = score
    userquiz.total_questions = total_questions
    userquiz.total_points = total_points
    userquiz.completed = True
    userquiz.taken_on = timezone.now()
    userquiz.save()

    # cleanup session
    anti_cheat_violation = request.session.pop('anti_cheat_violation', False)
    
    # Calculate actual attempted questions from database records
    attempted_questions = UserAnswer.objects.filter(user_quiz=userquiz).count()
    unattempted_questions = total_questions - attempted_questions
    for k in ['quiz_qs', 'quiz_idx', 'quiz_score', 'category_id']:
        request.session.pop(k, None)

    return render(request, 'quiz/result.html', {
        'category': category,
        'score': score,
        'total_points': total_points,
        'total_questions': total_questions,
        'attempted_questions': attempted_questions,
        'unattempted_questions': unattempted_questions,
        'wrong_answers': attempted_questions - score,  # Wrong from attempted
        'passing_score': total_points // 2,
        'correct_percentage': correct_percentage,
        'points_percentage': points_percentage,
        'taken_on': timezone.now(),
        'anti_cheat_violation': anti_cheat_violation
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
                current_site = get_current_site(request)
                mail_subject = 'Password Reset - SRMIST Quiz Platform'
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = email_verification_token.make_token(user)
                
                reset_url = f"http://{current_site.domain}/accounts/reset/{uid}/{token}/"
                
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

    if user is not None and email_verification_token.check_token(user, token):
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
