"""The small pages around the app: a friendly 404, a 500 that cannot itself break, and the phone-ready page shell."""
from unittest import mock

from django.template.loader import render_to_string
from django.test import Client, TestCase

from quiz.context import _version


class PageShellTests(TestCase):
    def test_a_missing_page_says_what_to_do(self):
        r = Client().get('/no/such/page/')
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, 'Page not found', status_code=404)
        self.assertContains(r, 'ask your teacher to send it again', status_code=404)

    def test_the_server_error_page_stands_alone(self):
        html = render_to_string('500.html')
        self.assertIn('Something went wrong', html)
        self.assertIn('Your saved answers are safe', html)
        self.assertNotIn('{%', html)  # no template tags: it must work when everything else is broken
        self.assertNotIn('<link rel="stylesheet"', html)  # and needs no stylesheet from the server

    def test_every_page_tells_phones_to_use_their_real_width(self):
        html = Client().get('/accounts/login/').content.decode()
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', html)
        self.assertIn('class="skip-link"', html)
        self.assertIn('lang="en"', html)

    def test_the_stylesheet_link_changes_whenever_the_file_does(self):
        """Browsers keep static files for a guessed time, so an updated stylesheet must have a new address."""
        html = Client().get('/accounts/login/').content.decode()
        self.assertRegex(html, r'href="/static/quiz/style\.css\?v=[1-9]\d+"')
        with mock.patch('quiz.context.os.path.getmtime', return_value=111):
            first = Client().get('/accounts/login/').content.decode()
        with mock.patch('quiz.context.os.path.getmtime', return_value=222):
            second = Client().get('/accounts/login/').content.decode()
        self.assertIn('style.css?v=111"', first)
        self.assertIn('style.css?v=222"', second)

    def test_a_file_that_does_not_exist_gets_version_zero_not_a_crash(self):
        self.assertEqual(_version('quiz/not-there.css'), 0)

    def test_the_fonts_are_served_by_this_site_not_a_third_party(self):
        html = Client().get('/accounts/login/').content.decode()
        self.assertNotIn('fonts.googleapis', html)
        self.assertNotIn('fonts.gstatic', html)
        self.assertIn('quiz/fonts/AtkinsonHyperlegibleNext.woff2', html)
