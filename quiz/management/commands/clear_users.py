from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Clears all users except superuser'

    def handle(self, *args, **kwargs):
        User = get_user_model()
        users_deleted = User.objects.filter(is_superuser=False).delete()
        self.stdout.write(self.style.SUCCESS('Successfully cleared non-superuser accounts'))