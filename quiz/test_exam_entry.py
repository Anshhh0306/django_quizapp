from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from quiz.exam_views import claim_seat
from quiz.models import Exam, ExamAllowed, ExamAttempt, ExamDenied, Question

PASSWORD = 'TestPassword123!'


class ExamEntryBase(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)
        self.teacher.groups.add(Group.objects.get(name='Teachers'))
        self.students = [User.objects.create_user(f'ab{1000 + i}', f'ab{1000 + i}@srmist.edu.in', PASSWORD)
                         for i in range(3)]
        self.exam = Exam.objects.create(owner=self.teacher, title='Unit 1', seat_limit=2,
                                        duration_minutes=30, status=Exam.LOBBY)
        self.exam.questions.add(Question.objects.create(text='q', owner=self.teacher))

    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PASSWORD)

    def enter(self, user):
        """Walk the whole door: link -> consent -> lobby. Returns the final response."""
        self.login(user)
        return self.client.post(reverse('exam_consent', args=[self.exam.token]), {'agree': 'on'}, follow=True)

    def entry(self):
        return self.client.get(reverse('exam_entry', args=[self.exam.token]))


class AdmissionTests(ExamEntryBase):
    def test_anonymous_goes_to_login_and_comes_back(self):
        r = self.entry()
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login/', r['Location'])
        self.assertIn(f'next=/exam/{self.exam.token}/', r['Location'])

    def test_unknown_link_is_404(self):
        self.login(self.students[0])
        self.assertEqual(self.client.get(reverse('exam_entry', args=['nope'])).status_code, 404)

    def test_teacher_and_pending_staff_are_not_admitted(self):
        pending = User.objects.create_user('newstaff', 'newstaff@srmist.edu.in', PASSWORD)
        for user in (self.teacher, pending):
            self.login(user)
            r = self.entry()
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'Only student accounts')
        self.assertEqual(ExamAttempt.objects.count(), 0)

    def test_draft_and_ended_exams_are_closed_to_new_students(self):
        self.login(self.students[0])
        for status, text in ((Exam.DRAFT, 'not open yet'), (Exam.ENDED, 'has ended')):
            Exam.objects.filter(pk=self.exam.pk).update(status=status)
            self.assertContains(self.entry(), text)

    def test_open_exam_leads_to_consent(self):
        self.login(self.students[0])
        self.assertRedirects(self.entry(), reverse('exam_consent', args=[self.exam.token]))

    def test_class_list_blocks_others_and_logs_each_student_once(self):
        ExamAllowed.objects.create(exam=self.exam, email='ab1000@srmist.edu.in')
        self.login(self.students[1])
        for _ in range(3):
            self.assertContains(self.entry(), 'not on the class list')
        row = ExamDenied.objects.get()
        self.assertEqual((row.user, row.reason, row.tries), (self.students[1], 'not_listed', 3))

    def test_class_list_match_ignores_case_in_the_account_email(self):
        User.objects.filter(pk=self.students[0].pk).update(email='AB1000@SRMIST.EDU.IN')
        ExamAllowed.objects.create(exam=self.exam, email='ab1000@srmist.edu.in')
        self.login(self.students[0])
        self.assertRedirects(self.entry(), reverse('exam_consent', args=[self.exam.token]))

    def test_consent_route_cannot_skip_the_class_list(self):
        ExamAllowed.objects.create(exam=self.exam, email='ab1000@srmist.edu.in')
        r = self.enter(self.students[1])
        self.assertContains(r, 'not on the class list')
        self.assertEqual(ExamAttempt.objects.count(), 0)


class ConsentAndSeatTests(ExamEntryBase):
    def test_no_seat_without_ticking_the_box(self):
        self.login(self.students[0])
        r = self.client.post(reverse('exam_consent', args=[self.exam.token]), {})
        self.assertContains(r, 'Tick the box')
        self.assertEqual(ExamAttempt.objects.count(), 0)

    def test_consent_claims_a_seat_and_shows_the_lobby(self):
        r = self.enter(self.students[0])
        self.assertTemplateUsed(r, 'quiz/exam/lobby.html')
        attempt = ExamAttempt.objects.get()
        self.assertEqual(attempt.user, self.students[0])
        self.assertIsNotNone(attempt.consented_at)

    def test_seat_limit_is_enforced_and_logged(self):
        self.enter(self.students[0])
        self.enter(self.students[1])
        r = self.enter(self.students[2])
        self.assertContains(r, 'No seats left')
        self.assertEqual(ExamAttempt.objects.count(), 2)
        self.assertEqual(ExamDenied.objects.get().reason, 'full')

    def test_student_with_a_seat_can_return_when_full(self):
        self.enter(self.students[0])
        self.enter(self.students[1])
        self.login(self.students[0])
        self.assertRedirects(self.entry(), reverse('exam_lobby', args=[self.exam.token]))

    def test_raising_the_limit_lets_the_next_student_in(self):
        self.enter(self.students[0]); self.enter(self.students[1])
        Exam.objects.filter(pk=self.exam.pk).update(seat_limit=3)
        self.assertTemplateUsed(self.enter(self.students[2]), 'quiz/exam/lobby.html')

    def test_claim_seat_is_idempotent_and_respects_the_limit(self):
        first, problem = claim_seat(self.exam, self.students[0])
        again, _ = claim_seat(self.exam, self.students[0])
        self.assertEqual((first.pk, problem), (again.pk, None))  # double click = same seat
        claim_seat(self.exam, self.students[1])
        self.assertEqual(claim_seat(self.exam, self.students[2]), (None, 'full'))
        self.assertEqual(ExamAttempt.objects.count(), 2)


class LobbyTests(ExamEntryBase):
    def test_lobby_requires_a_seat(self):
        self.login(self.students[0])
        self.assertRedirects(self.client.get(reverse('exam_lobby', args=[self.exam.token])),
                             reverse('exam_entry', args=[self.exam.token]), fetch_redirect_response=False)

    def test_status_endpoint_needs_a_seat_and_reports_status(self):
        url = reverse('exam_status', args=[self.exam.token])
        self.login(self.students[0])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.enter(self.students[0])
        self.assertEqual(self.client.get(url).json(), {'status': 'lobby'})
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.RUNNING)
        self.assertEqual(self.client.get(url).json(), {'status': 'running'})

    def test_status_poll_is_cheap(self):
        self.enter(self.students[0])
        with self.assertNumQueries(4):  # session, user, exam, attempt
            self.client.get(reverse('exam_status', args=[self.exam.token]))


class TeacherSideTests(ExamEntryBase):
    def setUp(self):
        super().setUp()
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.DRAFT)
        self.url = reverse('exam_detail', args=[self.exam.pk])

    def test_open_button_moves_draft_to_lobby(self):
        self.login(self.teacher)
        self.client.post(self.url, {'action': 'open'})
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, Exam.LOBBY)

    def test_open_mode_goes_straight_to_running(self):
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.OPEN)
        self.login(self.teacher)
        self.client.post(self.url, {'action': 'open'})
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, Exam.RUNNING)

    def test_other_teacher_cannot_open_it(self):
        other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        other.groups.add(Group.objects.get(name='Teachers'))
        self.login(other)
        self.assertEqual(self.client.post(self.url, {'action': 'open'}).status_code, 404)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, Exam.DRAFT)

    def test_turned_away_student_disappears_from_list_once_they_get_a_seat(self):
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.LOBBY, seat_limit=1)
        self.enter(self.students[0])
        self.enter(self.students[1])  # full -> logged
        self.login(self.teacher)
        self.assertEqual(len(self.client.get(self.url).context['denied']), 1)
        Exam.objects.filter(pk=self.exam.pk).update(seat_limit=2)  # teacher raises the limit
        self.enter(self.students[1])                               # now they get in
        self.login(self.teacher)
        self.assertEqual(len(self.client.get(self.url).context['denied']), 0)

    def test_detail_shows_seats_used_and_who_was_turned_away(self):
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.LOBBY, seat_limit=1)
        self.enter(self.students[0])
        self.enter(self.students[1])  # full
        self.login(self.teacher)
        r = self.client.get(self.url)
        self.assertEqual(r.context['seats_used'], 1)
        self.assertContains(r, 'ab1001')
        self.assertContains(r, '1 of 1 taken')


class ClassListSeatsTests(ExamEntryBase):
    """Class list = automatic seats. No list = plain counter."""

    def test_listed_students_always_get_a_seat_whatever_the_stored_limit(self):
        for s in self.students:  # 3 listed, stored limit 1
            ExamAllowed.objects.create(exam=self.exam, email=s.email)
        Exam.objects.filter(pk=self.exam.pk).update(seat_limit=1)
        for s in self.students:
            self.assertTemplateUsed(self.enter(s), 'quiz/exam/lobby.html')
        self.assertEqual(ExamAttempt.objects.count(), 3)
        self.assertEqual(ExamDenied.objects.count(), 0)

    def test_unlisted_student_is_still_refused_with_a_list(self):
        ExamAllowed.objects.create(exam=self.exam, email=self.students[0].email)
        self.assertContains(self.enter(self.students[1]), 'not on the class list')

    def test_no_list_uses_the_counter(self):
        self.enter(self.students[0]); self.enter(self.students[1])
        self.assertContains(self.enter(self.students[2]), 'No seats left')

    def test_claim_seat_ignores_limit_when_there_is_a_list(self):
        for s in self.students:
            ExamAllowed.objects.create(exam=self.exam, email=s.email)
        Exam.objects.filter(pk=self.exam.pk).update(seat_limit=1)
        results = [claim_seat(self.exam, s)[1] for s in self.students]
        self.assertEqual(results, [None, None, None])


class ReconnectTests(ExamEntryBase):
    def test_first_join_is_not_a_reconnect(self):
        self.enter(self.students[0])
        self.assertEqual(ExamAttempt.objects.get().rejoins, 0)

    def test_coming_back_through_the_link_is_let_in_and_flagged(self):
        self.enter(self.students[0])
        self.login(self.students[0])  # e.g. wifi dropped, logged in again
        r = self.entry()
        self.assertRedirects(r, reverse('exam_lobby', args=[self.exam.token]))
        self.entry()
        attempt = ExamAttempt.objects.get()
        self.assertEqual(attempt.rejoins, 2)
        self.assertIsNotNone(attempt.last_rejoin_at)

    def test_reconnect_works_even_when_the_exam_is_full_or_running(self):
        self.enter(self.students[0]); self.enter(self.students[1])
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.RUNNING)
        self.login(self.students[0])
        self.assertRedirects(self.entry(), reverse('exam_lobby', args=[self.exam.token]))

    def test_refreshing_the_lobby_is_not_counted(self):
        self.enter(self.students[0])
        for _ in range(3):
            self.client.get(reverse('exam_lobby', args=[self.exam.token]))
        self.assertEqual(ExamAttempt.objects.get().rejoins, 0)


class LiveTeacherViewTests(ExamEntryBase):
    def setUp(self):
        super().setUp()
        self.live = reverse('exam_live', args=[self.exam.pk])

    def test_live_fragment_shows_reconnects_and_turned_away(self):
        self.enter(self.students[0]); self.enter(self.students[1])
        self.enter(self.students[2])  # full (no list, limit 2)
        self.login(self.students[0]); self.entry()  # reconnect
        self.login(self.teacher)
        r = self.client.get(self.live)
        self.assertContains(r, 'Reconnected (1)')
        self.assertContains(r, self.students[0].username)
        self.assertContains(r, 'Turned away (1)')
        self.assertContains(r, self.students[2].username)

    def test_live_fragment_updates_without_reloading_the_page(self):
        self.login(self.teacher)
        self.assertNotContains(self.client.get(self.live), 'Turned away')
        self.enter(self.students[0]); self.enter(self.students[1]); self.enter(self.students[2])
        self.login(self.teacher)
        self.assertContains(self.client.get(self.live), 'Turned away (1)')

    def test_live_is_owner_only(self):
        other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        other.groups.add(Group.objects.get(name='Teachers'))
        self.login(other)
        self.assertEqual(self.client.get(self.live).status_code, 404)
        self.login(self.students[0])
        self.assertRedirects(self.client.get(self.live), reverse('home'))

    def test_detail_page_embeds_the_live_box_and_poller(self):
        self.login(self.teacher)
        r = self.client.get(reverse('exam_detail', args=[self.exam.pk]))
        self.assertContains(r, 'id="live"')
        self.assertContains(r, self.live)


class SeatSettingTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)
        self.teacher.groups.add(Group.objects.get(name='Teachers'))
        self.client.login(username='shantini', password=PASSWORD)
        self.q = Question.objects.create(text='q', owner=self.teacher)

    def _create(self, **over):
        data = {'title': 'T', 'mode': 'open', 'questions': [self.q.id], 'allowed_text': ''}
        data.update(over)
        return self.client.post(reverse('exam_new'), data)

    def test_class_list_needs_no_seat_limit_and_sets_it_to_the_list_size(self):
        self._create(allowed_text='AD3919 AB1234 CD5678')
        self.assertEqual(Exam.objects.get().seat_limit, 3)

    def test_without_a_list_a_seat_limit_is_still_required(self):
        self._create()
        self.assertEqual(Exam.objects.count(), 0)
        self._create(seat_limit=40)
        self.assertEqual(Exam.objects.get().seat_limit, 40)

    def test_adding_students_grows_seats_and_raising_is_refused_with_a_list(self):
        self._create(allowed_text='AD3919')
        exam = Exam.objects.get()
        url = reverse('exam_detail', args=[exam.pk])
        self.client.post(url, {'action': 'allow', 'students': 'AB1234 CD5678'})
        exam.refresh_from_db()
        self.assertEqual(exam.seat_limit, 3)
        self.client.post(url, {'action': 'seats', 'seat_limit': 99})
        exam.refresh_from_db()
        self.assertEqual(exam.seat_limit, 3)


class RosterTests(ExamEntryBase):
    def setUp(self):
        super().setUp()
        self.live = reverse('exam_live', args=[self.exam.pk])

    def _roster(self):
        self.login(self.teacher)
        return self.client.get(self.live).context['roster']

    def test_class_list_shows_ticks_for_joined_students_only(self):
        for s in self.students:
            ExamAllowed.objects.create(exam=self.exam, email=s.email)
        self.enter(self.students[1])
        self.assertEqual(self._roster(), [('ab1000', False), ('ab1001', True), ('ab1002', False)])

    def test_tick_appears_live_after_joining(self):
        ExamAllowed.objects.create(exam=self.exam, email=self.students[0].email)
        self.assertEqual(self._roster(), [('ab1000', False)])
        self.enter(self.students[0])
        r = self.client.get(self.live) if self.login(self.teacher) is None else None
        self.assertContains(r, '&#10003; ab1000')

    def test_without_a_list_the_roster_is_the_joined_students_in_order(self):
        self.enter(self.students[1]); self.enter(self.students[0])
        self.assertEqual(self._roster(), [('ab1001', True), ('ab1000', True)])

    def test_roster_match_ignores_email_case(self):
        ExamAllowed.objects.create(exam=self.exam, email='ab1000@srmist.edu.in')
        self.enter(self.students[0])
        User.objects.filter(pk=self.students[0].pk).update(email='AB1000@SRMIST.EDU.IN')
        self.assertEqual(self._roster(), [('ab1000', True)])
