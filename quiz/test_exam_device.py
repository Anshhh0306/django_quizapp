from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from quiz.exam_device import COOKIE, describe_device
from quiz.exam_results import result_rows, result_summary
from quiz.models import Exam, ExamAttempt, ExamEvent, Question
from quiz.test_exam_take import DESKTOP, PASSWORD, TakeBase

FIREFOX = 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0'


class DeviceBase(TakeBase):
    """Student ab1000 starts the exam on 'browser A' (self.client, Chrome on Windows). 'Browser B' is a second Client."""

    def setUp(self):
        super().setUp()
        self.run_now()
        self.s = self.students[0]
        self.take(self.s, HTTP_USER_AGENT=DESKTOP)  # binds browser A
        self.b = Client()
        self.b.login(username=self.s.username, password=PASSWORD)

    def attempt0(self):
        return ExamAttempt.objects.get(exam=self.exam, user=self.s)

    def a_ping(self):
        self.login(self.s)
        return self.client.get(self.url('exam_ping'), HTTP_USER_AGENT=DESKTOP).json()

    def b_ping(self):
        return self.b.get(self.url('exam_ping'), HTTP_USER_AGENT=FIREFOX, REMOTE_ADDR='10.1.1.5').json()

    def b_take(self):
        return self.b.get(self.url('exam_take'), HTTP_USER_AGENT=FIREFOX, REMOTE_ADDR='10.1.1.5')

    def go_silent(self):
        """The student's own browser stops checking in (dead laptop, dropped connection)."""
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(device_seen_at=timezone.now() - timedelta(seconds=60))

    def freeze(self):
        self.go_silent()  # a second device only freezes the seat when the first one has gone quiet
        self.b_take()

    def post_detail(self, user=None, **data):
        self.login(user or self.teacher)
        return self.client.post(reverse('exam_detail', args=[self.exam.pk]), data)

    def unfreeze(self, device='original', minutes=0):
        return self.post_detail(action='unfreeze', attempt=self.attempt0().pk, device=device, minutes=minutes)


class BindingTests(DeviceBase):
    def test_describe_device(self):
        self.assertEqual(describe_device(DESKTOP), 'Chrome on Windows')
        self.assertEqual(describe_device(FIREFOX), 'Firefox on Linux')
        self.assertEqual(describe_device('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1'), 'Safari on iPhone/iPad')
        self.assertEqual(describe_device('Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile'), 'Chrome on Android')
        self.assertEqual(describe_device(''), 'Unknown browser on unknown system')

    def test_starting_the_exam_locks_it_to_this_browser(self):
        a = self.attempt0()
        self.assertEqual(a.device_id, self.client.cookies[COOKIE].value)
        self.assertEqual(a.device_label, 'Chrome on Windows')
        self.assertIsNone(a.frozen_at)

    def test_cookie_is_httponly_and_lasts_a_year(self):
        fresh = Client()
        fresh.login(username=self.s.username, password=PASSWORD)
        fresh.get(self.url('exam_status'))
        morsel = fresh.cookies[COOKIE]
        self.assertTrue(morsel['httponly'])
        self.assertEqual(int(morsel['max-age']), 365 * 24 * 3600)

    def test_a_forged_cookie_is_replaced(self):
        fresh = Client()
        fresh.cookies[COOKIE] = 'x'  # too short to be one of ours
        fresh.login(username=self.s.username, password=PASSWORD)
        fresh.get(self.url('exam_status'))
        self.assertGreaterEqual(len(fresh.cookies[COOKIE].value), 16)

    def test_same_browser_never_freezes(self):
        for _ in range(3):
            self.assertEqual(self.a_ping()['state'], 'ok')
            self.login(self.s)
            self.assertEqual(self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP).status_code, 200)
        self.assertIsNone(self.attempt0().frozen_at)

    def test_only_exam_pages_get_the_cookie(self):
        self.assertNotIn(COOKIE, Client().get('/accounts/login/').cookies)

    def test_in_the_lobby_the_newest_browser_wins_without_a_freeze(self):
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.LOBBY, starts_at=None, ends_at=None)
        late = self.students[2]  # joined the lobby but never started
        self.login(late)
        self.client.get(self.url('exam_lobby'))  # laptop
        phone = Client()
        phone.login(username=late.username, password=PASSWORD)
        phone.get(self.url('exam_lobby'))        # then the phone
        a = ExamAttempt.objects.get(exam=self.exam, user=late)
        self.assertEqual(a.device_id, phone.cookies[COOKIE].value)
        self.assertIsNone(a.frozen_at)


class FreezeTests(DeviceBase):
    def test_a_second_browser_freezes_the_seat_and_sees_no_questions(self):
        self.go_silent()
        r = self.b_take()
        self.assertTemplateUsed(r, 'quiz/exam/frozen.html')
        self.assertContains(r, 'Your exam is paused')
        self.assertNotContains(r, 'Question ')
        a = self.attempt0()
        self.assertIsNotNone(a.frozen_at)
        self.assertEqual((a.freezes, a.challenger_label, a.challenger_ip), (1, 'Firefox on Linux', '10.1.1.5'))
        self.assertEqual(a.device_label, 'Chrome on Windows')

    def test_the_original_browser_is_paused_as_well(self):
        self.freeze()
        qid = self.exam.questions.first().pk
        self.login(self.s)
        r = self.answer(qid, self.choice(qid, True))
        self.assertEqual((r.status_code, r.json()['reason']), (423, 'frozen'))
        self.assertFalse(self.attempt0().answers.exists())
        self.assertEqual(self.a_ping()['state'], 'frozen')
        self.assertTemplateUsed(self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP), 'quiz/exam/frozen.html')

    def test_a_frozen_seat_cannot_be_submitted(self):
        self.freeze()
        self.login(self.s)
        r = self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)
        self.assertRedirects(r, self.url('exam_take'), fetch_redirect_response=False)
        self.assertIsNone(self.attempt0().submitted_at)

    def test_repeat_visits_do_not_refreeze_or_spam_the_log(self):
        self.go_silent()
        for _ in range(3):
            self.b_take()
        self.assertEqual(self.attempt0().freezes, 1)
        self.assertEqual(ExamEvent.objects.filter(kind='freeze').count(), 1)

    def test_freeze_is_logged_with_both_devices(self):
        self.freeze()
        detail = ExamEvent.objects.get(kind='freeze').detail
        self.assertIn('Firefox on Linux', detail)
        self.assertIn('Chrome on Windows', detail)

    def test_live_roster_shows_the_frozen_student(self):
        self.freeze()
        self.login(self.teacher)
        r = self.client.get(reverse('exam_live', args=[self.exam.pk]))
        self.assertEqual(dict(r.context['roster'])['ab1000'], 'frozen')
        self.assertContains(r, 'frozen')

    def test_frozen_seat_is_not_auto_submitted_at_the_deadline(self):
        self.freeze()
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=timezone.now() - timedelta(minutes=5))
        self.login(self.teacher)
        self.client.get(reverse('exam_live', args=[self.exam.pk]))
        self.assertIsNone(self.attempt0().submitted_at)
        rows = {r['name']: r for r in result_rows(self.exam)}
        self.assertEqual(rows['ab1000']['status'], 'Frozen: needs teacher')
        self.assertEqual(result_summary(list(rows.values()))['frozen'], 1)

    def test_ending_the_exam_still_closes_frozen_seats(self):
        self.freeze()
        self.teacher_post('end')
        self.assertIsNotNone(self.attempt0().submitted_at)


class UnfreezeTests(DeviceBase):
    def setUp(self):
        super().setUp()
        self.freeze()

    def test_keep_original_lets_it_continue_and_turns_the_other_away(self):
        self.unfreeze('original')
        self.assertEqual(self.a_ping()['state'], 'ok')
        self.assertIsNone(self.attempt0().frozen_at)
        self.assertEqual(self.b_ping()['state'], 'blocked')
        self.assertContains(self.b_take(), 'Open on another device')

    def test_a_turned_away_browser_does_not_freeze_again(self):
        self.unfreeze('original')
        for _ in range(3):
            self.b_take()
        a = self.attempt0()
        self.assertEqual((a.freezes, a.frozen_at), (1, None))
        self.assertEqual(self.b.post(self.url('exam_answer'), {'question': 1, 'choice': 1}).status_code, 403)

    def test_switch_to_new_hands_the_seat_over(self):
        self.unfreeze('new')
        self.assertEqual(self.b_ping()['state'], 'ok')
        self.assertEqual(self.a_ping()['state'], 'blocked')
        a = self.attempt0()
        self.assertEqual((a.device_label, a.device_ip), ('Firefox on Linux', '10.1.1.5'))
        self.assertEqual(self.b_take().status_code, 200)
        self.assertTemplateUsed(self.b_take(), 'quiz/exam/take.html')

    def test_extra_minutes_move_the_students_deadline(self):
        before = self.attempt0().ends_at
        self.unfreeze('original', minutes=10)
        a = self.attempt0()
        self.assertEqual(a.ends_at - before, timedelta(minutes=10))
        self.assertEqual(a.extra_seconds, 600)
        self.assertEqual(self.a_ping()['deadline_ms'], int(a.ends_at.timestamp() * 1000))  # their timer picks it up live

    def test_unfreeze_logs_who_did_it_and_what_they_chose(self):
        self.unfreeze('new', minutes=5)
        event = ExamEvent.objects.get(kind='unfreeze')
        self.assertEqual(event.actor, self.teacher)
        self.assertIn('switched to Firefox on Linux', event.detail)
        self.assertIn('+5 min', event.detail)

    def test_only_listed_minute_values_are_accepted(self):
        self.unfreeze(minutes=7)
        self.assertIsNotNone(self.attempt0().frozen_at)

    def test_unfreezing_someone_who_is_not_frozen_changes_nothing(self):
        self.unfreeze()
        self.unfreeze(minutes=15)  # second click
        self.assertEqual(self.attempt0().extra_seconds, 0)

    def test_nobody_else_can_unfreeze(self):
        other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        other.groups.add(Group.objects.get(name='Teachers'))
        self.assertEqual(self.post_detail(other, action='unfreeze', attempt=self.attempt0().pk, device='original', minutes=0).status_code, 404)
        self.post_detail(self.s, action='unfreeze', attempt=self.attempt0().pk, device='original', minutes=0)
        self.assertIsNotNone(self.attempt0().frozen_at)

    def test_a_released_seat_past_its_deadline_is_closed_on_the_next_touch(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=timezone.now() - timedelta(minutes=5))
        self.unfreeze('original', minutes=0)
        self.assertEqual(self.a_ping()['state'], 'closed')
        self.assertIsNotNone(self.attempt0().submitted_at)


class ExtraTimeTests(DeviceBase):
    def test_extra_time_for_one_student(self):
        before = self.attempt0().ends_at
        self.post_detail(action='extra_time', attempt=self.attempt0().pk, minutes=15)
        self.assertEqual(self.attempt0().ends_at - before, timedelta(minutes=15))
        self.assertIn('+15 min', ExamEvent.objects.get(kind='extra_time').detail)

    def test_extra_time_needs_a_real_amount_and_an_unfinished_attempt(self):
        before = self.attempt0().ends_at
        self.post_detail(action='extra_time', attempt=self.attempt0().pk, minutes=0)
        self.post_detail(action='extra_time', attempt=self.attempt0().pk, minutes=999)
        self.assertEqual(self.attempt0().ends_at, before)
        self.login(self.s)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)
        self.post_detail(action='extra_time', attempt=self.attempt0().pk, minutes=10)
        self.assertEqual(self.attempt0().ends_at, before)  # already submitted

    def test_extra_time_keeps_a_student_going_after_the_exam_ended_for_everyone(self):
        now = timezone.now()
        Exam.objects.filter(pk=self.exam.pk).update(ends_at=now - timedelta(minutes=2))  # natural end passed
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=now + timedelta(minutes=8))
        self.login(self.s)
        self.assertTemplateUsed(self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP), 'quiz/exam/take.html')
        qid = self.exam.questions.first().pk
        self.assertEqual(self.answer(qid, self.choice(qid, True)).status_code, 200)
        self.assertEqual(self.a_ping()['state'], 'ok')

    def test_without_extra_time_the_same_student_is_closed_out(self):
        now = timezone.now()
        Exam.objects.filter(pk=self.exam.pk).update(ends_at=now - timedelta(minutes=2))
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(ends_at=now - timedelta(minutes=2))
        self.login(self.s)
        r = self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP)
        self.assertRedirects(r, self.url('exam_done'), fetch_redirect_response=False)

    def test_extend_everyone(self):
        late = self.students[2]
        before_exam = Exam.objects.get(pk=self.exam.pk).ends_at
        self.post_detail(action='extend_all', minutes=10)
        self.assertEqual(Exam.objects.get(pk=self.exam.pk).ends_at - before_exam, timedelta(minutes=10))
        self.assertEqual(self.attempt0().extra_seconds, 600)
        self.assertEqual(self.attempt0().ends_at, Exam.objects.get(pk=self.exam.pk).ends_at)
        self.take(late, HTTP_USER_AGENT=DESKTOP)  # starts afterwards: gets the new end time too
        self.assertEqual(ExamAttempt.objects.get(user=late).ends_at, Exam.objects.get(pk=self.exam.pk).ends_at)
        self.assertEqual(ExamEvent.objects.get(kind='extend_all').detail, 'Everyone: +10 min')

    def test_extend_everyone_skips_finished_students(self):
        self.login(self.s)
        self.client.post(self.url('exam_submit'), HTTP_USER_AGENT=DESKTOP)
        done_at = self.attempt0().ends_at
        self.post_detail(action='extend_all', minutes=10)
        self.assertEqual(self.attempt0().ends_at, done_at)

    def test_extend_everyone_only_while_a_scheduled_exam_is_running(self):
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.LOBBY, starts_at=None, ends_at=None)
        self.post_detail(action='extend_all', minutes=10)
        self.assertFalse(ExamEvent.objects.filter(kind='extend_all').exists())
        self.run_now()
        self.post_detail(action='extend_all', minutes=7)  # not an allowed amount
        self.assertFalse(ExamEvent.objects.filter(kind='extend_all').exists())


class ControlsPanelTests(DeviceBase):
    def panel(self, user=None):
        self.login(user or self.teacher)
        return self.client.get(reverse('exam_controls', args=[self.exam.pk]))

    def test_panel_lists_both_devices_for_a_frozen_student(self):
        self.freeze()
        r = self.panel()
        self.assertContains(r, 'Frozen: needs you (1)')
        self.assertContains(r, 'Original: Chrome on Windows')
        self.assertContains(r, 'New: Firefox on Linux (10.1.1.5)')
        self.assertContains(r, 'Unfreeze')

    def test_signature_changes_when_someone_freezes_so_the_page_refreshes(self):
        before = self.panel().context['sig']
        self.freeze()
        self.assertNotEqual(self.panel().context['sig'], before)

    def test_panel_has_the_extra_time_box_for_students_taking_the_exam(self):
        r = self.panel()
        self.assertContains(r, 'Give extra time')
        self.assertContains(r, 'Extend everyone')
        self.assertEqual([a.user.username for a in r.context['taking']], ['ab1000'])

    def test_panel_is_owner_only(self):
        other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        other.groups.add(Group.objects.get(name='Teachers'))
        self.assertEqual(self.panel(other).status_code, 404)
        self.assertRedirects(self.panel(self.s), reverse('home'))

    def test_exam_page_embeds_the_panel_and_refreshes_it(self):
        self.login(self.teacher)
        r = self.client.get(reverse('exam_detail', args=[self.exam.pk]))
        self.assertContains(r, 'id="controls"')
        self.assertContains(r, reverse('exam_controls', args=[self.exam.pk]))

    def test_activity_log_appears_on_the_live_box(self):
        self.freeze()
        self.unfreeze('original', minutes=5)
        self.login(self.teacher)
        r = self.client.get(reverse('exam_live', args=[self.exam.pk]))
        self.assertContains(r, 'Activity log')
        self.assertContains(r, 'kept Chrome on Windows')
        self.assertContains(r, '(by shantini)')

    def test_students_never_see_the_audit_log_or_the_controls(self):
        self.freeze()
        self.login(self.s)
        page = self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP).content.decode()
        for word in ('Activity log', 'extra time', 'Unfreeze'):
            self.assertNotIn(word, page)


class ActiveOriginalTests(DeviceBase):
    """While the student's own browser is working, a second browser is turned away and the student is left alone."""

    def intrude(self, client=None, ua=FIREFOX, ip='10.1.1.5'):
        return (client or self.b).get(self.url('exam_take'), HTTP_USER_AGENT=ua, REMOTE_ADDR=ip)

    def test_second_browser_is_turned_away_not_frozen(self):
        r = self.intrude()
        self.assertContains(r, 'Open on another device')
        self.assertNotContains(r, 'Question ')  # none of the exam's questions reach the other browser
        a = self.attempt0()
        self.assertIsNone(a.frozen_at)
        self.assertEqual((a.freezes, a.intrusions, a.last_intruder_label, a.last_intruder_ip),
                         (0, 1, 'Firefox on Linux', '10.1.1.5'))

    def test_the_student_is_not_interrupted_at_all(self):
        self.intrude()
        self.assertEqual(self.a_ping()['state'], 'ok')
        qid = self.exam.questions.first().pk
        self.login(self.s)
        self.assertEqual(self.answer(qid, self.choice(qid, True)).status_code, 200)
        self.assertEqual(self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP).status_code, 200)

    def test_the_other_browser_cannot_answer_or_submit(self):
        self.intrude()
        qid = self.exam.questions.first().pk
        r = self.b.post(self.url('exam_answer'), {'question': qid, 'choice': self.choice(qid, True)})
        self.assertEqual((r.status_code, r.json()['reason']), (403, 'blocked'))
        self.b.post(self.url('exam_submit'))
        a = self.attempt0()
        self.assertIsNone(a.submitted_at)
        self.assertFalse(a.answers.exists())

    def test_repeats_count_but_log_once_per_browser(self):
        for _ in range(4):
            self.intrude()
        self.assertEqual(self.attempt0().intrusions, 4)
        self.assertEqual(ExamEvent.objects.filter(kind='intruder').count(), 1)

    def test_a_second_intruder_within_a_minute_updates_the_seat_but_not_the_log(self):
        self.intrude()
        c = Client()
        c.login(username=self.s.username, password=PASSWORD)
        self.intrude(c, ua='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605', ip='10.9.9.9')
        a = self.attempt0()
        self.assertEqual(ExamEvent.objects.filter(kind='intruder').count(), 1)  # one line a minute, so the log cannot be flooded
        self.assertEqual((a.intrusions, a.last_intruder_label, a.last_intruder_ip), (2, 'Safari on Mac', '10.9.9.9'))

    def test_intruders_are_listed_for_the_teacher_not_in_the_frozen_panel(self):
        self.intrude()
        self.intrude()
        self.login(self.teacher)
        live = self.client.get(reverse('exam_live', args=[self.exam.pk]))
        self.assertContains(live, 'Other-device attempts (1)')
        self.assertContains(live, 'ab1000: 2 attempts, last from Firefox on Linux (10.1.1.5)')
        self.assertContains(live, 'the student was not interrupted')
        panel = self.client.get(reverse('exam_controls', args=[self.exam.pk]))
        self.assertNotContains(panel, 'Frozen: needs you')

    def test_audit_log_explains_what_happened(self):
        self.intrude()
        detail = ExamEvent.objects.get(kind='intruder').detail
        self.assertIn('Firefox on Linux', detail)
        self.assertIn('Chrome on Windows', detail)
        self.assertIn('student was not interrupted', detail)

    def test_check_ins_keep_the_original_active(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(device_seen_at=timezone.now() - timedelta(seconds=20))
        self.a_ping()  # a check-in from the locked browser
        self.assertLess(timezone.now() - self.attempt0().device_seen_at, timedelta(seconds=3))

    def test_frequent_check_ins_do_not_hammer_the_database(self):
        stamp = timezone.now() - timedelta(seconds=2)
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(device_seen_at=stamp)
        self.a_ping()
        self.assertEqual(self.attempt0().device_seen_at, stamp)  # checked in 2s ago: no new write

    def test_once_the_original_goes_quiet_the_same_browser_freezes_the_seat_instead(self):
        self.intrude()                      # turned away while the student was working
        self.go_silent()                    # then the student's laptop dies
        r = self.intrude()
        self.assertContains(r, 'Your exam is paused')
        a = self.attempt0()
        self.assertIsNotNone(a.frozen_at)   # the teacher must decide: the student may have switched device legitimately
        self.assertEqual(a.freezes, 1)

    def test_never_seen_original_counts_as_quiet(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(device_seen_at=None)  # seats from before this rule
        self.assertContains(self.intrude(), 'Your exam is paused')

    def test_original_active_even_while_frozen_keeps_other_browsers_out_of_the_log(self):
        self.freeze()
        self.a_ping()
        self.intrude(ua='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605')
        self.assertEqual(self.attempt0().intrusions, 0)  # already frozen: nothing new to report
        self.assertEqual(ExamEvent.objects.filter(kind='freeze').count(), 1)

    def test_sign_in_and_join_screens_warn_against_sharing(self):
        self.assertContains(Client().get('/accounts/login/'), 'Do not share your login or your exam link')
        fresh = User.objects.create_user('ab5555', 'ab5555@srmist.edu.in', PASSWORD)
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.LOBBY, starts_at=None, ends_at=None)
        c = Client()
        c.login(username=fresh.username, password=PASSWORD)
        self.assertContains(c.get(self.url('exam_consent')), 'Do not share your login or this link')
