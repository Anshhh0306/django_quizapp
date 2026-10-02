import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from quiz.ratelimit import LOGIN_IP_LIMIT, LOGIN_PAIR_LIMIT

PASSWORD = 'StrongPass!4721'
LINK = re.compile(r'http://testserver(/verify/\S+)')


def verification_link():
    return LINK.search(mail.outbox[-1].body).group(1)


class AccountTestCase(TestCase):
    def setUp(self):
        cache.clear()  # rate-limit and lockout counters live in the cache

    def register(self, email='qq5555@srmist.edu.in', **extra):
        return self.client.post(reverse('register'), {'email': email, **extra})

    def finish_registration(self, email='qq5555@srmist.edu.in', password=PASSWORD):
        self.register(email)
        return self.client.post(verification_link(), {'new_password1': password, 'new_password2': password})


class PasswordChosenAfterTheLinkTests(AccountTestCase):
    def test_registering_creates_an_account_with_no_password(self):
        self.register()
        user = User.objects.get(username='qq5555')
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())

    def test_a_password_typed_at_registration_is_ignored(self):
        """The pre-hijack attack: register someone else's address with a password of your own."""
        self.register(password1='Attacker!pass1', password2='Attacker!pass1')
        user = User.objects.get(username='qq5555')
        self.assertFalse(user.has_usable_password())
        # even when the real owner clicks the emailed link, the attacker's password is not what gets set
        self.client.post(verification_link(), {'new_password1': PASSWORD, 'new_password2': PASSWORD})
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.check_password('Attacker!pass1'))

    def test_the_attacker_cannot_log_in_before_the_owner_finishes(self):
        self.register()
        r = self.client.post(reverse('login'), {'username': 'qq5555', 'password': 'anything-at-all'})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_link_leads_to_a_password_page_then_a_working_account(self):
        self.register()
        link = verification_link()
        self.assertTemplateUsed(self.client.get(link), 'quiz/verification_set_password.html')
        self.assertFalse(User.objects.get(username='qq5555').is_active)  # opening the link alone changes nothing
        r = self.client.post(link, {'new_password1': PASSWORD, 'new_password2': PASSWORD})
        self.assertTemplateUsed(r, 'quiz/verification_success.html')
        self.assertTrue(self.client.login(username='qq5555', password=PASSWORD))

    def test_weak_or_mismatched_passwords_are_refused_and_the_link_stays_usable(self):
        self.register()
        link = verification_link()
        for password in ('short1!', '12345678', 'password', 'qq5555qq'):
            r = self.client.post(link, {'new_password1': password, 'new_password2': password})
            self.assertTemplateUsed(r, 'quiz/verification_set_password.html')
            self.assertTrue(r.context['form'].errors, password)
        r = self.client.post(link, {'new_password1': PASSWORD, 'new_password2': PASSWORD + 'x'})
        self.assertTrue(r.context['form'].errors)
        self.assertFalse(User.objects.get(username='qq5555').is_active)
        self.client.post(link, {'new_password1': PASSWORD, 'new_password2': PASSWORD})
        self.assertTrue(User.objects.get(username='qq5555').is_active)

    def test_a_link_works_once_only(self):
        self.finish_registration()
        link = verification_link()
        for method in (self.client.get, lambda u: self.client.post(u, {'new_password1': 'Other!pass99', 'new_password2': 'Other!pass99'})):
            self.assertTemplateUsed(method(link), 'quiz/verification_failed.html')
        self.assertTrue(User.objects.get(username='qq5555').check_password(PASSWORD))

    def test_a_tampered_link_is_refused(self):
        self.register()
        link = verification_link()
        for bad in (link[:-4] + 'abc/', link.replace('/verify/', '/verify/ZZ'), '/verify/MQ/not-a-token/'):
            self.assertTemplateUsed(self.client.get(bad), 'quiz/verification_failed.html')

    def test_the_verification_email_comes_from_the_configured_sender(self):
        """A real email service rejects a made-up sender, so it must come from the setting the admin controls."""
        with self.settings(DEFAULT_FROM_EMAIL='SRM Quiz <quiz@example.edu>'):
            self.register()
        self.assertEqual(mail.outbox[-1].from_email, 'SRM Quiz <quiz@example.edu>')

    def test_the_email_says_what_will_happen(self):
        self.register()
        body = mail.outbox[-1].body
        self.assertIn('choose your password', body)
        self.assertRegex(body, r'http://testserver/verify/')
        self.assertNotIn(PASSWORD, body)

    def test_registering_again_resends_the_email_without_a_second_account(self):
        self.register()
        self.register()
        self.assertEqual((User.objects.count(), len(mail.outbox)), (1, 2))

    def test_resend_works_only_for_accounts_still_waiting(self):
        self.register()
        self.client.post(reverse('resend_verification'), {'email': 'QQ5555@srmist.edu.in'})
        self.assertEqual(len(mail.outbox), 2)
        self.client.post(verification_link(), {'new_password1': PASSWORD, 'new_password2': PASSWORD})
        self.client.post(reverse('resend_verification'), {'email': 'qq5555@srmist.edu.in'})
        self.assertEqual(len(mail.outbox), 2)  # already finished: nothing more is sent

    def test_staff_registration_still_waits_for_the_admin(self):
        r = self.finish_registration('shantini@srmist.edu.in')
        self.assertTrue(r.context['pending_teacher'])


class DeactivatedAccountsStayDeactivatedTests(AccountTestCase):
    def deactivated_student(self):
        self.finish_registration()
        User.objects.filter(username='qq5555').update(is_active=False)  # what the admin button does
        return User.objects.get(username='qq5555')

    def test_resend_verification_does_nothing_for_a_deactivated_account(self):
        self.deactivated_student()
        before = len(mail.outbox)
        self.client.post(reverse('resend_verification'), {'email': 'qq5555@srmist.edu.in'})
        self.assertEqual(len(mail.outbox), before)

    def test_an_old_verification_link_cannot_switch_it_back_on(self):
        self.register()
        link = verification_link()
        self.client.post(link, {'new_password1': PASSWORD, 'new_password2': PASSWORD})
        User.objects.filter(username='qq5555').update(is_active=False)
        for method in (self.client.get, lambda u: self.client.post(u, {'new_password1': 'Other!pass99', 'new_password2': 'Other!pass99'})):
            self.assertTemplateUsed(method(link), 'quiz/verification_failed.html')
        self.assertFalse(User.objects.get(username='qq5555').is_active)

    def test_even_a_freshly_made_valid_token_cannot_activate_a_deactivated_account(self):
        """Second layer: the account's own state refuses the link, not just the token's contents."""
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        from quiz.tokens import email_verification_token
        user = self.deactivated_student()
        link = reverse('verify_email', args=[urlsafe_base64_encode(force_bytes(user.pk)), email_verification_token.make_token(user)])
        self.assertTemplateUsed(self.client.get(link), 'quiz/verification_failed.html')
        r = self.client.post(link, {'new_password1': 'Other!pass99', 'new_password2': 'Other!pass99'})
        self.assertTemplateUsed(r, 'quiz/verification_failed.html')
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password(PASSWORD))

    def test_registering_again_does_not_revive_it(self):
        self.deactivated_student()
        r = self.register()
        self.assertContains(r, 'already registered')
        self.assertFalse(User.objects.get(username='qq5555').is_active)

    def test_password_reset_does_not_revive_it_either(self):
        user = self.deactivated_student()
        before = len(mail.outbox)
        self.client.post(reverse('password_reset'), {'email': user.email})
        self.assertEqual(len(mail.outbox), before)


class RegistrationRobustnessTests(AccountTestCase):
    def test_two_simultaneous_registrations_give_a_message_not_a_crash(self):
        with mock.patch('quiz.forms.RegisterForm.save', side_effect=IntegrityError):
            r = self.register()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'already registered')

    def test_a_broken_mail_server_gives_a_message_not_a_crash(self):
        with mock.patch('quiz.views.send_mail', side_effect=OSError('smtp down')):
            r = self.register()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'could not send the email')

    def test_resend_survives_a_broken_mail_server(self):
        self.register()
        with mock.patch('quiz.views.send_mail', side_effect=OSError('smtp down')):
            r = self.client.post(reverse('resend_verification'), {'email': 'qq5555@srmist.edu.in'})
        self.assertEqual(r.status_code, 302)

    def test_one_inbox_cannot_be_flooded_but_a_class_can_register(self):
        for _ in range(3):
            self.assertEqual(self.register('victim1@srmist.edu.in').status_code, 200)
        self.assertEqual(self.register('victim1@srmist.edu.in').status_code, 429)  # 3 an hour per address
        for i in range(60):  # 60 different students behind one campus address, in the same hour
            self.assertEqual(self.register(f'ab{1000 + i}@srmist.edu.in').status_code, 200)


class LoginLockoutTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.finish_registration('ab1000@srmist.edu.in')
        self.client = Client()

    def attempt(self, name='ab1000', password='wrong-password', ip='10.0.0.1'):
        return self.client.post(reverse('login'), {'username': name, 'password': password}, REMOTE_ADDR=ip)

    def test_repeated_wrong_passwords_lock_that_account_from_that_address(self):
        for _ in range(LOGIN_PAIR_LIMIT):
            self.assertContains(self.attempt(), 'correct username and password')
        r = self.attempt(password=PASSWORD)  # even the right password is refused during the lock
        self.assertContains(r, 'Too many failed login attempts')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_lock_is_per_address_so_a_stranger_cannot_lock_the_real_student_out(self):
        for _ in range(LOGIN_PAIR_LIMIT + 3):
            self.attempt(ip='10.9.9.9')  # someone else guessing
        r = self.attempt(password=PASSWORD, ip='10.0.0.1')  # the student, from their own address
        self.assertEqual(r.status_code, 302)

    def test_other_accounts_from_the_same_address_are_not_affected(self):
        self.finish_registration('ab1001@srmist.edu.in')
        for _ in range(LOGIN_PAIR_LIMIT + 1):
            self.attempt('ab1000')
        self.assertEqual(self.attempt('ab1001', PASSWORD).status_code, 302)

    def test_different_spellings_of_the_name_share_one_counter(self):
        for name in ('ab1000', 'AB1000', 'ab1000@srmist.edu.in', 'Ab1000', 'AB1000@SRMIST.EDU.IN'):
            self.attempt(name)
        self.assertContains(self.attempt('ab1000', PASSWORD), 'Too many failed login attempts')

    def test_a_correct_login_clears_the_strikes(self):
        for _ in range(LOGIN_PAIR_LIMIT - 1):
            self.attempt()
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)
        self.client.post(reverse('logout'))
        for _ in range(LOGIN_PAIR_LIMIT - 1):  # a fresh set of strikes is allowed again
            self.attempt()
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)

    def test_correct_passwords_are_never_counted_so_a_class_is_never_slowed_down(self):
        for _ in range(LOGIN_IP_LIMIT + 20):
            c = Client()
            r = c.post(reverse('login'), {'username': 'ab1000', 'password': PASSWORD}, REMOTE_ADDR='10.0.0.1')
            self.assertEqual(r.status_code, 302)

    def test_a_spray_from_one_address_across_many_accounts_is_stopped(self):
        for i in range(LOGIN_IP_LIMIT):
            self.attempt(f'nobody{i}', ip='10.5.5.5')
        self.assertContains(self.attempt('ab1000', PASSWORD, ip='10.5.5.5'), 'Too many failed login attempts')
        self.assertEqual(self.attempt('ab1000', PASSWORD, ip='10.0.0.1').status_code, 302)  # everyone else is fine

    def test_the_lock_ends_when_the_window_does(self):
        for _ in range(LOGIN_PAIR_LIMIT):
            self.attempt()
        cache.clear()  # the 15 minutes pass
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)

    def test_the_admin_login_page_is_locked_the_same_way(self):
        User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        post = lambda pw: self.client.post(reverse('admin:login'), {
            'username': 'root', 'password': pw, 'this_is_the_login_form': 1, 'next': '/admin/'}, REMOTE_ADDR='10.7.7.7')
        for _ in range(LOGIN_PAIR_LIMIT):
            post('wrong')
        self.assertContains(post(PASSWORD), 'Too many failed login attempts')
        self.assertEqual(self.client.post(reverse('admin:login'), {
            'username': 'root', 'password': PASSWORD, 'this_is_the_login_form': 1, 'next': '/admin/'},
            REMOTE_ADDR='10.8.8.8').status_code, 302)


class PasswordResetDoesNotRevealAccountsTests(AccountTestCase):
    def reset(self, email):
        return self.client.post(reverse('password_reset'), {'email': email})

    def test_every_case_gets_the_same_page(self):
        self.finish_registration('ab1000@srmist.edu.in')                              # a normal account
        self.register('ab1001@srmist.edu.in')                                         # waiting for its link
        User.objects.create_user('gmailer', 'someone@gmail.com', PASSWORD)            # not an SRMIST address
        pages = {}
        for email in ('ab1000@srmist.edu.in', 'ab1001@srmist.edu.in', 'someone@gmail.com', 'nobody@srmist.edu.in'):
            r = self.reset(email)
            self.assertIn('quiz/password_reset_done.html', [t.name for t in r.templates])
            # the page repeats the address that was typed; apart from that it must be byte-for-byte identical
            pages[email] = (r.status_code, r.content.decode().replace(email, 'ADDRESS'))
        self.assertEqual(len(set(pages.values())), 1, 'the reset page differs depending on the account')

    def test_only_a_verified_srmist_account_gets_an_email(self):
        self.finish_registration('ab1000@srmist.edu.in')
        self.register('ab1001@srmist.edu.in')
        User.objects.create_user('gmailer', 'someone@gmail.com', PASSWORD)
        before = len(mail.outbox)
        for email in ('ab1001@srmist.edu.in', 'someone@gmail.com', 'nobody@srmist.edu.in'):
            self.reset(email)
        self.assertEqual(len(mail.outbox), before)
        self.reset('AB1000@SRMIST.EDU.IN')
        self.assertEqual(len(mail.outbox), before + 1)

    def test_two_accounts_with_one_email_do_not_crash_the_reset(self):
        User.objects.create_user('a1', 'shared@srmist.edu.in', PASSWORD)
        User.objects.create_superuser('a2', 'shared@srmist.edu.in', PASSWORD)  # createsuperuser does not enforce unique emails
        self.assertEqual(self.reset('shared@srmist.edu.in').status_code, 200)

    def test_a_deactivated_user_cannot_use_an_old_reset_link(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        user = User.objects.create_user('ab1000', 'ab1000@srmist.edu.in', PASSWORD)
        url = reverse('password_reset_confirm', args=[urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)])
        user.is_active = False
        user.save()
        self.assertFalse(self.client.get(url).context['validlink'])


class AdminButtonTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        self.victim = User.objects.create_user('ab1000', 'ab1000@srmist.edu.in', PASSWORD)
        self.client.force_login(self.admin)

    def url(self, name, user=None):
        return reverse(f'admin:{name}', args=[(user or self.victim).pk])

    def test_a_plain_link_click_changes_nothing(self):
        for name in ('deactivate_user', 'activate_user', 'reset_user_password'):
            self.assertEqual(self.client.get(self.url(name)).status_code, 405, name)
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.is_active)
        self.assertEqual(len(mail.outbox), 0)

    def test_deactivate_and_activate_work_as_form_posts(self):
        self.client.post(self.url('deactivate_user'))
        self.victim.refresh_from_db()
        self.assertFalse(self.victim.is_active)
        self.client.post(self.url('activate_user'))
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.is_active)

    def test_the_csrf_check_is_enforced(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        self.assertEqual(strict.post(self.url('deactivate_user')).status_code, 403)
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.is_active)

    def test_a_superuser_cannot_deactivate_themselves(self):
        self.client.post(self.url('deactivate_user', self.admin))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_ordinary_users_cannot_use_the_buttons(self):
        self.client.force_login(self.victim)
        self.assertEqual(self.client.post(self.url('deactivate_user', self.admin)).status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_reset_emails_a_link_never_a_password(self):
        old_hash = self.victim.password
        self.client.post(self.url('reset_user_password'))
        self.victim.refresh_from_db()
        self.assertEqual(self.victim.password, old_hash)  # the password itself was not touched
        body = mail.outbox[-1].body
        self.assertRegex(body, r'http://testserver/accounts/reset/\S+/\S+/')
        self.assertNotIn('new password is', body.lower())

    def test_reset_for_someone_without_an_email_explains_itself(self):
        User.objects.filter(pk=self.victim.pk).update(email='')
        r = self.client.post(self.url('reset_user_password'), follow=True)
        self.assertContains(r, 'no email address')


class SettingsFailClosedTests(TestCase):
    """Starting the app the way a server does (not through manage.py) must refuse to run half-configured."""

    def settings_result(self, argv0, **env):
        root = Path(settings.BASE_DIR)
        if (root / '.env').exists():
            self.skipTest('a local .env file would change these results')
        clean = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        clean.update(env)
        code = ('import sys, os; sys.argv=[%r]; os.environ["DJANGO_SETTINGS_MODULE"]="quiz_project.settings"; '
                'from django.conf import settings; print("OK", settings.DEBUG, settings.ALLOWED_HOSTS)' % argv0)
        r = subprocess.run([sys.executable, '-c', code], env=clean, cwd=root, capture_output=True, text=True)
        return r.stdout.strip() or r.stderr.strip().splitlines()[-1]

    def test_a_server_with_no_configuration_refuses_to_start(self):
        self.assertIn('DJANGO_SECRET_KEY must be set', self.settings_result('gunicorn'))

    def test_a_server_must_also_name_its_hosts(self):
        self.assertIn('DJANGO_ALLOWED_HOSTS must be set', self.settings_result('gunicorn', DJANGO_SECRET_KEY='k' * 50))

    def test_a_configured_server_runs_with_debug_off_and_only_its_own_host(self):
        out = self.settings_result('gunicorn', DJANGO_SECRET_KEY='k' * 50, DJANGO_ALLOWED_HOSTS='quiz.example.edu')
        self.assertEqual(out, "OK False ['quiz.example.edu']")

    def test_local_commands_still_work_without_any_setup(self):
        out = self.settings_result('manage.py')
        self.assertEqual(out, "OK True ['localhost', '127.0.0.1', '[::1]']")

    def test_debug_can_still_be_forced_either_way(self):
        self.assertIn('OK False', self.settings_result('manage.py', DJANGO_DEBUG='False', DJANGO_SECRET_KEY='k' * 50, DJANGO_ALLOWED_HOSTS='h.example'))
        self.assertIn('OK True', self.settings_result('gunicorn', DJANGO_DEBUG='True'))
