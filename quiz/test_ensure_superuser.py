"""The command that makes the first superadmin on a host without a shell: it makes one when there is none, never a second, and never a
weak one."""
import os
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from quiz.roles import role_of

PASSWORD = 'Correct-Horse-Battery-9'
ENV = {'DJANGO_SUPERUSER_USERNAME': 'headmaster', 'DJANGO_SUPERUSER_EMAIL': 'head@example.com', 'DJANGO_SUPERUSER_PASSWORD': PASSWORD}


def run(**env):
    """Run the command with exactly these DJANGO_SUPERUSER_* variables set (none of the others), and return what it printed."""
    out = StringIO()
    with mock.patch.dict(os.environ, env):
        for name in ENV:
            if name not in env:
                os.environ.pop(name, None)
        call_command('ensure_superuser', stdout=out)
    return out.getvalue()


class EnsureSuperuserTests(TestCase):
    def test_it_makes_the_first_superadmin(self):
        printed = run(**ENV)
        user = User.objects.get(username='headmaster')
        self.assertTrue(user.is_superuser and user.is_staff and user.is_active)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual((user.email, role_of(user)), ('head@example.com', 'admin'))
        self.assertFalse(PASSWORD in printed, 'the password must never be printed')

    def test_running_it_again_changes_nothing(self):
        run(**ENV)
        before = list(User.objects.values_list('pk', 'username', 'password'))
        self.assertIn('already exists', run(**ENV))
        self.assertEqual(list(User.objects.values_list('pk', 'username', 'password')), before)

    def test_it_never_makes_a_second_superadmin(self):
        User.objects.create_superuser('root', 'root@example.com', 'Some-Other-Pass-1')
        run(**ENV)
        self.assertEqual(list(User.objects.values_list('username', flat=True)), ['root'])

    def test_it_does_nothing_unless_all_three_are_set(self):
        for left_out in ENV:
            printed = run(**{name: value for name, value in ENV.items() if name != left_out})
            self.assertIn(left_out, printed)
        self.assertEqual(User.objects.count(), 0)

    def test_a_short_or_weak_password_is_refused(self):
        for bad in ('Short-1', '1234567890qwertyuiop', '123456789012345'):  # too short, on the common list, all digits
            with self.assertRaises(CommandError, msg=bad):
                run(**{**ENV, 'DJANGO_SUPERUSER_PASSWORD': bad})
        self.assertEqual(User.objects.count(), 0)

    def test_a_bad_username_is_refused(self):
        with self.assertRaisesMessage(CommandError, 'username'):
            run(**{**ENV, 'DJANGO_SUPERUSER_USERNAME': 'head master'})
        self.assertEqual(User.objects.count(), 0)

    def test_an_ordinary_account_with_that_name_is_left_alone(self):
        other = User.objects.create_user('headmaster', 'someone@example.com', 'Their-Own-Pass-5')
        with self.assertRaisesMessage(CommandError, 'not a superadmin'):
            run(**ENV)
        other.refresh_from_db()
        self.assertTrue(other.check_password('Their-Own-Pass-5') and not other.is_superuser)
