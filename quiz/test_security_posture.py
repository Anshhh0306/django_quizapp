"""The site's overall security posture, as plain regression checks: browser protections, caching of personal pages, who may open which
route, cookie flags and HSTS on a real server, the sign-in session, and roles that a form must never hand out. Each test names a
protection that must hold; a route or setting added later is covered too (the route walk) or fails here until someone looks at it."""
import importlib
import json
import os
import re
import sys
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpResponse
from django.utils import timezone
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

import quiz_project.settings as project_settings
from quiz.middleware import NoStoreForSignedInMiddleware
from quiz import urls as quiz_urls
from quiz.models import Exam, ExamAttempt
from quiz.test_account_security import AccountTestCase
from quiz.test_adversarial import PASSWORD, World, signed_in

# Routes an anonymous visitor may open (what is on them is the same for everyone). Anything else must send them to sign in.
PUBLIC = {'/', '/accounts/login/', '/register/', '/resend-verification/', '/accounts/password_reset/', '/accounts/password_reset/done/',
          '/accounts/reset/abc/abc/', '/accounts/reset/done/', '/verify/abc/abc/'}


def real_routes(world):
    """A path for every named route in quiz/urls.py, with arguments that really exist (an exam, its token, a question set, an attempt), so a
    missing check cannot hide behind a 404 for a made-up id. A route with new kinds of arguments stops the test until it is listed here."""
    attempt = ExamAttempt.objects.get_or_create(exam=world.exam, user=world.bob, defaults={'consented_at': timezone.now()})[0]
    by_name = {'question_set_action': [world.qset.pk], 'exam_detail': [world.exam.pk], 'exam_live': [world.exam.pk],
               'exam_controls': [world.exam.pk], 'exam_results': [world.exam.pk], 'exam_result_detail': [world.exam.pk, attempt.pk],
               'verify_email': ['abc', 'abc'], 'password_reset_confirm': ['abc', 'abc']}
    paths = []
    for entry in quiz_urls.urlpatterns:
        arguments = re.findall(r'<(?:\w+:)?(\w+)>', str(entry.pattern))
        if entry.name in by_name:
            args = by_name[entry.name]
        elif arguments == ['token']:
            args = [world.exam.token]
        else:
            assert not arguments, f'route {entry.name!r} has arguments {arguments}: say what to fill in, in real_routes()'
            args = []
        paths.append(reverse(entry.name, args=args))
    return paths


class BrowserProtectionTests(World):
    PROTECTIONS = {'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin',
                   'Cross-Origin-Opener-Policy': 'same-origin'}

    def test_pages_say_they_may_not_be_framed_sniffed_or_leak_their_address(self):
        for who, path in ((Client(), reverse('login')), (signed_in(self.alice), '/profile/'), (signed_in(self.teacher), '/teach/')):
            response = who.get(path)
            self.assertEqual({name: response.headers.get(name) for name in self.PROTECTIONS}, self.PROTECTIONS, path)

    def test_pages_that_show_a_persons_data_are_not_cached(self):
        pages = {'/profile/': self.alice, '/teach/': self.teacher, f'/teach/exams/{self.exam.pk}/': self.teacher,
                 f'/teach/exams/{self.exam.pk}/results/': self.teacher, '/': self.alice}
        for path, user in pages.items():
            response = signed_in(user).get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('no-store', response.headers.get('Cache-Control', ''), path)

    def test_a_page_that_chose_its_own_caching_keeps_it(self):
        request = RequestFactory().get('/')
        request.user = self.alice
        own = NoStoreForSignedInMiddleware(lambda r: HttpResponse(headers={'Cache-Control': 'max-age=60'}))(request)
        self.assertEqual(own.headers['Cache-Control'], 'max-age=60')
        plain = NoStoreForSignedInMiddleware(lambda r: HttpResponse())(request)
        self.assertIn('no-store', plain.headers['Cache-Control'])
        request.user = AnonymousUser()  # not signed in: left alone
        self.assertNotIn('Cache-Control', NoStoreForSignedInMiddleware(lambda r: HttpResponse())(request).headers)


class RouteAccessTests(World):
    """Every route in quiz/urls.py, walked by path, as someone who is not signed in and as a plain student."""

    def test_a_visitor_who_is_not_signed_in_gets_only_the_public_pages(self):
        for method in ('get', 'post'):
            seen = {}
            for path in real_routes(self):
                response = getattr(Client(), method)(path)
                seen[path] = (response.status_code, response.headers.get('Location', ''))
            for path, (code, location) in seen.items():
                self.assertLess(code, 500, f'{method.upper()} {path} crashed')
                if path in PUBLIC or path == '/accounts/logout/':  # signing out when nobody is signed in just goes to the front page
                    continue
                self.assertIn(code, (301, 302, 400, 403, 404, 405), f'{method.upper()} {path} answered {code} to a visitor')
                if code in (301, 302):
                    self.assertTrue(location.startswith(('/accounts/login/', reverse('login'))), f'{method.upper()} {path} went to {location}')
            self.assertGreater(len(seen), 30)  # the walk really covered the routes

    def test_a_plain_student_is_kept_out_of_teacher_and_admin_routes(self):
        client = signed_in(self.alice)
        closed = [p for p in real_routes(self) if p.startswith('/teach') or p.startswith('/locks')] + ['/admin/', '/admin/auth/user/']
        for path in closed:
            for method in ('get', 'post'):
                response = getattr(client, method)(path)
                self.assertNotEqual(response.status_code, 200, f'a student opened {method.upper()} {path}')
                self.assertLess(response.status_code, 500, f'{method.upper()} {path} crashed')
        self.assertGreater(len(closed), 10)

    def test_a_teacher_is_kept_out_of_the_superadmin_pages(self):
        client = signed_in(self.teacher)
        for path in ('/locks/', '/admin/', '/admin/auth/user/', '/admin/quiz/exam/'):
            self.assertNotEqual(client.get(path).status_code, 200, f'a teacher opened {path}')
        self.assertNotEqual(client.post('/locks/unlock/', {'name': 'ab1000'}).status_code, 200)


class RolesFromFormsTests(AccountTestCase):
    """Extra fields in a sign-up or profile form must never hand out a role."""

    EXTRA = {'is_staff': 'on', 'is_superuser': 'on', 'is_active': 'on', 'groups': '1', 'user_permissions': '1'}

    def roles(self, user):
        user.refresh_from_db()
        return user.is_staff, user.is_superuser, user.groups.count(), user.user_permissions.count()

    def test_signing_up_with_role_fields_makes_an_ordinary_account(self):
        self.register('ab4321@srmist.edu.in', **self.EXTRA)
        user = User.objects.get(email='ab4321@srmist.edu.in')  # (a refused sign-up would be a failure here too: the form only needs the address)
        self.assertEqual(self.roles(user), (False, False, 0, 0))
        self.assertFalse(user.is_active)  # nothing is switched on until the owner opens the emailed link

    def test_finishing_the_sign_up_with_role_fields_still_makes_an_ordinary_account(self):
        self.finish_registration('ab4322@srmist.edu.in')
        user = User.objects.get(email='ab4322@srmist.edu.in')
        self.client.post(reverse('user_profile'), {'username': user.username, 'email': user.email, **self.EXTRA})
        self.assertEqual(self.roles(user), (False, False, 0, 0))
        self.assertTrue(user.is_active)


class SignInSessionTests(World):
    def sign_in(self, client, name='ab1000'):
        return client.post(reverse('login'), {'username': name, 'password': PASSWORD})

    def test_signing_in_starts_a_new_session(self):
        """A session an attacker planted before sign-in must not become the signed-in session."""
        client = Client()
        planted = client.session
        planted['probe'] = 'planted before sign-in'
        planted.save()
        before = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(self.sign_in(client).status_code, 302)
        self.assertNotEqual(client.cookies[settings.SESSION_COOKIE_NAME].value, before)
        old = Client()
        old.cookies[settings.SESSION_COOKIE_NAME] = before
        self.assertEqual(old.get('/profile/').status_code, 302)  # the planted session is not signed in

    def test_signing_out_ends_the_session_for_good(self):
        client = Client()
        self.sign_in(client)
        old_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(client.get('/profile/').status_code, 200)
        client.post(reverse('logout'))
        thief = Client()
        thief.cookies[settings.SESSION_COOKIE_NAME] = old_cookie  # the cookie copied before signing out
        self.assertEqual(thief.get('/profile/').status_code, 302)

    def test_a_password_change_signs_the_other_sessions_out(self):
        first, second = Client(), Client()
        self.sign_in(first)
        self.sign_in(second)
        self.assertEqual(second.get('/profile/').status_code, 200)
        self.alice.set_password('Another-Str0ng-Pass-5531!')
        self.alice.save()
        self.assertEqual(first.get('/profile/').status_code, 302)
        self.assertEqual(second.get('/profile/').status_code, 302)

    def test_the_sign_in_page_gives_the_same_answer_for_an_unknown_name_and_a_wrong_password(self):
        def answer(name):
            page = Client().post(reverse('login'), {'username': name, 'password': 'not-the-password'})
            return page.status_code, re.sub(r'(csrfmiddlewaretoken" value=")[^"]+', r'\1', page.content.decode()).replace(name, '@')
        self.assertEqual(answer('ab1000'), answer('zz9999'))


class StudentPagesNeverShowTheRightAnswerTests(World):
    """While an exam is on, nothing a student's browser receives says which choice is right."""

    def test_no_student_facing_response_of_a_running_exam_carries_a_correctness_field(self):
        client = signed_in(self.alice)
        token = self.exam.token
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.RUNNING)  # an open exam that is on: no clock, no lobby
        client.post(f'/exam/{token}/consent/', {'agree': 'on'})
        page = client.get(f'/exam/{token}/take/')
        self.assertEqual(page.status_code, 200)
        data = json.loads(re.search(r'<script id="exam-data" type="application/json">(.*?)</script>', page.content.decode(), re.S).group(1))
        flagged = []

        def look(node, where='payload'):
            if isinstance(node, dict):
                for key, value in node.items():
                    if re.search(r'correct|right|solution|answer_key', key, re.I) and key != 'answers':  # "answers" = the student's own picks
                        flagged.append(f'{where}.{key}')
                    look(value, f'{where}.{key}')
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    look(value, f'{where}[{index}]')
        look(data)
        self.assertEqual(flagged, [])
        question = data['questions'][0]
        for url_name, body in (('exam_answer', {'question': question['id'], 'choice': question['options'][0]['id']}), ('exam_ping', None),
                               ('exam_status', None)):
            response = client.post(reverse(url_name, args=[token]), body) if body else client.get(reverse(url_name, args=[token]))
            self.assertNotRegex(response.content.decode(), r'(?i)is_correct|"correct"|right_choice', url_name)


class AddressBehindAzureTests(SimpleTestCase):
    """Azure writes the visitor as "address:port". What a visitor writes to the left of it must still change nothing."""

    def ip(self, forwarded):
        from django.test import RequestFactory
        from quiz.util import client_ip
        return client_ip(RequestFactory().get('/', REMOTE_ADDR='169.254.130.1', HTTP_X_FORWARDED_FOR=forwarded))

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_a_visitor_cannot_choose_the_address_the_limits_see(self):
        real = '203.0.113.9:56571'
        for forged in ('6.6.6.6', '6.6.6.6:80', '[2001:db8::6]:80', '6.6.6.6, 7.7.7.7:9', ',', ' , ', 'x' * 500):
            self.assertEqual(self.ip(f'{forged}, {real}'), '203.0.113.9', forged[:20])

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_a_header_with_nothing_trusted_in_it_falls_back_to_the_proxy_address(self):
        for bad in ('', ',', '6.6.6.6:99999', 'localhost:80', '6.6.6.6:80:80'):
            self.assertEqual(self.ip(bad), '169.254.130.1', repr(bad))


class RealServerSettingsTests(SimpleTestCase):
    """settings.py as gunicorn builds it (debug off), which is not how the rest of the suite runs it."""

    def server_settings(self, **env):
        base = {'DATABASE_URL': 'postgres://u:p@localhost:5432/scratch', 'TEST_DATABASE_URL': '', 'DJANGO_DEBUG': 'False',
                'DJANGO_SECRET_KEY': 'x' * 60, 'DJANGO_ALLOWED_HOSTS': 'quiz.example.com', 'DJANGO_TRUSTED_PROXY_COUNT': '',
                'DJANGO_ASSUME_HTTPS': '', 'RENDER_EXTERNAL_HOSTNAME': '', 'DJANGO_HSTS_SECONDS': ''}

        def reload_clean():
            for name in ('STORAGES', 'SILENCED_SYSTEM_CHECKS', 'WHITENOISE_USE_FINDERS', 'WHITENOISE_AUTOREFRESH'):
                vars(project_settings).pop(name, None)
            return importlib.reload(project_settings)
        self.addCleanup(reload_clean)
        with mock.patch.dict(os.environ, {**base, **env}), mock.patch.object(sys, 'argv', ['gunicorn']), mock.patch('dotenv.load_dotenv'):
            return reload_clean()

    def test_cookies_are_marked_secure_and_the_session_cookie_is_not_readable_by_scripts(self):
        module = self.server_settings()
        self.assertTrue(module.SESSION_COOKIE_SECURE and module.CSRF_COOKIE_SECURE)
        self.assertTrue(getattr(module, 'SESSION_COOKIE_HTTPONLY', True))  # Django's default is True; it must not be switched off
        self.assertIn(getattr(module, 'SESSION_COOKIE_SAMESITE', 'Lax'), ('Lax', 'Strict'))
        self.assertIn(getattr(module, 'CSRF_COOKIE_SAMESITE', 'Lax'), ('Lax', 'Strict'))
        self.assertEqual((module.DEBUG, module.X_FRAME_OPTIONS, module.SECURE_CONTENT_TYPE_NOSNIFF), (False, 'DENY', True))

    def test_hsts_is_off_unless_the_host_asks_for_it(self):
        self.assertEqual(self.server_settings().SECURE_HSTS_SECONDS, 0)
        module = self.server_settings(DJANGO_HSTS_SECONDS='31536000', DJANGO_ASSUME_HTTPS='True')
        self.assertEqual(module.SECURE_HSTS_SECONDS, 31536000)
        self.assertEqual(module.SILENCED_SYSTEM_CHECKS, ['security.W008'])  # the HSTS warning is no longer hidden: HSTS is on

    def test_a_host_that_sends_its_own_hsts_keeps_both_warnings_silenced(self):
        module = self.server_settings(DJANGO_ASSUME_HTTPS='True')
        self.assertEqual(module.SILENCED_SYSTEM_CHECKS, ['security.W004', 'security.W008'])


class HstsHeaderTests(TestCase):
    @override_settings(SECURE_HSTS_SECONDS=31536000)
    def test_a_secure_request_gets_the_header_when_hsts_is_on(self):
        response = Client().get(reverse('login'), secure=True)
        self.assertEqual(response.headers.get('Strict-Transport-Security'), 'max-age=31536000')

    @override_settings(SECURE_HSTS_SECONDS=0)
    def test_no_header_when_it_is_off(self):
        self.assertNotIn('Strict-Transport-Security', Client().get(reverse('login'), secure=True).headers)
