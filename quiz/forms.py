from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.exceptions import ValidationError
from .exams import parse_allowed, read_student_list
from .models import Exam, Question
from .roles import STUDENT_RE, STAFF_RE

class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if not (STUDENT_RE.match(email) or STAFF_RE.match(email)):
            raise ValidationError(
                "Use your SRMIST email: students like AD3919@srmist.edu.in, staff like name@srmist.edu.in")
        username = email.split('@')[0]
        if (User.objects.filter(email__iexact=email).exists()
                or User.objects.filter(username__iexact=username).exists()):
            raise ValidationError("This email address is already registered.")
        self.instance.username = username  # login name = the part before the @
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.is_active = False  # User won't be able to login until email is verified
        if commit:
            user.save()
        return user

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].help_text = "Students: AD3919@srmist.edu.in. Staff: name@srmist.edu.in (needs admin approval)."
        self.fields['password1'].help_text = "Choose a secure password with at least 8 characters"


class LoginForm(AuthenticationForm):
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

    def clean(self):
        data = super().clean()
        if data.get('mode') == Exam.SCHEDULED and not data.get('duration_minutes'):
            self.add_error('duration_minutes', 'Duration is required for a scheduled exam.')
        if data.get('mode') == Exam.OPEN:
            data['duration_minutes'] = None  # open exams have no timer
        text = data.get('allowed_text', '')
        if data.get('allowed_file'):
            try:
                text += '\n' + read_student_list(data['allowed_file'].read(), data['allowed_file'].name)
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
