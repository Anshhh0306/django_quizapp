"""Hostile-input checks for our own app. Each test names a protection that must hold and fails if it does not.

To see whether teacher-supplied text can turn into live markup, the text used here contains a made-up tag, <zz-probe>:
if it ever reaches a page unescaped, markup could be injected there."""
import re
import threading
from urllib.parse import quote

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from quiz import urls as quiz_urls
from quiz.exam_views import claim_seat
from quiz.models import Choice, Exam, ExamAttempt, Question, QuestionSet

PASSWORD = 'Str0ng-Pass-9271!'
MARK = '<zz-probe>'
ESCAPED = '&lt;zz-probe&gt;'
JSON_ESCAPED = '\\u003Czz-probe\\u003E'


def staff(name, approved=True):
    user = User.objects.create_user(name, f'{name}@srmist.edu.in', PASSWORD)
    if approved:
        user.groups.add(Group.objects.get_or_create(name='Teachers')[0])
    return user


def student(number):
    return User.objects.create_user(f'ab{number}', f'ab{number}@srmist.edu.in', PASSWORD)


def signed_in(user, **client_options):
    client = Client(**client_options)
    client.force_login(user)
    return client


class World(TestCase):
    """Two approved teachers (the first owns everything), an unapproved staff account, a superadmin and two students."""

    def setUp(self):
        cache.clear()
        self.teacher, self.other = staff('shantini'), staff('meena')
        self.pending = staff('newstaff', approved=False)
        self.admin = User.objects.create_superuser('root', 'root@srmist.edu.in', PASSWORD)
        self.alice, self.bob = student(1000), student(1001)
        self.qset = QuestionSet.objects.create(owner=self.teacher, name=f'{MARK}set')
        self.question = Question.objects.create(text=f'{MARK}question', owner=self.teacher, question_set=self.qset)
        self.right = Choice.objects.create(question=self.question, text=f'{MARK}right', is_correct=True)
        self.wrong = Choice.objects.create(question=self.question, text=f'{MARK}wrong')
        self.exam = Exam.objects.create(owner=self.teacher, title=f'{MARK}exam', mode=Exam.OPEN, seat_limit=5)
        self.exam.questions.add(self.question)


class HostileTextTests(World):
    """Everything a teacher types is shown to students, to other staff and in the admin site: all of it must be escaped.
    (Plain assertTrue/False below, not assertIn: a failed assertIn would print the whole page.)"""

    def setUp(self):
        super().setUp()
        Exam.objects.filter(pk=self.exam.pk).update(status=Exam.RUNNING)

    def sit_the_exam(self):
        token = self.exam.token
        client = signed_in(self.alice)
        client.get(reverse('exam_entry', args=[token]))
        client.post(reverse('exam_consent', args=[token]), {'agree': 'on'})
        pages = {'lobby': client.get(reverse('exam_lobby', args=[token])),
                 'take': client.get(reverse('exam_take', args=[token]))}
        client.post(reverse('exam_answer', args=[token]), {'question': self.question.pk, 'choice': self.right.pk})
        client.post(reverse('exam_submit', args=[token]))
        pages['done'] = client.get(reverse('exam_done', args=[token]))
        pages['home'] = client.get(reverse('home'))
        return pages

    def check(self, response, where, shown):
        self.assertEqual(response.status_code, 200, where)
        html = response.content.decode()
        self.assertFalse(MARK in html, f'{where}: teacher-supplied text reached the page as live markup')
        if shown:
            self.assertTrue(ESCAPED in html or JSON_ESCAPED in html, f'{where}: the text should be on the page, escaped')

    def test_what_students_see_is_escaped(self):
        pages = self.sit_the_exam()
        for name in ('lobby', 'take', 'done', 'home'):
            self.check(pages[name], f'student {name} page', shown=True)

    def test_what_teachers_see_is_escaped(self):
        self.sit_the_exam()
        attempt = ExamAttempt.objects.get(exam=self.exam, user=self.alice)
        teacher, e = signed_in(self.teacher), self.exam.pk
        for where, url, shown in (
                ('teacher home', reverse('teach_home'), True),
                ('question bank', reverse('question_bank'), True),
                ('new exam picker', reverse('exam_new'), True),
                ('exam page', reverse('exam_detail', args=[e]), True),
                ('live panel', reverse('exam_live', args=[e]), False),
                ('controls panel', reverse('exam_controls', args=[e]), False),
                ('results', reverse('exam_results', args=[e]), False),
                ('one student result', reverse('exam_result_detail', args=[e, attempt.pk]), True)):
            self.check(teacher.get(url), where, shown)

    def test_the_admin_question_list_escapes_choice_text(self):
        response = signed_in(self.admin).get('/admin/quiz/question/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertFalse(MARK in html, 'the admin question list shows a choice as live markup')
        self.assertTrue(ESCAPED + 'right' in html, 'the choice text should be on the admin question list, escaped')

    def test_braces_in_choice_text_do_not_break_the_admin_question_list(self):
        question = Question.objects.create(text='plain', owner=self.teacher, question_set=self.qset)
        Choice.objects.create(question=question, text='{0}', is_correct=True)
        Choice.objects.create(question=question, text='{name}')
        try:
            response = signed_in(self.admin).get('/admin/quiz/question/')
        except (IndexError, KeyError) as error:
            self.fail(f'the admin question list crashed on choice text containing braces: {error!r}')
        self.assertEqual(response.status_code, 200)
        self.assertTrue('{0}' in response.content.decode())


class TeacherRouteAccessTests(World):
    def setUp(self):
        super().setUp()
        self.attempt = ExamAttempt.objects.create(exam=self.exam, user=self.alice, consented_at=timezone.now())
        e = self.exam.pk
        self.mine = [reverse('exam_detail', args=[e]), reverse('exam_live', args=[e]), reverse('exam_controls', args=[e]),
                     reverse('exam_results', args=[e]), reverse('exam_result_detail', args=[e, self.attempt.pk])]
        self.teachers_only = [reverse('teach_home'), reverse('question_bank'), reverse('question_template'),
                              reverse('student_template'), reverse('exam_new')]
        self.admin_only = [reverse('login_locks')]

    def test_nobody_gets_into_pages_that_are_not_theirs(self):
        outsiders = [('not signed in', Client()), ('a student', signed_in(self.alice)), ('unapproved staff', signed_in(self.pending))]
        for who, client in outsiders:
            for url in self.mine + self.teachers_only + self.admin_only:
                self.assertIn(client.get(url).status_code, (302, 403, 404), f'{who} got into {url}')
        rival = signed_in(self.other)  # an approved teacher, but not the owner
        for url in self.mine + self.admin_only:
            self.assertIn(rival.get(url).status_code, (302, 403, 404), f'a rival teacher got into {url}')

    def test_the_owner_and_the_admin_do_get_in(self):  # so the test above is not passing for the wrong reason
        for who, client in (('owner', signed_in(self.teacher)), ('admin', signed_in(self.admin))):
            for url in self.mine + self.teachers_only:
                self.assertEqual(client.get(url).status_code, 200, f'{who}: {url}')
        self.assertEqual(signed_in(self.admin).get(self.admin_only[0]).status_code, 200)

    def snapshot(self):
        exam = Exam.objects.get(pk=self.exam.pk)
        return exam.status, exam.seat_limit

    def test_nobody_else_can_change_an_exam(self):
        url, before = reverse('exam_detail', args=[self.exam.pk]), self.snapshot()
        for who, client in (('not signed in', Client()), ('a student', signed_in(self.alice)),
                            ('unapproved staff', signed_in(self.pending)), ('a rival teacher', signed_in(self.other))):
            for data in ({'action': 'open'}, {'action': 'seats', 'seat_limit': '50'}, {'action': 'end'}):
                client.post(url, data)
            self.assertEqual(self.snapshot(), before, f'{who} changed the exam')
        owner = signed_in(self.teacher)  # the same requests from the owner DO work
        owner.post(url, {'action': 'seats', 'seat_limit': '50'})
        owner.post(url, {'action': 'open'})
        self.assertEqual(self.snapshot(), (Exam.RUNNING, 50))

    def test_nobody_else_can_hide_or_delete_a_question_set(self):
        spare = QuestionSet.objects.create(owner=self.teacher, name='spare')
        for url, action in ((reverse('question_set_action', args=[self.qset.pk]), 'hide'),
                            (reverse('question_set_action', args=[spare.pk]), 'delete')):
            for client in (Client(), signed_in(self.alice), signed_in(self.pending), signed_in(self.other)):
                client.post(url, {'action': action})
        self.qset.refresh_from_db()
        self.assertFalse(self.qset.hidden)
        self.assertTrue(QuestionSet.objects.filter(pk=spare.pk).exists())
        signed_in(self.teacher).post(reverse('question_set_action', args=[spare.pk]), {'action': 'delete'})
        self.assertFalse(QuestionSet.objects.filter(pk=spare.pk).exists())  # the owner can

    def test_a_teacher_cannot_act_on_a_student_of_someone_elses_exam(self):
        rivals_exam = Exam.objects.create(owner=self.other, title='rival exam', mode=Exam.OPEN, seat_limit=5)
        data = {'action': 'reset_device', 'attempt': self.attempt.pk, 'minutes': '5'}
        outsider = signed_in(self.other).post(reverse('exam_detail', args=[rivals_exam.pk]), data, follow=True)
        self.assertTrue('Student not found' in outsider.content.decode())
        owner = signed_in(self.teacher).post(reverse('exam_detail', args=[self.exam.pk]), data, follow=True)
        self.assertFalse('Student not found' in owner.content.decode())


def every_route():
    """A path for every route in quiz/urls.py, with placeholders filled in (so a route added later is covered too)."""
    paths = []
    for entry in quiz_urls.urlpatterns:
        route = re.sub(r'<int:\w+>', '1', str(entry.pattern))
        paths.append('/' + re.sub(r'<(?:str:)?\w+>', 'abc', route))
    return paths


class CsrfTests(World):
    def test_every_page_refuses_a_post_that_lacks_the_csrf_token(self):
        client = signed_in(self.admin, enforce_csrf_checks=True)
        answers = {path: client.post(path, {}).status_code for path in every_route()}
        self.assertEqual({path: code for path, code in answers.items() if code != 403}, {})
        self.assertGreater(len(answers), 30)  # the walk really covered the routes


@override_settings(TWO_FACTOR_REQUIRED_ROLES={'admin', 'teacher'})
class TwoFactorGatePathTests(World):
    def test_a_password_only_session_reaches_nothing_but_the_code_pages(self):
        for user in (self.teacher, self.admin):
            TOTPDevice.objects.create(user=user, name='authenticator', confirmed=True)
        token = self.exam.token
        straight = ['/', '/profile/', '/teach/', f'/teach/exams/{self.exam.pk}/', '/teach/templates/questions.csv', '/locks/',
                    '/admin/', '/admin/auth/user/', f'/exam/{token}/', f'/exam/{token}/take/', f'/exam/{token}/answer/']
        sneaky = ['/static/../teach/', '/2fa/../teach/', '/accounts/logout/../../teach/', '/static/%2e%2e/teach/',
                  '/teach', '/TEACH/', '/teach/./']
        for user in (self.teacher, self.admin):
            client = signed_in(user)
            for path in straight + sneaky:
                self.assertNotEqual(client.get(path).status_code, 200, f'{user.username} reached {path} with only a password')
            double_slash = client.get('/x/', PATH_INFO='//teach/')  # a real server passes this through untouched
            self.assertNotEqual(double_slash.status_code, 200)


class LoginTests(World):
    def test_next_cannot_send_people_to_another_site(self):
        for target in ('https://evil.example/', '//evil.example/', 'javascript:void(0)', '/\\evil.example'):
            response = Client().post(reverse('login') + '?next=' + quote(target),
                                     {'username': 'ab1000', 'password': PASSWORD, 'next': target})
            self.assertEqual(response.status_code, 302, target)
            self.assertEqual(response['Location'], '/', f'{target} was followed')

    def test_the_lock_cannot_be_dodged_by_writing_the_name_differently(self):
        spellings = ['ab1000', 'AB1000', 'ab1000@srmist.edu.in', 'Ab1000@SRMIST.EDU.IN', 'ab1000']
        for name in spellings:
            Client().post(reverse('login'), {'username': name, 'password': 'wrong-password'})
        for name in spellings:
            response = Client().post(reverse('login'), {'username': name, 'password': PASSWORD})
            self.assertEqual(response.status_code, 200, f'{name} got in while the account was locked')


class SeatRaceTests(TransactionTestCase):
    def test_students_racing_for_the_last_seats_never_get_more_than_the_limit(self):
        teacher = staff('shantini')
        exam = Exam.objects.create(owner=teacher, title='race', mode=Exam.OPEN, seat_limit=3, status=Exam.RUNNING)
        students = [student(1000 + i) for i in range(12)]
        start, outcomes, errors = threading.Barrier(len(students)), [], []

        def claim(user):
            try:
                start.wait(timeout=30)
                outcomes.append(claim_seat(exam, user)[1] or 'seat')
            except Exception as error:  # a deadlock or any other failure must show up here
                errors.append(repr(error))
            finally:
                connection.close()

        threads = [threading.Thread(target=claim, args=(user,)) for user in students]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(outcomes), ['full'] * 9 + ['seat'] * 3)
        self.assertEqual(ExamAttempt.objects.filter(exam=exam).count(), 3)
