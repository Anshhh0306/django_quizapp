"""Two-factor sign-in: the gate, the code page, setup, remembered browsers, recovery codes, the emails, the resets."""
import io
import re
import time
from base64 import b32encode
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from quiz.exam_device import describe_device
from quiz.models import ExamAttempt, ExamEvent
from quiz.test_exam_device import DeviceBase
from quiz.test_exam_take import DESKTOP, PASSWORD
from quiz.test_login_limits import later
from quiz.tokens import email_verification_token

REQUIRED = {'admin', 'teacher'}
VERIFY = reverse('two_factor_verify')
SETUP = reverse('two_factor_setup')


def code_for(device, steps_ahead=0):
    """What the person's authenticator app shows (a step in the future if asked)."""
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits)
    totp.time = time.time() + steps_ahead * device.step
    return f'{totp.token():06d}'


def shown_codes(response):
    """The recovery codes on the page: only what is inside the code box."""
    box = re.search(r'<pre[^>]*>(.*?)</pre>', response.content.decode(), re.S).group(1)
    return box.split()


def verification_link(user):
    return reverse('verify_email', args=[urlsafe_base64_encode(force_bytes(user.pk)), email_verification_token.make_token(user)])


def fresh_code(device):
    """A code the server has not seen yet and no wrong-code delay in the way (tests that sign in more than once)."""
    TOTPDevice.objects.filter(pk=device.pk).update(last_t=-1, throttling_failure_count=0, throttling_failure_timestamp=None)
    return code_for(device)


class TwoFactorBase(TestCase):
    def setUp(self):
        cache.clear()
        self.student = User.objects.create_user('ab1000', 'ab1000@srmist.edu.in', PASSWORD)
        self.teacher = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)
        self.teacher.groups.add(Group.objects.get(name='Teachers'))
        self.admin = User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        self.client = Client()

    def enrol(self, user, codes=3):
        """The user already has an authenticator and recovery codes. Returns (device, ['abcd-efgh', ...])."""
        device = TOTPDevice.objects.create(user=user, name='authenticator', confirmed=True)
        static = StaticDevice.objects.create(user=user, name='recovery')
        tokens = [StaticToken.random_token() for _ in range(codes)]
        StaticToken.objects.bulk_create([StaticToken(device=static, token=t) for t in tokens])
        return device, [f'{t[:4]}-{t[4:]}' for t in tokens]

    def sign_in(self, user, client=None, **extra):
        return (client or self.client).post(reverse('login'), {'username': user.username, 'password': PASSWORD}, **extra)

    def verify(self, code, client=None, **data):
        return (client or self.client).post(VERIFY, {'code': code, **data})

    def assertGated(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(VERIFY), response['Location'])


class GateTests(TwoFactorBase):
    def test_a_password_alone_does_not_get_past_the_code_page(self):
        self.enrol(self.student)
        self.sign_in(self.student)
        self.assertGated(self.client.get('/'))
        self.assertGated(self.client.get('/exam/anything/take/'))
        self.assertGated(self.client.post('/exam/anything/answer/', {'question': 1, 'choice': 1}))
        self.assertGated(self.client.get('/teach/'))
        self.assertGated(self.client.get('/profile/'))

    def test_the_page_after_the_password_remembers_where_they_were_going(self):
        self.enrol(self.student)
        r = self.sign_in(self.student)
        self.assertEqual(r.status_code, 302)
        r = self.client.get('/profile/?x=1')
        self.assertEqual(r['Location'], f'{VERIFY}?next=%2Fprofile%2F%3Fx%3D1')

    def test_only_the_code_page_logout_and_the_setup_pages_are_open_before_the_code(self):
        self.enrol(self.student)
        self.sign_in(self.student)
        self.assertEqual(self.client.get(VERIFY).status_code, 200)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)
        self.assertEqual(self.client.get('/').status_code, 200)  # signed out: the public home page

    def test_the_admin_site_is_covered_too(self):
        self.enrol(self.admin)
        self.sign_in(self.admin)
        self.assertGated(self.client.get('/admin/'))
        self.verify(fresh_code(TOTPDevice.objects.get(user=self.admin)))
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_a_student_who_never_turned_it_on_is_never_asked(self):
        self.sign_in(self.student)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/profile/').status_code, 200)

    @override_settings(TWO_FACTOR_REQUIRED_ROLES=REQUIRED)
    def test_teachers_and_the_superadmin_without_one_are_sent_to_set_it_up(self):
        for user in (self.teacher, self.admin):
            c = Client()
            self.sign_in(user, c)
            r = c.get('/teach/')
            self.assertEqual((r.status_code, r['Location'].startswith(SETUP)), (302, True), user.username)

    @override_settings(TWO_FACTOR_REQUIRED_ROLES=REQUIRED)
    def test_students_and_unapproved_staff_are_not_forced(self):
        waiting = User.objects.create_user('newstaff', 'newstaff@srmist.edu.in', PASSWORD)  # not in the Teachers group
        for user in (self.student, waiting):
            c = Client()
            self.sign_in(user, c)
            self.assertEqual(c.get('/').status_code, 200, user.username)

    def test_a_signed_out_visitor_is_not_affected_and_the_code_page_needs_a_sign_in(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get(VERIFY).status_code, 302)
        self.assertIn('/accounts/login/', self.client.get(VERIFY)['Location'])


class CodePageTests(TwoFactorBase):
    def setUp(self):
        super().setUp()
        self.device, self.recovery = self.enrol(self.student)
        self.sign_in(self.student)

    def test_the_right_code_opens_everything_and_goes_to_where_they_were_headed(self):
        before = self.client.session.session_key
        r = self.verify(fresh_code(self.device), next='/profile/')
        self.assertEqual((r.status_code, r['Location']), (302, '/profile/'))
        self.assertEqual(self.client.get('/profile/').status_code, 200)
        self.assertNotEqual(self.client.session.session_key, before)  # a new session key at the moment of more trust

    def test_a_wrong_code_gets_a_message_and_nothing_opens(self):
        r = self.verify('000000')
        self.assertContains(r, 'not accepted')
        self.assertGated(self.client.get('/'))

    def test_a_code_works_only_once(self):
        code = fresh_code(self.device)
        self.assertEqual(self.verify(code).status_code, 302)
        other = Client()
        self.sign_in(self.student, other)
        self.assertContains(self.verify(code, other), 'not accepted')  # the same code, a moment later
        self.assertGated(other.get('/'))

    def test_wrong_codes_slow_themselves_down_even_for_the_right_code(self):
        self.verify('000000')
        r = self.verify(code_for(self.device))  # right code, straight away
        self.assertContains(r, 'Too many wrong codes')
        self.assertGated(self.client.get('/'))
        TOTPDevice.objects.filter(pk=self.device.pk).update(
            throttling_failure_timestamp=timezone.now() - timedelta(minutes=5))  # a while ago
        self.assertEqual(self.verify(code_for(self.device)).status_code, 302)

    def long_ago(self, minutes, count=20):
        """The state after `count` wrong codes, the last one `minutes` ago (django-otp alone would now say: wait years)."""
        stamp = timezone.now() - timedelta(minutes=minutes)
        TOTPDevice.objects.filter(pk=self.device.pk).update(throttling_failure_count=count, throttling_failure_timestamp=stamp)
        StaticDevice.objects.filter(user=self.student).update(throttling_failure_count=count, throttling_failure_timestamp=stamp)

    def test_nobody_is_held_out_for_more_than_fifteen_minutes(self):
        self.long_ago(minutes=16)
        self.assertEqual(self.verify(code_for(self.device)).status_code, 302)

    def test_the_same_ceiling_applies_to_recovery_codes(self):
        self.long_ago(minutes=16)
        self.assertEqual(self.verify(self.recovery[0]).status_code, 302)

    def test_inside_the_ceiling_the_wait_is_real_and_shown_in_minutes(self):
        self.long_ago(minutes=1)
        r = self.verify(code_for(self.device))
        self.assertContains(r, 'Too many wrong codes')
        waited = int(re.search(r'Wait (\d+) minutes', r.content.decode()).group(1))
        self.assertTrue(10 <= waited <= 14, waited)  # 15 minutes after the last wrong try, so about 14 are left
        self.assertGated(self.client.get('/'))

    def test_the_count_starts_again_after_the_quiet_time_so_one_slip_is_a_short_wait(self):
        self.long_ago(minutes=16)
        self.verify('000000')  # one wrong code after a long quiet
        self.assertEqual(TOTPDevice.objects.get(pk=self.device.pk).throttling_failure_count, 1)  # not 21

    def test_a_recovery_code_works_once_in_any_letter_case_with_or_without_the_dash(self):
        spelled = self.recovery[0].upper().replace('-', ' ')
        r = self.verify(spelled)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], reverse('two_factor'))  # sent to the page that shows how many are left
        self.assertEqual(StaticToken.objects.filter(device__user=self.student).count(), 2)
        other = Client()
        self.sign_in(self.student, other)
        self.assertContains(self.verify(self.recovery[0], other), 'not accepted')
        self.assertIn('recovery code was used', mail.outbox[-1].subject.lower() + mail.outbox[-1].body.lower())

    def test_it_will_not_send_people_to_other_sites(self):
        for bad in ('https://evil.example/', '//evil.example/x', 'javascript:alert(1)', '/2fa/verify/'):
            c = Client()
            self.sign_in(self.student, c)
            self.assertEqual(self.verify(fresh_code(self.device), c, next=bad)['Location'], reverse('home'), bad)

    def test_remember_this_browser_only_when_ticked(self):
        r = self.verify(fresh_code(self.device))
        self.assertNotIn(f'trusted_{self.student.pk}', r.cookies)
        other = Client()
        self.sign_in(self.student, other)
        r = self.verify(fresh_code(self.device), other, remember='on')
        cookie = r.cookies[f'trusted_{self.student.pk}']
        self.assertEqual((cookie['httponly'], cookie['samesite']), (True, 'Lax'))
        self.assertEqual(int(cookie['max-age']), 30 * 86400)

    def test_the_page_has_the_fields_the_tests_post(self):
        """The other tests post fields directly; this makes sure the real form offers the same ones."""
        page = self.client.get(VERIFY, {'next': '/profile/'}).content.decode()
        for field in ('name="code"', 'name="remember"', 'name="next" value="/profile/"', 'autocomplete="one-time-code"',
                      'name="csrfmiddlewaretoken"'):
            self.assertIn(field, page)
        self.assertIn('30 days', page)

    def test_without_an_authenticator_there_is_nothing_to_verify(self):
        c = Client()
        self.sign_in(self.teacher, c)
        self.assertRedirects(c.get(VERIFY), reverse('home'), fetch_redirect_response=False)
        with override_settings(TWO_FACTOR_REQUIRED_ROLES=REQUIRED):
            self.assertRedirects(c.get(VERIFY), SETUP, fetch_redirect_response=False)


class SetupTests(TwoFactorBase):
    def setUp(self):
        super().setUp()
        self.sign_in(self.student)

    def test_the_page_shows_the_picture_and_the_key_and_makes_one_unconfirmed_device(self):
        r = self.client.get(SETUP)
        self.assertContains(r, 'data:image/svg+xml')
        device = TOTPDevice.objects.get(user=self.student)
        self.assertFalse(device.confirmed)
        self.assertContains(r, ' '.join(re.findall('.{1,4}', b32encode(device.bin_key).decode())))
        self.client.get(SETUP)
        self.assertEqual(TOTPDevice.objects.filter(user=self.student).count(), 1)  # a reload does not make another

    def test_a_wrong_code_does_not_turn_it_on(self):
        self.client.get(SETUP)
        r = self.client.post(SETUP, {'code': '000000'})
        self.assertContains(r, 'not accepted')
        self.assertFalse(TOTPDevice.objects.get(user=self.student).confirmed)

    def test_the_right_code_turns_it_on_shows_ten_recovery_codes_once_and_emails_the_owner(self):
        self.client.get(SETUP)
        device = TOTPDevice.objects.get(user=self.student)
        r = self.client.post(SETUP, {'code': code_for(device)})
        self.assertContains(r, 'Save these recovery codes')
        shown = shown_codes(r)
        self.assertEqual(len(set(shown)), 10)
        self.assertTrue(all(re.fullmatch(r'[a-z2-7]{4}-[a-z2-7]{4}', c) for c in shown), shown)
        stored = set(StaticToken.objects.filter(device__user=self.student).values_list('token', flat=True))
        self.assertEqual({c.replace('-', '') for c in shown}, stored)
        self.assertTrue(TOTPDevice.objects.get(user=self.student).confirmed)
        self.assertEqual(self.client.get(reverse('two_factor')).status_code, 200)  # this session is verified already
        self.assertEqual(mail.outbox[-1].to, ['ab1000@srmist.edu.in'])
        self.assertIn('turned on', mail.outbox[-1].subject)
        self.assertNotContains(self.client.get(reverse('two_factor')), shown[0])  # never shown again

    def test_setup_is_not_offered_twice(self):
        self.enrol(self.student)
        self.client.post(reverse('logout'))
        self.sign_in(self.student)
        self.verify(fresh_code(TOTPDevice.objects.get(user=self.student)))
        self.assertRedirects(self.client.get(SETUP), reverse('two_factor'), fetch_redirect_response=False)

    @override_settings(TWO_FACTOR_REQUIRED_ROLES=REQUIRED)
    def test_a_teacher_who_sets_it_up_gets_through_to_the_teacher_pages(self):
        c = Client()
        self.sign_in(self.teacher, c)
        c.get(SETUP)
        c.post(SETUP, {'code': code_for(TOTPDevice.objects.get(user=self.teacher))})
        self.assertEqual(c.get('/teach/').status_code, 200)


class RememberedBrowserTests(TwoFactorBase):
    def setUp(self):
        super().setUp()
        self.device, _ = self.enrol(self.student)
        self.sign_in(self.student)
        r = self.verify(fresh_code(self.device), remember='on')
        self.cookie = r.cookies[f'trusted_{self.student.pk}'].value

    def same_browser_later(self):
        browser = Client()
        browser.cookies[f'trusted_{self.student.pk}'] = self.cookie
        self.sign_in(self.student, browser)
        return browser

    def test_the_same_browser_needs_only_the_password_next_time(self):
        self.assertEqual(self.same_browser_later().get('/profile/').status_code, 200)

    def test_another_browser_still_needs_the_code(self):
        other = Client()
        self.sign_in(self.student, other)
        self.assertGated(other.get('/profile/'))

    def test_it_is_for_that_account_only(self):
        mine, _ = self.enrol(self.teacher)
        browser = Client()
        browser.cookies[f'trusted_{self.teacher.pk}'] = self.cookie  # the student's cookie offered for the teacher
        self.sign_in(self.teacher, browser)
        self.assertGated(browser.get('/profile/'))

    def test_a_forged_cookie_is_refused(self):
        browser = Client()
        browser.cookies[f'trusted_{self.student.pk}'] = f'{self.student.pk}:1abc:forged'
        self.sign_in(self.student, browser)
        self.assertGated(browser.get('/profile/'))

    def test_a_new_password_makes_every_remembered_browser_forget(self):
        self.student.set_password('AnotherPass!9182')
        self.student.save()
        browser = Client()
        browser.cookies[f'trusted_{self.student.pk}'] = self.cookie
        browser.post(reverse('login'), {'username': 'ab1000', 'password': 'AnotherPass!9182'})
        self.assertGated(browser.get('/profile/'))

    def test_a_reset_or_new_authenticator_makes_every_remembered_browser_forget(self):
        self.device.delete()
        self.enrol(self.student)
        self.assertGated(self.same_browser_later().get('/profile/'))

    def test_it_runs_out_after_thirty_days(self):
        with later(31 * 86400):
            self.assertGated(self.same_browser_later().get('/profile/'))
        with later(29 * 86400):
            self.assertEqual(self.same_browser_later().get('/profile/').status_code, 200)


class ManageTests(TwoFactorBase):
    def setUp(self):
        super().setUp()
        self.device, self.recovery = self.enrol(self.student)
        self.sign_in(self.student)
        self.verify(fresh_code(self.device))

    def test_the_page_says_how_many_recovery_codes_are_left(self):
        self.assertContains(self.client.get(reverse('two_factor')), 'Recovery codes left: <strong>3</strong>')

    def test_the_page_needs_the_code_first_if_there_is_an_authenticator(self):
        other = Client()
        self.sign_in(self.student, other)
        self.assertRedirects(other.get(reverse('two_factor')), f'{VERIFY}?next=/2fa/', fetch_redirect_response=False)

    def test_new_recovery_codes_replace_the_old_ones(self):
        r = self.client.post(reverse('two_factor_codes'))
        self.assertContains(r, 'Your new recovery codes')
        self.assertEqual(len(set(shown_codes(r))), 10)
        other = Client()
        self.sign_in(self.student, other)
        self.assertContains(self.verify(self.recovery[0], other), 'not accepted')  # an old code is dead now
        self.assertIn('New recovery codes', mail.outbox[-1].subject)

    def test_only_a_verified_session_can_make_new_codes_or_turn_it_off(self):
        other = Client()
        self.sign_in(self.student, other)
        before = list(StaticToken.objects.values_list('token', flat=True))
        other.post(reverse('two_factor_codes'))
        other.post(reverse('two_factor_off'), {'password': PASSWORD})
        self.assertEqual(list(StaticToken.objects.values_list('token', flat=True)), before)
        self.assertTrue(TOTPDevice.objects.filter(user=self.student).exists())

    def test_turning_it_off_needs_the_password_removes_everything_and_tells_the_owner(self):
        self.client.post(reverse('two_factor_off'), {'password': 'not-the-password'})
        self.assertTrue(TOTPDevice.objects.filter(user=self.student).exists())
        self.client.post(reverse('two_factor_off'), {'password': PASSWORD})
        self.assertFalse(TOTPDevice.objects.filter(user=self.student).exists())
        self.assertFalse(StaticDevice.objects.filter(user=self.student).exists())
        self.assertIn('turned off', mail.outbox[-1].subject)
        self.assertEqual(self.client.get('/profile/').status_code, 200)  # and they are not shut out

    @override_settings(TWO_FACTOR_REQUIRED_ROLES=REQUIRED)
    def test_a_teacher_cannot_turn_it_off(self):
        device, _ = self.enrol(self.teacher)
        c = Client()
        self.sign_in(self.teacher, c)
        self.verify(fresh_code(device), c)
        c.post(reverse('two_factor_off'), {'password': PASSWORD})
        self.assertTrue(TOTPDevice.objects.filter(user=self.teacher).exists())
        self.assertContains(c.get(reverse('two_factor')), 'cannot be turned off')


class ResetTests(TwoFactorBase):
    def test_removing_an_authenticator_by_any_route_removes_the_recovery_codes_and_emails_the_owner(self):
        device, _ = self.enrol(self.student)
        device.delete()  # what the admin site's delete does
        self.assertFalse(StaticDevice.objects.filter(user=self.student).exists())
        self.assertEqual((mail.outbox[-1].to, 'turned off' in mail.outbox[-1].subject), (['ab1000@srmist.edu.in'], True))

    def test_an_unfinished_setup_going_away_sends_nothing(self):
        TOTPDevice.objects.create(user=self.student, name='authenticator', confirmed=False).delete()
        self.assertEqual(mail.outbox, [])

    @override_settings(TWO_FACTOR_REQUIRED_ROLES=REQUIRED)
    def test_the_command_is_the_way_back_for_a_locked_out_teacher_or_superadmin(self):
        for user in (self.teacher, self.admin):
            self.enrol(user)
            call_command('reset_two_factor', user.username.upper(), stdout=io.StringIO())
            self.assertFalse(TOTPDevice.objects.filter(user=user).exists())
            c = Client()
            self.sign_in(user, c)
            self.assertTrue(c.get('/teach/')['Location'].startswith(SETUP), user.username)  # asked to set it up again

    def test_the_command_refuses_an_unknown_name(self):
        with self.assertRaises(CommandError):
            call_command('reset_two_factor', 'nobody-here')

    def test_the_admin_site_never_shows_a_secret_key(self):
        device, _ = self.enrol(self.admin)
        self.sign_in(self.admin)
        self.verify(fresh_code(device))
        page = self.client.get(f'/admin/otp_totp/totpdevice/{device.pk}/change/')
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, device.key)


@override_settings(NEW_BROWSER_ALERTS=True)
class NewBrowserEmailTests(TwoFactorBase):
    def alerts(self):
        return [m for m in mail.outbox if 'New sign-in' in m.subject]

    def test_a_browser_the_account_has_not_used_before_gets_one_email_with_the_details(self):
        self.sign_in(self.student)
        self.client.get('/', HTTP_USER_AGENT=DESKTOP)
        (note,) = self.alerts()
        self.assertEqual(note.to, ['ab1000@srmist.edu.in'])
        self.assertIn(describe_device(DESKTOP), note.body)
        self.assertIn('127.0.0.1', note.body)
        self.assertIn('IST', note.body)
        self.assertIn(reverse('password_reset'), note.body)
        self.assertIn(f'kb_{self.student.pk}', self.client.cookies)

    def test_the_same_browser_is_not_emailed_again(self):
        self.sign_in(self.student)
        for _ in range(3):
            self.client.get('/')
        self.assertEqual(len(self.alerts()), 1)

    def test_at_most_one_an_hour_per_account_however_many_new_browsers(self):
        for _ in range(3):
            c = Client()
            self.sign_in(self.student, c)
            c.get('/')
            self.assertIn(f'kb_{self.student.pk}', c.cookies)  # each is still marked as known afterwards
        self.assertEqual(len(self.alerts()), 1)

    def test_another_accounts_marker_does_not_count(self):
        self.sign_in(self.student)
        self.client.get('/')
        c = Client()
        c.cookies[f'kb_{self.teacher.pk}'] = self.client.cookies[f'kb_{self.student.pk}'].value
        self.sign_in(self.teacher, c)
        c.get('/')
        self.assertEqual(len(self.alerts()), 2)

    def test_nothing_is_sent_until_the_second_step_is_passed(self):
        device, _ = self.enrol(self.student)
        self.sign_in(self.student)
        self.client.get('/')  # gated
        self.assertEqual(self.alerts(), [])
        self.verify(fresh_code(device))
        self.client.get('/')
        self.assertEqual(len(self.alerts()), 1)

    def test_signing_out_works_after_the_code_step(self):
        """Found by a real-browser run: for someone who had passed the code step, the new-browser check ran after logout
        had emptied request.user, and the page crashed. (A student without 2FA never reaches that check on logout.)"""
        device, _ = self.enrol(self.student)
        self.sign_in(self.student)
        self.verify(fresh_code(device))
        self.client.get('/')
        r = self.client.post(reverse('logout'))
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_signing_out_works_for_a_browser_that_is_new_to_the_account_too(self):
        device, _ = self.enrol(self.student)
        self.sign_in(self.student)
        self.verify(fresh_code(device))  # the first thing this verified session does is sign out
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)

    def test_signing_out_works_for_a_student_without_it(self):
        self.sign_in(self.student)
        self.client.get('/')
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)

    def test_nothing_is_sent_to_a_signed_out_visitor(self):
        self.client.get('/')
        self.assertEqual(self.alerts(), [])

    def test_the_browser_where_the_password_was_chosen_is_known(self):
        pending = User(username='cd2000', email='cd2000@srmist.edu.in', is_active=False)
        pending.set_unusable_password()
        pending.save()
        link = verification_link(pending)
        self.client.post(link, {'new_password1': PASSWORD, 'new_password2': PASSWORD})
        mail.outbox.clear()
        self.client.post(reverse('login'), {'username': 'cd2000', 'password': PASSWORD})
        self.client.get('/')
        self.assertEqual(self.alerts(), [])


class ExamLogTests(DeviceBase):
    """The teacher's log notes a sign-in for a student whose exam is running (evidence only)."""

    def sign_in_again(self, user, **extra):
        return Client().post(reverse('login'), {'username': user.username, 'password': PASSWORD},
                             HTTP_USER_AGENT=DESKTOP, **extra)

    def test_a_sign_in_during_the_exam_is_logged_with_the_browser_and_address(self):
        self.sign_in_again(self.s)
        line = ExamEvent.objects.get(exam=self.exam, kind='login')
        self.assertEqual(line.attempt, self.attempt0())
        self.assertIn('ab1000 signed in again', line.detail)
        self.assertIn(describe_device(DESKTOP), line.detail)
        self.assertIn('127.0.0.1', line.detail)
        self.assertEqual(self.attempt0().strikes, 0)  # evidence only: nothing is punished

    def test_nothing_is_logged_for_a_student_who_is_not_in_a_running_exam(self):
        self.sign_in_again(self.students[1])  # joined the lobby only, never started
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(submitted_at=self.attempt0().started_at)
        self.sign_in_again(self.s)  # already submitted
        self.assertFalse(ExamEvent.objects.filter(kind='login').exists())

    def test_signing_in_without_a_real_request_is_not_logged(self):
        self.client.login(username=self.s.username, password=PASSWORD)
        self.assertFalse(ExamEvent.objects.filter(kind='login').exists())


class BannerTests(TwoFactorBase):
    def test_students_without_it_are_nudged_and_those_with_it_are_not(self):
        self.sign_in(self.student)
        self.assertContains(self.client.get('/'), 'Secure your account')
        device, _ = self.enrol(self.student)
        self.verify(fresh_code(device))
        self.assertNotContains(self.client.get('/'), 'Secure your account')

    def test_teachers_do_not_get_the_student_note(self):
        self.sign_in(self.teacher)
        self.assertNotContains(self.client.get('/'), 'Secure your account')


class SettingsTests(TestCase):
    def test_teachers_and_the_superadmin_are_required_to_use_it_outside_the_tests(self):
        """The test run switches the rule off, so the real setting is read from the file: a typo there must not pass."""
        text = (Path(settings.BASE_DIR) / 'quiz_project' / 'settings.py').read_text(encoding='utf-8')
        self.assertIn("TWO_FACTOR_REQUIRED_ROLES = {'admin', 'teacher'}", text)
        self.assertIn('NEW_BROWSER_ALERTS = True', text)

    def test_a_blocked_mail_server_cannot_hang_a_page(self):
        self.assertTrue(0 < settings.EMAIL_TIMEOUT <= 30)
