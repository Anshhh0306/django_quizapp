from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = ('Turns off two-factor sign-in for one person who has lost both their phone and their recovery codes '
            '(the way back for a superadmin who is locked out). The person is emailed, and must set it up again.')

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, *args, username, **options):
        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            raise CommandError(f'There is no user called {username!r}.')
        for device in TOTPDevice.objects.filter(user=user):
            device.delete()  # one by one: that is what removes the recovery codes and emails the owner
        StaticDevice.objects.filter(user=user).delete()
        self.stdout.write(self.style.SUCCESS(
            f'Two-factor sign-in is now off for {user.username}. They are asked to set it up again at their next sign-in.'))
