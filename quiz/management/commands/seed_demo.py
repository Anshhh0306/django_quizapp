"""Demo accounts, questions and exams, for trying the site out and for the test rounds (many students at once, cheaters,
attackers). Every demo account has a password that whoever runs this knows, so the command is built to be unable to run
anywhere real: the database must be on this computer, no real email may be switched on, and the database must hold no
accounts of its own (use a separate, empty database for demo data)."""
import secrets
from base64 import b32encode

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from quiz.exams import create_questions
from quiz.models import Exam, ExamAllowed, Question, QuestionSet
from quiz.roles import TEACHERS_GROUP

LOCAL_HOSTS = {'', 'localhost', '127.0.0.1', '::1'}  # '' = this computer's own socket
HARMLESS_MAIL = {f'django.core.mail.backends.{name}.EmailBackend' for name in ('console', 'dummy', 'locmem', 'filebased')}

ADMIN, PENDING = 'demo.admin', 'demo.pending'
TEACHERS = ['demo.teacher1', 'demo.teacher2']
STUDENTS = [f'zz{n:04d}' for n in range(1, 51)]  # "zz" so nobody takes them for a real register number
LISTED = 40  # the scheduled exam's class list is the first 40 students; the other 10 are turned away at the door
DEMO_USERNAMES = {ADMIN, PENDING, *TEACHERS, *STUDENTS}

PYTHON = [  # (question, right answer, three wrong ones, marks)
    ('What does len([1, 2, 3]) return?', '3', ['2', '4', '1'], 1),
    ('Which keyword defines a function?', 'def', ['fun', 'function', 'define'], 1),
    ('What is the type of 3.14?', 'float', ['int', 'str', 'decimal'], 1),
    ('Which of these can be changed after it is made?', 'list', ['tuple', 'str', 'int'], 1),
    ('What does 7 // 2 give?', '3', ['3.5', '4', '2'], 1),
    ('What does "ab" * 3 give?', 'ababab', ['ab3', 'aaabbb', 'an error'], 1),
    ('Which symbol starts a comment?', '#', ['//', '--', '/*'], 1),
    ('What does list(range(3)) give?', '[0, 1, 2]', ['[1, 2, 3]', '[0, 1, 2, 3]', '[1, 2]'], 1),
    ('Which method adds an item to the end of a list?', 'append', ['add', 'push', 'insert_last'], 1),
    ('What does bool([]) give?', 'False', ['True', 'None', 'an error'], 1),
    ('What does "hello".upper() give?', 'HELLO', ['Hello', 'hello', 'hELLO'], 1),
    ('Which keyword handles an exception?', 'except', ['catch', 'handle', 'rescue'], 2),
    ('What does the "in" operator test?', 'membership', ['identity', 'equality', 'ordering'], 2),
    ('What does print(type(None)) show?', "<class 'NoneType'>", ["<class 'null'>", "<class 'None'>", 'None'], 2),
    ('Which of these makes an empty dictionary?', '{}', ['[]', '()', '<>'], 2),
]


def times_table(first, count, points):
    """Questions like "What is 7 x 8?" with three wrong answers close to the right one."""
    questions = []
    for n in range(first, first + count):
        a, b = n + 5, n + 2
        questions.append((f'What is {a} x {b}?', str(a * b), [str(a * b + d) for d in (-10, -1, 1)], points))
    return questions


def make_set(owner, name, questions):
    qset, created = QuestionSet.objects.get_or_create(owner=owner, name=name)
    if created:  # a set that is already there (a second run) keeps its questions
        create_questions(owner, [(text, [(right, True)] + [(wrong, False) for wrong in wrongs], points)
                                 for text, right, wrongs, points in questions], qset)
    return qset


def make_exam(owner, title, mode, minutes, seats, sets, listed=()):
    exam, created = Exam.objects.get_or_create(
        owner=owner, title=title, defaults={'mode': mode, 'duration_minutes': minutes, 'seat_limit': seats})
    if created:  # left in draft, as a teacher leaves a new exam: opening it is the first thing to try
        exam.questions.set(Question.objects.filter(question_set__in=sets))
        ExamAllowed.objects.bulk_create(ExamAllowed(exam=exam, email=f'{name}@srmist.edu.in') for name in listed)
    return exam


class Command(BaseCommand):
    help = ('Makes demo accounts, questions and exams in a database on this computer that holds nothing else. '
            'With --code USERNAME it prints the current sign-in code of a demo teacher or admin instead.')

    def add_arguments(self, parser):
        parser.add_argument('--password', help='the password every demo account gets (default: a random one, shown at the end)')
        parser.add_argument('--code', metavar='USERNAME', help='print this demo teacher or admin\'s current sign-in code and do nothing else')

    def handle(self, *args, password=None, code=None, **options):
        host = connection.settings_dict.get('HOST') or ''
        if host not in LOCAL_HOSTS:
            raise CommandError(f'Refusing to run: the database is on {host}, not on this computer. These accounts have a password '
                               'everyone knows, so they must never exist on a real server.')
        if code:
            self.stdout.write(self.sign_in_code(code))
            return
        if settings.EMAIL_BACKEND not in HARMLESS_MAIL:
            raise CommandError('Refusing to run while real email is switched on: the demo accounts have made-up addresses on the college '
                               'domain, and the site would send them mail (lock alerts, new-browser notices). Set the environment variable '
                               'EMAIL_BACKEND to django.core.mail.backends.dummy.EmailBackend (for this window only) and try again.')
        others = User.objects.exclude(username__in=DEMO_USERNAMES).count()
        if others:
            raise CommandError(f'Refusing to run: this database already has {others} account(s) that are not demo accounts. '
                               'Use a separate, empty database for demo data (see the README).')
        self.seed(password or secrets.token_urlsafe(9))

    def sign_in_code(self, username):
        device = TOTPDevice.objects.filter(user__username=username, confirmed=True).first() if username in DEMO_USERNAMES else None
        if device is None:
            raise CommandError(f'{username!r} is not a demo teacher or admin with an authenticator.')
        # Start the device afresh, as if its phone had just been set up: a code the site has already accepted (or the wait
        # after wrong codes) would otherwise make the code printed here fail.
        TOTPDevice.objects.filter(pk=device.pk).update(last_t=-1, drift=0, throttling_failure_count=0, throttling_failure_timestamp=None)
        return f'{TOTP(device.bin_key, device.step, device.t0, device.digits).token():0{device.digits}d}'

    def seed(self, password):
        hashed = make_password(password)  # one hash for everyone: 54 slow hashes would take half a minute
        with transaction.atomic():
            users = {name: User.objects.update_or_create(
                username=name, defaults={'email': f'{name}@srmist.edu.in', 'password': hashed, 'is_active': True,
                                         'is_staff': name == ADMIN, 'is_superuser': name == ADMIN})[0]
                     for name in sorted(DEMO_USERNAMES)}
            # exactly the two teachers: a second run puts demo.pending (approved by someone testing the approval) back to waiting
            Group.objects.get_or_create(name=TEACHERS_GROUP)[0].user_set.set([users[name] for name in TEACHERS])
            keys = {}
            for name in (ADMIN, *TEACHERS):  # the roles that must use an authenticator
                device = TOTPDevice.objects.update_or_create(
                    user=users[name], name='authenticator',
                    defaults={'key': random_hex(), 'confirmed': True, 'last_t': -1, 'drift': 0,
                              'throttling_failure_count': 0, 'throttling_failure_timestamp': None})[0]
                keys[name] = b32encode(device.bin_key).decode()
            first, second = users[TEACHERS[0]], users[TEACHERS[1]]
            python = make_set(first, 'Demo: Python basics', PYTHON)
            maths = make_set(first, 'Demo: Quick maths', times_table(1, 10, 2))
            tables = make_set(second, 'Demo: Times tables', times_table(11, 5, 1))
            exams = [
                make_exam(first, 'Demo test (scheduled)', Exam.SCHEDULED, 30, LISTED, [python, maths], STUDENTS[:LISTED]),
                make_exam(first, 'Demo practice (open)', Exam.OPEN, None, len(STUDENTS), [python]),
                make_exam(second, 'Demo quick quiz (open)', Exam.OPEN, None, len(STUDENTS), [tables]),
            ]
        out = self.stdout.write
        out(self.style.SUCCESS('Demo data is ready.'))
        out(f'\nEvery demo account has this password: {password}\n')
        out(f'  {ADMIN:<14} superadmin   authenticator key {keys[ADMIN]}')
        for name in TEACHERS:
            out(f'  {name:<14} teacher       authenticator key {keys[name]}')
        out(f'  {PENDING:<14} a teacher waiting for approval')
        out(f'  {STUDENTS[0]} ... {STUDENTS[-1]}  students; the first {LISTED} are on the scheduled exam\'s class list, the other '
            f'{len(STUDENTS) - LISTED} are not')
        out('\nExam links (put the site address in front):')
        for exam in exams:
            out(f'  {reverse("exam_entry", args=[exam.token])}   {exam.title}')
        out(f'\nThe sign-in code for a staff account (the authenticator step), whenever you need one:\n'
            f'  python manage.py seed_demo --code {TEACHERS[0]}')
