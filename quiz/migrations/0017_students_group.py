from django.db import migrations


def create_group(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.get_or_create(name='Students')


class Migration(migrations.Migration):
    dependencies = [
        ('quiz', '0016_remove_old_quiz'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]
    operations = [migrations.RunPython(create_group, migrations.RunPython.noop)]
