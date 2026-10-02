from django import forms
from django.contrib.auth.models import User
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import UNUSABLE_PASSWORD_PREFIX
from django.core.exceptions import ValidationError
from .exams import parse_allowed, read_student_list, read_upload
from .models import Exam, Question
from .ratelimit import login_blocked, login_failed, login_succeeded
from .roles import STUDENT_RE, STAFF_RE

def pending_account(email):
    """An account that registered but has not clicked its email link yet. Such an account has NO password until
    then, which is what tells it apart from one a superadmin deactivated (that one still has a password)."""
    return User.objects.filter(email__iexact=email, is_active=False,
                               password__startswith=UNUSABLE_PASSWORD_PREFIX).first()


class RegisterForm(forms.Form):
    """Only the email: the password is chosen AFTER the emailed link is clicked, so nobody can register
    someone else's address with a password of their own and wait for the owner to confirm it."""
    email = forms.EmailField(required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending = None
        self.fields['email'].help_text = "Students: AD3919@srmist.edu.in. Staff: name@srmist.edu.in (needs admin approval)."

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if not (STUDENT_RE.match(email) or STAFF_RE.match(email)):
            raise ValidationError(
                "Use your SRMIST email: students like AD3919@srmist.edu.in, staff like name@srmist.edu.in")
        self.pending = pending_account(email)  # registering again just sends the verification email again
        if not self.pending and (User.objects.filter(email__iexact=email).exists()
                                 or User.objects.filter(username__iexact=email.split('@')[0]).exists()):
            raise ValidationError("This email address is already registered. Try logging in, or reset your password.")
        return email

    def save(self):
        if self.pending:
            return self.pending
        email = self.cleaned_data['email']
        user = User(username=email.split('@')[0], email=email, is_active=False)  # login name = the part before the @
        user.set_unusable_password()
        user.save()
        return user


class LoginThrottleMixin:
    """Locks a login for 15 minutes after repeated wrong passwords (counted per account+address, and per address)."""

    def clean(self):
        username = self.cleaned_data.get('username', '')
        ip = self.request.META.get('REMOTE_ADDR') if getattr(self, 'request', None) else None
        if login_blocked(username, ip):
            raise ValidationError('Too many failed login attempts. Please wait 15 minutes and try again.', code='locked')
        try:
            cleaned = super().clean()
        except ValidationError:
            login_failed(username, ip)
            raise
        login_succeeded(username, ip)
        return cleaned


class LoginForm(LoginThrottleMixin, AuthenticationForm):
    """Log in with username or email, in any letter case (AD3919, ad3919, ad3919@srmist.edu.in)."""

    def clean_username(self):
        name = self.cleaned_data['username'].strip()
        user = (User.objects.filter(username__iexact=name).first()
                or User.objects.filter(email__iexact=name).first())
        return user.username if user else name


class ExamForm(forms.ModelForm):
    allowed_text = forms.CharField(
        label='Class list (optional)', required=False, widget=forms.Textarea(attrs={'rows': 5}),
        help_text='Register numbers or emails separated by spaces, commas or new lines. '
                  'Leave empty to let anyone with the link in (up to the seat limit).')

    allowed_file = forms.FileField(
        label='Or upload a class list (CSV or Excel)', required=False,
        help_text='One register number or email per row (first column). Added to anything typed above.')

    class Meta:
        model = Exam
        fields = ('title', 'mode', 'duration_minutes', 'seat_limit', 'questions')
        widgets = {'questions': forms.CheckboxSelectMultiple}
        labels = {'duration_minutes': 'Duration (minutes)'}

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['questions'].queryset = Question.objects.filter(owner=owner).order_by('id')
        self.fields['seat_limit'].required = False
        self.fields['seat_limit'].help_text = ('Only needed without a class list. '
                                               'With a class list, every listed student automatically has a seat.')

    def question_groups(self):
        """[(marks, [checkbox, ...])] so the picker shows 1-mark, 2-mark, ... sections instead of one long list."""
        groups = {}
        for box in self['questions']:
            groups.setdefault(box.data['value'].instance.points, []).append(box)
        return sorted(groups.items())

    def clean(self):
        data = super().clean()
        if data.get('mode') == Exam.SCHEDULED and not data.get('duration_minutes'):
            self.add_error('duration_minutes', 'Duration is required for a scheduled exam.')
        if data.get('mode') == Exam.OPEN:
            data['duration_minutes'] = None  # open exams have no timer
        if (data.get('duration_minutes') or 0) > 600:
            self.add_error('duration_minutes', 'An exam can last at most 600 minutes (10 hours).')
        if (data.get('seat_limit') or 0) > 100_000:
            self.add_error('seat_limit', 'The seat limit can be at most 100,000.')
        text = data.get('allowed_text', '')
        if data.get('allowed_file'):
            try:
                text += '\n' + read_student_list(read_upload(data['allowed_file']), data['allowed_file'].name)
            except ValueError as e:
                self.add_error('allowed_file', str(e))
        emails, bad = parse_allowed(text)
        if bad:
            self.add_error('allowed_text', f'Not valid student IDs: {", ".join(bad[:10])}')
        self.cleaned_data['allowed_emails'] = emails
        if emails:
            data['seat_limit'] = len(emails)  # class list = one seat per listed student
        elif not data.get('seat_limit'):
            self.add_error('seat_limit', 'Enter a seat limit, or add a class list.')
        return data


class AdminLoginForm(LoginThrottleMixin, AdminAuthenticationForm):
    """The same lockout on /admin/login/, which is the most valuable door to guess at."""
