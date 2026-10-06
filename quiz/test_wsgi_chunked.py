"""Zoho Catalyst's gateway passes every request body on as "Transfer-Encoding: chunked" with no Content-Length, and Django then sees an EMPTY form (every
sign-in failed with "This field is required"). quiz_project/wsgi.py reads such a body and hands it on with a Content-Length."""
import re
from io import BytesIO
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

from django.contrib.auth.models import User
from django.core import signals
from django.core.cache import cache
from django.db import close_old_connections
from django.test import SimpleTestCase, TestCase

import quiz_project.wsgi as project_wsgi
from quiz import exams
from quiz_project.wsgi import MAX_CHUNKED_BODY, ReadChunkedBodies


class FakeSite:
    """Stands in for Django: remembers what it was handed and reads the body the way Django does (CONTENT_LENGTH bytes of wsgi.input)."""

    def __init__(self):
        self.called, self.environ, self.body = False, None, None

    def __call__(self, environ, start_response):
        self.called, self.environ = True, dict(environ)
        length = int(environ.get('CONTENT_LENGTH') or 0)
        self.body = environ['wsgi.input'].read(length) if length else b''
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'ok']


def environ_for(body=b'', transfer_encoding='chunked', content_length=None, method='POST', **extra):
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': '/x/', 'wsgi.input': BytesIO(body), **extra}
    setup_testing_defaults(environ)
    if transfer_encoding:
        environ['HTTP_TRANSFER_ENCODING'] = transfer_encoding
    if content_length is not None:
        environ['CONTENT_LENGTH'] = str(content_length)
    return environ


def call(app, environ):
    seen = {}

    def start_response(status, headers, exc_info=None):
        seen['status'], seen['headers'] = status, headers

    body = b''.join(app(environ, start_response))
    return seen['status'], seen['headers'], body


class ReadChunkedBodiesTests(SimpleTestCase):
    def setUp(self):
        self.site = FakeSite()
        self.wrapped = ReadChunkedBodies(self.site, limit=10)

    def test_a_chunked_body_is_handed_on_with_a_content_length(self):
        call(self.wrapped, environ_for(b'a=1&b=2'))
        self.assertEqual((self.site.body, self.site.environ['CONTENT_LENGTH']), (b'a=1&b=2', '7'))
        self.assertNotIn('HTTP_TRANSFER_ENCODING', self.site.environ)

    def test_an_empty_chunked_body_is_fine(self):
        call(self.wrapped, environ_for(b''))
        self.assertEqual((self.site.body, self.site.environ['CONTENT_LENGTH']), (b'', '0'))

    def test_the_header_is_recognised_whatever_its_case_or_company(self):
        for value in ('chunked', 'Chunked', 'gzip, CHUNKED'):
            site = FakeSite()
            call(ReadChunkedBodies(site, limit=10), environ_for(b'x=1', transfer_encoding=value))
            self.assertEqual((site.body, site.environ['CONTENT_LENGTH']), (b'x=1', '3'), value)

    def test_a_body_with_a_content_length_is_not_touched(self):
        stream = BytesIO(b'a=1')
        environ = environ_for(b'', transfer_encoding=None, content_length=3)
        environ['wsgi.input'] = stream
        call(self.wrapped, environ)
        self.assertIs(self.site.environ['wsgi.input'], stream)
        self.assertEqual(self.site.body, b'a=1')

    def test_chunked_and_a_content_length_together_are_left_for_the_server_to_judge(self):
        stream = BytesIO(b'a=1')
        environ = environ_for(b'', transfer_encoding='chunked', content_length=3)
        environ['wsgi.input'] = stream
        call(self.wrapped, environ)
        self.assertIs(self.site.environ['wsgi.input'], stream)

    def test_a_request_without_a_body_passes_untouched(self):
        status, _, _ = call(self.wrapped, environ_for(b'', transfer_encoding=None, method='GET'))
        self.assertTrue(status.startswith('200') and self.site.called)
        self.assertNotIn('HTTP_TRANSFER_ENCODING', self.site.environ)

    def test_a_chunked_body_at_the_limit_goes_through_and_one_byte_more_gets_a_413(self):
        call(self.wrapped, environ_for(b'x' * 10))
        self.assertEqual(len(self.site.body), 10)
        site = FakeSite()
        status, _, _ = call(ReadChunkedBodies(site, limit=10), environ_for(b'x' * 11))
        self.assertTrue(status.startswith('413'), status)
        self.assertFalse(site.called, 'a body over the limit must never reach the site')

    def test_the_limit_is_bigger_than_the_biggest_real_upload(self):
        self.assertGreater(MAX_CHUNKED_BODY, exams.MAX_BYTES * 2)

    def test_the_real_entry_point_is_wrapped(self):
        self.assertIsInstance(project_wsgi.application, ReadChunkedBodies)


class ChunkedSignInTests(TestCase):
    """The whole path with Django itself: a sign-in whose body arrives chunked, as it does on Zoho."""

    def setUp(self):
        cache.clear()
        User.objects.create_user('ab1000', 'ab1000@srmist.edu.in', 'Some-Long-Pass-78')
        for signal in (signals.request_started, signals.request_finished):  # Django's test client switches these off while it runs a request
            signal.disconnect(close_old_connections)  # (they would close the test's own connection); a bare WSGI call must do the same
            self.addCleanup(signal.connect, close_old_connections)

    def sign_in(self, password):
        common = {'PATH_INFO': '/accounts/login/', 'HTTP_HOST': 'testserver', 'REMOTE_ADDR': '127.0.0.1'}
        status, headers, page = call(project_wsgi.application, environ_for(b'', transfer_encoding=None, method='GET', **common))
        self.assertTrue(status.startswith('200'), f'GET of the login page: {status}, {page[:200]!r}')
        cookies = [value.strip().split(';')[0] for name, value in headers if name.lower() == 'set-cookie']  # Django's WSGI layer puts a space before the value
        self.assertTrue([c for c in cookies if c.startswith('csrftoken=')], f'no CSRF cookie; headers: {[(n, v[:30]) for n, v in headers]}')
        cookie = '; '.join(cookies)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.decode()).group(1)
        form = urlencode({'csrfmiddlewaretoken': token, 'username': 'ab1000', 'password': password}).encode()
        return call(project_wsgi.application, environ_for(form, HTTP_COOKIE=cookie, CONTENT_TYPE='application/x-www-form-urlencoded', **common))

    def test_a_chunked_form_reaches_django_with_its_fields(self):
        status, headers, page = self.sign_in('Some-Long-Pass-78')
        self.assertTrue(status.startswith('302'), f'{status}: the right password must sign in (the fields did not arrive?)')
        self.assertTrue([v for n, v in headers if n.lower() == 'set-cookie' and v.strip().startswith('sessionid=')], 'no session was started')

    def test_a_wrong_password_is_judged_not_reported_as_missing(self):
        status, _, page = self.sign_in('wrong-password')
        text = page.decode()
        self.assertTrue(status.startswith('200'))
        self.assertNotIn('This field is required', text)  # that message means the body never arrived
        self.assertIn('ab1000', text)  # the form is shown again with the username that was typed
