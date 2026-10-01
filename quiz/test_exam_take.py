from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from quiz.exam_run import COUNTDOWN_SECONDS, GRACE_SECONDS, finalize, shuffled_choices
from quiz.models import Choice, Exam, ExamAnswer, ExamAttempt, Question

PASSWORD = 'TestPassword123!'
DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari/604.1'


class TakeBase(TestCase):
    """A scheduled exam with 10 questions (the last is worth 2 points) and three students who joined the lobby."""

    def setUp(self):
        self.teacher = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)
        self.teacher.groups.add(Group.objects.get(name='Teachers'))
        self.students = [User.objects.create_user(f'ab{1000 + i}', f'ab{1000 + i}@srmist.edu.in', PASSWORD)
                         for i in range(3)]
        self.exam = Exam.objects.create(owner=self.teacher, title='Unit 1', seat_limit=10,
                                        duration_minutes=30, status=Exam.LOBBY)
        for i in range(10):
            q = Question.objects.create(text=f'Question {i}?', owner=self.teacher, points=2 if i == 9 else 1)
            Choice.objects.create(question=q, text='right', is_correct=True)
            Choice.objects.create(question=q, text='wrong 1', is_correct=False)
            Choice.objects.create(question=q, text='wrong 2', is_correct=False)
            self.exam.questions.add(q)
        for s in self.students:
            self.login(s)
            self.client.post(reverse('exam_consent', args=[self.exam.token]), {'agree': 'on'})

    # ---- helpers ----
    def login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password=PASSWORD)

    def url(self, name):
        return reverse(name, args=[self.exam.token])

    def teacher_post(self, action):
        self.login(self.teacher)
        return self.client.post(reverse('exam_detail', args=[self.exam.pk]), {'action': action})

    def run_now(self, minutes=30):
        """Fast-forward: the exam started a second ago and has `minutes` left."""
        now = timezone.now()
        Exam.objects.filter(pk=self.exam.pk).update(
            status=Exam.RUNNING, starts_at=now - timedelta(seconds=1), ends_at=now + timedelta(minutes=minutes))
        self.exam.refresh_from_db()

    def attempt(self, student):
        return ExamAttempt.objects.get(exam=self.exam, user=student)

    def take(self, student, **extra):
        self.login(student)
        return self.client.get(self.url('exam_take'), **extra)

    def payload(self, student):
        return self.take(student).context['payload']

    def answer(self, qid, choice_id):
        return self.client.post(self.url('exam_answer'), {'question': qid, 'choice': choice_id})

    def choice(self, qid, correct):
        return Choice.objects.filter(question_id=qid, is_correct=correct).first().pk

    def worth(self, payload, n):
        """Points of the first n questions in the student's own (shuffled) order."""
        return sum(Question.objects.get(pk=q['id']).points for q in payload['questions'][:n])

    def answer_all(self, student, n_correct):
        """Take the exam as `student`, answering the first n_correct questions (in their order) correctly, the rest wrong."""
        p = self.payload(student)
        for i, q in enumerate(p['questions']):
            self.answer(q['id'], self.choice(q['id'], correct=i < n_correct))
        return p


class PhaseAndStartTests(TakeBase):
    def test_phase_boundaries(self):
        now = timezone.now()
        e = Exam(status=Exam.RUNNING, starts_at=now + timedelta(seconds=5), ends_at=now + timedelta(minutes=5))
        self.assertEqual(e.phase(now), 'countdown')
        self.assertEqual(e.phase(now + timedelta(seconds=5)), 'running')
        self.assertEqual(e.phase(now + timedelta(minutes=5)), 'ended')
        self.assertEqual(Exam(status=Exam.RUNNING).phase(), 'running')  # open exam: no clock
        self.assertEqual(Exam(status=Exam.LOBBY).phase(), 'lobby')

    def test_start_sets_a_countdown_and_the_end_time(self):
        self.teacher_post('start')
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, Exam.RUNNING)
        self.assertEqual(self.exam.phase(), 'countdown')
        self.assertAlmostEqual((self.exam.starts_at - timezone.now()).total_seconds(), COUNTDOWN_SECONDS, delta=3)
        self.assertEqual(self.exam.ends_at - self.exam.starts_at, timedelta(minutes=30))

    def test_students_see_the_countdown_from_the_status_endpoint(self):
        self.teacher_post('start')
        self.login(self.students[0])
        data = self.client.get(self.url('exam_status')).json()
        self.assertEqual(data['phase'], 'countdown')
        self.assertGreater(data['starts_at'], data['now'])

    def test_only_the_owner_can_start_and_only_from_the_lobby(self):
        other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        other.groups.add(Group.objects.get(name='Teachers'))
        self.login(other)
        self.assertEqual(self.client.post(reverse('exam_detail', args=[self.exam.pk]), {'action': 'start'}).status_code, 404)
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.DRAFT)
        self.teacher_post('start')
        self.exam.refresh_from_db()
        self.assertEqual((self.exam.status, self.exam.starts_at), (Exam.DRAFT, None))

    def test_cannot_open_an_exam_without_questions(self):
        empty = Exam.objects.create(owner=self.teacher, title='Empty', seat_limit=5, duration_minutes=10)
        self.login(self.teacher)
        self.client.post(reverse('exam_detail', args=[empty.pk]), {'action': 'open'})
        empty.refresh_from_db()
        self.assertEqual(empty.status, Exam.DRAFT)


class TakingTests(TakeBase):
    def test_no_questions_before_the_start(self):
        self.login(self.students[0])
        for phase_setup in ('lobby', 'countdown'):
            if phase_setup == 'countdown':
                self.teacher_post('start')
                self.login(self.students[0])
            r = self.client.get(self.url('exam_take'))
            self.assertRedirects(r, self.url('exam_lobby'), fetch_redirect_response=False)

    def test_questions_appear_at_the_start_without_the_answers(self):
        self.run_now()
        r = self.take(self.students[0])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['payload']['questions']), 10)
        self.assertNotContains(r, 'is_correct')
        self.assertNotContains(r, 'is_correct')

    def test_starting_stamps_the_student_clock_and_deadline(self):
        self.run_now()
        self.take(self.students[0])
        a = self.attempt(self.students[0])
        self.assertIsNotNone(a.started_at)
        self.assertEqual(a.ends_at, self.exam.ends_at)
        self.assertCountEqual(a.question_ids, list(self.exam.questions.values_list('id', flat=True)))

    def test_order_is_fixed_per_student_and_different_between_students(self):
        self.run_now()
        first = self.payload(self.students[0])
        again = self.payload(self.students[0])  # reload
        self.assertEqual(first['questions'], again['questions'])
        other = self.payload(self.students[1])
        self.assertNotEqual([q['id'] for q in first['questions']], [q['id'] for q in other['questions']])
        self.assertNotEqual([[o['id'] for o in q['options']] for q in first['questions']],
                            [[o['id'] for o in q['options']] for q in sorted(other['questions'], key=lambda q: [x['id'] for x in first['questions']].index(q['id']))])

    def test_option_shuffle_is_stable_for_a_seed(self):
        q = Question.objects.first()
        a = [c.id for c in shuffled_choices(7, q.pk, q.choices.all())]
        self.assertEqual(a, [c.id for c in shuffled_choices(7, q.pk, q.choices.all())])
        self.assertCountEqual(a, list(q.choices.values_list('id', flat=True)))

    def test_autosave_overwrites_clears_and_restores_on_reload(self):
        self.run_now()
        qid = self.payload(self.students[0])['questions'][0]['id']
        self.assertEqual(self.answer(qid, self.choice(qid, False)).json(), {'ok': True})
        self.answer(qid, self.choice(qid, True))  # changed their mind
        self.assertEqual(ExamAnswer.objects.count(), 1)
        self.assertTrue(ExamAnswer.objects.get().choice.is_correct)
        self.assertEqual(self.payload(self.students[0])['answers'], {str(qid): self.choice(qid, True)})  # refresh keeps it
        self.answer(qid, '')  # cleared
        self.assertEqual(ExamAnswer.objects.count(), 0)

    def test_answer_endpoint_rejects_bad_input(self):
        self.run_now()
        qs = self.payload(self.students[0])['questions']
        a, b = qs[0]['id'], qs[1]['id']
        self.assertEqual(self.answer(a, self.choice(b, True)).status_code, 400)   # choice from another question
        self.assertEqual(self.answer(a, 'abc').status_code, 400)
        self.assertEqual(self.answer('x', 1).status_code, 400)
        self.assertEqual(self.answer(999999, 1).status_code, 400)                 # not in this exam
        self.assertEqual(self.client.get(self.url('exam_answer')).status_code, 405)
        self.assertEqual(ExamAnswer.objects.count(), 0)

    def test_cannot_answer_before_taking_the_exam_or_without_a_seat(self):
        self.run_now()
        self.login(self.students[0])  # joined, but never opened the question page
        q = self.exam.questions.first()
        self.assertEqual(self.answer(q.pk, self.choice(q.pk, True)).status_code, 409)
        outsider = User.objects.create_user('cd5678', 'cd5678@srmist.edu.in', PASSWORD)
        self.login(outsider)
        self.assertEqual(self.answer(q.pk, self.choice(q.pk, True)).status_code, 409)
        self.assertRedirects(self.client.get(self.url('exam_take')), self.url('exam_entry'), fetch_redirect_response=False)

    def test_submit_scores_with_points_and_is_idempotent(self):
        self.run_now()
        p = self.answer_all(self.students[0], 0)  # everything wrong...
        big = next(q for q in p['questions'] if Question.objects.get(pk=q['id']).points == 2)
        small = next(q for q in p['questions'] if Question.objects.get(pk=q['id']).points == 1)
        for q in (big, small):                    # ...then fix the points-2 question and one points-1 question
            self.answer(q['id'], self.choice(q['id'], True))
        self.client.post(self.url('exam_submit'))
        a = self.attempt(self.students[0])
        self.assertEqual((a.score, a.total_points), (3, 11))  # 2 + 1 of 11, whatever the shuffled order
        self.assertIsNotNone(a.submitted_at)
        stamp = a.submitted_at
        self.client.post(self.url('exam_submit'))
        self.assertEqual(self.attempt(self.students[0]).submitted_at, stamp)

    def test_no_changes_after_submitting(self):
        self.run_now()
        p = self.answer_all(self.students[0], 10)
        self.client.post(self.url('exam_submit'))
        qid = p['questions'][0]['id']
        self.assertEqual(self.answer(qid, self.choice(qid, False)).status_code, 409)
        self.assertRedirects(self.client.get(self.url('exam_take')), self.url('exam_done'), fetch_redirect_response=False)
        self.assertEqual(self.attempt(self.students[0]).score, 11)

    def test_answers_are_refused_after_the_deadline_and_the_exam_is_scored(self):
        self.run_now()
        p = self.answer_all(self.students[0], 4)
        expected = self.worth(p, 4)
        ExamAttempt.objects.filter(exam=self.exam).update(
            ends_at=timezone.now() - timedelta(seconds=GRACE_SECONDS + 5))
        qid = p['questions'][5]['id']
        r = self.answer(qid, self.choice(qid, True))
        self.assertEqual((r.status_code, r.json()['reason']), (409, 'closed'))
        a = self.attempt(self.students[0])
        self.assertIsNotNone(a.submitted_at)
        self.assertEqual(a.score, expected)  # only what was saved before time ran out

    def test_answers_inside_the_grace_window_are_still_accepted(self):
        self.run_now()
        p = self.payload(self.students[0])
        ExamAttempt.objects.filter(exam=self.exam).update(ends_at=timezone.now() - timedelta(seconds=1))
        qid = p['questions'][0]['id']
        self.assertEqual(self.answer(qid, self.choice(qid, True)).status_code, 200)  # last-second autosave

    def test_late_joiner_gets_less_time_not_a_fresh_clock(self):
        self.run_now()
        late = User.objects.create_user('cd5678', 'cd5678@srmist.edu.in', PASSWORD)
        self.login(late)
        self.client.post(self.url('exam_consent'), {'agree': 'on'})
        self.client.get(self.url('exam_take'))
        self.assertEqual(ExamAttempt.objects.get(user=late).ends_at, self.exam.ends_at)

    def test_questions_page_is_blocked_on_phones_for_scheduled_exams(self):
        self.run_now()
        self.login(self.students[0])
        r = self.client.get(self.url('exam_take'), HTTP_USER_AGENT=IPHONE)
        self.assertContains(r, 'laptop or desktop')
        self.assertIsNone(self.attempt(self.students[0]).started_at)
        self.assertEqual(self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP).status_code, 200)

    def test_phones_are_stopped_at_the_door_too(self):
        newcomer = User.objects.create_user('cd5678', 'cd5678@srmist.edu.in', PASSWORD)
        self.login(newcomer)
        r = self.client.get(self.url('exam_entry'), HTTP_USER_AGENT=IPHONE)
        self.assertContains(r, 'laptop or desktop')
        self.assertFalse(ExamAttempt.objects.filter(user=newcomer).exists())


class ScoreVisibilityTests(TakeBase):
    def finish(self, student, n_correct):
        self.answer_all(student, n_correct)
        self.client.post(self.url('exam_submit'))

    def test_scheduled_score_is_hidden_until_the_exam_has_ended(self):
        self.run_now()
        self.finish(self.students[0], 10)
        r = self.client.get(self.url('exam_done'))
        self.assertContains(r, 'has been submitted')
        self.assertNotContains(r, 'Your score:')
        self.assertNotIn('selections', r.context)  # nothing about their answers is shown yet

    def test_after_the_end_students_see_score_and_their_own_choices_only(self):
        self.run_now()
        self.finish(self.students[0], 10)
        self.teacher_post('end')
        self.login(self.students[0])
        r = self.client.get(self.url('exam_done'))
        self.assertContains(r, 'Your score: 11 / 11')
        self.assertEqual(len(r.context['selections']), 10)
        self.assertNotContains(r, 'wrong 1')  # the options they did not pick are not shown

    def test_student_who_never_started_is_told_so(self):
        self.run_now()
        self.teacher_post('end')
        self.login(self.students[2])
        self.assertContains(self.client.get(self.url('exam_done')), 'did not start')


class EndingTests(TakeBase):
    def test_end_now_submits_everyone_and_stops_the_clock(self):
        self.run_now()
        p0 = self.answer_all(self.students[0], 3)
        p1 = self.answer_all(self.students[1], 6)
        self.teacher_post('end')
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.phase(), 'ended')
        self.assertLessEqual(self.exam.ends_at, timezone.now())
        self.assertEqual([self.attempt(s).score for s in self.students[:2]], [self.worth(p0, 3), self.worth(p1, 6)])
        self.assertTrue(all(self.attempt(s).submitted_at for s in self.students[:2]))
        self.assertIsNone(self.attempt(self.students[2]).submitted_at)  # never started: not scored

    def test_students_who_walk_away_are_submitted_when_time_runs_out(self):
        self.run_now()
        p = self.answer_all(self.students[0], 5)  # never presses submit
        now = timezone.now()
        Exam.objects.filter(pk=self.exam.pk).update(ends_at=now - timedelta(minutes=1))
        ExamAttempt.objects.filter(exam=self.exam).update(ends_at=now - timedelta(minutes=1))
        self.login(self.teacher)
        self.client.get(reverse('exam_live', args=[self.exam.pk]))  # the teacher's page refresh does it
        a = self.attempt(self.students[0])
        self.assertEqual((a.score, a.total_points), (self.worth(p, 5), 11))
        self.assertLessEqual(a.submitted_at, now)  # stamped at the deadline, not at the check

    def test_late_arrivals_after_the_end_cannot_join(self):
        self.run_now(minutes=-1)  # already past ends_at
        late = User.objects.create_user('cd5678', 'cd5678@srmist.edu.in', PASSWORD)
        self.login(late)
        self.assertContains(self.client.get(self.url('exam_entry')), 'has ended')

    def test_lobby_sends_a_finished_student_to_the_done_page(self):
        self.run_now()
        self.answer_all(self.students[0], 1)
        self.client.post(self.url('exam_submit'))
        self.assertRedirects(self.client.get(self.url('exam_lobby')), self.url('exam_done'), fetch_redirect_response=False)

    def test_finalize_is_safe_to_call_twice(self):
        self.run_now()
        self.answer_all(self.students[0], 2)
        a = self.attempt(self.students[0])
        first = finalize(a)
        again = finalize(a)
        self.assertEqual((first.score, first.submitted_at), (again.score, again.submitted_at))


class TeacherLiveTests(TakeBase):
    def test_roster_shows_who_is_answering_and_who_submitted(self):
        self.run_now()
        self.answer_all(self.students[0], 1)
        self.answer_all(self.students[1], 1)
        self.client.post(self.url('exam_submit'))
        self.login(self.teacher)
        r = self.client.get(reverse('exam_live', args=[self.exam.pk]))
        self.assertEqual(dict(r.context['roster']), {'ab1000': 'answering', 'ab1001': 'submitted', 'ab1002': 'lobby'})
        self.assertEqual((r.context['started_count'], r.context['submitted_count']), (2, 1))
        self.assertContains(r, 'answering')

    def test_start_and_end_buttons_show_at_the_right_time(self):
        self.login(self.teacher)
        page = reverse('exam_detail', args=[self.exam.pk])
        self.assertContains(self.client.get(page), 'Start exam')
        self.run_now()
        r = self.client.get(page)
        self.assertNotContains(r, 'Start exam')
        self.assertContains(r, 'End exam now')


class OpenExamTests(TakeBase):
    def setUp(self):
        super().setUp()
        Exam.objects.filter(pk=self.exam.pk).update(mode=Exam.OPEN, status=Exam.RUNNING, duration_minutes=None)
        self.exam.refresh_from_db()

    def test_open_exam_has_no_timer_and_starts_whenever_the_student_arrives(self):
        r = self.take(self.students[0])
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['payload']['deadline_ms'])
        self.assertIsNone(self.attempt(self.students[0]).ends_at)

    def test_open_exam_allows_phones(self):
        self.login(self.students[0])
        self.assertEqual(self.client.get(self.url('exam_take'), HTTP_USER_AGENT=IPHONE).status_code, 200)

    def test_open_exam_shows_the_score_straight_after_submitting(self):
        self.answer_all(self.students[0], 10)
        self.client.post(self.url('exam_submit'))
        self.assertContains(self.client.get(self.url('exam_done')), 'Your score: 11 / 11')

    def test_open_exam_answers_stay_open_until_the_teacher_closes_it(self):
        p = self.payload(self.students[0])
        qid = p['questions'][0]['id']
        self.assertEqual(self.answer(qid, self.choice(qid, True)).status_code, 200)
        self.teacher_post('end')
        self.login(self.students[0])
        self.assertEqual(self.answer(qid, self.choice(qid, False)).status_code, 409)
        self.assertEqual(self.attempt(self.students[0]).score, Question.objects.get(pk=qid).points)
