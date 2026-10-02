from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Single-use: the token stops working once the account is activated or its password is set."""

    def _make_hash_value(self, user, timestamp):
        return f'{user.pk}{timestamp}{user.is_active}{user.password}'


email_verification_token = EmailVerificationTokenGenerator()
