import io
import re
import zipfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from quiz.exam_device import COOKIE
from quiz.exams import QUESTION_ROWS, parse_allowed, read_student_list, read_table
from quiz.models import Exam, ExamAllowed, Question
from quiz.test_exam_device import DESKTOP, FIREFOX, DeviceBase
from quiz.test_exam_take import PASSWORD, TakeBase
from quiz.test_exams import TeacherBase, xlsx
from quiz.test_question_sets import make_set, set_url


class OptionOrderTests(TeacherBase):
    def test_option_ids_do_not_follow_the_files_a_to_d_order(self):
        rows = ['question,option_a,option_b,option_c,option_d,correct,points']
        rows += [f'Q{i}?,right{i},b{i},c{i},d{i},A,1' for i in range(40)]
        self.client.post(reverse('question_bank'), {'file': SimpleUploadedFile('many.csv', '\n'.join(rows).encode())})
        ranks = []
        for question in Question.objects.filter(owner=self.teacher):
            n = question.text[1:-1]
            self.assertEqual({c.text for c in question.choices.all()}, {f'right{n}', f'b{n}', f'c{n}', f'd{n}'})
            right = question.choices.get(is_correct=True)
            self.assertEqual(right.text, f'right{n}')  # shuffling must never move the tick
            ranks.append(sorted(question.choices.values_list('id', flat=True)).index(right.id))
        self.assertEqual(len(ranks), 40)
        self.assertGreater(len(set(ranks)), 1)  # option A always having the lowest id would mean the file order leaked


class ReconnectCountTests(DeviceBase):
    def test_the_same_browser_coming_back_through_the_link_is_a_reconnect(self):
        self.login(self.s)
        self.client.get(self.url('exam_entry'), HTTP_USER_AGENT=DESKTOP)
        self.assertEqual(self.attempt0().rejoins, 1)

    def test_another_browser_is_not_a_reconnect_the_device_lock_handles_it(self):
        r = self.b.get(self.url('exam_entry'), HTTP_USER_AGENT=FIREFOX)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.attempt0().rejoins, 0)
        self.b_take()  # and the lock turns it away
        self.assertEqual(self.attempt0().intrusions, 1)

    def test_a_seat_with_no_device_yet_counts_the_first_return(self):
        s = self.students[1]  # joined the lobby but never opened the exam
        self.login(s)
        self.client.get(self.url('exam_entry'))
        self.assertEqual(self.attempt(s).rejoins, 1)


class DeviceCodeTests(DeviceBase):
    def test_codes_match_between_the_student_screens_and_the_teachers_list(self):
        code_a = self.attempt0().device_tag
        self.login(self.s)
        self.assertContains(self.client.get(self.url('exam_take'), HTTP_USER_AGENT=DESKTOP),
                            f'Device code: <strong>{code_a}</strong>')
        self.freeze()  # the second browser opens after the first went quiet
        code_b = self.attempt0().challenger_tag
        self.assertEqual(len(code_b), 4)
        self.assertNotEqual(code_a, code_b)
        self.assertEqual(code_b, self.b.cookies[COOKIE].value[:4])
        self.assertContains(self.b_take(), f'Device code: <strong>{code_b}</strong>')
        self.login(self.teacher)
        r = self.client.get(reverse('exam_controls', args=[self.exam.pk]))
        self.assertContains(r, f'Original [{code_a}]')
        self.assertContains(r, f'New [{code_b}]')
        self.assertContains(r, 'last active')


class ClassListCapTests(TeacherBase):
    def test_a_typed_list_over_the_cap_is_refused(self):
        with mock.patch('quiz.exams.MAX_STUDENTS', 3):
            self.assertEqual(len(parse_allowed('ab1001 ab1002 ab1003')[0]), 3)
            with self.assertRaisesRegex(ValueError, 'at most 3'):
                parse_allowed('ab1001 ab1002 ab1003 ab1004')

    def test_a_file_over_the_cap_is_refused_not_silently_cut_short(self):
        with mock.patch('quiz.exams.MAX_STUDENTS', 3):
            read_student_list(b'register_number\nab1001\nab1002\nab1003\n')  # a header and three students: fine
            read_student_list(b'ab1001\nab1002\nab1003\n')
            with self.assertRaisesRegex(ValueError, 'at most 3'):
                read_student_list(b'register_number\nab1001\nab1002\nab1003\nab1004\n')
            with self.assertRaises(ValueError):
                read_student_list(b'ab1001\nab1002\nab1003\nab1004\nab1005\nab1006\n')

    def test_the_create_exam_form_gives_one_clear_error(self):
        self._upload()
        ids = list(self.teacher.question_bank.values_list('id', flat=True))
        with mock.patch('quiz.exams.MAX_STUDENTS', 3):
            r = self.client.post(reverse('exam_new'), {'title': 't', 'mode': 'open', 'questions': ids,
                                                       'allowed_text': 'ab1001 ab1002 ab1003 ab1004'})
        self.assertEqual(Exam.objects.count(), 0)
        self.assertEqual(list(r.context['form'].errors), ['allowed_text'])  # and no "enter a seat limit" on top
        self.assertContains(r, 'at most 3')

    def test_adding_too_many_students_later_adds_nobody(self):
        self._make_exam(allowed_text='AD3919')
        exam = Exam.objects.get()
        with mock.patch('quiz.exams.MAX_STUDENTS', 3):
            r = self.client.post(reverse('exam_detail', args=[exam.pk]),
                                 {'action': 'allow', 'students': 'ab1001 ab1002 ab1003 ab1004'}, follow=True)
        self.assertEqual(exam.allowed.count(), 1)
        self.assertIn('at most 3', ' '.join(str(m) for m in r.context['messages']))


class TeacherExamPageTests(TakeBase):
    def setUp(self):
        super().setUp()
        self.page = reverse('exam_detail', args=[self.exam.pk])

    def test_end_button_goes_away_once_the_clock_has_ended(self):
        self.login(self.teacher)
        self.run_now()
        self.assertContains(self.client.get(self.page), 'End exam now')
        now = timezone.now()  # the clock ran out; the stored status still says "running"
        Exam.objects.filter(pk=self.exam.pk).update(starts_at=now - timedelta(minutes=31), ends_at=now - timedelta(minutes=1))
        r = self.client.get(self.page)
        self.assertEqual(r.context['phase'], 'ended')
        self.assertNotContains(r, 'End exam now')

    def test_the_exam_link_has_a_copy_button(self):
        self.login(self.teacher)
        r = self.client.get(self.page)
        self.assertContains(r, 'id="copy-link"')
        self.assertContains(r, 'id="exam-link"')

    def test_not_on_the_list_is_shown_in_plain_words(self):
        ExamAllowed.objects.create(exam=self.exam, email=self.students[0].email)
        stranger = User.objects.create_user('ab9999', 'ab9999@srmist.edu.in', PASSWORD)
        self.login(stranger)
        self.client.get(self.url('exam_entry'))
        self.login(self.teacher)
        r = self.client.get(reverse('exam_live', args=[self.exam.pk]))
        self.assertContains(r, 'ab9999: not on the class list')
        self.assertNotContains(r, 'not_listed')

    def test_full_is_shown_in_plain_words(self):
        Exam.objects.filter(pk=self.exam.pk).update(seat_limit=3)  # all three seats are taken
        stranger = User.objects.create_user('ab9998', 'ab9998@srmist.edu.in', PASSWORD)
        self.login(stranger)
        self.client.get(self.url('exam_entry'))
        self.login(self.teacher)
        r = self.client.get(reverse('exam_live', args=[self.exam.pk]))
        self.assertContains(r, 'ab9998: no seats left')


class StudentPageTests(TakeBase):
    def home(self, student):
        self.login(student)
        return self.client.get(reverse('home'))

    def newcomer(self):
        return User.objects.create_user('ab5555', 'ab5555@srmist.edu.in', PASSWORD)

    def test_the_student_home_has_no_leftover_old_quiz_text(self):
        r = self.home(self.students[0])
        self.assertContains(r, 'My exams')
        for text in ('Available Quizzes', 'Choose of', 'No quiz categories'):
            self.assertNotContains(r, text)

    def test_a_student_with_no_exams_is_told_what_to_do(self):
        self.assertContains(self.home(self.newcomer()), 'You have no exams yet')

    def test_view_result_appears_only_once_there_is_a_result(self):
        self.run_now()
        self.answer_all(self.students[0], 3)
        self.client.post(self.url('exam_submit'))
        self.take(self.students[1])  # still working, so nobody sees a score yet
        r = self.home(self.students[0])
        self.assertContains(r, 'Your score appears here')
        self.assertNotContains(r, 'View result')
        self.teacher_post('end')
        self.assertContains(self.home(self.students[0]), 'View result')

    def test_timer_turns_red_in_the_last_tenth_but_never_for_more_than_five_minutes(self):
        self.run_now()
        for minutes, expected in ((3, 18), (30, 180), (120, 300)):
            Exam.objects.filter(pk=self.exam.pk).update(duration_minutes=minutes)
            self.assertEqual(self.payload(self.students[0])['low_seconds'], expected)

    def test_consent_page_only_promises_what_exists(self):
        stranger = self.newcomer()
        self.login(stranger)
        r = self.client.get(self.url('exam_consent'))
        self.assertContains(r, 'when you reconnect')


class BankLayoutTests(TeacherBase):
    def test_hide_and_delete_buttons_are_visible_without_opening_the_set(self):
        make_set(self.teacher, 'Mine')
        html = self.client.get(reverse('question_bank')).content.decode()
        inside = re.search(r'<details class="bank-set".*?</details>', html, re.S).group(0)
        self.assertNotIn('value="hide"', inside)
        self.assertIn('value="hide"', html)
        self.assertIn('value="delete"', html)

    def test_page_says_all_sets_are_hidden_not_that_there_are_none(self):
        qset = make_set(self.teacher, 'Only one')
        self.client.post(set_url(qset), {'action': 'hide'})
        r = self.client.get(reverse('question_bank'))
        self.assertContains(r, 'All your sets are hidden')
        self.assertNotContains(r, 'No sets yet')

    def test_page_explains_the_option_order(self):
        self.assertContains(self.client.get(reverse('question_bank')), 'random order')


class XlsxEntityTests(TeacherBase):
    def test_xml_entities_inside_an_excel_file_are_refused(self):
        try:
            import defusedxml  # noqa: F401
        except ImportError:
            self.fail('defusedxml is not installed. Run: pip install -r requirements.txt')
        source = zipfile.ZipFile(io.BytesIO(xlsx(QUESTION_ROWS)))
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == 'xl/worksheets/sheet1.xml':  # declare an entity and use it, as an entity-expansion attack does
                    text, declaration = data.decode(), ''
                    if text.startswith('<?xml'):
                        declaration, text = text.split('?>', 1)
                        declaration += '?>'
                    data = (declaration + '<!DOCTYPE worksheet [<!ENTITY boom "boom">]>'
                            + text.replace('<t>question</t>', '<t>&boom;</t>', 1)).encode()
                target.writestr(item, data)
        with self.assertRaisesRegex(ValueError, 'Could not read the Excel file'):
            read_table(out.getvalue(), 'bomb.xlsx')
