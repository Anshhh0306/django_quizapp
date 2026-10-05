"""The demo-data command: what it makes works with the real sign-in pages, and it cannot run anywhere real."""
import re
from collections import Counter
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from quiz.management.commands.seed_demo import ADMIN, LISTED, PENDING, STUDENTS, TEACHERS
from quiz.models import Exam, ExamAllowed, Question
from quiz.roles import role_of

PASSWORD = 'Demo-Pass-123'
REQUIRED = {'admin', 'teacher'}
VERIFY = reverse('two_factor_verify')


def run(**options):
    out = StringIO()
    call_command('seed_demo', stdout=out, **options)
    return out.getvalue()


class DemoBase(TestCase):
    def setUp(self):
        cache.clear()
        # the happy path must not depend on where the test database happens to live
        local = mock.patch.dict(connection.settings_dict, {'HOST': 'localhost'})
        local.start()
        self.addCleanup(local.stop)

    def sign_in_with_code(self, username):
        client = Client()
        client.post(reverse('login'), {'username': username, 'password': PASSWORD})
        client.post(VERIFY, {'code': run(code=username).strip()})
        return client


class WhatItMakesTests(DemoBase):
    def test_every_kind_of_account_with_the_right_role(self):
        run(password=PASSWORD)
        roles = Counter(role_of(user) for user in User.objects.all())
        self.assertEqual(roles, {'admin': 1, 'teacher': 2, 'pending': 1, 'student': len(STUDENTS)})
        self.assertTrue(all(user.is_active and user.check_password(PASSWORD) for user in User.objects.all()))

    def test_the_password_is_random_unless_chosen(self):
        shown = re.search(r'password: (\S+)', run()).group(1)
        self.assertTrue(User.objects.get(username=ADMIN).check_password(shown))
        self.assertNotEqual(shown, PASSWORD)

    def test_only_the_admin_and_teachers_get_an_authenticator(self):
        run(password=PASSWORD)
        owners = set(TOTPDevice.objects.filter(confirmed=True).values_list('user__username', flat=True))
        self.assertEqual(owners, {ADMIN, *TEACHERS})

    @override_settings(TWO_FACTOR_REQUIRED_ROLES=REQUIRED)
    def test_staff_get_through_the_real_code_page(self):
        run(password=PASSWORD)
        for username, page in ((ADMIN, '/admin/'), (TEACHERS[0], '/teach/'), (TEACHERS[1], '/teach/')):
            client = Client()
            client.post(reverse('login'), {'username': username, 'password': PASSWORD})
            shut = client.get(page)
            self.assertTrue(shut.status_code == 302 and shut['Location'].startswith(VERIFY), f'{username}: not gated before the code')
            client.post(VERIFY, {'code': run(code=username).strip()})
            self.assertEqual(client.get(page).status_code, 200, f'{username}: the printed code was not accepted')

    @override_settings(TWO_FACTOR_REQUIRED_ROLES=REQUIRED)
    def test_a_code_can_be_asked_for_again_straight_away(self):
        run(password=PASSWORD)
        for _ in range(2):  # the site takes each code once; asking again must start afresh
            self.assertEqual(self.sign_in_with_code(TEACHERS[0]).get('/teach/').status_code, 200)

    def test_the_pending_teacher_is_not_approved(self):
        run(password=PASSWORD)
        self.assertEqual(role_of(User.objects.get(username=PENDING)), 'pending')

    def test_exams_and_questions(self):
        run(password=PASSWORD)
        scheduled = Exam.objects.get(title='Demo test (scheduled)')
        self.assertEqual((scheduled.owner.username, scheduled.mode, scheduled.duration_minutes, scheduled.seat_limit, scheduled.status),
                         (TEACHERS[0], Exam.SCHEDULED, 30, LISTED, Exam.DRAFT))
        self.assertEqual(set(scheduled.allowed.values_list('email', flat=True)), {f'{name}@srmist.edu.in' for name in STUDENTS[:LISTED]})
        self.assertEqual(scheduled.questions.count(), 25)
        practice = Exam.objects.get(title='Demo practice (open)')
        self.assertEqual((practice.mode, practice.duration_minutes, practice.allowed.count(), practice.questions.count()),
                         (Exam.OPEN, None, 0, 15))
        quiz = Exam.objects.get(title='Demo quick quiz (open)')
        self.assertEqual((quiz.owner.username, quiz.questions.count()), (TEACHERS[1], 5))
        self.assertEqual(Counter(Question.objects.values_list('owner__username', flat=True)), {TEACHERS[0]: 25, TEACHERS[1]: 5})
        for question in Question.objects.prefetch_related('choices'):
            choices = list(question.choices.all())
            self.assertTrue(len(choices) == 4 and sum(c.is_correct for c in choices) == 1, f'bad answers on: {question.text}')

    def test_running_it_again_keeps_the_data_and_changes_the_secrets(self):
        run(password=PASSWORD)
        key = TOTPDevice.objects.get(user__username=TEACHERS[0]).key
        counts = lambda: (User.objects.count(), Exam.objects.count(), Question.objects.count(), TOTPDevice.objects.count(),
                          ExamAllowed.objects.count())
        before = counts()
        Group.objects.get(name='Teachers').user_set.add(User.objects.get(username=PENDING))  # someone tried the approval
        run(password='Another-Pass-456')
        self.assertEqual(counts(), before)
        teacher = User.objects.get(username=TEACHERS[0])
        self.assertTrue(teacher.check_password('Another-Pass-456') and not teacher.check_password(PASSWORD))
        self.assertNotEqual(TOTPDevice.objects.get(user=teacher).key, key)
        self.assertEqual(role_of(User.objects.get(username=PENDING)), 'pending')


class CannotRunAnywhereRealTests(DemoBase):
    def test_a_database_on_another_computer_is_refused(self):
        for host in ('ep-quiet-sound.ap-southeast-1.aws.neon.tech', '10.0.0.5', 'localhost.example.com', 'db'):
            with mock.patch.dict(connection.settings_dict, {'HOST': host}):
                with self.assertRaisesMessage(CommandError, 'not on this computer'):
                    run(password=PASSWORD)
        self.assertEqual(User.objects.count(), 0)

    def test_this_computers_own_names_are_fine(self):
        for host in ('', 'localhost', '127.0.0.1', '::1'):
            with mock.patch.dict(connection.settings_dict, {'HOST': host}):
                run(password=PASSWORD)

    def test_the_code_printer_is_refused_there_too(self):
        run(password=PASSWORD)
        with mock.patch.dict(connection.settings_dict, {'HOST': 'ep-quiet-sound.ap-southeast-1.aws.neon.tech'}):
            with self.assertRaisesMessage(CommandError, 'not on this computer'):
                run(code=TEACHERS[0])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend')
    def test_real_email_is_refused(self):
        with self.assertRaisesMessage(CommandError, 'real email'):
            run(password=PASSWORD)
        self.assertEqual(User.objects.count(), 0)

    def test_a_database_with_real_accounts_is_refused_and_left_alone(self):
        real = User.objects.create_user('shantini', 'shantini@srmist.edu.in', 'Keep-This-1')
        with self.assertRaisesMessage(CommandError, 'not demo accounts'):
            run(password=PASSWORD)
        self.assertEqual(list(User.objects.all()), [real])
        self.assertTrue(User.objects.get(pk=real.pk).check_password('Keep-This-1'))

    def test_the_code_printer_only_serves_demo_accounts(self):
        run(password=PASSWORD)
        real = User.objects.create_user('shantini', 'shantini@srmist.edu.in', 'Keep-This-1')
        TOTPDevice.objects.create(user=real, name='authenticator', confirmed=True)
        for username in ('shantini', PENDING, STUDENTS[0], 'nobody'):
            with self.assertRaises(CommandError, msg=username):
                run(code=username)
