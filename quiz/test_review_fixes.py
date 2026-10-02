from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from quiz.exam_control import extend_all, grant_extra, reset_device, unfreeze
from quiz.exam_device import check_device
from quiz.exam_results import result_rows, result_table
from quiz.exam_run import scores_visible
from quiz.exams import parse_questions
from quiz.models import Exam, ExamAnswer, ExamAttempt, ExamEvent
from quiz.test_exam_device import DESKTOP, FIREFOX, DeviceBase, PASSWORD
from quiz.util import to_int


def fake_request(device_id, user_agent=FIREFOX, ip='10.1.1.5'):
    request = RequestFactory().get('/exam/x/', HTTP_USER_AGENT=user_agent, REMOTE_ADDR=ip)
    request.device_id = device_id
    return request


class ToIntTests(DeviceBase):
    def test_accepts_plain_numbers_only(self):
        self.assertEqual([to_int(v) for v in ('5', ' 12 ', '0', 7)], [5, 12, 0, 7])
        for bad in ('', 'x', '-1', '1.5', '²', '٣', '9' * 30, '1e3', None):
            self.assertIsNone(to_int(bad), repr(bad))
        self.assertIsNone(to_int('50', max_value=10))

    def test_odd_input_never_crashes_the_student_endpoints(self):
        qid = self.exam.questions.first().pk
        self.login(self.s)
        for question, choice in (('²', '1'), (str(qid), '²'), ('9' * 30, '1'), (str(qid), '9' * 30), ('-3', '')):
            r = self.client.post(self.url('exam_answer'), {'question': question, 'choice': choice},
                                 HTTP_USER_AGENT=DESKTOP)
            self.assertEqual(r.status_code, 400, (question, choice))

    def test_odd_input_never_crashes_the_teacher_endpoints(self):
        for data in ({'action': 'seats', 'seat_limit': '²'}, {'action': 'seats', 'seat_limit': '9' * 30},
                     {'action': 'extra_time', 'attempt': '²', 'minutes': '5'},
                     {'action': 'extra_time', 'attempt': self.attempt0().pk, 'minutes': '²'},
                     {'action': 'unfreeze', 'attempt': self.attempt0().pk, 'minutes': '9' * 30},
                     {'action': 'extend_all', 'minutes': '²'}, {'action': 'reset_device', 'attempt': '²'}):
            self.assertEqual(self.post_detail(**data).status_code, 302, data)  # redirected back with a message, not a 500
        self.assertEqual(Exam.objects.get(pk=self.exam.pk).seat_limit, 10)

    def test_csv_points_with_odd_digits_are_a_row_error(self):
        for points in ('²', '99999999999', '0', '-2', '1.5'):
            csv = f'question,option_a,option_b,correct,points\nq,a,b,A,{points}\n'.encode()
            rows, errors = parse_questions(csv, 'q.csv')
            self.assertEqual(rows, [], points)
            self.assertIn('points must be a whole number', errors[0], points)


class CloseOutTests(DeviceBase):
    """The review's findings about time running out, extra time and the score reveal."""

    def test_grant_extra_cannot_revive_an_attempt_whose_time_is_up(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=timezone.now() - timedelta(minutes=2))
        self.post_detail(action='extra_time', attempt=self.attempt0().pk, minutes=5)
        a = self.attempt0()
        self.assertIsNotNone(a.submitted_at)               # it was scored, not extended
        self.assertEqual(a.extra_seconds, 0)
        self.assertFalse(ExamEvent.objects.filter(kind='extra_time').exists())
        self.login(self.s)
        qid = self.exam.questions.first().pk
        self.assertEqual(self.answer(qid, self.choice(qid, True)).status_code, 409)

    def test_grant_extra_returns_an_explanation(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=timezone.now() - timedelta(minutes=2))
        self.assertIn('already up', grant_extra(self.attempt0(), 5, self.teacher))

    def test_scores_stay_hidden_while_an_extra_time_student_is_still_working(self):
        early, late = self.students[1], self.students[0]  # self.s == students[0] is still taking the exam
        self.take(early, HTTP_USER_AGENT=DESKTOP)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)  # the early finisher submits
        now = timezone.now()
        Exam.objects.filter(pk=self.exam.pk).update(ends_at=now - timedelta(minutes=2))  # the clock has run out...
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=now + timedelta(minutes=8))  # ...but ab1000 has extra time
        self.exam.refresh_from_db()
        self.assertFalse(scores_visible(self.exam))
        self.login(early)
        r = self.client.get(self.url('exam_done'))
        self.assertNotContains(r, 'Your score:')
        self.assertNotIn('selections', r.context)
        card = self.client.get(reverse('home')).context['my_exams'][0]
        self.assertIsNone(card['score'])
        self.assertTrue(card['waiting_for_scores'])

    def test_scores_appear_once_the_extra_time_student_has_finished(self):
        early = self.students[1]
        self.take(early, HTTP_USER_AGENT=DESKTOP)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)
        now = timezone.now()
        Exam.objects.filter(pk=self.exam.pk).update(ends_at=now - timedelta(minutes=2))
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=now + timedelta(minutes=8))
        self.login(self.s)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)  # the extra-time student submits
        self.exam.refresh_from_db()
        self.assertTrue(scores_visible(self.exam))
        self.login(early)
        self.assertContains(self.client.get(self.url('exam_done')), 'Your score:')

    def test_a_frozen_seat_also_holds_back_the_reveal(self):
        self.take(self.students[1], HTTP_USER_AGENT=DESKTOP)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)
        self.freeze()
        Exam.objects.filter(pk=self.exam.pk).update(ends_at=timezone.now() - timedelta(minutes=2))
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=timezone.now() - timedelta(minutes=2))
        self.exam.refresh_from_db()
        self.assertFalse(scores_visible(self.exam))  # the teacher has not looked at the frozen seat yet

    def test_the_client_can_wait_out_the_grace_window_by_pinging(self):
        """The exam page no longer submits itself at 0:00: it pings until the server says closed."""
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.a_ping()['state'], 'ok')             # still inside the 5s grace window
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=timezone.now() - timedelta(seconds=7))
        self.assertEqual(self.a_ping()['state'], 'closed')         # past it: the server closes and scores
        self.assertIsNotNone(self.attempt0().submitted_at)

    def test_extra_time_arriving_just_before_zero_is_picked_up_by_the_ping(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=timezone.now() + timedelta(seconds=2))
        self.post_detail(action='extra_time', attempt=self.attempt0().pk, minutes=10)
        ping = self.a_ping()
        self.assertEqual(ping['state'], 'ok')
        self.assertGreater(ping['deadline_ms'] - ping['now_ms'], 9 * 60 * 1000)
        self.assertIsNone(self.attempt0().submitted_at)

    def test_page_script_asks_the_server_instead_of_submitting_at_zero(self):
        self.login(self.s)
        html = self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP).content.decode()
        self.assertIn('async function timeUp', html)
        self.assertNotIn('submit(true)', html)
        self.assertIn('while (unsaved()', html)  # submit waits for pending answers first


class AnswerVersusSubmitTests(DeviceBase):
    def test_an_answer_that_loses_the_race_with_submit_is_refused(self):
        qid = self.exam.questions.first().pk
        self.login(self.s)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)
        with mock.patch('quiz.exam_take.is_closed', return_value=False):  # the pre-check passed just before the submit landed
            r = self.answer(qid, self.choice(qid, True), HTTP_USER_AGENT=DESKTOP)
        self.assertEqual((r.status_code, r.json()['reason']), (409, 'closed'))
        self.assertFalse(ExamAnswer.objects.exists())

    def answer(self, qid, choice_id, **extra):
        return self.client.post(self.url('exam_answer'), {'question': qid, 'choice': choice_id}, **extra)


class SubmittedSeatTests(DeviceBase):
    def test_a_stale_unfreeze_row_cannot_touch_a_submitted_attempt(self):
        self.freeze()
        self.teacher_post('end')  # submits everyone, including the frozen seat
        before = self.attempt0().extra_seconds
        self.assertFalse(unfreeze(self.attempt0(), 'original', 10, self.teacher))
        self.assertEqual(self.attempt0().extra_seconds, before)
        self.assertFalse(ExamEvent.objects.filter(kind='unfreeze').exists())

    def test_a_second_browser_posting_submit_on_a_finished_exam_raises_no_alarm(self):
        self.login(self.s)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)
        self.b.post(self.url('exam_submit'), HTTP_USER_AGENT=FIREFOX)
        a = self.attempt0()
        self.assertEqual(a.intrusions, 0)
        self.assertFalse(ExamEvent.objects.filter(kind='intruder').exists())


class StaleCopyTests(DeviceBase):
    """Decisions are made on a freshly locked copy, so a request that loaded the seat earlier cannot undo the teacher."""

    def test_two_requests_with_stale_copies_freeze_the_seat_once(self):
        self.go_silent()
        first, second = self.attempt0(), self.attempt0()  # both loaded before anyone froze it
        check_device(fake_request('B' * 22), first)
        check_device(fake_request('B' * 22), second)
        a = self.attempt0()
        self.assertEqual((a.freezes, ExamEvent.objects.filter(kind='freeze').count()), (1, 1))

    def test_a_browser_the_teacher_just_turned_away_cannot_slip_a_new_freeze_through(self):
        self.freeze()
        stale = self.attempt0()                      # loaded while still frozen... then the teacher decides:
        challenger = stale.challenger_id
        unfreeze(self.attempt0(), 'original', 0, self.teacher)
        stale.frozen_at = None                       # what an in-flight request would still believe
        stale.blocked_devices = []
        self.go_silent()                             # even with the original quiet
        self.assertEqual(check_device(fake_request(challenger), stale), 'blocked')
        a = self.attempt0()
        self.assertEqual((a.freezes, a.frozen_at), (1, None))

    def test_a_stale_view_of_a_just_switched_seat_still_lets_the_new_browser_in(self):
        self.freeze()
        stale = self.attempt0()
        challenger = stale.challenger_id
        unfreeze(self.attempt0(), 'new', 0, self.teacher)
        stale.device_id = 'old' * 7
        self.assertEqual(check_device(fake_request(challenger), stale), 'ok')

    def test_extending_everyone_twice_from_stale_copies_adds_both(self):
        stale_a, stale_b = Exam.objects.get(pk=self.exam.pk), Exam.objects.get(pk=self.exam.pk)
        original = stale_a.ends_at
        self.assertIsNone(extend_all(stale_a, 10, self.teacher))
        self.assertIsNone(extend_all(stale_b, 10, self.teacher))
        exam = Exam.objects.get(pk=self.exam.pk)
        self.assertEqual(exam.ends_at - original, timedelta(minutes=20))
        self.assertEqual(self.attempt0().ends_at, exam.ends_at)
        self.assertEqual(stale_b.ends_at, exam.ends_at)  # the caller's copy is refreshed too


class ResetDeviceTests(DeviceBase):
    def test_reset_lets_the_next_browser_in_and_logs_it(self):
        self.freeze()
        unfreeze(self.attempt0(), 'original', 0, self.teacher)  # the phone is turned away for good...
        self.assertEqual(self.b_ping()['state'], 'blocked')
        self.assertIsNone(reset_device(self.attempt0(), self.teacher))  # ...but then the laptop turns out to be dead
        a = self.attempt0()
        self.assertEqual((a.device_id, a.blocked_devices, a.frozen_at), ('', [], None))
        self.assertEqual(self.b_ping()['state'], 'ok')           # the next browser to arrive is accepted
        self.assertEqual(self.attempt0().device_label, 'Firefox on Linux')
        self.assertTrue(ExamEvent.objects.filter(kind='reset_device').exists())

    def test_reset_through_the_teachers_page(self):
        self.post_detail(action='reset_device', attempt=self.attempt0().pk)
        self.assertEqual(self.attempt0().device_id, '')

    def test_reset_is_refused_for_submitted_students_and_other_teachers(self):
        self.login(self.s)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)
        self.assertIn('already been submitted', reset_device(self.attempt0(), self.teacher))
        other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        other.groups.add(Group.objects.get(name='Teachers'))
        self.assertEqual(self.post_detail(other, action='reset_device', attempt=self.attempt0().pk).status_code, 404)


class PanelAndPagesTests(DeviceBase):
    def test_controls_panel_has_confirmations_and_the_reset_form(self):
        self.freeze()
        self.login(self.teacher)
        html = self.client.get(reverse('exam_controls', args=[self.exam.pk])).content.decode()
        self.assertIn("Unfreeze ab1000? The device you did NOT choose will be turned away.", html)
        self.assertIn('Reset device lock', html)
        self.assertIn('data-key="unfreeze-', html)

    def test_exam_page_keeps_dropdown_choices_when_the_panel_refreshes(self):
        self.login(self.teacher)
        html = self.client.get(reverse('exam_detail', args=[self.exam.pk])).content.decode()
        self.assertIn("chosen[s.form.dataset.key + '/' + s.name]", html)

    def test_blocked_page_mentions_cookies(self):
        r = self.b.get(self.url('exam_take'), HTTP_USER_AGENT=FIREFOX)
        self.assertContains(r, 'cookies are allowed')

    def test_students_never_see_teacher_controls_on_the_real_exam_page(self):
        self.login(self.s)
        r = self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP)
        self.assertTemplateUsed(r, 'quiz/exam/take.html')  # the exam page itself, not the frozen page
        for word in ('Activity log', 'Unfreeze', 'Reset device lock', 'Give extra time', 'Extend everyone'):
            self.assertNotContains(r, word)

    def test_frozen_students_show_in_the_results_export(self):
        self.freeze()
        rows = result_rows(self.exam)
        table = result_table(rows)
        self.assertIn('Frozen: needs teacher', [r[2] for r in table[1:]])
