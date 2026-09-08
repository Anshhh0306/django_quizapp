from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.management import call_command
from django.utils import timezone
from quiz.models import Category, Question, Choice, UserQuiz, UserAnswer, UserStatistics


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='srmuser',
            email='test@srmist.edu.in',
            password='Password123!'
        )
        self.category = Category.objects.create(
            name='Django Basics',
            description='Test category for Django fundamentals'
        )
        self.question = Question.objects.create(
            text='What command runs the development server?',
            category=self.category,
            time_limit=30,
            points=1
        )
        self.choice_correct = Choice.objects.create(
            question=self.question,
            text='python manage.py runserver',
            is_correct=True,
            explanation='Correct! runserver launches the local server.'
        )
        self.choice_wrong = Choice.objects.create(
            question=self.question,
            text='python manage.py startserver',
            is_correct=False,
            explanation='startserver is not a valid Django command.'
        )

    def test_category_string_representation(self):
        self.assertEqual(str(self.category), 'Django Basics')

    def test_question_string_representation(self):
        self.assertEqual(str(self.question), 'What command runs the development server?')

    def test_choice_string_representation(self):
        self.assertEqual(str(self.choice_correct), 'python manage.py runserver')

    def test_user_quiz_and_statistics(self):
        user_quiz = UserQuiz.objects.create(
            user=self.user,
            category=self.category,
            completed=True,
            score=1,
            total_questions=1,
            total_points=1,
            taken_on=timezone.now()
        )
        self.assertTrue(user_quiz.completed)
        self.assertIn('srmuser', str(user_quiz))

        # Check that post_save signal generated or updated UserStatistics
        stats = UserStatistics.objects.filter(user=self.user).first()
        self.assertIsNotNone(stats)
        self.assertEqual(stats.total_quizzes, 1)
        self.assertEqual(stats.total_points, 1)
        self.assertEqual(stats.average_score, 100.0)

    def test_user_answer_creation(self):
        user_quiz = UserQuiz.objects.create(
            user=self.user,
            category=self.category,
            completed=False
        )
        user_ans = UserAnswer.objects.create(
            user_quiz=user_quiz,
            question=self.question,
            selected_choice=self.choice_correct,
            is_correct=True,
            time_taken=12.5
        )
        self.assertTrue(user_ans.is_correct)
        self.assertIn('✓', str(user_ans))


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='student1',
            email='student1@srmist.edu.in',
            password='TestPassword123!'
        )
        self.category = Category.objects.create(
            name='Python',
            description='Python fundamentals'
        )
        self.question = Question.objects.create(
            text='Is Python an interpreted language?',
            category=self.category,
            time_limit=30,
            points=1
        )
        self.choice = Choice.objects.create(
            question=self.question,
            text='Yes',
            is_correct=True,
            explanation='Python is an interpreted language.'
        )

    def test_home_page_unauthenticated(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/home.html')

    def test_home_page_authenticated(self):
        self.client.login(username='student1', password='TestPassword123!')
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('categories', response.context)

    def test_anti_cheat_warning_view(self):
        self.client.login(username='student1', password='TestPassword123!')
        response = self.client.get(reverse('anti_cheat_warning', args=[self.category.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/anti_cheat_warning.html')

    def test_start_quiz_view(self):
        self.client.login(username='student1', password='TestPassword123!')
        response = self.client.get(reverse('start_quiz', args=[self.category.id]))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('question'))

        # Check session initialization
        session = self.client.session
        self.assertEqual(session['category_id'], self.category.id)
        self.assertEqual(session['quiz_idx'], 0)
        self.assertIn(self.question.id, session['quiz_qs'])

    def test_question_view_and_answer_submission(self):
        self.client.login(username='student1', password='TestPassword123!')
        # Initialize quiz session
        self.client.get(reverse('start_quiz', args=[self.category.id]))

        # GET question
        response = self.client.get(reverse('question'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/question.html')

        # POST answer
        post_response = self.client.post(reverse('question'), {
            'choice': self.choice.id,
            'time_taken': 10
        })
        self.assertEqual(post_response.status_code, 200)
        self.assertTemplateUsed(post_response, 'quiz/feedback_anticheat.html')
        self.assertTrue(post_response.context['correct'])

    def test_leaderboard_view(self):
        self.client.login(username='student1', password='TestPassword123!')
        response = self.client.get(reverse('leaderboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/leaderboard.html')

    def test_user_profile_view(self):
        self.client.login(username='student1', password='TestPassword123!')
        response = self.client.get(reverse('user_profile'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/user_profile.html')


class MiddlewareAndAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@srmist.edu.in',
            password='RegularPassword123!'
        )
        self.superuser = User.objects.create_superuser(
            username='superadmin',
            email='admin@srmist.edu.in',
            password='SuperPassword123!'
        )

    def test_admin_login_page_accessible(self):
        # Unauthenticated user should be able to view /admin/login/
        response = self.client.get('/admin/login/')
        self.assertEqual(response.status_code, 200)

    def test_admin_protected_for_regular_user(self):
        self.client.login(username='regular', password='RegularPassword123!')
        response = self.client.get('/admin/')
        # Non-superusers are denied and redirected to home
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('home'))

    def test_admin_accessible_for_superuser(self):
        self.client.login(username='superadmin', password='SuperPassword123!')
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)


class ManagementCommandTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Django', description='Django Category')

    def test_add_questions_command(self):
        call_command('add_questions')
        self.assertTrue(Question.objects.filter(category=self.category).exists())

    def test_clear_users_command(self):
        User.objects.create_user(username='dummy', email='dummy@srmist.edu.in', password='pass')
        User.objects.create_superuser(username='super', email='super@srmist.edu.in', password='pass')
        call_command('clear_users')
        self.assertFalse(User.objects.filter(username='dummy').exists())
        self.assertTrue(User.objects.filter(username='super').exists())
