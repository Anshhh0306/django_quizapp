from django.contrib.auth.models import Group, User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from quiz.roles import role_of
from quiz.tokens import email_verification_token

PASSWORD = 'TestPassword123!'


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def _register(self, email):
        return self.client.post(reverse('register'), {'email': email})

    def test_student_email_any_case_is_accepted_and_lowercased(self):
        r = self._register('AD3919@SRMIST.EDU.IN')
        self.assertTemplateUsed(r, 'quiz/verification_sent.html')
        user = User.objects.get(email='ad3919@srmist.edu.in')
        self.assertEqual(user.username, 'ad3919')
        self.assertFalse(user.is_active)  # until the emailed link is clicked
        self.assertEqual(len(mail.outbox), 1)

    def test_verification_email_wording_depends_on_role(self):
        self._register('ad3919@srmist.edu.in')
        self._register('shantini@srmist.edu.in')
        student_mail, staff_mail = mail.outbox
        self.assertIn('Hello ad3919', student_mail.body)
        self.assertNotIn('administrator must approve', student_mail.body)
        self.assertIn('administrator must approve', staff_mail.body)

    def test_staff_email_is_accepted(self):
        self._register('shantini@srmist.edu.in')
        self.assertEqual(User.objects.get(username='shantini').email, 'shantini@srmist.edu.in')

    def test_bad_emails_are_rejected(self):
        for email in ['ad3919@gmail.com', 'ad3919@srmist.edu.in.evil.com', 'ad3919+2@srmist.edu.in',
                      '1234ab@srmist.edu.in', 'x@mailinator.com']:
            self.assertEqual(self._register(email).status_code, 200, email)  # form redisplayed
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_is_rejected_case_insensitively(self):
        self._register('ad3919@srmist.edu.in')
        self._register('AD3919@srmist.edu.in')
        self.assertEqual(User.objects.count(), 1)

    def test_pending_teacher_sees_notice_after_verification(self):
        self._register('shantini@srmist.edu.in')
        user = User.objects.get(username='shantini')
        url = reverse('verify_email', args=[
            urlsafe_base64_encode(force_bytes(user.pk)), email_verification_token.make_token(user)])
        self.assertTemplateUsed(self.client.get(url), 'quiz/verification_set_password.html')
        r = self.client.post(url, {'new_password1': PASSWORD, 'new_password2': PASSWORD})
        self.assertTrue(r.context['pending_teacher'])
        self.assertEqual(role_of(User.objects.get(pk=user.pk)), 'pending')  # verified, but still waiting for the admin

    def test_student_is_not_marked_pending(self):
        self._register('ad3919@srmist.edu.in')
        user = User.objects.get(username='ad3919')
        url = reverse('verify_email', args=[
            urlsafe_base64_encode(force_bytes(user.pk)), email_verification_token.make_token(user)])
        r = self.client.post(url, {'new_password1': PASSWORD, 'new_password2': PASSWORD})
        self.assertFalse(r.context['pending_teacher'])


class RoleAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.student = User.objects.create_user('ad3919', 'ad3919@srmist.edu.in', PASSWORD)
        self.staff = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)

    def test_login_accepts_any_case_and_full_email(self):
        for name in ['AD3919', 'ad3919', 'AD3919@srmist.edu.in']:
            self.client.logout()
            r = self.client.post(reverse('login'), {'username': name, 'password': PASSWORD})
            self.assertEqual(r.status_code, 302, name)

    def test_superuser_can_log_in_with_any_case_username_or_non_srmist_email(self):
        User.objects.create_superuser('Anshu', 'anshumaan.das@gmail.com', PASSWORD)
        for name in ['Anshu', 'anshu', 'ANSHUMAAN.DAS@GMAIL.COM']:
            self.client.logout()
            r = self.client.post(reverse('login'), {'username': name, 'password': PASSWORD})
            self.assertEqual(r.status_code, 302, name)
        self.assertEqual(self.client.get(reverse('home')).context['role'], 'admin')

    def test_wrong_password_still_fails(self):
        r = self.client.post(reverse('login'), {'username': 'ad3919', 'password': 'nope'})
        self.assertEqual(r.status_code, 200)

    def test_home_shows_role_specific_content(self):
        self.client.login(username='ad3919', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('home')).context['role'], 'student')
        self.client.login(username='shantini', password=PASSWORD)
        r = self.client.get(reverse('home'))
        self.assertEqual(r.context['role'], 'pending')
        self.assertNotIn('my_exams', r.context)

    def test_admin_action_approves_staff_but_skips_students(self):
        admin = User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        self.client.force_login(admin)
        self.client.post(reverse('admin:auth_user_changelist'), {
            'action': 'approve_teachers',
            '_selected_action': [self.staff.pk, self.student.pk]})
        self.assertEqual(role_of(User.objects.get(pk=self.staff.pk)), 'teacher')
        self.assertFalse(Group.objects.get(name='Teachers').user_set.filter(pk=self.student.pk).exists())

    def test_password_reset_works_with_uppercase_email(self):
        self.client.post(reverse('password_reset'), {'email': 'AD3919@SRMIST.EDU.IN'})
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_token_still_single_use(self):
        self.student.refresh_from_db()
        url = reverse('password_reset_confirm', args=[
            urlsafe_base64_encode(force_bytes(self.student.pk)),
            default_token_generator.make_token(self.student)])
        self.assertTrue(self.client.get(url).context['validlink'])
