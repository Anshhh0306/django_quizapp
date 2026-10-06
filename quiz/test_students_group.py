"""The Students group: an account with ANY address becomes a student by group, as a teacher becomes one by the Teachers group. It matters for test accounts
(made in the admin site with whatever address) and keeps working for the register-number addresses that need no group."""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from quiz.exams import group_student_emails, parse_allowed
from quiz.models import Choice, Exam, ExamAllowed, ExamAttempt
from quiz.roles import STUDENTS_GROUP, TEACHERS_GROUP, is_student, role_of
from quiz.test_exam_entry import PASSWORD, ExamEntryBase


def tester(name='tester1', email='tester1@example.com', group=None):
    user = User.objects.create_user(name, email, PASSWORD)
    if group:
        user.groups.add(Group.objects.get(name=group))
    return user


class RoleByGroupTests(TestCase):
    def test_the_group_is_made_by_the_migrations(self):
        self.assertTrue(Group.objects.filter(name=STUDENTS_GROUP).exists())

    def test_any_address_becomes_a_student_by_group_and_stops_being_one_when_removed(self):
        user = tester()
        self.assertEqual((role_of(user), is_student(user)), ('pending', False))
        user.groups.add(Group.objects.get(name=STUDENTS_GROUP))
        self.assertEqual((role_of(user), is_student(user)), ('student', True))
        user.groups.clear()
        self.assertEqual((role_of(user), is_student(user)), ('pending', False))

    def test_a_register_number_address_needs_no_group_and_no_query(self):
        user = User.objects.create_user('ad3919', 'ad3919@srmist.edu.in', PASSWORD)
        with self.assertNumQueries(0):
            self.assertEqual(role_of(user), 'student')
            self.assertTrue(is_student(user))

    def test_a_role_costs_one_query_at_most(self):
        staff, teacher, student = tester('s1', 's1@srmist.edu.in'), tester('t1', 't1@srmist.edu.in', TEACHERS_GROUP), tester('g1', 'g1@x.org', STUDENTS_GROUP)
        admin = User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        for user, role, queries in ((staff, 'pending', 1), (teacher, 'teacher', 1), (student, 'student', 1), (admin, 'admin', 0)):
            with self.assertNumQueries(queries):
                self.assertEqual(role_of(user), role)

    def test_a_superuser_stays_admin_even_in_the_group(self):
        admin = User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        admin.groups.add(Group.objects.get(name=STUDENTS_GROUP))
        self.assertEqual(role_of(admin), 'admin')

    def test_a_member_of_both_groups_is_a_student_as_a_register_number_with_the_teachers_group_always_was(self):
        user = tester('both', 'both@srmist.edu.in', TEACHERS_GROUP)
        self.assertEqual(role_of(user), 'teacher')
        user.groups.add(Group.objects.get(name=STUDENTS_GROUP))
        self.assertEqual(role_of(user), 'student')
        register = tester('ad3919', 'ad3919@srmist.edu.in', TEACHERS_GROUP)
        self.assertEqual(role_of(register), 'student')

    def test_the_teachers_group_still_makes_exactly_a_teacher(self):
        user = tester('shantini', 'shantini@srmist.edu.in')
        self.assertEqual(role_of(user), 'pending')
        user.groups.add(Group.objects.get(name=TEACHERS_GROUP))
        self.assertEqual((role_of(user), is_student(user)), ('teacher', False))


class ExamAccessByGroupTests(ExamEntryBase):
    def test_a_group_student_can_walk_the_whole_door(self):
        user = tester(group=STUDENTS_GROUP)
        self.enter(user)
        self.assertEqual(ExamAttempt.objects.filter(user=user).count(), 1)

    def test_the_same_account_without_the_group_is_turned_away(self):
        user = tester()
        self.login(user)
        self.assertContains(self.entry(), 'Only student accounts')
        self.assertEqual(ExamAttempt.objects.count(), 0)

    def test_a_class_list_that_names_a_group_student_admits_them_and_nobody_else(self):
        listed, other = tester(group=STUDENTS_GROUP), tester('tester2', 'tester2@example.com', STUDENTS_GROUP)
        ExamAllowed.objects.create(exam=self.exam, email='tester1@example.com')
        self.enter(listed)
        self.login(other)
        self.assertContains(self.entry(), 'Not on the list')
        self.assertEqual(list(ExamAttempt.objects.values_list('user__username', flat=True)), ['tester1'])


class ClassListByGroupTests(ExamEntryBase):
    def test_parse_allowed_takes_other_addresses_only_when_told(self):
        emails, bad = parse_allowed('ad3919 tester1@example.com tester2@example.com', {'tester1@example.com'})
        self.assertEqual((emails, bad), (['ad3919@srmist.edu.in', 'tester1@example.com'], ['tester2@example.com']))
        self.assertEqual(parse_allowed('tester1@example.com'), ([], ['tester1@example.com']))  # nothing changes without the group's addresses

    def test_group_student_emails_lists_members_only_in_lowercase(self):
        tester('a', 'a@x.org', STUDENTS_GROUP)
        tester('b', 'b@x.org')
        tester('c', 'C@X.ORG', STUDENTS_GROUP)
        tester('d', '', STUDENTS_GROUP)
        self.assertEqual(group_student_emails(), {'a@x.org', 'c@x.org'})

    def test_a_teacher_can_put_a_group_student_on_the_class_list_and_a_stranger_is_refused(self):
        tester(group=STUDENTS_GROUP)
        self.login(self.teacher)
        url = reverse('exam_detail', args=[self.exam.pk])
        self.client.post(url, {'action': 'allow', 'students': 'tester1@example.com stranger@example.com'})
        self.assertFalse(ExamAllowed.objects.filter(exam=self.exam).exists(), 'a list with an invalid entry adds nothing')
        self.client.post(url, {'action': 'allow', 'students': 'tester1@example.com'})
        self.assertEqual(list(ExamAllowed.objects.filter(exam=self.exam).values_list('email', flat=True)), ['tester1@example.com'])


    def test_the_new_exam_form_takes_a_group_student_in_its_class_list_too(self):
        tester(group=STUDENTS_GROUP)
        self.login(self.teacher)
        question = self.exam.questions.get()
        Choice.objects.create(question=question, text='x', is_correct=True)
        form = {'mode': 'open', 'seat_limit': 5, 'questions': [question.pk]}
        self.client.post(reverse('exam_new'), {**form, 'title': 'Group exam', 'allowed_text': 'tester1@example.com'})
        self.assertEqual(list(Exam.objects.get(title='Group exam').allowed.values_list('email', flat=True)), ['tester1@example.com'])
        self.client.post(reverse('exam_new'), {**form, 'title': 'Bad exam', 'allowed_text': 'tester1@example.com nobody@example.com'})
        self.assertFalse(Exam.objects.filter(title='Bad exam').exists(), 'a stranger on the list blocks the whole exam')


class AdminActionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        self.client.force_login(self.admin)

    def action(self, name, *users):
        return self.client.post(reverse('admin:auth_user_changelist'), {'action': name, '_selected_action': [u.pk for u in users]})

    def test_make_students_adds_the_group_ends_teacher_status_and_leaves_superadmins_alone(self):
        teacher, plain = tester('shantini', 'shantini@srmist.edu.in', TEACHERS_GROUP), tester()
        self.action('make_students', teacher, plain, self.admin)
        self.assertEqual([role_of(User.objects.get(pk=u.pk)) for u in (teacher, plain, self.admin)], ['student', 'student', 'admin'])
        self.assertFalse(Group.objects.get(name=TEACHERS_GROUP).user_set.filter(pk=teacher.pk).exists())
        self.assertFalse(Group.objects.get(name=STUDENTS_GROUP).user_set.filter(pk=self.admin.pk).exists())

    def test_approving_teachers_still_skips_students_by_group(self):
        group_student = tester(group=STUDENTS_GROUP)
        staff = tester('shantini', 'shantini@srmist.edu.in')
        self.action('approve_teachers', group_student, staff)
        self.assertEqual((role_of(User.objects.get(pk=group_student.pk)), role_of(User.objects.get(pk=staff.pk))), ('student', 'teacher'))

    def test_the_user_list_shows_the_role(self):
        tester(group=STUDENTS_GROUP)
        self.assertContains(self.client.get(reverse('admin:auth_user_changelist')), 'student')
