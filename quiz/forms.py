from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data.get('email').lower()
        if not email.endswith('@srmist.edu.in'):
            raise ValidationError("Please use your SRMIST email address (@srmist.edu.in)")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("This email address is already registered.")
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
        self.fields['email'].help_text = "Use your SRMIST email address (@srmist.edu.in)"
        self.fields['password1'].help_text = "Choose a secure password with at least 8 characters"
        self.fields['username'].help_text = "Choose your preferred username"
