from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from quiz.exam_device import COOKIE
from quiz.exam_integrity import MAX_STRIKES, enforce
from quiz.exam_results import result_rows, result_table
from quiz.models import Exam, ExamAttempt, ExamEvent, Question
from quiz.test_exam_device import DESKTOP, FIREFOX, DeviceBase
from quiz.test_exam_take import PASSWORD


class AntiCheatBase(DeviceBase):
    """Student ab1000 is taking a running scheduled exam on browser A (Chrome on Windows, self.client)."""

    def a_get(self, name):
        self.login(self.s)
        return self.client.get(self.url(name), HTTP_USER_AGENT=DESKTOP)

    def a_post(self, name, **data):
        self.login(self.s)
        return self.client.post(self.url(name), data, HTTP_USER_AGENT=DESKTOP)

    def event(self, kind, **extra):
        return self.a_post('exam_event', kind=kind, **extra)

    def leave(self, kind='hidden'):
        """One counted absence: first move the last report out of the duplicate window, as waiting would."""
        ExamAttempt.objects.filter(pk=self.attempt0().pk, last_leave_at__isnull=False).update(
            last_leave_at=timezone.now() - timedelta(seconds=10))
        return self.event(kind)

    def answer_right(self, n=1):
        questions = self.a_get('exam_take').context['payload']['questions'][:n]
        for q in questions:
            self.a_post('exam_answer', question=q['id'], choice=self.choice(q['id'], True))
        return sum(Question.objects.get(pk=q['id']).points for q in questions)

    def strike_out(self):
        points = self.answer_right()
        last = None
        for _ in range(MAX_STRIKES):
            last = self.leave()
        return points, last

    def events(self, kind):
        return ExamEvent.objects.filter(exam=self.exam, kind=kind)

    def panel(self):
        self.login(self.teacher)
        return self.client.get(reverse('exam_controls', args=[self.exam.pk]))

    def live(self):
        self.login(self.teacher)
        return self.client.get(reverse('exam_live', args=[self.exam.pk]))

    def teacher_detail(self, follow=False, **data):
        self.login(self.teacher)
        return self.client.post(reverse('exam_detail', args=[self.exam.pk]), data, follow=follow)


class LeaveAndStrikeTests(AntiCheatBase):
    def test_a_leave_is_a_strike_and_is_logged(self):
        r = self.event('hidden')
        body = r.json()
        self.assertEqual((r.status_code, body['ok'], body['counted'], body['closed']), (200, True, True, False))
        self.assertEqual((body['anti_cheat'], body['strikes'], body['max_strikes']), (True, 1, 3))
        a = self.attempt0()
        self.assertEqual((a.strikes, a.leaves), (1, 1))
        self.assertIn('strike 1 of 3', self.events('strike').get().detail)

    def test_one_absence_reported_three_ways_is_one_strike(self):
        results = [self.event(kind).json()['counted'] for kind in ('hidden', 'blur', 'fullscreen')]
        self.assertEqual(results, [True, False, False])
        self.assertEqual((self.attempt0().strikes, self.attempt0().leaves), (1, 1))

    def test_three_strikes_submit_the_exam_and_keep_and_score_the_answers(self):
        points, last = self.strike_out()
        self.assertTrue(last.json()['closed'])
        a = self.attempt0()
        self.assertEqual((a.strikes, a.submit_reason, a.score), (3, 'strikes', points))
        self.assertIsNotNone(a.submitted_at)
        self.assertEqual(self.events('auto_submit').count(), 1)
        self.assertEqual(self.a_post('exam_answer', question=1, choice=1).status_code, 409)  # nothing more can be changed
        self.assertRedirects(self.a_get('exam_take'), self.url('exam_done'), fetch_redirect_response=False)
        self.assertContains(self.a_get('exam_done'), 'submitted automatically')

    def test_a_normal_submit_has_no_reason(self):
        self.a_post('exam_submit')
        self.assertEqual(self.attempt0().submit_reason, '')
        self.assertNotContains(self.a_get('exam_done'), 'submitted automatically')

    def test_the_count_lives_on_the_server_so_reloading_resets_nothing(self):
        self.event('hidden')
        payload = self.a_get('exam_take').context['payload']
        self.assertEqual((payload['strikes'], payload['anti_cheat'], payload['max_strikes']), (1, True, 3))
        ping = self.a_get('exam_ping').json()
        self.assertEqual((ping['strikes'], ping['anti_cheat']), (1, True))

    def test_back_adds_the_time_away_but_never_more_than_the_server_saw(self):
        self.event('hidden')
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(away_since=timezone.now() - timedelta(seconds=100))
        self.event('back', away=5000)  # the page claims far more than the 100 seconds the server saw
        self.assertEqual(self.attempt0().away_seconds, 100)
        self.assertIsNone(self.attempt0().away_since)
        self.event('back', away=40)  # nothing is open any more: ignored
        self.assertEqual(self.attempt0().away_seconds, 100)

    def test_back_with_a_smaller_figure_and_with_rubbish(self):
        self.event('hidden')
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(away_since=timezone.now() - timedelta(seconds=100))
        self.event('back', away=30)
        self.assertEqual(self.attempt0().away_seconds, 30)
        self.leave()
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(away_since=timezone.now() - timedelta(seconds=50))
        self.event('back', away='abc')
        self.assertEqual(self.attempt0().away_seconds, 30)

    def test_unknown_kinds_are_refused(self):
        self.assertEqual(self.event('lunch').status_code, 400)
        self.assertEqual(self.a_post('exam_event').status_code, 400)
        self.assertEqual(self.attempt0().leaves, 0)

    def test_open_exams_have_no_strikes(self):
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.OPEN)
        body = self.event('hidden').json()
        self.assertEqual((body['counted'], body['anti_cheat'], body['strikes']), (False, False, 0))
        self.assertEqual(self.attempt0().leaves, 0)

    def test_get_is_refused_and_a_forged_post_needs_the_csrf_token(self):
        self.login(self.s)
        self.assertEqual(self.client.get(self.url('exam_event')).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.login(username=self.s.username, password=PASSWORD)
        self.assertEqual(strict.post(self.url('exam_event'), {'kind': 'hidden'}).status_code, 403)
        self.assertEqual(self.attempt0().strikes, 0)

    def test_only_a_student_who_started_can_report(self):
        waiting = self.students[1]  # joined the lobby but never opened the exam
        self.login(waiting)
        self.assertEqual(self.client.post(self.url('exam_event'), {'kind': 'hidden'}).status_code, 409)
        self.client.logout()
        self.assertEqual(self.client.post(self.url('exam_event'), {'kind': 'hidden'}).status_code, 302)  # to the login page

    def test_another_browser_cannot_add_strikes_to_the_seat(self):
        r = self.b.post(self.url('exam_event'), {'kind': 'hidden'}, HTTP_USER_AGENT=FIREFOX, REMOTE_ADDR='10.1.1.5')
        self.assertEqual(r.status_code, 403)
        self.assertEqual((self.attempt0().strikes, self.attempt0().leaves), (0, 0))

    def test_after_the_exam_ended_reports_are_refused(self):
        self.teacher_detail(action='end')
        r = self.event('hidden')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.attempt0().strikes, 0)

    def test_leaving_while_the_seat_is_frozen_is_flagged_but_costs_no_strike(self):
        self.freeze()
        r = self.event('hidden')
        self.assertEqual((r.status_code, r.json()['counted']), (200, True))
        a = self.attempt0()
        self.assertEqual((a.strikes, a.leaves), (0, 1))
        self.assertIn('while the seat was frozen', self.events('leave_frozen').get().detail)


class ServerClockTests(AntiCheatBase):
    """The page cannot be trusted to say it is not in fullscreen (a student can delete its overlay in devtools), so the
    server runs its own clock from the moment the exam page opens."""

    def overdue(self, seconds=50, leave=None):
        fields = {'away_since': timezone.now() - timedelta(seconds=seconds)}
        if leave is not None:
            fields['last_leave_at'] = timezone.now() - timedelta(seconds=leave)
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(**fields)

    def ping(self):
        return self.a_get('exam_ping').json()

    def test_the_servers_clock_starts_when_the_exam_page_opens(self):
        self.assertIsNotNone(self.attempt0().away_since)
        self.assertEqual(self.attempt0().strikes, 0)
        self.assertEqual(self.ping()['strikes'], 0)  # 45 seconds have not passed

    def test_a_student_who_never_goes_fullscreen_is_counted_by_the_server_alone(self):
        self.overdue(50)
        self.assertEqual(self.ping()['strikes'], 1)  # the page reported nothing at all
        self.assertIn('did not go fullscreen in time', self.events('strike').get().detail)
        self.assertEqual(self.ping()['strikes'], 1)  # not again straight away
        self.overdue(200, leave=50)
        self.assertEqual(self.ping()['strikes'], 1)  # 50 seconds is not yet a minute
        self.overdue(200, leave=61)  # a minute later the absence has gone on
        self.assertEqual(self.ping()['strikes'], 2)
        self.assertIn('still outside the exam window', self.events('strike').first().detail)
        self.overdue(200, leave=61)
        self.assertEqual(self.ping()['state'], 'closed')  # the third strike submits the exam
        a = self.attempt0()
        self.assertEqual((a.strikes, a.submit_reason), (3, 'strikes'))

    def test_going_fullscreen_in_time_stops_the_clock(self):
        self.overdue(50)
        self.event('back', away=0)  # the page says it is in fullscreen
        self.assertIsNone(self.attempt0().away_since)
        self.assertEqual(self.ping()['strikes'], 0)

    def test_reloading_does_not_buy_a_fresh_45_seconds(self):
        self.overdue(40)
        self.a_get('exam_take')
        self.assertLess(abs((self.attempt0().away_since - (timezone.now() - timedelta(seconds=40))).total_seconds()), 3)
        self.overdue(50)
        self.assertEqual(self.a_get('exam_take').status_code, 200)
        self.assertEqual(self.attempt0().strikes, 1)  # counted when the page was reloaded

    def test_reloading_after_the_third_strike_lands_on_the_finished_page(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(strikes=2)
        self.overdue(50)
        self.assertRedirects(self.a_get('exam_take'), self.url('exam_done'), fetch_redirect_response=False)
        self.assertEqual(self.attempt0().submit_reason, 'strikes')

    def test_a_reload_after_being_in_fullscreen_starts_a_new_clock(self):
        self.event('back', away=0)
        self.assertIsNone(self.attempt0().away_since)
        self.a_get('exam_take')
        self.assertLess(abs((self.attempt0().away_since - timezone.now()).total_seconds()), 3)

    def test_strikes_off_open_exams_and_frozen_seats_are_not_counted_by_the_server(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(strikes_off=True)
        self.overdue(500)
        self.assertEqual(self.ping()['strikes'], 0)
        a = self.attempt0()
        self.assertEqual((a.leaves, ExamEvent.objects.filter(exam=self.exam, attempt=a, kind__in=('leave', 'strike')).count()), (0, 0))
        ExamAttempt.objects.filter(pk=a.pk).update(strikes_off=False)
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.OPEN)
        self.assertEqual(self.ping()['strikes'], 0)
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.SCHEDULED)
        self.freeze()
        self.overdue(500)
        self.assertEqual(self.a_ping()['state'], 'frozen')
        self.assertEqual(self.attempt0().strikes, 0)

    def test_enforce_itself_leaves_a_frozen_seat_alone(self):
        self.freeze()
        self.overdue(500)
        attempt = ExamAttempt.objects.select_related('exam').get(pk=self.attempt0().pk)
        self.assertIsNotNone(attempt.frozen_at)
        result = enforce(attempt)
        self.assertEqual((result.strikes, self.attempt0().strikes, self.attempt0().leaves), (0, 0, 0))

    def test_another_browser_cannot_make_the_server_count_strikes(self):
        self.overdue(50)
        self.assertEqual(self.b_ping()['state'], 'blocked')
        self.assertEqual(self.attempt0().strikes, 0)
        self.assertEqual(self.ping()['strikes'], 1)  # only the seat's own browser's check-in counts

    def test_saving_an_answer_is_a_check_in_too(self):
        self.overdue(50)
        questions = self.a_get('exam_take').context['payload']['questions']
        self.a_post('exam_answer', question=questions[0]['id'], choice=self.choice(questions[0]['id'], True))
        self.assertEqual(self.attempt0().strikes, 1)
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(strikes=2)
        self.overdue(200, leave=61)
        r = self.a_post('exam_answer', question=questions[0]['id'], choice=self.choice(questions[0]['id'], True))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.attempt0().submit_reason, 'strikes')

    def test_the_page_may_not_report_the_kinds_only_the_server_uses(self):
        self.assertEqual(self.event('never').status_code, 400)
        self.assertEqual(self.event('away').status_code, 400)

    def test_teachers_see_a_student_who_never_entered_fullscreen(self):
        self.assertNotContains(self.live(), 'Integrity flags')  # the exam page has only just opened: nothing to flag yet
        self.overdue(30)
        r = self.live()
        self.assertContains(r, 'Integrity flags (1)')
        self.assertContains(r, 'not in fullscreen')

    def test_switching_strikes_on_gives_a_fresh_clock_and_off_clears_it(self):
        self.teacher_detail(action='strikes', attempt=self.attempt0().pk, value='off')
        self.assertIsNone(self.attempt0().away_since)
        self.teacher_detail(action='strikes', attempt=self.attempt0().pk, value='on')
        self.assertLess(abs((self.attempt0().away_since - timezone.now()).total_seconds()), 3)
        self.assertEqual(self.ping()['strikes'], 0)

    def test_the_page_is_told_how_long_it_has(self):
        self.assertEqual(self.a_get('exam_take').context['payload']['enter_seconds'], 45)


class StrikesOffTests(AntiCheatBase):
    def switch(self, value):
        return self.teacher_detail(follow=True, action='strikes', attempt=self.attempt0().pk, value=value)

    def test_turning_strikes_off_stops_them_and_the_fullscreen_rule_but_keeps_the_log(self):
        r = self.switch('off')
        self.assertIn('now off', ' '.join(str(m) for m in r.context['messages']))
        self.assertTrue(self.attempt0().strikes_off)
        self.assertEqual(self.events('strikes_off').get().actor, self.teacher)
        self.assertFalse(self.a_get('exam_take').context['payload']['anti_cheat'])
        self.assertFalse(self.a_get('exam_ping').json()['anti_cheat'])
        for _ in range(MAX_STRIKES + 2):
            body = self.leave().json()
        self.assertEqual((body['strikes'], body['closed']), (0, False))
        a = self.attempt0()
        self.assertEqual((a.strikes, a.leaves, a.submitted_at), (0, MAX_STRIKES + 2, None))
        self.assertEqual(self.events('leave').count(), 1)  # one log line for the burst, not one per leave
        ExamAttempt.objects.filter(pk=a.pk).update(last_leave_at=timezone.now() - timedelta(seconds=61))
        self.event('hidden')
        self.assertEqual(self.events('leave').count(), 2)  # a new burst after a quiet minute is logged again

    def test_turning_it_back_on(self):
        self.switch('off')
        self.switch('on')
        self.assertFalse(self.attempt0().strikes_off)
        self.assertTrue(self.a_get('exam_ping').json()['anti_cheat'])
        self.assertEqual(self.events('strikes_on').count(), 1)

    def test_it_is_refused_for_open_exams_and_for_other_teachers(self):
        other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        other.groups.add(Group.objects.get(name='Teachers'))
        self.login(other)
        r = self.client.post(reverse('exam_detail', args=[self.exam.pk]),
                             {'action': 'strikes', 'attempt': self.attempt0().pk, 'value': 'off'})
        self.assertEqual(r.status_code, 404)
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.OPEN)
        r = self.switch('off')
        self.assertIn('only apply to scheduled', ' '.join(str(m) for m in r.context['messages']))
        self.assertFalse(self.attempt0().strikes_off)

    def test_the_panel_lists_everyone_not_submitted_with_their_state(self):
        self.switch('off')
        rows = {a.user.username: a.strikes_off for a in self.panel().context['strike_rows']}
        self.assertEqual(rows, {'ab1000': True, 'ab1001': False, 'ab1002': False})  # the lobby students too


class ReopenTests(AntiCheatBase):
    def reopen(self, minutes=0, follow=False):
        return self.teacher_detail(follow=follow, action='reopen', attempt=self.attempt0().pk, minutes=minutes)

    def messages(self, response):
        return ' '.join(str(m) for m in response.context['messages'])

    def test_reopen_lets_the_student_carry_on_with_their_answers_and_clean_strikes(self):
        self.strike_out()
        before = self.attempt0().ends_at
        r = self.reopen(5, follow=True)
        self.assertIn('can continue', self.messages(r))
        a = self.attempt0()
        self.assertEqual((a.submitted_at, a.score, a.strikes, a.submit_reason, a.total_points), (None, None, 0, '', 0))
        self.assertEqual(a.ends_at, before + timedelta(minutes=5))
        self.assertEqual(a.extra_seconds, 300)
        entry = self.events('reopen').get()
        self.assertEqual(entry.actor, self.teacher)
        self.assertEqual(self.a_get('exam_ping').json()['state'], 'ok')
        self.assertEqual(self.a_get('exam_take').status_code, 200)  # the exam page, not the done page
        self.assertEqual(len(self.a_get('exam_take').context['payload']['answers']), 1)  # the answer is still there
        self.assertEqual(self.a_get('exam_take').context['payload']['strikes'], 0)

    def test_the_finished_page_sends_the_student_back_once_reopened(self):
        self.strike_out()
        self.assertEqual(self.a_get('exam_ping').json()['state'], 'closed')
        self.assertContains(self.a_get('exam_done'), 'taken back to your exam')
        self.reopen(0)
        self.assertRedirects(self.a_get('exam_done'), self.url('exam_take'), fetch_redirect_response=False)

    def test_it_is_refused_unless_the_server_submitted_the_student_for_strikes(self):
        self.a_post('exam_submit')  # an ordinary submission
        r = self.reopen(5, follow=True)
        self.assertIn('not submitted automatically', self.messages(r))
        self.assertIsNotNone(self.attempt0().submitted_at)

    def test_it_is_refused_once_the_exam_is_over(self):
        self.strike_out()
        self.teacher_detail(action='end')
        r = self.reopen(5, follow=True)
        self.assertIn('exam is over', self.messages(r))
        self.assertIsNotNone(self.attempt0().submitted_at)

    def test_only_listed_extra_minutes_are_accepted(self):
        self.strike_out()
        r = self.reopen(7, follow=True)
        self.assertIn('Choose how many extra minutes', self.messages(r))
        self.assertIsNotNone(self.attempt0().submitted_at)

    def test_the_administrator_may_reopen_and_it_is_logged_as_theirs(self):
        self.strike_out()
        root = User.objects.create_superuser('root', 'root@example.com', PASSWORD)
        self.login(root)
        self.client.post(reverse('exam_detail', args=[self.exam.pk]),
                         {'action': 'reopen', 'attempt': self.attempt0().pk, 'minutes': 0})
        self.assertIsNone(self.attempt0().submitted_at)
        self.assertEqual(self.events('reopen').get().actor, root)

    def test_the_panel_offers_reopening_only_while_the_exam_runs(self):
        self.strike_out()
        self.assertEqual([a.user.username for a in self.panel().context['reopenable']], ['ab1000'])
        self.assertContains(self.panel(), 'Let them continue')
        self.teacher_detail(action='end')
        self.assertEqual(self.panel().context['reopenable'], [])


class FreezeEvidenceTests(AntiCheatBase):
    def evidence(self):
        return self.panel().context['frozen'][0].evidence

    def test_the_panel_shows_silence_network_progress_time_and_history(self):
        self.answer_right(2)
        self.go_silent()  # the original has said nothing for 60 seconds
        self.freeze()
        ev = self.evidence()
        self.assertGreaterEqual(ev['silent_before'], 60)
        self.assertIsNone(ev['original_back_ago'])
        self.assertIs(ev['same_network'], False)  # 127.0.0.1 against 10.1.1.5
        self.assertEqual((ev['answered'], ev['questions']), (2, 10))
        self.assertRegex(ev['time_left'], r'^(29|30):\d\d$')
        self.assertTrue(ev['events'])
        r = self.panel()
        for text in ('had been silent for', 'different addresses', '2 of 10 answered', 'left the window 0 times'):
            self.assertContains(r, text)

    def test_the_original_checking_in_again_after_the_freeze_is_called_out(self):
        self.freeze()
        self.assertEqual(self.a_ping()['state'], 'frozen')  # the original is alive and answers the server
        ev = self.evidence()
        self.assertIsNotNone(ev['original_back_ago'])
        self.assertContains(self.panel(), 'probably still in use')

    def test_same_network_is_reported_when_both_devices_share_an_address(self):
        self.freeze()
        a = self.attempt0()
        ExamAttempt.objects.filter(pk=a.pk).update(challenger_ip=a.device_ip)
        self.assertIs(self.evidence()['same_network'], True)
        self.assertContains(self.panel(), 'same address')

    def test_history_counts_earlier_trouble(self):
        self.b.post(self.url('exam_event'), {'kind': 'hidden'}, HTTP_USER_AGENT=FIREFOX)  # no effect, but a turn-away happens
        self.event('hidden')
        self.freeze()
        r = self.panel()
        self.assertContains(r, 'other-device attempts 1')
        self.assertContains(r, 'strikes 1')
        self.assertContains(r, 'left the window 1 time')

    def sig_at(self, seconds_later):
        with mock.patch('quiz.teacher_views.timezone') as clock:
            clock.now.return_value = timezone.now() + timedelta(seconds=seconds_later)
            return self.panel().context['sig']

    def test_while_a_seat_is_frozen_the_panel_refreshes_every_ten_seconds_so_the_evidence_stays_fresh(self):
        self.freeze()
        self.assertNotEqual(self.sig_at(0), self.sig_at(25))

    def test_with_nothing_frozen_the_panel_is_left_alone(self):
        self.assertEqual(self.sig_at(0), self.sig_at(25))  # no needless rebuilds while the teacher is typing


class FlagsTests(AntiCheatBase):
    def test_a_quiet_page_is_flagged_for_the_teacher_but_never_a_strike(self):
        self.assertNotContains(self.live(), 'Integrity flags')
        self.go_silent()
        r = self.live()
        self.assertContains(r, 'Integrity flags (1)')
        self.assertContains(r, 'No signal from the page for')
        a = self.attempt0()
        self.assertEqual((a.strikes, a.leaves), (0, 0))

    def test_only_started_unsubmitted_students_in_scheduled_exams_are_watched(self):
        self.go_silent()
        self.a_post('exam_submit')
        self.assertNotContains(self.live(), 'No signal')
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(submitted_at=None, device_seen_at=timezone.now() - timedelta(seconds=90))
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.OPEN)
        self.assertNotContains(self.live(), 'No signal')

    def test_strikes_and_being_away_show_in_the_table(self):
        self.leave()
        self.leave()
        r = self.live()
        self.assertContains(r, 'Integrity flags (1)')
        self.assertContains(r, '2 of 3')
        self.assertContains(r, 'away right now')
        self.event('back', away=5)
        self.assertNotContains(self.live(), 'away right now')

    def test_an_automatic_submission_is_called_out(self):
        self.strike_out()
        self.assertContains(self.live(), 'submitted automatically after 3 strikes')

    def test_results_and_exports_carry_the_strikes(self):
        self.strike_out()
        rows = {r['name']: r for r in result_rows(self.exam)}
        self.assertEqual((rows['ab1000']['strikes'], rows['ab1000']['leaves'], rows['ab1000']['auto']), (3, 3, 'Yes (strikes)'))
        table = result_table(list(rows.values()))
        self.assertEqual(table[0][-3:], ['Strikes', 'Left the window', 'Auto-submitted'])
        mine = next(row for row in table[1:] if row[0] == 'ab1000')
        self.assertEqual(mine[-3:], [3, 3, 'Yes (strikes)'])
        self.login(self.teacher)
        self.assertContains(self.client.get(reverse('exam_results', args=[self.exam.pk])), 'auto-submitted')


class CopiedCodeTests(AntiCheatBase):
    def test_the_device_code_used_from_another_kind_of_browser_is_flagged(self):
        self.b.cookies[COOKIE] = self.attempt0().device_id  # the cookie value was copied into another browser
        self.assertEqual(self.b_ping()['state'], 'ok')  # a web page cannot stop the copy from working...
        a = self.attempt0()
        self.assertEqual(a.mismatches, 1)  # ...but it is seen
        detail = self.events('copied_code').get().detail
        for text in ('Chrome on Windows', 'Firefox on Linux', a.device_tag):
            self.assertIn(text, detail)
        self.b_ping()
        self.assertEqual(self.attempt0().mismatches, 1)  # one line a minute, not one per ping
        ExamAttempt.objects.filter(pk=a.pk).update(last_mismatch_at=timezone.now() - timedelta(seconds=61))
        self.b_ping()
        self.assertEqual(self.attempt0().mismatches, 2)

    def test_ordinary_use_never_raises_the_flag(self):
        for _ in range(3):
            self.a_get('exam_ping')
            self.a_get('exam_take')
        self.assertEqual(self.attempt0().mismatches, 0)
        self.assertFalse(self.events('copied_code').exists())

    def test_the_flag_reaches_the_teachers_table(self):
        self.b.cookies[COOKIE] = self.attempt0().device_id
        self.b_ping()
        self.assertContains(self.live(), 'Device code used from a different browser')


class FreezeSilenceRecordTests(AntiCheatBase):
    def test_how_long_the_original_had_been_silent_is_recorded_when_the_seat_freezes(self):
        self.assertIsNone(self.attempt0().freeze_silent_seconds)
        self.go_silent()
        self.b_take()
        self.assertGreaterEqual(self.attempt0().freeze_silent_seconds, 60)


class PageTests(AntiCheatBase):
    def newcomer(self):
        return User.objects.create_user('ab5555', 'ab5555@srmist.edu.in', PASSWORD)

    def test_consent_states_the_fullscreen_and_strike_rules_for_scheduled_exams_only(self):
        self.login(self.newcomer())
        r = self.client.get(self.url('exam_consent'))
        for text in ('must be taken in fullscreen', 'third submits your exam automatically', 'when you reconnect'):
            self.assertContains(r, text)
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.OPEN, status=Exam.RUNNING)
        self.assertNotContains(self.client.get(self.url('exam_consent')), 'fullscreen')

    def test_the_exam_page_carries_the_rules_and_the_gate(self):
        r = self.a_get('exam_take')
        payload = r.context['payload']
        self.assertEqual((payload['scheduled'], payload['anti_cheat'], payload['strikes'], payload['max_strikes']),
                         (True, True, 0, 3))
        self.assertEqual(payload['event_url'], self.url('exam_event'))
        self.assertContains(r, 'id="gate"')
        self.assertContains(r, 'Warnings:')

    def test_the_exam_page_carries_the_click_anywhere_and_esc_lock_code_and_no_inactivity_rule(self):
        r = self.a_get('exam_take')
        for text in ("navigator.keyboard.lock(['Escape'])", "['pointerdown', 'keydown']"):
            self.assertContains(r, text)
        self.assertNotIn('idle_warn_seconds', r.context['payload'])
        self.assertNotContains(r, 'Are you still there?')

    def test_inactivity_is_not_a_reportable_kind_and_never_a_strike(self):
        self.event('back', away=0)
        r = self.event('idle')
        self.assertEqual((r.status_code, r.json()['reason']), (400, 'bad_kind'))
        self.assertEqual(self.attempt0().strikes, 0)

    def test_open_exam_pages_switch_the_rules_off_and_do_not_report_leaving(self):
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.OPEN)
        payload = self.a_get('exam_take').context['payload']
        self.assertEqual((payload['scheduled'], payload['anti_cheat']), (False, False))

    def test_strikes_off_keeps_the_page_reporting_but_drops_the_fullscreen_rule(self):
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(strikes_off=True)
        payload = self.a_get('exam_take').context['payload']
        self.assertEqual((payload['scheduled'], payload['anti_cheat']), (True, False))
