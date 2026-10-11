"""Passwords are stored with small-settings Argon2id (quiz/hashers.py); old PBKDF2 passwords still work and are upgraded at the next sign-in.
The rest of the suite runs with a fast fake hasher (settings.py), so every test here switches the real list on."""
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.hashers import Argon2PasswordHasher, check_password, identify_hasher, make_password
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from quiz.hashers import SmallArgon2PasswordHasher
from quiz.test_account_security import PASSWORD

REAL_HASHERS = ['quiz.hashers.SmallArgon2PasswordHasher', 'django.contrib.auth.hashers.PBKDF2PasswordHasher']  # settings.py must say the same
ARGON2_PREFIX = 'argon2$argon2id$v=19$m=19456,t=2,p=1$'


@override_settings(PASSWORD_HASHERS=REAL_HASHERS)
class StoredPasswordTests(SimpleTestCase):
    def test_a_new_password_is_stored_as_small_argon2id(self):
        encoded = make_password(PASSWORD)
        self.assertTrue(encoded.startswith(ARGON2_PREFIX), encoded[:40])
        self.assertTrue(check_password(PASSWORD, encoded))
        self.assertFalse(check_password(PASSWORD + 'x', encoded))

    def test_the_same_password_gets_a_different_hash_each_time(self):
        self.assertNotEqual(make_password(PASSWORD), make_password(PASSWORD))

    def test_a_hash_with_the_current_settings_is_not_rewritten(self):
        self.assertFalse(SmallArgon2PasswordHasher().must_update(make_password(PASSWORD)))

    def test_a_hash_made_with_other_argon2_settings_is_upgraded(self):
        other = Argon2PasswordHasher().encode(PASSWORD, 'somesalt')  # Django's own numbers: 100 MiB, 8 lanes
        self.assertFalse(other.startswith(ARGON2_PREFIX))
        upgraded = []
        self.assertTrue(check_password(PASSWORD, other, setter=upgraded.append))
        self.assertEqual(upgraded, [PASSWORD])  # Django asks to store it again with the current settings

    def test_an_old_pbkdf2_hash_is_still_accepted_and_marked_for_upgrade(self):
        old = make_password(PASSWORD, hasher='pbkdf2_sha256')
        self.assertTrue(old.startswith('pbkdf2_sha256$'))
        upgraded = []
        self.assertTrue(check_password(PASSWORD, old, setter=upgraded.append))
        self.assertEqual(upgraded, [PASSWORD])
        self.assertFalse(check_password(PASSWORD + 'x', old, setter=upgraded.append))
        self.assertEqual(len(upgraded), 1)  # a wrong password changes nothing

    def test_the_hasher_in_use_is_ours(self):
        self.assertIsInstance(identify_hasher(make_password(PASSWORD)), SmallArgon2PasswordHasher)

    def test_the_settings_stay_inside_what_was_decided(self):
        """Not above: eight sign-ins at once must stay far below a small host's memory (Django's own 100 MiB x 8 lanes would not).
        Not below: OWASP's minimum for Argon2id is 19 MiB with 2 passes and 1 lane."""
        hasher = SmallArgon2PasswordHasher
        self.assertEqual(hasher.parallelism, 1)
        self.assertTrue(19456 <= hasher.memory_cost <= 65536, hasher.memory_cost)
        self.assertTrue(2 <= hasher.time_cost <= 4, hasher.time_cost)


@override_settings(PASSWORD_HASHERS=REAL_HASHERS)
class SigningInUpgradesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('ab0001', 'ab0001@srmist.edu.in', PASSWORD)

    def make_it_old(self):
        self.user.password = make_password(PASSWORD, hasher='pbkdf2_sha256')
        self.user.save()

    def sign_in(self, password=PASSWORD):
        return self.client.post(reverse('login'), {'username': 'ab0001', 'password': password})

    def stored(self):
        return User.objects.get(pk=self.user.pk).password

    def test_a_new_account_signs_in_with_argon2id(self):
        self.assertTrue(self.stored().startswith(ARGON2_PREFIX))
        self.assertEqual(self.sign_in().status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_an_account_with_an_old_hash_signs_in_and_is_upgraded(self):
        self.make_it_old()
        self.assertTrue(self.stored().startswith('pbkdf2_sha256$'))
        self.assertEqual(self.sign_in().status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        self.assertTrue(self.stored().startswith(ARGON2_PREFIX))
        self.assertEqual(self.client.get('/profile/').status_code, 200)  # storing the password again did not sign this very session out
        self.client.logout()
        self.assertEqual(self.sign_in().status_code, 302)  # and the upgraded password still works
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_a_wrong_password_leaves_the_old_hash_alone(self):
        self.make_it_old()
        before = self.stored()
        self.assertEqual(self.sign_in('not the password').status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.stored(), before)


class WhereTheHostsGetTheLibraryTests(SimpleTestCase):
    def test_both_halves_are_pinned_in_requirements(self):
        """Without these lines a host's build would not install the library and the first password check would crash."""
        text = (Path(settings.BASE_DIR) / 'requirements.txt').read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^argon2-cffi==\d')
        self.assertRegex(text, r'(?m)^argon2-cffi-bindings==\d')

    def test_the_library_loads(self):
        with mock.patch.object(SmallArgon2PasswordHasher, 'library', 'argon2'):
            self.assertTrue(SmallArgon2PasswordHasher()._load_library())
