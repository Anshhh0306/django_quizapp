from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.exceptions import ValidationError
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
    """Accepts AD3919, ad3919 or ad3919@srmist.edu.in."""

    def clean_username(self):
        name = self.cleaned_data['username'].strip().split('@')[0]
        return User.objects.filter(username__iexact=name).values_list('username', flat=True).first() or name
