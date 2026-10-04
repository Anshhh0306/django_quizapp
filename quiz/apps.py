from django.apps import AppConfig


class QuizConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quiz'

    def ready(self):
        from . import two_factor  # noqa: F401  (connects its signals: the 2FA emails and the exam log line for sign-ins)
