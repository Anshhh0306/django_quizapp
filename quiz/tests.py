import time
from unittest import mock

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core import mail
from django.core.cache import cache
from quiz.models import Question, Choice


class ModelTests(TestCase):
    def setUp(self):
        self.question = Question.objects.create(
            text='What command runs the development server?',
            time_limit=30,
            points=1
        )
        self.choice_correct = Choice.objects.create(
            question=self.question,
            text='python manage.py runserver',
            is_correct=True,
            explanation='Correct! runserver launches the local server.'
        )

    def test_question_string_representation(self):
        self.assertEqual(str(self.question), 'What command runs the development server?')

    def test_choice_string_representation(self):
        self.assertEqual(str(self.choice_correct), 'python manage.py runserver')


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='student1',
            email='ab1234@srmist.edu.in',
            password='TestPassword123!'
        )

    def test_home_page_unauthenticated(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/home.html')

    def test_home_page_authenticated(self):
        self.client.login(username='student1', password='TestPassword123!')
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['role'], 'student')

    def test_user_profile_view(self):
        self.client.login(username='student1', password='TestPassword123!')
        response = self.client.get(reverse('user_profile'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/user_profile.html')
        self.assertContains(response, 'ab1234@srmist.edu.in')

    def test_user_profile_needs_a_login(self):
        response = self.client.get(reverse('user_profile'))
        self.assertEqual(response.status_code, 302)


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


class AccountFlowTests(TestCase):
    """Password reset and sign-up holes: single-use links, per-address limits, no account enumeration."""

    def setUp(self):
        cache.clear()  # rate-limit counters live in the cache
        self.user = User.objects.create_user('s1', 'ab1234@srmist.edu.in', 'TestPassword123!')
        self.client.login(username='s1', password='TestPassword123!')

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
        offset, real, codes = [0], time.time, []
        with mock.patch('time.time', lambda: real() + offset[0]):
            for i in range(10):
                codes.append(self.client.post(reverse('resend_verification'), {'email': 'u2@srmist.edu.in'},
                                              REMOTE_ADDR=f'10.0.0.{i}').status_code)
                offset[0] += 61  # a minute apart: each is a new request (the same press repeated at once is free)
        self.assertEqual(codes, [200] * 8 + [429] * 2)  # different IPs, same target address: 8 an hour per mailbox
        self.assertEqual(len(mail.outbox), 8)

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
