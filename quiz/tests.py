from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.management import call_command
from django.utils import timezone
from django.core import mail
from django.core.cache import cache
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
            email='ab1234@srmist.edu.in',
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
        self.assertEqual(self.client.session['category_id'], self.category.id)
        userquiz = UserQuiz.objects.get(user=self.user, category=self.category)
        self.assertEqual(userquiz.current_index, 0)
        self.assertIn(self.question.id, userquiz.question_ids)

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


class QuizFlowTests(TestCase):
    """Regression tests for the restart / timer / result / reset-token holes."""

    def setUp(self):
        cache.clear()  # rate-limit counters live in the cache
        self.user = User.objects.create_user('s1', 'ab1234@srmist.edu.in', 'TestPassword123!')
        self.client.login(username='s1', password='TestPassword123!')
        self.cat = self._category('Python', 2)
        self.other = self._category('Django', 2)

    def _category(self, name, n):
        cat = Category.objects.create(name=name)
        for i in range(n):
            q = Question.objects.create(text=f'{name} q{i}', category=cat, time_limit=30)
            Choice.objects.create(question=q, text='right', is_correct=True)
            Choice.objects.create(question=q, text='wrong', is_correct=False)
        return cat

    def _uq(self, cat=None):
        return UserQuiz.objects.get(user=self.user, category=cat or self.cat)

    def _current(self, cat=None):
        return Question.objects.get(pk=self._uq(cat).question_ids[self._uq(cat).current_index])

    def _answer(self, correct=True, follow=False, **extra):
        c = self._current().choices.get(is_correct=correct)
        return self.client.post(reverse('question'), {'choice': c.id, **extra}, follow=follow)

    def test_restart_resumes_instead_of_resetting(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        self.client.get(reverse('question'))
        self._answer()
        self.client.get(reverse('start_quiz', args=[self.cat.id]))  # the "replay the answers" attempt
        uq = self._uq()
        self.assertEqual((uq.current_index, uq.score), (1, 1))

    def test_other_category_does_not_reuse_questions(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        self.client.get(reverse('start_quiz', args=[self.other.id]))
        ids = set(self._uq(self.other).question_ids)
        self.assertEqual(ids, set(self.other.questions.values_list('id', flat=True)))

    def test_server_timer_ignores_client_time_taken(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        self.client.get(reverse('question'))
        UserQuiz.objects.filter(pk=self._uq().pk).update(
            question_started_at=timezone.now() - timezone.timedelta(seconds=100))
        self._answer(time_taken=0)  # spoofed; server sees the answer is late
        self.assertEqual(self._uq().score, 0)
        self.assertFalse(UserAnswer.objects.get().is_correct)

    def test_bad_input_does_not_crash(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        self.client.get(reverse('question'))
        r = self.client.post(reverse('question'), {'choice': 'abc', 'time_taken': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['error'], 'Pick an option!')

    def test_choice_from_another_question_rejected(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        self.client.get(reverse('question'))
        foreign = Choice.objects.filter(question__category=self.other).first()
        r = self.client.post(reverse('question'), {'choice': foreign.id})
        self.assertEqual(r.context['error'], 'Pick an option!')
        self.assertEqual(self._uq().current_index, 0)

    def test_result_mid_quiz_does_not_end_quiz(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        r = self.client.get(reverse('result'))
        self.assertRedirects(r, reverse('question'))
        self.assertFalse(self._uq().completed)

    def test_violation_redirect_ends_quiz(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        self.client.get(reverse('question'))
        r = self.client.get(reverse('result') + '?violation=tab_switch')
        self.assertTrue(r.context['anti_cheat_violation'])
        self.assertTrue(self._uq().completed)

    def test_early_submission_shows_violation_result(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        self.client.get(reverse('question'))
        r = self._answer(early_submission='true', follow=True)
        self.assertTemplateUsed(r, 'quiz/result.html')
        self.assertTrue(r.context['anti_cheat_violation'])
        self.assertEqual(self._uq().score, 1)

    def test_full_quiz_completes_with_score(self):
        self.client.get(reverse('start_quiz', args=[self.cat.id]))
        for _ in range(2):
            self.client.get(reverse('question'))
            self._answer()
        r = self.client.get(reverse('result'))
        self.assertEqual((r.context['score'], r.context['total_questions']), (2, 2))
        self.assertEqual(r.context['wrong_answers'], 0)

    def test_password_reset_link_is_single_use(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        self.client.logout()
        self.user.refresh_from_db()  # login updated last_login, which is part of the token
        url = reverse('password_reset_confirm', args=[
            urlsafe_base64_encode(force_bytes(self.user.pk)),
            default_token_generator.make_token(self.user)])
        self.assertTrue(self.client.get(url).context['validlink'])
        self.client.post(url, {'new_password1': 'BrandNewPass!987', 'new_password2': 'BrandNewPass!987'})
        self.assertFalse(self.client.get(url).context['validlink'])

    def test_an_existing_address_is_recognised_in_any_letter_case_without_an_error_message(self):
        from quiz.forms import RegisterForm
        form = RegisterForm({'email': 'AB1234@SRMIST.EDU.IN'})
        self.assertTrue(form.is_valid())  # no error to show: the page must not say which addresses exist
        self.assertTrue(form.taken)
        fresh = RegisterForm({'email': 'ab9999@srmist.edu.in'})
        self.assertTrue(fresh.is_valid())
        self.assertFalse(fresh.taken)

    def test_resend_verification_is_rate_limited_per_email(self):
        self.client.logout()
        pending = User.objects.create_user('u2', 'u2@srmist.edu.in', is_active=False)
        pending.set_unusable_password()  # a registration that has not chosen its password yet
        pending.save()
        codes = [self.client.post(reverse('resend_verification'), {'email': 'u2@srmist.edu.in'},
                                  REMOTE_ADDR=f'10.0.0.{i}').status_code for i in range(7)]
        self.assertEqual(codes, [200] * 5 + [429] * 2)  # different IPs, same target address
        self.assertEqual(len(mail.outbox), 5)

    def test_password_reset_is_rate_limited_per_ip(self):
        self.client.logout()
        codes = [self.client.post(reverse('password_reset'), {'email': f'x{i}@srmist.edu.in'}).status_code
                 for i in range(1001)]
        self.assertEqual((codes[999], codes[1000]), (200, 429))  # 1000 an hour per address: a whole campus behind one IP is fine

    def test_register_is_rate_limited_per_ip(self):
        self.client.logout()
        codes = [self.client.post(reverse('register'), {}).status_code for _ in range(1001)]
        self.assertEqual((codes[999], codes[1000]), (200, 429))

    def test_get_requests_are_not_counted(self):
        self.client.logout()
        codes = {self.client.get(reverse('register')).status_code for _ in range(15)}
        self.assertEqual(codes, {200})
