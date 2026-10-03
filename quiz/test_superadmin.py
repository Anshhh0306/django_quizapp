from django.contrib.auth.models import Group, User
from django.urls import NoReverseMatch, reverse

from quiz.models import Exam, ExamEvent, QuestionSet
from quiz.test_exam_take import PASSWORD, TakeBase
from quiz.test_question_sets import make_set, set_url


class SuperadminBase(TakeBase):
    """TakeBase's teacher (shantini) owns the exam. root is the superadmin; meena is another teacher."""

    def setUp(self):
        super().setUp()
        self.root = User.objects.create_superuser('root', 'root@example.com', PASSWORD)
        self.meena = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        self.meena.groups.add(Group.objects.get(name='Teachers'))
        self.pages = {
            'exam_detail': reverse('exam_detail', args=[self.exam.pk]),
            'exam_live': reverse('exam_live', args=[self.exam.pk]),
            'exam_controls': reverse('exam_controls', args=[self.exam.pk]),
            'exam_results': reverse('exam_results', args=[self.exam.pk]),
            'exam_result_detail': reverse('exam_result_detail', args=[self.exam.pk, self.attempt(self.students[0]).pk]),
            'results_csv': reverse('exam_results', args=[self.exam.pk]) + '?format=csv',
        }

    def events(self, kind):
        return ExamEvent.objects.filter(exam=self.exam, kind=kind)


class SeeingEverythingTests(SuperadminBase):
    def test_the_administrators_home_page_has_a_teacher_tools_button(self):
        self.login(self.root)
        self.assertContains(self.client.get(reverse('home')), reverse('teach_home'))

    def test_teacher_tools_list_other_teachers_exams_with_their_owner(self):
        self.login(self.root)
        r = self.client.get(reverse('teach_home'))
        self.assertEqual(list(r.context['others']), [self.exam])
        self.assertContains(r, 'Unit 1')
        self.assertContains(r, 'shantini')

    def test_a_teacher_never_gets_that_list(self):
        self.login(self.meena)
        r = self.client.get(reverse('teach_home'))
        self.assertNotIn('others', r.context)
        self.assertNotContains(r, 'Unit 1')

    def test_the_administrator_can_open_every_page_of_any_exam(self):
        self.login(self.root)
        for name, url in self.pages.items():
            self.assertEqual(self.client.get(url).status_code, 200, name)

    def test_other_teachers_and_students_are_still_locked_out(self):
        self.login(self.meena)
        for name, url in self.pages.items():
            self.assertEqual(self.client.get(url).status_code, 404, name)
        self.login(self.students[0])
        for name, url in self.pages.items():
            self.assertEqual(self.client.get(url).status_code, 302, name)  # sent home

    def test_the_exam_page_says_whose_exam_it_is_only_to_the_administrator(self):
        self.login(self.root)
        self.assertContains(self.client.get(self.pages['exam_detail']), 'This exam belongs to shantini')
        self.login(self.teacher)
        self.assertNotContains(self.client.get(self.pages['exam_detail']), 'This exam belongs to')


class ActingTests(SuperadminBase):
    def test_the_administrator_can_end_someone_elses_exam_and_it_is_logged(self):
        self.login(self.root)
        self.client.post(self.pages['exam_detail'], {'action': 'end'})
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, Exam.ENDED)
        entry = self.events('admin').get()
        self.assertEqual(entry.actor, self.root)
        self.assertEqual(entry.detail, 'Administrator action: end')

    def test_extra_time_given_by_the_administrator_is_logged_with_their_name(self):
        self.run_now()
        self.take(self.students[0])  # the student starts
        attempt = self.attempt(self.students[0])
        self.login(self.root)
        self.client.post(self.pages['exam_detail'], {'action': 'extra_time', 'attempt': attempt.pk, 'minutes': 5})
        attempt.refresh_from_db()
        self.assertEqual(attempt.extra_seconds, 300)
        self.assertEqual(self.events('extra_time').get().actor, self.root)
        self.assertEqual(self.events('admin').count(), 1)

    def test_the_owners_own_actions_are_not_marked_as_administrator_actions(self):
        self.login(self.teacher)
        self.client.post(self.pages['exam_detail'], {'action': 'end'})
        self.assertEqual(self.events('admin').count(), 0)

    def test_another_teacher_still_cannot_act_on_the_exam(self):
        self.login(self.meena)
        self.assertEqual(self.client.post(self.pages['exam_detail'], {'action': 'end'}).status_code, 404)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, Exam.LOBBY)
        self.assertEqual(self.events('admin').count(), 0)


class PrivacyTests(SuperadminBase):
    def test_question_banks_stay_private_even_from_the_administrator(self):
        theirs = make_set(self.meena, 'Meena secret set')
        self.login(self.root)
        r = self.client.get(reverse('question_bank'))
        self.assertEqual(list(r.context['sets']), [])
        self.assertNotContains(r, 'Meena secret set')
        for action in ('delete', 'hide'):
            self.assertEqual(self.client.post(set_url(theirs), {'action': action}).status_code, 404)
        self.assertTrue(QuestionSet.objects.filter(pk=theirs.pk, hidden=False).exists())


class RoleBadgeTests(SuperadminBase):
    """The coloured box in the top bar follows the real role, not Django's old is_staff flag."""

    def badge(self, user):
        self.login(user)
        html = self.client.get(reverse('home')).content.decode()
        return [name for name in ('Superuser', 'Teacher', 'Awaiting approval') if f'>{name}<' in html]

    def test_an_approved_teacher_gets_the_teacher_box_even_without_the_staff_flag(self):
        self.assertFalse(self.teacher.is_staff)
        self.assertEqual(self.badge(self.teacher), ['Teacher'])

    def test_the_staff_flag_changes_nothing(self):
        User.objects.filter(pk=self.teacher.pk).update(is_staff=True)
        self.assertEqual(self.badge(self.teacher), ['Teacher'])
        User.objects.filter(pk=self.students[0].pk).update(is_staff=True)
        self.assertEqual(self.badge(self.students[0]), [])

    def test_the_superadmin_box(self):
        self.assertEqual(self.badge(self.root), ['Superuser'])

    def test_unapproved_staff_see_awaiting_approval(self):
        pending = User.objects.create_user('newstaff', 'newstaff@srmist.edu.in', PASSWORD)
        self.assertEqual(self.badge(pending), ['Awaiting approval'])

    def test_students_get_no_box(self):
        self.login(self.students[0])
        self.assertNotContains(self.client.get(reverse('home')), 'role-badge')

    def test_logged_out_pages_still_render(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('login')).status_code, 200)


class LeaderboardGoneTests(SuperadminBase):
    def test_the_leaderboard_page_and_links_are_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse('leaderboard')
        self.login(self.students[0])
        self.assertEqual(self.client.get('/leaderboard/').status_code, 404)
        self.assertNotContains(self.client.get(reverse('home')), 'Leaderboard')
