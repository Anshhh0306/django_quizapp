"""Which database the site uses (PostgreSQL only, named by DATABASE_URL, never the live one while testing), and the one
rule about row locks that PostgreSQL enforces."""
import importlib
import os
import pathlib
import re
import sys
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

import quiz_project.settings as project_settings

LIVE = 'postgres://u:p@live.example.com:5432/live'
LOCAL = 'postgres://u:p@localhost:5432/scratch'


class DatabaseChoiceTests(SimpleTestCase):
    def database(self, command, **env):
        """DATABASES['default'] as settings.py builds it for this command (manage.py <command>) and these variables."""
        env = {'DATABASE_URL': '', 'TEST_DATABASE_URL': '', 'DJANGO_DEBUG': 'True', **env}
        self.addCleanup(importlib.reload, project_settings)  # put the module back as it was for the real run
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, 'argv', ['manage.py', command]), \
                mock.patch('dotenv.load_dotenv'):  # a real .env on this computer must not change the answer
            return importlib.reload(project_settings).DATABASES['default']

    def test_the_site_refuses_to_start_without_a_database_address(self):
        with self.assertRaisesMessage(ImproperlyConfigured, 'DATABASE_URL must be set'):
            self.database('runserver')

    def test_an_address_selects_postgresql(self):
        db = self.database('runserver', DATABASE_URL=LIVE)
        self.assertEqual((db['ENGINE'], db['HOST'], db['NAME']), ('django.db.backends.postgresql', 'live.example.com', 'live'))
        self.assertTrue(db['CONN_HEALTH_CHECKS'])  # a sleeping database drops connections; test one before reusing it

    def test_a_database_that_does_not_answer_is_given_up_on_after_a_few_seconds(self):
        """Without a limit a database that is down or waking up holds each request for minutes (260 seconds measured)."""
        self.assertEqual(self.database('runserver', DATABASE_URL=LIVE)['OPTIONS']['connect_timeout'], 10)
        self.assertEqual(int(self.database('runserver', DATABASE_URL=LIVE + '?connect_timeout=3')['OPTIONS']['connect_timeout']), 3)

    def test_tests_never_use_the_live_address(self):
        self.assertEqual(self.database('test', DATABASE_URL=LIVE, TEST_DATABASE_URL=LOCAL)['NAME'], 'scratch')
        # no test address: refuse, rather than fall back to the live database
        with self.assertRaisesMessage(ImproperlyConfigured, 'TEST_DATABASE_URL must be set'):
            self.database('test', DATABASE_URL=LIVE)

    def test_the_test_address_is_ignored_when_not_testing(self):
        self.assertEqual(self.database('runserver', DATABASE_URL=LIVE, TEST_DATABASE_URL=LOCAL)['NAME'], 'live')


class RowLockTests(SimpleTestCase):
    def test_a_seat_lock_that_joins_other_tables_locks_only_the_seat(self):
        """A plain FOR UPDATE also locks the joined exam and user rows. Every student's seat then waits on the one exam
        row, and a teacher's lock on the exam can deadlock with a student's save (shown on a real PostgreSQL: the
        student's request is killed). of=('self',) locks the seat only.
        ponytail: sees a chain written on one line; one split over several lines would not be checked."""
        chain = re.compile(r'select_for_update\(([^)]*)\)[^\n]*\.select_related|\.select_related\([^)]*\)[^\n]*select_for_update\(([^)]*)\)')
        for path in pathlib.Path(__file__).parent.glob('*.py'):
            if path.name.startswith('test'):
                continue
            for match in chain.finditer(path.read_text(encoding='utf-8')):
                self.assertIn('of=', ''.join(group or '' for group in match.groups()), f'{path.name}: {match.group(0)}')
