"""Makes the first superadmin from DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD, but only while no
superadmin exists. For a host without a shell (Render's free plan): the build runs it on every deploy, and once there is a superadmin it
does nothing. Take DJANGO_SUPERUSER_PASSWORD out of the host's settings after the first deploy."""
import os

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

MIN_PASSWORD = 12


class Command(BaseCommand):
    help = 'Makes the first superadmin from the DJANGO_SUPERUSER_* variables if there is none yet (safe to run on every deploy).'

    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write('A superadmin already exists: nothing to do.')
            return
        names = ('USERNAME', 'EMAIL', 'PASSWORD')
        value = {name: os.environ.get(f'DJANGO_SUPERUSER_{name}', '').strip() for name in names}
        missing = [f'DJANGO_SUPERUSER_{name}' for name in names if not value[name]]
        if missing:
            self.stdout.write(f'No superadmin yet, and {", ".join(missing)} not set: not making one.')
            return
        try:
            User.username_validator(value['USERNAME'])
        except ValidationError as error:
            raise CommandError('DJANGO_SUPERUSER_USERNAME is not a valid username: ' + ' '.join(error.messages))
        if len(value['PASSWORD']) < MIN_PASSWORD:
            raise CommandError(f'DJANGO_SUPERUSER_PASSWORD must be at least {MIN_PASSWORD} characters.')
        try:
            validate_password(value['PASSWORD'])
        except ValidationError as error:
            raise CommandError('DJANGO_SUPERUSER_PASSWORD is too weak: ' + ' '.join(error.messages))
        try:
            with transaction.atomic():  # a savepoint: a failed insert must not leave a broken transaction behind
                user = User.objects.create_superuser(value['USERNAME'], value['EMAIL'], value['PASSWORD'])
        except IntegrityError:
            raise CommandError(f'There is already an account called {value["USERNAME"]!r}, and it is not a superadmin.')
        self.stdout.write(self.style.SUCCESS(f'Made the superadmin {user.username}. Take DJANGO_SUPERUSER_PASSWORD out of the host settings now.'))
