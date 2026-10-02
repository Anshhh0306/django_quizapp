import io
import time
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from quiz.exams import MAX_COLUMNS, parse_questions, read_table
from quiz.exam_results import result_rows
from quiz.models import ExamAttempt, ExamEvent, Exam
from quiz.test_exam_device import DESKTOP, FIREFOX, DeviceBase, PASSWORD
from quiz.test_exams import GOOD_CSV, TeacherBase


class UploadHardeningTests(TeacherBase):
    def zip_bomb(self, unpacked_bytes):
        """A tiny .xlsx-named file that unpacks to a huge size."""
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('xl/junk.bin', b'\0' * unpacked_bytes)
        return out.getvalue()

    def test_a_file_that_unpacks_to_far_too_much_is_refused_quickly(self):
        bomb = self.zip_bomb(25_000_000)
        self.assertLess(len(bomb), 100_000)  # tiny on disk
        started = time.time()
        rows, errors = parse_questions(bomb, 'bomb.xlsx')
        self.assertEqual(rows, [])
        self.assertIn('too large once opened', errors[0])
        self.assertLess(time.time() - started, 2)

    def test_a_very_wide_row_is_cut_to_the_first_columns(self):
        book = Workbook()
        book.active.append(['question', 'option_a', 'option_b', 'correct'] + [''] * 5000)
        book.active.append(['q', 'a', 'b', 'A'] + ['x'] * 5000)
        out = io.BytesIO(); book.save(out)
        table = read_table(out.getvalue(), 'wide.xlsx')
        self.assertTrue(all(len(row) <= MAX_COLUMNS for row in table))
        rows, errors = parse_questions(out.getvalue(), 'wide.xlsx')
        self.assertEqual((len(rows), errors), (1, []))

    def test_corrupt_xlsx_still_gets_a_friendly_message(self):
        self.assertIn('Could not read', parse_questions(b'PK not really a zip', 'x.xlsx')[1][0])

    def test_an_oversized_upload_is_refused_before_it_is_read(self):
        big = SimpleUploadedFile('q.csv', b'x' * 1_000_001, content_type='text/csv')
        r = self.client.post(reverse('question_bank'), {'file': big})
        self.assertIn('too large', r.context['errors'][0])
        self.assertEqual(self.teacher.question_bank.count(), 0)

    def test_an_oversized_class_list_is_refused_everywhere(self):
        self._upload()
        exam_ids = list(self.teacher.question_bank.values_list('id', flat=True))
        big = SimpleUploadedFile('s.csv', b'AD3919\n' * 200_000, content_type='text/csv')
        r = self.client.post(reverse('exam_new'), {'title': 'T', 'mode': 'open', 'seat_limit': 5, 'questions': exam_ids,
                                                   'allowed_text': '', 'allowed_file': big})
        self.assertEqual(Exam.objects.count(), 0)
        self.assertContains(r, 'too large')

    def test_normal_uploads_still_work(self):
        self.assertRedirects(self._upload(GOOD_CSV), reverse('question_bank'))


class ExamLimitsTests(TeacherBase):
    def create(self, **over):
        self._upload()
        data = {'title': 'T', 'mode': 'scheduled', 'duration_minutes': 30, 'seat_limit': 10, 'allowed_text': '',
                'questions': list(self.teacher.question_bank.values_list('id', flat=True))}
        data.update(over)
        return self.client.post(reverse('exam_new'), data)

    def test_absurd_durations_and_seat_limits_are_rejected_not_crashed(self):
        for over in ({'duration_minutes': 5_000_000_000}, {'duration_minutes': 2 ** 63 - 1}, {'duration_minutes': 601},
                     {'seat_limit': 100_001}, {'seat_limit': 2 ** 63}):
            self.assertEqual(self.create(**over).status_code, 200, over)  # the form is shown again with an error
        self.assertEqual(Exam.objects.count(), 0)

    def test_the_limits_themselves_are_allowed(self):
        self.create(duration_minutes=600, seat_limit=100_000)
        self.assertEqual(Exam.objects.get().duration_minutes, 600)


class IntruderLogTests(DeviceBase):
    def test_forty_cookieless_requests_do_not_flood_the_log(self):
        for _ in range(40):
            Client().login(username=self.s.username, password=PASSWORD)  # warm-up no-op to keep the loop honest
            c = Client()
            c.login(username=self.s.username, password=PASSWORD)
            c.get(self.url('exam_take'), HTTP_USER_AGENT=FIREFOX)  # a fresh cookie every time = a "new device" every time
        a = self.attempt0()
        self.assertEqual(a.intrusions, 40)                                  # every attempt is still counted
        self.assertEqual(ExamEvent.objects.filter(kind='intruder').count(), 1)  # but the log shows it once
        self.assertIsNone(a.frozen_at)

    def test_a_later_attempt_after_a_minute_is_logged_again(self):
        self.b.get(self.url('exam_take'), HTTP_USER_AGENT=FIREFOX)
        ExamAttempt.objects.filter(pk=self.attempt0().pk).update(
            last_intrusion_at=self.attempt0().last_intrusion_at.replace(year=2020))
        c = Client()
        c.login(username=self.s.username, password=PASSWORD)
        c.get(self.url('exam_take'), HTTP_USER_AGENT=FIREFOX)
        self.assertEqual(ExamEvent.objects.filter(kind='intruder').count(), 2)


class CachingTests(DeviceBase):
    def test_exam_pages_are_never_cached(self):
        self.login(self.s)
        for name in ('exam_take', 'exam_ping', 'exam_status', 'exam_done', 'exam_lobby', 'exam_entry'):
            r = self.client.get(self.url(name), HTTP_USER_AGENT=DESKTOP)
            self.assertIn('no-store', r.headers.get('Cache-Control', ''), name)

    def test_answer_and_submit_responses_are_not_cached_either(self):
        self.login(self.s)
        r = self.client.post(self.url('exam_answer'), {'question': 'x', 'choice': ''}, HTTP_USER_AGENT=DESKTOP)
        self.assertIn('no-store', r.headers.get('Cache-Control', ''))


class ExportSafetyTests(DeviceBase):
    def test_spreadsheet_formulas_in_names_are_made_harmless(self):
        User.objects.filter(pk=self.s.pk).update(username='=cmd|calc', email='+evil@srmist.edu.in')
        self.login(self.teacher)
        csv_text = self.client.get(reverse('exam_results', args=[self.exam.pk]), {'format': 'csv'}).content.decode('utf-8-sig')
        self.assertIn("'=cmd|calc", csv_text)
        self.assertNotIn(',=cmd|calc', csv_text.replace("'=cmd|calc", ''))
        sheet = load_workbook(io.BytesIO(self.client.get(reverse('exam_results', args=[self.exam.pk]),
                                                         {'format': 'xlsx'}).content)).active
        cells = [c for row in sheet.iter_rows() for c in row]
        self.assertTrue(all(c.data_type != 'f' for c in cells))
