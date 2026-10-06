"""Running behind a host's proxy: who the visitor is, https, cache keys, error logging, the server config."""
import importlib
import logging
import os
import re
import runpy
import sys
import tempfile
import warnings
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.cache import cache
from django.core.cache.backends.base import CacheKeyWarning
from django.core.management import call_command
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

import quiz_project.settings as project_settings
from quiz.exam_device import _here
from quiz.util import client_ip

PROXY = '10.9.9.9'  # what REMOTE_ADDR shows behind a proxy: the proxy itself


class ClientIpTests(SimpleTestCase):
    def ip(self, forwarded=None, direct=PROXY):
        extra = {'REMOTE_ADDR': direct}
        if forwarded is not None:
            extra['HTTP_X_FORWARDED_FOR'] = forwarded
        return client_ip(RequestFactory().get('/', **extra))

    def test_by_default_the_header_is_not_believed(self):
        self.assertEqual(self.ip('6.6.6.6'), PROXY)

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_one_proxy_means_the_last_entry_is_the_visitor(self):
        self.assertEqual(self.ip('203.0.113.9'), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_what_the_visitor_wrote_to_the_left_is_ignored(self):
        self.assertEqual(self.ip('6.6.6.6, 203.0.113.9'), '203.0.113.9')
        self.assertEqual(self.ip('1.1.1.1,2.2.2.2,203.0.113.9'), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_two_proxies_count_two_from_the_right(self):
        self.assertEqual(self.ip('6.6.6.6, 203.0.113.9, 10.1.1.1'), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_a_header_with_too_few_entries_falls_back(self):
        self.assertEqual(self.ip('203.0.113.9'), PROXY)

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_no_header_falls_back(self):
        self.assertEqual(self.ip(), PROXY)

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_anything_that_is_not_an_address_falls_back(self):
        for bad in ('not-an-ip', '1.2.3.4:80', '<script>', 'x' * 300, '999.1.1.1', ',', ' '):
            self.assertEqual(self.ip(bad), PROXY, repr(bad[:20]))

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_an_ipv6_address_is_written_one_way(self):
        self.assertEqual(self.ip('2001:DB8:0:0:0:0:0:1'), '2001:db8::1')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_no_address_at_all_is_none(self):
        self.assertIsNone(self.ip(direct=''))

    def test_only_client_ip_reads_the_raw_address(self):
        """Every place that needs an address goes through client_ip; a new REMOTE_ADDR somewhere would quietly see the proxy."""
        offenders = [path.name for path in Path(__file__).parent.glob('*.py')
                     if not path.name.startswith('test') and path.name != 'util.py' and 'REMOTE_ADDR' in path.read_text(encoding='utf-8')]
        self.assertEqual(offenders, [])


class NoHeaderDumpTests(SimpleTestCase):
    """A host's gateway can put credentials in request headers (Zoho's puts an admin token and the project secret key in x-zc-*
    on every request). So no code may print, log or show the headers as a whole: only look up the one header it needs."""
    FORBIDDEN = re.compile(r'request\.headers|META\.(?:items|keys|values|copy)\(|dict\(request\.META|vars\(request|repr\(request|print\(request')

    def test_no_module_or_template_dumps_the_headers(self):
        quiz = Path(__file__).parent
        files = [p for p in quiz.glob('*.py') if not p.name.startswith('test')] + list(quiz.rglob('*.html')) + list(quiz.rglob('*.txt')) \
            + list((Path(settings.BASE_DIR) / 'templates').rglob('*.html'))
        offenders = [p.name for p in files if self.FORBIDDEN.search(p.read_text(encoding='utf-8')) or re.search(r'{{\s*request\.META', p.read_text(encoding='utf-8'))]
        self.assertTrue(len(files) > 40, 'the scan found too few files')
        self.assertEqual(offenders, [])


@override_settings(TRUSTED_PROXY_COUNT=1)
class VisitorsBehindOneProxyTests(TestCase):
    """The proxy's own address is the same for everybody: limits must count the visitors, not the proxy."""

    def setUp(self):
        cache.clear()

    def wrong_password(self, visitor, name):
        return self.client.post(reverse('login'), {'username': name, 'password': 'wrong'},
                                REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=f'6.6.6.6, {visitor}')

    def spray_and_try_again(self, first_visitor, second_visitor):
        for name in ('ab0001', 'ab0002', 'ab0003'):
            self.wrong_password(first_visitor, name)
        return self.wrong_password(first_visitor, 'ab0004'), self.wrong_password(second_visitor, 'ab0005')

    def test_a_visitor_who_guesses_is_held_up_alone(self):
        with mock.patch('quiz.ratelimit.LOGIN_IP_LIMIT', 3):
            guesser, bystander = self.spray_and_try_again('203.0.113.1', '203.0.113.2')
        self.assertContains(guesser, 'Too many failed login attempts')
        self.assertNotContains(bystander, 'Too many failed login attempts')

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_trusted_proxies_the_header_is_not_believed(self):
        """Not told about the proxy, the app must not let a visitor pick the address the limits see: both share the proxy's."""
        with mock.patch('quiz.ratelimit.LOGIN_IP_LIMIT', 3):
            guesser, bystander = self.spray_and_try_again('203.0.113.1', '203.0.113.2')
        self.assertContains(bystander, 'Too many failed login attempts')

    @override_settings(REQUEST_CAPS={'address': 2, 'user': 1000})
    def test_the_request_cap_is_per_visitor(self):
        def hit(visitor):
            return self.client.get('/', REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=visitor).status_code
        self.assertEqual([hit('203.0.113.1'), hit('203.0.113.1'), hit('203.0.113.2'), hit('203.0.113.2')], [200] * 4)
        self.assertEqual(hit('203.0.113.1'), 429)  # the first visitor is over their own cap
        self.assertEqual(hit('203.0.113.3'), 200)  # a third is not

    def test_the_exam_device_records_the_visitor(self):
        request = RequestFactory().get('/exam/x/', REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.9')
        request.device_id = 'd' * 20
        self.assertEqual(_here(request)[2], '203.0.113.9')


@override_settings(ALLOWED_HOSTS=['quiz.example.com'])
class AssumeHttpsTests(TestCase):
    """Zoho's gateway ends HTTPS, sends no X-Forwarded-Proto and puts the port in Host ("name:443")."""
    HOST = 'quiz.example.com:443'

    def browser_login_post(self):
        client = Client(enforce_csrf_checks=True)
        client.get('/accounts/login/', HTTP_HOST=self.HOST)  # the page sets the CSRF cookie
        return client.post('/accounts/login/', {'username': 'nobody', 'password': 'x', 'csrfmiddlewaretoken': client.cookies['csrftoken'].value},
                           HTTP_HOST=self.HOST, HTTP_ORIGIN='https://quiz.example.com', HTTP_REFERER='https://quiz.example.com/accounts/login/')

    def test_without_the_setting_a_form_post_from_the_browser_is_refused(self):
        """The failure the host would show: Django takes the page for http://quiz.example.com:443 and the Origin does not match."""
        self.assertEqual(self.browser_login_post().status_code, 403)

    @override_settings(ASSUME_HTTPS=True)
    def test_with_the_setting_the_same_post_goes_through(self):
        self.assertEqual(self.browser_login_post().status_code, 200)  # the login page again, with "wrong password"

    @override_settings(ASSUME_HTTPS=True)
    def test_links_are_https_without_the_port(self):
        request = Client().get('/accounts/login/', HTTP_HOST=self.HOST).wsgi_request
        self.assertTrue(request.is_secure())
        self.assertEqual(request.build_absolute_uri('/verify/x/'), 'https://quiz.example.com/verify/x/')

    def test_off_by_default_nothing_is_changed(self):
        request = Client().get('/accounts/login/', HTTP_HOST=self.HOST).wsgi_request
        self.assertFalse(request.is_secure())
        self.assertEqual(request.get_host(), self.HOST)

    @override_settings(ASSUME_HTTPS=True)
    def test_only_the_default_https_port_is_dropped(self):
        for sent, seen in (('quiz.example.com:8443', 'quiz.example.com:8443'), ('quiz.example.com', 'quiz.example.com')):
            self.assertEqual(Client().get('/accounts/login/', HTTP_HOST=sent).wsgi_request.get_host(), seen)

    @override_settings(ASSUME_HTTPS=True)
    def test_a_host_that_is_not_allowed_is_still_refused(self):
        self.assertEqual(Client().get('/accounts/login/', HTTP_HOST='evil.example.net:443').status_code, 400)


class CacheKeyTests(TestCase):
    """Names, posted values and URL pieces go into cache keys as hashes: a key may not be long or hold spaces and control characters."""

    def test_hostile_text_never_reaches_a_cache_key(self):
        cache.clear()
        student = User.objects.create_user('ab1000', 'ab1000@srmist.edu.in', 'Some-Password-1')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            for _ in range(5):  # spaces and a control character; the fifth wrong password starts a lock and its alert
                self.client.post(reverse('login'), {'username': 'a b\x01c' * 20, 'password': 'wrong'})
            self.client.post(reverse('register'), {'email': 'x' * 300 + '@srmist.edu.in'})                    # longer than a key may be
            self.client.force_login(student)
            self.client.get('/exam/' + 'T' * 2000 + '/ping/')                                                  # a huge token in the URL
        self.assertEqual([w.message for w in caught if issubclass(w.category, CacheKeyWarning)], [])
        keys = list(cache._cache)  # LocMemCache's own dictionary
        self.assertTrue(keys and max(map(len, keys)) < 90, f'longest key: {max(map(len, keys), default=0)}')
        self.assertFalse([key for key in keys if not key.isprintable() or ' ' in key])


class ProductionSettingsTests(SimpleTestCase):
    """settings.py as a real server (DEBUG off, started by gunicorn, not manage.py) builds it; the rest of the suite runs in debug mode."""

    def settings_for(self, **env):
        base = {'DATABASE_URL': 'postgres://u:p@localhost:5432/scratch', 'TEST_DATABASE_URL': '', 'DJANGO_DEBUG': 'False',
                'DJANGO_SECRET_KEY': 'x' * 60, 'DJANGO_ALLOWED_HOSTS': 'quiz.example.com', 'DJANGO_TRUSTED_PROXY_COUNT': '',
                'DJANGO_ASSUME_HTTPS': ''}
        def reload_clean():  # reload() re-runs the file in the same namespace, so a name set by an earlier run would linger
            for name in ('STORAGES', 'SILENCED_SYSTEM_CHECKS', 'WHITENOISE_USE_FINDERS', 'WHITENOISE_AUTOREFRESH'):
                vars(project_settings).pop(name, None)
            return importlib.reload(project_settings)
        self.addCleanup(reload_clean)  # put the module back as it was for the real run
        with mock.patch.dict(os.environ, {**base, **env}), mock.patch.object(sys, 'argv', ['gunicorn']), mock.patch('dotenv.load_dotenv'):
            return reload_clean()

    def test_nothing_about_the_proxy_is_believed_unless_the_host_is_set_up_for_it(self):
        module = self.settings_for()
        self.assertEqual((module.TRUSTED_PROXY_COUNT, module.ASSUME_HTTPS, getattr(module, 'SILENCED_SYSTEM_CHECKS', [])), (0, False, []))

    def test_the_switches_for_a_host_like_zoho(self):
        module = self.settings_for(DJANGO_TRUSTED_PROXY_COUNT='1', DJANGO_ASSUME_HTTPS='True')
        self.assertEqual((module.TRUSTED_PROXY_COUNT, module.ASSUME_HTTPS), (1, True))
        self.assertEqual(module.SILENCED_SYSTEM_CHECKS, ['security.W004', 'security.W008'])  # the host does HTTPS and HSTS itself

    def test_a_real_server_uses_fingerprinted_static_files_and_secure_cookies(self):
        module = self.settings_for()
        self.assertEqual(module.STORAGES['staticfiles']['BACKEND'], 'whitenoise.storage.CompressedManifestStaticFilesStorage')
        self.assertTrue(module.SESSION_COOKIE_SECURE and module.CSRF_COOKIE_SECURE)

    def test_on_your_own_computer_static_files_come_straight_from_the_app(self):
        module = self.settings_for(DJANGO_DEBUG='True')
        self.assertFalse(hasattr(module, 'STORAGES'))
        self.assertTrue(module.WHITENOISE_USE_FINDERS and module.WHITENOISE_AUTOREFRESH)


class StaticFilesTests(SimpleTestCase):
    """A real server serves fingerprinted, compressed copies made by collectstatic. A template that names a file that does
    not exist, or a stylesheet that points at a missing font, would break there and nowhere else: so it is checked here."""

    def test_the_app_serves_its_own_static_files(self):
        response = Client().get('/static/quiz/style.css')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/css', response['Content-Type'])

    def test_every_file_a_template_names_is_collected_and_fingerprinted(self):
        production = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                      'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
        named = set()
        for template in (Path(settings.BASE_DIR) / 'templates', Path(__file__).parent / 'templates'):
            for page in template.rglob('*.html'):
                named.update(re.findall(r"{%\s*static\s+['\"]([^'\"]+)['\"]", page.read_text(encoding='utf-8')))
        self.assertTrue(named, 'the scan found no {% static %} in the templates')
        with tempfile.TemporaryDirectory() as root, override_settings(STATIC_ROOT=root, STORAGES=production):
            call_command('collectstatic', interactive=False, verbosity=0)  # fails on a stylesheet that points at a missing file
            for name in sorted(named):
                self.assertRegex(staticfiles_storage.url(name), r'\.[0-9a-f]{12}\.', name)  # style.5f3a1c9d2b7e.css


class LoggingTests(SimpleTestCase):
    def test_errors_are_not_hidden_when_debug_is_off(self):
        """Django's own console handler only works with DEBUG on: on a real server every crash would leave no trace."""
        self.assertEqual(settings.LOGGING['loggers']['django']['handlers'], ['console'])
        self.assertNotIn('filters', settings.LOGGING['handlers']['console'])
        self.assertTrue([h for h in logging.getLogger('django').handlers if isinstance(h, logging.StreamHandler) and not h.filters])


class GunicornConfigTests(SimpleTestCase):
    def config(self, **env):
        with mock.patch.dict(os.environ, env):
            for name in ('X_ZOHO_CATALYST_LISTEN_PORT', 'PORT'):
                if name not in env:
                    os.environ.pop(name, None)
            return runpy.run_path(str(settings.BASE_DIR / 'gunicorn.conf.py'))

    def test_the_host_says_which_port(self):
        self.assertEqual(self.config(X_ZOHO_CATALYST_LISTEN_PORT='9123', PORT='1111')['bind'], '0.0.0.0:9123')
        self.assertEqual(self.config(PORT='1111')['bind'], '0.0.0.0:1111')
        self.assertEqual(self.config()['bind'], '0.0.0.0:8000')

    def test_one_process_so_the_counters_are_exact(self):
        self.assertEqual(self.config()['workers'], 1)
