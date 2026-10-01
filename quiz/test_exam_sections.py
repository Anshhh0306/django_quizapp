from django.urls import reverse

from quiz.exam_run import sectioned_order
from quiz.forms import ExamForm
from quiz.models import Choice, ExamAttempt, Question
from quiz.test_exam_take import TakeBase


class SectionOrderTests(TakeBase):
    """TakeBase has nine 1-mark questions and one 2-mark question; these tests add 3-mark questions too."""

    def setUp(self):
        super().setUp()
        for i in range(3):
            q = Question.objects.create(text=f'Hard {i}?', owner=self.teacher, points=3)
            Choice.objects.create(question=q, text='right', is_correct=True)
            Choice.objects.create(question=q, text='wrong', is_correct=False)
            self.exam.questions.add(q)
        self.run_now()

    def marks_in_order(self, student):
        return [q['points'] for q in self.payload(student)['questions']]

    def test_pure_function_groups_by_marks_and_keeps_every_question(self):
        pairs = [(1, 3), (2, 1), (3, 1), (4, 2), (5, 3), (6, 1)]
        ids = sectioned_order(pairs)
        self.assertCountEqual(ids, [1, 2, 3, 4, 5, 6])
        marks = dict(pairs)
        self.assertEqual([marks[i] for i in ids], [1, 1, 1, 2, 3, 3])

    def test_students_see_one_mark_then_two_mark_then_three_mark(self):
        self.assertEqual(self.marks_in_order(self.students[0]), [1] * 9 + [2] + [3] * 3)

    def test_questions_are_still_shuffled_inside_each_section(self):
        first, second = (self.payload(s)['questions'] for s in self.students[:2])
        ones = lambda qs: [q['id'] for q in qs if q['points'] == 1]
        self.assertNotEqual(ones(first), ones(second))  # nine questions: chance of a match is 1 in 362880

    def test_order_is_fixed_for_a_student_across_reloads(self):
        a = self.payload(self.students[0])['questions']
        b = self.payload(self.students[0])['questions']
        self.assertEqual([q['id'] for q in a], [q['id'] for q in b])

    def test_page_script_labels_sections(self):
        r = self.take(self.students[0])
        self.assertContains(r, 'pal-title')
        self.assertContains(r, "'-mark questions'")


class ExamFormSectionTests(TakeBase):
    def setUp(self):
        super().setUp()
        for marks in (3, 3):
            Question.objects.create(text=f'{marks}-marker', owner=self.teacher, points=marks)

    def test_picker_groups_the_teachers_questions_by_marks(self):
        form = ExamForm(owner=self.teacher)
        groups = {marks: len(boxes) for marks, boxes in form.question_groups()}
        self.assertEqual(groups, {1: 9, 2: 1, 3: 2})
        self.assertEqual([m for m, _ in form.question_groups()], [1, 2, 3])

    def test_create_exam_page_shows_a_section_per_marks_value(self):
        self.login(self.teacher)
        r = self.client.get(reverse('exam_new'))
        for heading in ('1-mark questions (9)', '2-mark questions (1)', '3-mark questions (2)'):
            self.assertContains(r, heading)
        self.assertContains(r, 'select all / none')

    def test_only_the_teachers_own_questions_are_listed(self):
        from django.contrib.auth.models import Group, User
        other = User.objects.create_user('meena', 'meena@srmist.edu.in', 'TestPassword123!')
        other.groups.add(Group.objects.get(name='Teachers'))
        Question.objects.create(text='theirs', owner=other, points=5)
        self.assertNotIn(5, [m for m, _ in ExamForm(owner=self.teacher).question_groups()])

    def test_exam_can_still_be_created_from_the_grouped_picker(self):
        self.login(self.teacher)
        ids = list(Question.objects.filter(owner=self.teacher, points__in=[1, 3]).values_list('id', flat=True))
        r = self.client.post(reverse('exam_new'), {'title': 'Mixed', 'mode': 'open', 'seat_limit': 5,
                                                   'questions': ids, 'allowed_text': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.exam.__class__.objects.get(title='Mixed').questions.count(), len(ids))


class ResultSectionTests(TakeBase):
    def test_teacher_detail_groups_answers_by_marks_with_subtotals(self):
        three = Question.objects.create(text='Hard?', owner=self.teacher, points=3)
        Choice.objects.create(question=three, text='right', is_correct=True)
        Choice.objects.create(question=three, text='wrong', is_correct=False)
        self.exam.questions.add(three)
        self.run_now()
        p = self.payload(self.students[0])
        for q in p['questions']:  # right on every 1-mark question except one, right on the 3-mark one
            marks = Question.objects.get(pk=q['id']).points
            self.answer(q['id'], self.choice(q['id'], correct=(marks in (1, 3))))
        self.client.post(self.url('exam_submit'))
        attempt = ExamAttempt.objects.get(user=self.students[0])
        self.login(self.teacher)
        r = self.client.get(reverse('exam_result_detail', args=[self.exam.pk, attempt.pk]))
        sections = {s['marks']: (s['earned'], s['possible']) for s in r.context['sections']}
        self.assertEqual(sections, {1: (9, 9), 2: (0, 2), 3: (3, 3)})
        self.assertEqual([s['marks'] for s in r.context['sections']], [1, 2, 3])
        self.assertContains(r, '1-mark questions: 9 / 9')
        self.assertContains(r, '2-mark questions: 0 / 2')
