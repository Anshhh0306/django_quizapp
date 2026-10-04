"""Part of the hardening before going online: the registration and resend pages must not reveal which addresses
have accounts, and the exam endpoints must not be hammerable by one student. (The login lock has its own tests in
test_account_security.py.)"""
import re
import threading
import time
from unittest import mock

from django.contrib.auth.models import Group, User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from quiz.models import ExamAttempt
from quiz.ratelimit import LOGIN_FREE_TRIES, LOGIN_LOCK_FIRST, LOGIN_MEMORY
from quiz.test_account_security import PASSWORD, AccountTestCase
from quiz.test_anticheat import AntiCheatBase
from quiz.test_exam_take import DESKTOP


def plain(response, email):
    """The page with the address and the per-render CSRF value taken out, so two pages can be compared."""
    html = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', '', response.content.decode())
    return html.replace(email.lower(), '@').replace(email, '@')


class RegistrationRevealsNothingTests(AccountTestCase):
    """The same page, whether the address is new, waiting for its link, already an account, or deactivated."""

    def setUp(self):
        super().setUp()
        self.finish_registration('ab1000@srmist.edu.in')  # an active account
        User.objects.create_user('ab2000', 'ab2000@srmist.edu.in', PASSWORD, is_active=False)  # deactivated by a superadmin
        waiting = User(username='ab3000', email='ab3000@srmist.edu.in', is_active=False)
        waiting.set_unusable_password()
        waiting.save()
        self.client = Client()
        mail.outbox.clear()

    def test_every_kind_of_address_gets_the_same_page(self):
        pages = []
        for email in ('ab9999@srmist.edu.in', 'ab1000@srmist.edu.in', 'AB1000@SRMIST.EDU.IN',
                      'ab2000@srmist.edu.in', 'ab3000@srmist.edu.in'):
            r = self.register(email)
            self.assertTemplateUsed(r, 'quiz/verification_sent.html')
            self.assertNotContains(r, 'already registered')
            pages.append(plain(r, email))
        self.assertEqual(len(set(pages)), 1)

    def test_an_existing_account_gets_a_note_not_a_link_and_no_second_account(self):
        count = User.objects.count()
        self.register('ab1000@srmist.edu.in')
        self.assertEqual(User.objects.count(), count)
        (note,) = mail.outbox
        self.assertEqual(note.to, ['ab1000@srmist.edu.in'])
        self.assertIn('already has an account', note.body)
        self.assertIn('/login/', note.body)
        self.assertNotIn('/verify/', note.body)

    def test_a_new_address_still_gets_its_verification_link(self):
        self.register('ab9999@srmist.edu.in')
        self.assertIn('/verify/', mail.outbox[-1].body)

    def test_a_mail_problem_looks_the_same_for_every_address(self):
        from unittest import mock
        for email in ('ab9999@srmist.edu.in', 'ab1000@srmist.edu.in'):
            with mock.patch('quiz.views.send_mail', side_effect=OSError('smtp down')):
                self.assertContains(self.register(email), 'could not send the email')

    def test_resend_gives_the_same_page_for_every_address_and_mails_only_a_waiting_one(self):
        pages = []
        for email in ('nobody@srmist.edu.in', 'ab1000@srmist.edu.in', 'ab2000@srmist.edu.in', 'ab3000@srmist.edu.in'):
            r = self.client.post(reverse('resend_verification'), {'email': email})
            self.assertTemplateUsed(r, 'quiz/verification_sent.html')
            pages.append(plain(r, email))
        self.assertEqual(len(set(pages)), 1)
        self.assertEqual([m.to for m in mail.outbox], [['ab3000@srmist.edu.in']])

    def test_resend_without_an_address_goes_back_to_the_form(self):
        self.assertRedirects(self.client.post(reverse('resend_verification'), {}), reverse('register'))


class CacheSizeTests(TestCase):
    def test_the_cache_that_holds_locks_and_counters_does_not_drop_entries_at_300(self):
        from django.conf import settings
        self.assertGreaterEqual(settings.CACHES['default']['OPTIONS']['MAX_ENTRIES'], 10_000)


class ExamEndpointLimitTests(AntiCheatBase):
    """One student cannot hammer the exam endpoints, and the 429 never changes the exam itself."""

    def setUp(self):
        cache.clear()
        super().setUp()

    def hit(self, name, times, post=False):
        self.login(self.s)
        send = self.client.post if post else self.client.get
        return [send(self.url(name), {'kind': 'back', 'away': 0} if post else {}, HTTP_USER_AGENT=DESKTOP).status_code
                for _ in range(times)]

    def test_pings_are_capped_at_thirty_a_minute_and_the_answer_is_json(self):
        codes = self.hit('exam_ping', 32)
        self.assertEqual(codes, [200] * 30 + [429] * 2)
        r = self.client.get(self.url('exam_ping'), HTTP_USER_AGENT=DESKTOP)
        self.assertEqual((r.json(), r['Retry-After']), ({'ok': False, 'reason': 'slow_down'}, '60'))

    def test_the_page_pings_every_eight_seconds_which_is_well_inside_the_cap(self):
        self.assertLess(60 / 8, 30)

    def test_event_reports_are_capped_at_sixty_a_minute(self):
        self.assertEqual(self.hit('exam_event', 62, post=True), [200] * 60 + [429] * 2)

    def test_answers_are_capped_at_180_a_minute_and_a_refused_one_saves_nothing(self):
        q = self.a_get('exam_take').context['payload']['questions'][0]['id']
        right, wrong = self.choice(q, True), self.choice(q, False)
        self.login(self.s)
        post = lambda c: self.client.post(self.url('exam_answer'), {'question': q, 'choice': c}, HTTP_USER_AGENT=DESKTOP)
        codes = [post(wrong).status_code for _ in range(180)]
        self.assertEqual(set(codes), {200})
        refused = post(right)
        self.assertEqual(refused.status_code, 429)
        self.assertEqual(self.attempt0().answers.get(question_id=q).choice_id, wrong)  # the refused answer was not stored

    def test_the_cap_is_per_student_and_per_exam_so_a_class_is_never_slowed_down(self):
        self.hit('exam_ping', 31)  # student ab1000 is now refused
        other = self.students[1]
        self.assertEqual(self.take(other, HTTP_USER_AGENT=DESKTOP).status_code, 200)
        self.assertEqual(self.client.get(self.url('exam_ping'), HTTP_USER_AGENT=DESKTOP).status_code, 200)

    def test_refusing_a_ping_does_not_touch_the_attempt(self):
        before = ExamAttempt.objects.values().get(pk=self.attempt0().pk)
        self.hit('exam_ping', 35)
        after = ExamAttempt.objects.values().get(pk=self.attempt0().pk)
        for field in ('strikes', 'leaves', 'submitted_at', 'frozen_at', 'away_since'):
            self.assertEqual(before[field], after[field], field)

    def test_the_page_keeps_a_refused_report_and_sends_it_again(self):
        self.assertContains(self.a_get('exam_take'), "r.status === 429) { pendingEvents.push([kind, away]); return; }")

    def test_a_signed_out_request_is_sent_to_log_in_not_counted(self):
        self.client.logout()
        r = self.client.get(self.url('exam_ping'))
        self.assertEqual(r.status_code, 302)  # login_required runs first, so request.user is never anonymous here


def later(seconds):
    """Let `seconds` pass for the locks and for the cache that holds them."""
    real = time.time
    return mock.patch('time.time', lambda: real() + seconds)


class LockAlertTests(AccountTestCase):
    """The owner is told when someone gets locked out of their account (and nobody else learns anything)."""

    def setUp(self):
        super().setUp()
        self.finish_registration('ab1000@srmist.edu.in')
        User.objects.create_user('ab2000', 'ab2000@srmist.edu.in', PASSWORD, is_active=False)
        self.client = Client()
        mail.outbox.clear()

    def wrong(self, name='ab1000', times=LOGIN_FREE_TRIES):
        return [self.client.post(reverse('login'), {'username': name, 'password': 'wrong-password'}, REMOTE_ADDR='10.0.0.1')
                for _ in range(times)]

    def test_the_owner_is_emailed_when_the_lock_starts_and_not_before(self):
        self.wrong(times=LOGIN_FREE_TRIES - 1)
        self.assertEqual(mail.outbox, [])
        self.wrong(times=1)
        (note,) = mail.outbox
        self.assertEqual(note.to, ['ab1000@srmist.edu.in'])
        self.assertIn('Wrong password attempts', note.subject)
        self.assertIn('locked for 2 minutes', note.body)
        self.assertIn('/accounts/password_reset/', note.body)
        self.assertNotIn('10.0.0.1', note.body)  # an address on a campus belongs to everybody

    def test_one_alert_an_hour_per_account(self):
        self.wrong()
        with later(LOGIN_LOCK_FIRST + 1):
            self.wrong(times=1)  # a second, longer lock
        self.assertEqual(len(mail.outbox), 1)
        with later(LOGIN_MEMORY + 1):
            self.wrong()  # an hour later it starts afresh
        self.assertEqual(len(mail.outbox), 2)

    def test_nothing_is_sent_for_unknown_or_deactivated_accounts(self):
        self.wrong('nobody')
        self.wrong('ab2000')
        self.assertEqual(mail.outbox, [])

    def test_the_page_is_the_same_for_a_real_and_a_made_up_account_at_the_moment_of_the_lock(self):
        real = self.wrong('ab1000')[-1]
        fake = self.wrong('nobody')[-1]
        self.assertEqual((real.status_code, plain(real, 'ab1000')), (fake.status_code, plain(fake, 'nobody')))
        real, fake = self.wrong('ab1000', 1)[0], self.wrong('nobody', 1)[0]  # and while locked
        self.assertEqual(plain(real, 'ab1000'), plain(fake, 'nobody'))

    def test_a_mail_problem_changes_nothing_the_person_typing_sees(self):
        with mock.patch('quiz.lock_alert.send_mail', side_effect=OSError('smtp down')):
            last = self.wrong()[-1]
        self.assertContains(last, 'correct username and password')

    def test_in_real_use_the_mail_goes_from_a_background_thread(self):
        with override_settings(LOCK_ALERT_BACKGROUND=True), mock.patch('quiz.lock_alert.threading.Thread') as thread:
            self.wrong()
        self.assertEqual(thread.call_args.kwargs['daemon'], True)
        thread.return_value.start.assert_called_once()
        self.assertEqual(mail.outbox, [])  # the request itself sent nothing, so it was not slowed down

    def test_the_background_thread_really_sends_the_mail(self):
        real, made = threading.Thread, []

        def spy(*args, **kwargs):
            made.append(real(*args, **kwargs))
            return made[-1]

        with override_settings(LOCK_ALERT_BACKGROUND=True), mock.patch('quiz.lock_alert.threading.Thread', spy):
            self.wrong()
        for thread in made:
            thread.join(5)
        self.assertEqual([m.to for m in mail.outbox], [['ab1000@srmist.edu.in']])

    def test_the_admin_login_alerts_the_superuser_too(self):
        User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        for _ in range(LOGIN_FREE_TRIES):
            self.client.post(reverse('admin:login'), {'username': 'root', 'password': 'wrong',
                                                      'this_is_the_login_form': 1, 'next': '/admin/'})
        self.assertEqual([m.to for m in mail.outbox], [['root@srmist.edu.in']])


class RequestCapTests(AccountTestCase):
    """The catch-all: one address or one signed-in user cannot hammer any page. (Off in the test suite; on here.)"""

    def get(self, path='/accounts/login/', client=None, ip='10.0.0.1'):
        return (client or self.client).get(path, REMOTE_ADDR=ip)

    @override_settings(REQUEST_CAPS={'address': 8, 'user': 1000})
    def test_one_address_is_capped_without_touching_the_database(self):
        user = User.objects.create_user('ab1000', 'ab1000@srmist.edu.in', PASSWORD)
        c = Client()
        c.login(username=user.username, password=PASSWORD)  # has a session: looking the user up WOULD cost queries
        pages = ['/accounts/login/', '/register/']  # the cap is for the address, whichever pages it asks for
        self.assertEqual({self.get(pages[i % 2], c).status_code for i in range(8)}, {200})
        with self.assertNumQueries(0):
            refused = self.get('/accounts/login/', c)
        self.assertEqual((refused.status_code, refused['Retry-After']), (429, '60'))
        self.assertEqual(self.get().status_code, 429)  # the whole address is capped, signed in or not
        self.assertEqual(self.get(ip='10.9.9.9').status_code, 200)  # everyone else is fine

    @override_settings(REQUEST_CAPS={'address': 1000, 'user': 5})
    def test_one_signed_in_user_is_capped_and_the_others_are_not(self):
        a = User.objects.create_user('ab1000', 'ab1000@srmist.edu.in', PASSWORD)
        b = User.objects.create_user('ab1001', 'ab1001@srmist.edu.in', PASSWORD)
        ca, cb = Client(), Client()
        ca.login(username=a.username, password=PASSWORD)
        cb.login(username=b.username, password=PASSWORD)
        self.assertEqual({self.get('/', ca).status_code for _ in range(5)}, {200})
        self.assertEqual(self.get('/', ca).status_code, 429)
        self.assertEqual(self.get('/', cb).status_code, 200)
        self.assertEqual({self.get().status_code for _ in range(10)}, {200})  # signed-out visitors have no user cap

    @override_settings(REQUEST_CAPS={'address': 1000, 'user': 1})
    def test_the_exam_pages_background_calls_get_json(self):
        user = User.objects.create_user('ab1000', 'ab1000@srmist.edu.in', PASSWORD)
        c = Client()
        c.login(username=user.username, password=PASSWORD)
        self.get('/', c)
        r = self.get('/exam/anything/ping/', c)
        self.assertEqual((r.status_code, r.json()), (429, {'ok': False, 'reason': 'slow_down'}))

    @override_settings(REQUEST_CAPS={})
    def test_empty_caps_mean_off(self):
        self.assertEqual({self.get().status_code for _ in range(30)}, {200})


class LockedLoginsTests(AccountTestCase):
    """A password reset by email ends the lock; the superadmin can see locked accounts and unlock them."""

    def setUp(self):
        super().setUp()
        self.finish_registration('ab1000@srmist.edu.in')
        self.student = User.objects.get(username='ab1000')
        self.teacher = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)
        self.teacher.groups.add(Group.objects.get(name='Teachers'))
        self.root = User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        self.client = Client()

    def lock(self, name='ab1000'):
        for _ in range(LOGIN_FREE_TRIES):
            self.client.post(reverse('login'), {'username': name, 'password': 'wrong-password'})

    def try_login(self, password=PASSWORD, name='ab1000'):
        return Client().post(reverse('login'), {'username': name, 'password': password})

    def page(self, user):
        c = Client()
        c.login(username=user.username, password=PASSWORD)
        return c

    # ---- a reset by email ends the lock ----
    def reset_link(self):
        return reverse('password_reset_confirm', args=[urlsafe_base64_encode(force_bytes(self.student.pk)),
                                                      default_token_generator.make_token(self.student)])

    def test_a_password_reset_by_email_ends_the_lock(self):
        self.lock()
        self.assertContains(self.try_login(), 'Too many failed login attempts')
        self.client.post(self.reset_link(), {'new_password1': 'BrandNewPass!987', 'new_password2': 'BrandNewPass!987'})
        self.assertEqual(self.try_login('BrandNewPass!987').status_code, 302)  # straight in, no waiting

    def test_a_wrong_or_missing_link_does_not(self):
        self.lock()
        self.client.post(reverse('password_reset_confirm', args=[urlsafe_base64_encode(force_bytes(self.student.pk)), 'bad-token']),
                         {'new_password1': 'BrandNewPass!987', 'new_password2': 'BrandNewPass!987'})
        self.assertContains(self.try_login('BrandNewPass!987'), 'Too many failed login attempts')

    # ---- the superadmin's list ----
    def test_the_superadmin_sees_who_is_locked_and_for_how_long(self):
        self.lock()
        self.lock('nobody')
        r = self.page(self.root).get(reverse('login_locks'))
        for text in ('ab1000', 'student', 'ab1000@srmist.edu.in', 'nobody', 'no such account'):
            self.assertContains(r, text)
        seconds = [row['seconds'] for row in r.context['rows']]
        self.assertTrue(all(0 < s <= LOGIN_LOCK_FIRST for s in seconds), seconds)

    def test_an_empty_list_says_so(self):
        self.assertContains(self.page(self.root).get(reverse('login_locks')), 'No account is locked right now')

    def test_nobody_else_can_see_the_list_or_unlock(self):
        self.lock()
        for user in (self.student, self.teacher):
            c = self.page(user)
            self.assertRedirects(c.get(reverse('login_locks')), reverse('home'), fetch_redirect_response=False)
            c.post(reverse('login_unlock'), {'name': 'ab1000'})
        self.assertIn('/accounts/login/', Client().get(reverse('login_locks'))['Location'])
        self.assertContains(self.try_login(), 'Too many failed login attempts')  # still locked

    def test_unlock_ends_the_lock_and_removes_it_from_the_list(self):
        self.lock()
        admin = self.page(self.root)
        r = admin.post(reverse('login_unlock'), {'name': 'AB1000'}, follow=True)  # any letter case
        self.assertNotContains(r, '>Unlock<')
        self.assertEqual(self.try_login().status_code, 302)

    def test_unlocking_needs_a_post(self):
        self.assertEqual(self.page(self.root).get(reverse('login_unlock')).status_code, 405)

    def test_an_ended_lock_leaves_the_list(self):
        self.lock()
        with later(LOGIN_LOCK_FIRST + 5):
            self.assertContains(self.page(self.root).get(reverse('login_locks')), 'No account is locked right now')

    def test_a_correct_login_after_the_lock_takes_it_off_the_list(self):
        self.lock()
        with later(LOGIN_LOCK_FIRST + 1):
            self.assertEqual(self.try_login().status_code, 302)
        self.assertContains(self.page(self.root).get(reverse('login_locks')), 'No account is locked right now')

    def test_the_home_page_links_the_superadmin_to_it(self):
        self.assertContains(self.page(self.root).get('/'), reverse('login_locks'))
