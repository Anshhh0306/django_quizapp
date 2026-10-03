import importlib
import re
from unittest import mock

from django.apps import apps
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from quiz.exams import QUESTION_ROWS
from quiz.forms import ExamForm
from quiz.models import Category, Choice, Exam, ExamAnswer, ExamAttempt, Question, QuestionSet
from quiz.question_sets import clean_set_name, create_set, name_for_upload, unique_name
from quiz.test_exams import GOOD_CSV, PASSWORD, TeacherBase, xlsx


def make_set(owner, name, marks=(1, 1, 2)):
    """A set with one question per entry in `marks`, each with a right and a wrong option."""
    qset = QuestionSet.objects.create(owner=owner, name=name)
    for number, points in enumerate(marks, start=1):
        question = Question.objects.create(text=f'{name} question {number}', owner=owner, points=points, question_set=qset)
        Choice.objects.create(question=question, text='right', is_correct=True)
        Choice.objects.create(question=question, text='wrong', is_correct=False)
    return qset


def make_exam(owner, title, questions):
    exam = Exam.objects.create(owner=owner, title=title, mode=Exam.OPEN, seat_limit=5)
    exam.questions.set(list(questions))
    return exam


def set_url(qset):
    return reverse('question_set_action', args=[qset.pk])


class NamingTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)
        self.other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)

    def test_names_are_one_tidy_line(self):
        self.assertEqual(clean_set_name('  Unit\t1 \n test  '), 'Unit 1 test')
        self.assertEqual(clean_set_name('a‮b\x00c'), 'a b c')  # invisible and control characters become spaces
        self.assertEqual(len(clean_set_name('x' * 150)), 100)
        self.assertEqual(clean_set_name(' \t '), '')

    def test_the_typed_name_wins_otherwise_the_file_name_without_its_extension(self):
        self.assertEqual(name_for_upload('Midterm', 'q.csv'), 'Midterm')
        self.assertEqual(name_for_upload('', 'Unit 1.xlsx'), 'Unit 1')
        self.assertEqual(name_for_upload('   ', 'a.b.csv'), 'a.b')
        self.assertEqual(name_for_upload('', '\x00\x01.csv'), 'Untitled set')

    def test_a_taken_name_gets_the_next_free_number_in_any_letter_case(self):
        QuestionSet.objects.create(owner=self.teacher, name='Unit 1')
        QuestionSet.objects.create(owner=self.teacher, name='unit 1 (2)')
        self.assertEqual(unique_name(self.teacher, 'UNIT 1'), 'UNIT 1 (3)')
        self.assertEqual(unique_name(self.teacher, 'Fresh'), 'Fresh')
        self.assertEqual(unique_name(self.other, 'Unit 1'), 'Unit 1')  # another teacher's names do not count

    def test_the_number_fits_inside_the_length_limit(self):
        long_name = 'x' * 100
        QuestionSet.objects.create(owner=self.teacher, name=long_name)
        name = unique_name(self.teacher, long_name)
        self.assertEqual(len(name), 100)
        self.assertTrue(name.endswith(' (2)'))

    def test_two_uploads_grabbing_one_name_at_once_both_get_a_set(self):
        QuestionSet.objects.create(owner=self.teacher, name='Taken')
        with mock.patch('quiz.question_sets.unique_name', side_effect=['Taken', 'Taken (2)']):  # the first pick is stale
            qset = create_set(self.teacher, 'Taken')
        self.assertEqual(qset.name, 'Taken (2)')
        self.assertEqual(QuestionSet.objects.filter(owner=self.teacher).count(), 2)

    def test_the_database_itself_refuses_a_duplicate_name_for_one_teacher(self):
        QuestionSet.objects.create(owner=self.teacher, name='A')
        QuestionSet.objects.create(owner=self.other, name='A')  # a different teacher may use the same name
        with self.assertRaises(IntegrityError), transaction.atomic():
            QuestionSet.objects.create(owner=self.teacher, name='A')


class UploadSetTests(TeacherBase):
    def upload(self, filename='Unit 1.csv', content=GOOD_CSV, name=None):
        data = {'file': SimpleUploadedFile(filename, content.encode() if isinstance(content, str) else content)}
        if name is not None:
            data['name'] = name
        return self.client.post(reverse('question_bank'), data, follow=True)

    def messages(self, response):
        return [str(m) for m in response.context['messages']]

    def test_an_upload_becomes_a_set_named_after_the_file(self):
        r = self.upload('Unit 1 test.csv')
        qset = self.teacher.question_sets.get()
        self.assertEqual(qset.name, 'Unit 1 test')
        self.assertEqual(qset.questions.count(), 2)
        self.assertEqual(set(qset.questions.values_list('owner', flat=True)), {self.teacher.pk})
        self.assertIn('2 question(s) added as the set "Unit 1 test".', self.messages(r))

    def test_a_typed_name_wins_over_the_file_name(self):
        self.upload('q.csv', name='  Midterm   Paper ')
        self.assertEqual(self.teacher.question_sets.get().name, 'Midterm Paper')

    def test_the_same_name_again_becomes_name_2_and_says_so(self):
        self.upload('Unit 1.csv')
        r = self.upload('unit 1.csv')
        self.assertEqual(sorted(self.teacher.question_sets.values_list('name', flat=True)), ['Unit 1', 'unit 1 (2)'])
        self.assertTrue(any('you already had a set called "unit 1"' in m for m in self.messages(r)))

    def test_two_teachers_can_each_have_a_set_with_the_same_name(self):
        self.upload('Unit 1.csv')
        self.client.login(username='meena', password=PASSWORD)
        self.upload('Unit 1.csv')
        self.assertEqual(QuestionSet.objects.filter(name='Unit 1').count(), 2)

    def test_excel_uploads_become_sets_too(self):
        self.upload('Quiz 3.xlsx', xlsx(QUESTION_ROWS))
        self.assertEqual(self.teacher.question_sets.get().name, 'Quiz 3')

    def test_a_bad_file_leaves_no_set_behind_and_keeps_the_typed_name(self):
        r = self.upload('Bad.csv', 'question,option_a,option_b,correct\nok,a,b,A\n,a,b,A\n', name='My name')
        self.assertTrue(r.context['errors'])
        self.assertEqual(r.context['typed_name'], 'My name')
        self.assertContains(r, 'value="My name"')
        self.assertEqual((QuestionSet.objects.count(), Question.objects.count()), (0, 0))

    def test_no_file_is_a_friendly_error_and_creates_nothing(self):
        r = self.client.post(reverse('question_bank'), {'name': 'x'})
        self.assertContains(r, 'Choose a CSV or Excel file')
        self.assertEqual(QuestionSet.objects.count(), 0)


class BankPageTests(TeacherBase):
    def test_lists_only_my_sets_newest_first_with_the_right_answer_marked(self):
        make_set(self.teacher, 'Older set', marks=(1, 2))
        make_set(self.teacher, 'Newer set', marks=(1,))
        make_set(self.other, 'Secret of someone else')
        r = self.client.get(reverse('question_bank'))
        self.assertEqual([s.name for s in r.context['sets']], ['Newer set', 'Older set'])
        self.assertNotContains(r, 'Secret of someone else')
        older = r.context['sets'][1]
        self.assertEqual([q.points for q in older.question_list], [1, 2])  # upload order
        self.assertEqual([c.text for c in older.question_list[0].choices.all()], ['right', 'wrong'])
        self.assertEqual(older.mark_total, 3)
        self.assertContains(r, 'Older set</strong> &mdash; 2 question(s), 3 marks')
        self.assertContains(r, '<strong>&#10003; right</strong>')

    def test_heading_counts_questions_and_sets(self):
        make_set(self.teacher, 'A', marks=(1, 1))
        make_set(self.teacher, 'B', marks=(1,))
        r = self.client.get(reverse('question_bank'))
        self.assertEqual((r.context['count'], r.context['set_count']), (3, 2))

    def test_a_used_set_says_which_exams_use_it_and_has_no_delete_button(self):
        used = make_set(self.teacher, 'Used set')
        make_set(self.teacher, 'Free set')
        make_exam(self.teacher, 'Midterm', used.questions.all()[:1])
        r = self.client.get(reverse('question_bank'))
        self.assertEqual({s.name: s.used_by for s in r.context['sets']}, {'Used set': ['Midterm'], 'Free set': []})
        self.assertContains(r, 'Used by: Midterm')
        self.assertContains(r, 'data-confirm="Delete “Free set”')
        self.assertNotContains(r, 'Delete “Used set”')

    def test_page_cost_does_not_grow_with_the_number_of_sets_and_questions(self):
        make_set(self.teacher, 'One', marks=(1,))

        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.client.get(reverse('question_bank'))
            return len(captured)

        small = queries()
        for i in range(4):
            qset = make_set(self.teacher, f'More {i}', marks=(1, 2, 3, 1, 1))
            make_exam(self.teacher, f'Exam {i}', qset.questions.all())
        self.assertEqual(queries(), small)

    def test_set_names_cannot_inject_html(self):
        evil = '"><img src=x onerror=alert(1)>'
        make_set(self.teacher, evil)
        for page in ('question_bank', 'exam_new'):
            r = self.client.get(reverse(page))
            self.assertNotContains(r, '<img src=x')
            self.assertContains(r, '&lt;img src=x')


class DeleteSetTests(TeacherBase):
    def delete(self, qset):
        return self.client.post(set_url(qset), {'action': 'delete'}, follow=True)

    def test_an_unused_set_is_deleted_with_its_questions_and_options(self):
        gone = make_set(self.teacher, 'Gone', marks=(1, 2))
        keep = make_set(self.teacher, 'Keep', marks=(1,))
        r = self.delete(gone)
        self.assertFalse(QuestionSet.objects.filter(pk=gone.pk).exists())
        self.assertEqual(Question.objects.filter(question_set=gone).count(), 0)
        self.assertEqual(Choice.objects.count(), 2)  # only the kept question's two options remain
        self.assertEqual(keep.questions.count(), 1)
        self.assertIn('Deleted "Gone" and its 2 question(s).', [str(m) for m in r.context['messages']])

    def test_a_set_used_by_any_exam_is_not_deleted_even_if_only_one_question_is_used(self):
        qset = make_set(self.teacher, 'Used', marks=(1, 1, 1))
        make_exam(self.teacher, 'Midterm', qset.questions.all()[:1])  # a draft with a single question from the set
        r = self.delete(qset)
        self.assertEqual(qset.questions.count(), 3)
        message = ' '.join(str(m) for m in r.context['messages'])
        self.assertIn('"Used" is used by 1 exam(s) (Midterm)', message)
        self.assertIn('Hide it instead', message)

    def test_a_set_students_answered_is_never_deleted_and_results_survive(self):
        qset = make_set(self.teacher, 'Taken', marks=(1, 1))
        exam = make_exam(self.teacher, 'Unit test', qset.questions.all())
        attempt = ExamAttempt.objects.create(exam=exam, user=self.student, consented_at=timezone.now())
        question = qset.questions.first()
        ExamAnswer.objects.create(attempt=attempt, question=question, choice=question.choices.get(is_correct=True))
        self.delete(qset)
        self.assertTrue(QuestionSet.objects.filter(pk=qset.pk).exists())
        self.assertEqual(ExamAnswer.objects.count(), 1)
        self.assertEqual(exam.questions.count(), 2)

    def test_two_exams_with_the_same_title_are_counted_separately(self):
        qset = make_set(self.teacher, 'Used', marks=(1,))
        make_exam(self.teacher, 'Quiz', qset.questions.all())
        make_exam(self.teacher, 'Quiz', qset.questions.all())
        message = ' '.join(str(m) for m in self.delete(qset).context['messages'])
        self.assertIn('used by 2 exam(s) (Quiz, Quiz)', message)

    def test_a_long_list_of_exams_is_shortened_in_the_message(self):
        qset = make_set(self.teacher, 'Used', marks=(1,))
        for i in range(7):
            make_exam(self.teacher, f'Exam {i}', qset.questions.all())
        message = ' '.join(str(m) for m in self.delete(qset).context['messages'])
        self.assertIn('used by 7 exam(s)', message)
        self.assertIn('and 2 more', message)

    def test_a_hidden_unused_set_can_be_deleted(self):
        qset = make_set(self.teacher, 'Hidden one')
        self.client.post(set_url(qset), {'action': 'hide'})
        self.delete(qset)
        self.assertFalse(QuestionSet.objects.filter(pk=qset.pk).exists())

    def test_only_the_owner_can_act_on_a_set(self):
        theirs = make_set(self.other, 'Theirs')
        for action in ('delete', 'hide'):
            self.assertEqual(self.client.post(set_url(theirs), {'action': action}).status_code, 404)
        theirs.refresh_from_db()
        self.assertFalse(theirs.hidden)
        self.assertEqual(theirs.questions.count(), 3)

    def test_get_is_refused_and_students_and_visitors_cannot_delete(self):
        mine = make_set(self.teacher, 'Mine')
        self.assertEqual(self.client.get(set_url(mine)).status_code, 405)
        self.client.login(username='ad3919', password=PASSWORD)
        self.assertRedirects(self.client.post(set_url(mine), {'action': 'delete'}), reverse('home'))
        self.client.logout()
        self.assertEqual(self.client.post(set_url(mine), {'action': 'delete'}).status_code, 302)  # to the login page
        self.assertEqual(mine.questions.count(), 3)

    def test_an_unknown_action_changes_nothing(self):
        mine = make_set(self.teacher, 'Mine')
        r = self.client.post(set_url(mine), {'action': 'explode'}, follow=True)
        self.assertIn('Unknown action.', [str(m) for m in r.context['messages']])
        mine.refresh_from_db()
        self.assertFalse(mine.hidden)
        self.assertEqual(mine.questions.count(), 3)


class HideSetTests(TeacherBase):
    def picker_names(self):
        return [group['name'] for group in ExamForm(owner=self.teacher).question_sets()]

    def test_a_hidden_set_leaves_the_picker_and_comes_back(self):
        make_set(self.teacher, 'Keep')
        gone = make_set(self.teacher, 'Gone')
        self.client.post(set_url(gone), {'action': 'hide'})
        gone.refresh_from_db()
        self.assertTrue(gone.hidden)
        self.assertEqual(self.picker_names(), ['Keep'])
        r = self.client.get(reverse('question_bank'))
        self.assertEqual([s.name for s in r.context['sets']], ['Keep'])
        self.assertEqual([s.name for s in r.context['hidden_sets']], ['Gone'])
        self.assertEqual(r.context['hidden_sets'][0].question_count, 3)
        self.client.post(set_url(gone), {'action': 'unhide'})
        self.assertEqual(self.picker_names(), ['Gone', 'Keep'])

    def test_a_hidden_sets_questions_cannot_be_posted_into_a_new_exam(self):
        gone = make_set(self.teacher, 'Gone')
        self.client.post(set_url(gone), {'action': 'hide'})
        r = self.client.post(reverse('exam_new'), {
            'title': 't', 'mode': 'open', 'seat_limit': 5, 'allowed_text': '',
            'questions': list(gone.questions.values_list('id', flat=True))})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Exam.objects.count(), 0)

    def test_hiding_leaves_exams_that_already_use_the_set_alone_and_it_still_cannot_be_deleted(self):
        qset = make_set(self.teacher, 'Used', marks=(1, 2))
        exam = make_exam(self.teacher, 'Midterm', qset.questions.all())
        self.client.post(set_url(qset), {'action': 'hide'})
        self.assertEqual(exam.questions.count(), 2)
        self.assertEqual(self.client.get(reverse('exam_detail', args=[exam.pk])).status_code, 200)
        r = self.client.get(reverse('question_bank'))
        self.assertEqual(r.context['hidden_sets'][0].used_by, ['Midterm'])
        self.assertNotContains(r, 'Delete “Used”')
        self.client.post(set_url(qset), {'action': 'delete'})
        self.assertTrue(QuestionSet.objects.filter(pk=qset.pk).exists())

    def test_create_exam_page_explains_when_every_set_is_hidden(self):
        qset = make_set(self.teacher, 'Only one')
        self.client.post(set_url(qset), {'action': 'hide'})
        self.assertContains(self.client.get(reverse('exam_new')), 'no questions to pick from')

    def test_questions_outside_any_set_are_still_offered(self):
        loose = Question.objects.create(text='loose', owner=self.teacher)  # the exclude must not drop NULL sets
        hidden = make_set(self.teacher, 'Hidden')
        self.client.post(set_url(hidden), {'action': 'hide'})
        offered = ExamForm(owner=self.teacher).fields['questions'].queryset
        self.assertEqual(list(offered), [loose])


class PickerTests(TeacherBase):
    def test_sets_come_newest_first_with_numbers_and_marks_sections(self):
        make_set(self.teacher, 'Old', marks=(1, 2, 1))
        make_set(self.teacher, 'New', marks=(3, 1))
        Question.objects.create(text='loose', owner=self.teacher)
        groups = ExamForm(owner=self.teacher).question_sets()
        self.assertEqual([g['name'] for g in groups], ['New', 'Old', 'Other questions (not in a set)'])
        new, old, other = groups
        self.assertEqual((new['count'], new['marks']), (2, 4))
        numbers = lambda group: [(marks, [n for n, _ in items]) for marks, items in group['sections']]
        self.assertEqual(numbers(old), [(1, [1, 3]), (2, [2])])  # a number is the place in the set, not in the section
        self.assertEqual(numbers(new), [(1, [2]), (3, [1])])

    def test_picker_numbers_match_the_numbered_list_on_the_bank_page(self):
        make_set(self.teacher, 'Old', marks=(1, 2, 1, 3))
        bank = self.client.get(reverse('question_bank')).context['sets'][0]
        (group,) = ExamForm(owner=self.teacher).question_sets()
        for _, items in group['sections']:
            for number, box in items:
                self.assertEqual(box.choice_label, bank.question_list[number - 1].text[:75])

    def test_page_has_the_counter_select_buttons_and_opens_only_the_newest_set(self):
        make_set(self.teacher, 'Old', marks=(1,))
        make_set(self.teacher, 'New', marks=(1, 2))
        r = self.client.get(reverse('exam_new'))
        for text in ('id="pick-count"', 'id="pick-marks"', 'select whole set / none', 'select all / none',
                     'data-marks="1"', 'data-marks="2"', '1-mark questions (1)', '2-mark questions (1)'):
            self.assertContains(r, text)
        html = r.content.decode()
        self.assertEqual(len(re.findall(r'<details class="pick-set"', html)), 2)
        self.assertEqual(len(re.findall(r'<details class="pick-set"[^>]*\sopen>', html)), 1)

    def test_an_exam_can_mix_questions_from_several_sets(self):
        a = make_set(self.teacher, 'A', marks=(1, 1))
        b = make_set(self.teacher, 'B', marks=(2,))
        ids = [a.questions.first().id, b.questions.first().id]
        r = self.client.post(reverse('exam_new'), {'title': 'Mix', 'mode': 'open', 'seat_limit': 5,
                                                   'questions': ids, 'allowed_text': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(set(Exam.objects.get().questions.values_list('id', flat=True)), set(ids))

    def test_after_a_mistake_the_set_with_ticked_boxes_stays_open(self):
        older = make_set(self.teacher, 'Older', marks=(1,))
        make_set(self.teacher, 'Newer', marks=(1,))
        r = self.client.post(reverse('exam_new'), {'title': '', 'mode': 'open', 'seat_limit': 5, 'allowed_text': '',
                                                   'questions': [older.questions.get().id]})
        self.assertEqual(r.status_code, 200)  # title missing: the form comes back
        picked = {g['name']: g['picked'] for g in r.context['form'].question_sets()}
        self.assertEqual(picked, {'Newer': False, 'Older': True})

    def test_another_teachers_set_cannot_be_used(self):
        theirs = make_set(self.other, 'Theirs')
        self.client.post(reverse('exam_new'), {'title': 't', 'mode': 'open', 'seat_limit': 5, 'allowed_text': '',
                                               'questions': [theirs.questions.first().id]})
        self.assertEqual(Exam.objects.count(), 0)


class EarlierUploadsMigrationTests(TestCase):
    def run_migration(self):
        module = importlib.import_module('quiz.migrations.0014_earlier_uploads_set')
        module.group_old_questions(apps, None)

    def test_old_questions_move_into_one_set_per_teacher(self):
        a = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)
        b = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        c = User.objects.create_user('nobody', 'nobody@srmist.edu.in', PASSWORD)
        for i in range(2):
            Question.objects.create(text=f'a{i}', owner=a)
        Question.objects.create(text='b loose', owner=b)
        kept = make_set(b, 'Kept', marks=(1,))
        quiz_question = Question.objects.create(text='old quiz', category=Category.objects.create(name='Python'))

        self.run_migration()

        self.assertEqual(a.question_sets.get().name, 'Earlier uploads')
        self.assertEqual(a.question_sets.get().questions.count(), 2)
        self.assertEqual(sorted(b.question_sets.values_list('name', flat=True)), ['Earlier uploads', 'Kept'])
        self.assertEqual(b.question_sets.get(name='Earlier uploads').questions.get().text, 'b loose')
        self.assertEqual(kept.questions.count(), 1)  # a question already in a set stays where it is
        quiz_question.refresh_from_db()
        self.assertIsNone(quiz_question.question_set)  # the old per-category quiz has no teacher and no set
        self.assertFalse(c.question_sets.exists())

        self.run_migration()  # running it again changes nothing
        self.assertEqual(QuestionSet.objects.count(), 3)
