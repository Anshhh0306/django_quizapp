import io

from django.contrib.auth.models import Group, User
from openpyxl import Workbook
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from quiz.exams import parse_allowed, parse_questions, read_student_list, template_bytes, QUESTION_ROWS
from quiz.models import Choice, Exam, ExamAllowed, Question

PASSWORD = 'TestPassword123!'
GOOD_CSV = (
    'question,option_a,option_b,option_c,option_d,correct,points\n'
    'What does len("abc") return?,2,3,4,,B,1\n'
    'Keyword for a function?,func,def,function,lambda,b,2\n'
)


class ParserTests(TestCase):
    def test_allowed_normalises_case_and_domain(self):
        emails, bad = parse_allowed('AD3919, ab1234@SRMIST.EDU.IN\nad3919;;  xx')
        self.assertEqual(emails, ['ad3919@srmist.edu.in', 'ab1234@srmist.edu.in'])  # deduplicated
        self.assertEqual(bad, ['xx'])

    def test_allowed_rejects_other_domains(self):
        self.assertEqual(parse_allowed('ad3919@gmail.com')[1], ['ad3919@gmail.com'])

    def test_good_csv(self):
        rows, errors = parse_questions(GOOD_CSV.encode())
        self.assertEqual(errors, [])
        self.assertEqual([len(r[1]) for r in rows], [3, 4])  # blank option dropped
        self.assertEqual([[ok for _, ok in r[1]].index(True) for r in rows], [1, 1])
        self.assertEqual([r[2] for r in rows], [1, 2])

    def test_bad_csv_reports_rows(self):
        bad = ('question,option_a,option_b,correct\n'
               ',a,b,A\n'            # empty question
               'q,a,,A\n'            # only one option
               'q,a,b,C\n'           # correct points at a missing option
               'q,a,b,B\n')          # ok
        rows, errors = parse_questions(bad.encode())
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errors), 3)
        self.assertTrue(errors[0].startswith('Row 2'))

    def test_missing_columns_and_bad_encoding(self):
        self.assertIn('Missing column', parse_questions(b'question,correct\nq,A\n')[1][0])
        self.assertIn('UTF-8', parse_questions(b'\xff\xfe\x00')[1][0])


class TeacherBase(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('shantini', 'shantini@srmist.edu.in', PASSWORD)
        self.teacher.groups.add(Group.objects.get(name='Teachers'))
        self.other = User.objects.create_user('meena', 'meena@srmist.edu.in', PASSWORD)
        self.other.groups.add(Group.objects.get(name='Teachers'))
        self.student = User.objects.create_user('ad3919', 'ad3919@srmist.edu.in', PASSWORD)
        self.pending = User.objects.create_user('newstaff', 'newstaff@srmist.edu.in', PASSWORD)
        self.client.login(username='shantini', password=PASSWORD)

    def _upload(self, csv=GOOD_CSV):
        return self.client.post(reverse('question_bank'), {
            'file': SimpleUploadedFile('q.csv', csv.encode(), content_type='text/csv')})

    def _make_exam(self, **over):
        self._upload()
        data = {'title': 'Unit 1', 'mode': 'scheduled', 'duration_minutes': 30, 'seat_limit': 60,
                'questions': list(self.teacher.question_bank.values_list('id', flat=True)),
                'allowed_text': ''}
        data.update(over)
        return self.client.post(reverse('exam_new'), data)

class TeacherToolsTests(TeacherBase):
    def test_only_approved_teachers_get_in(self):
        for name in ['ad3919', 'newstaff']:
            self.client.login(username=name, password=PASSWORD)
            for url in ['teach_home', 'question_bank', 'exam_new']:
                self.assertRedirects(self.client.get(reverse(url)), reverse('home'))
        self.client.logout()
        self.assertEqual(self.client.get(reverse('teach_home')).status_code, 302)

    def test_upload_creates_owned_questions_with_correct_answer(self):
        self._upload()
        self.assertEqual(self.teacher.question_bank.count(), 2)
        q = self.teacher.question_bank.get(text__startswith='What does')
        self.assertEqual(list(q.choices.filter(is_correct=True).values_list('text', flat=True)), ['3'])

    def test_bad_upload_is_all_or_nothing(self):
        r = self._upload('question,option_a,option_b,correct\nok,a,b,A\n,a,b,A\n')
        self.assertTrue(r.context['errors'])
        self.assertEqual(Question.objects.count(), 0)

    def test_create_exam_with_class_list_and_unguessable_link(self):
        r = self._make_exam(allowed_text='AD3919 ab1234')
        exam = Exam.objects.get()
        self.assertRedirects(r, reverse('exam_detail', args=[exam.pk]))
        self.assertEqual(exam.owner, self.teacher)
        self.assertEqual(exam.questions.count(), 2)
        self.assertEqual(set(exam.allowed.values_list('email', flat=True)),
                         {'ad3919@srmist.edu.in', 'ab1234@srmist.edu.in'})
        self.assertGreaterEqual(len(exam.token), 20)
        self.assertIn(exam.token, self.client.get(reverse('exam_detail', args=[exam.pk])).context['link'])

    def test_scheduled_exam_needs_duration_and_seat_limit(self):
        self._make_exam(duration_minutes='')
        self._make_exam(seat_limit=0)
        self.assertEqual(Exam.objects.count(), 0)

    def test_open_exam_drops_duration(self):
        self._make_exam(mode='open', duration_minutes=45)
        self.assertIsNone(Exam.objects.get().duration_minutes)

    def test_cannot_use_another_teachers_questions(self):
        q = Question.objects.create(text='theirs', owner=self.other)
        Choice.objects.create(question=q, text='x', is_correct=True)
        self._upload()
        self.client.post(reverse('exam_new'), {'title': 't', 'mode': 'open', 'seat_limit': 5,
                                               'questions': [q.id], 'allowed_text': ''})
        self.assertEqual(Exam.objects.count(), 0)

    def test_bad_class_list_blocks_creation(self):
        self._make_exam(allowed_text='AD3919 not-an-id')
        self.assertEqual(Exam.objects.count(), 0)

    def test_seat_limit_can_only_be_raised(self):
        self._make_exam()
        exam = Exam.objects.get()
        url = reverse('exam_detail', args=[exam.pk])
        self.client.post(url, {'action': 'seats', 'seat_limit': 40})
        exam.refresh_from_db(); self.assertEqual(exam.seat_limit, 60)
        self.client.post(url, {'action': 'seats', 'seat_limit': 75})
        exam.refresh_from_db(); self.assertEqual(exam.seat_limit, 75)

    def test_add_students_later_dedupes_and_rejects_bad_input(self):
        self._make_exam(allowed_text='AD3919')
        exam = Exam.objects.get()
        url = reverse('exam_detail', args=[exam.pk])
        self.client.post(url, {'action': 'allow', 'students': 'ad3919 ab1234'})
        self.assertEqual(ExamAllowed.objects.filter(exam=exam).count(), 2)
        self.client.post(url, {'action': 'allow', 'students': 'cd5678 bogus'})
        self.assertEqual(ExamAllowed.objects.filter(exam=exam).count(), 2)  # nothing added

    def test_teachers_only_see_their_own_exams(self):
        self._make_exam()
        exam = Exam.objects.get()
        self.client.login(username='meena', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('exam_detail', args=[exam.pk])).status_code, 404)
        self.assertNotIn(exam, self.client.get(reverse('teach_home')).context['exams'])

    def test_exam_link_resolves_only_for_real_tokens(self):
        self._make_exam()
        exam = Exam.objects.get()
        self.assertEqual(self.client.get(reverse('exam_entry', args=[exam.token])).status_code, 200)
        self.assertEqual(self.client.get(reverse('exam_entry', args=['nope'])).status_code, 404)


class TemplateAndFileTests(TeacherBase):
    def test_templates_download_and_round_trip(self):
        q = self.client.get(reverse('question_template'))
        self.assertIn('attachment', q['Content-Disposition'])
        rows, errors = parse_questions(q.content)  # BOM must be tolerated
        self.assertEqual((len(rows), errors), (2, []))  # the template itself must upload cleanly
        s = self.client.get(reverse('student_template')).content
        self.assertEqual(parse_allowed(read_student_list(s)),
                         (['ad3919@srmist.edu.in', 'ab1234@srmist.edu.in'], []))

    def test_templates_are_teacher_only(self):
        self.client.login(username='ad3919', password=PASSWORD)
        self.assertRedirects(self.client.get(reverse('question_template')), reverse('home'))

    def test_student_file_skips_header_and_uses_first_column(self):
        text = read_student_list(b'Register Number,Name\nAD3919,Asha\n\nab1234,Ravi\n')
        self.assertEqual(parse_allowed(text)[0], ['ad3919@srmist.edu.in', 'ab1234@srmist.edu.in'])

    def test_create_exam_with_uploaded_class_list(self):
        self._upload()
        self.client.post(reverse('exam_new'), {
            'title': 'T', 'mode': 'open', 'seat_limit': 5, 'allowed_text': 'cd5678',
            'questions': list(self.teacher.question_bank.values_list('id', flat=True)),
            'allowed_file': SimpleUploadedFile('s.csv', b'register_number\nAD3919\n')})
        self.assertEqual(set(Exam.objects.get().allowed.values_list('email', flat=True)),
                         {'cd5678@srmist.edu.in', 'ad3919@srmist.edu.in'})

    def test_add_students_by_file_on_detail_page(self):
        self._make_exam()
        exam = Exam.objects.get()
        self.client.post(reverse('exam_detail', args=[exam.pk]), {
            'action': 'allow', 'students_file': SimpleUploadedFile('s.csv', b'AD3919\nAB1234\n')})
        self.assertEqual(exam.allowed.count(), 2)

    def test_bad_student_file_adds_nothing(self):
        self._make_exam()
        exam = Exam.objects.get()
        self.client.post(reverse('exam_detail', args=[exam.pk]), {
            'action': 'allow', 'students_file': SimpleUploadedFile('s.csv', b'AD3919\nhello\n')})
        self.assertEqual(exam.allowed.count(), 0)


def xlsx(rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


class ExcelTests(TeacherBase):
    def test_xlsx_questions_parse_like_csv(self):
        rows, errors = parse_questions(xlsx(QUESTION_ROWS), 'q.xlsx')
        self.assertEqual((len(rows), errors), (2, []))
        self.assertEqual([r[2] for r in rows], [1, 2])  # points survive as numbers

    def test_xlsx_floats_and_blank_rows(self):
        data = xlsx([['question', 'option_a', 'option_b', 'correct', 'points'],
                     ['q1', 'a', 'b', 'A', 2.0], [None, None, None, None, None], ['q2', 1, 2, 'B', None]])
        rows, errors = parse_questions(data, 'q.xlsx')
        self.assertEqual(errors, [])
        self.assertEqual([r[2] for r in rows], [2, 1])
        self.assertEqual(rows[1][1], [('1', False), ('2', True)])  # numeric options become text

    def test_xlsx_error_row_numbers_match_excel(self):
        data = xlsx([['question', 'option_a', 'option_b', 'correct'], ['ok', 'a', 'b', 'A'], ['', 'a', 'b', 'A']])
        self.assertTrue(parse_questions(data, 'q.xlsx')[1][0].startswith('Row 3'))

    def test_old_xls_and_garbage_are_rejected_politely(self):
        self.assertIn('.xls', parse_questions(b'x', 'old.xls')[1][0])
        self.assertIn('Could not read', parse_questions(b'not a zip file', 'q.xlsx')[1][0])

    def test_student_list_from_xlsx_ignores_extra_columns(self):
        data = xlsx([['Register Number', 'Name'], ['AD3919', 'Asha'], ['ab1234', 'Ravi']])
        self.assertEqual(parse_allowed(read_student_list(data, 's.xlsx'))[0],
                         ['ad3919@srmist.edu.in', 'ab1234@srmist.edu.in'])

    def test_xlsx_templates_download_and_round_trip(self):
        q = self.client.get(reverse('question_template') + '?format=xlsx')
        self.assertIn('.xlsx', q['Content-Disposition'])
        self.assertEqual(parse_questions(q.content, 'q.xlsx')[1], [])
        s = self.client.get(reverse('student_template') + '?format=xlsx').content
        self.assertEqual(parse_allowed(read_student_list(s, 's.xlsx'))[1], [])

    def test_upload_xlsx_questions_through_the_page(self):
        r = self.client.post(reverse('question_bank'), {
            'file': SimpleUploadedFile('q.xlsx', xlsx(QUESTION_ROWS))})
        self.assertRedirects(r, reverse('question_bank'))
        self.assertEqual(self.teacher.question_bank.count(), 2)

    def test_create_exam_with_xlsx_class_list(self):
        self._upload()
        self.client.post(reverse('exam_new'), {
            'title': 'T', 'mode': 'open', 'seat_limit': 5,
            'questions': list(self.teacher.question_bank.values_list('id', flat=True)),
            'allowed_file': SimpleUploadedFile('s.xlsx', xlsx([['AD3919'], ['AB1234']]))})
        self.assertEqual(Exam.objects.get().allowed.count(), 2)
