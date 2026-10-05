from django.db import migrations


class Migration(migrations.Migration):
    """Drops the old per-category quiz: its four tables and Question.category. Exams are untouched."""

    dependencies = [
        ('quiz', '0015_anti_cheat_strikes'),
    ]

    operations = [
        # the "one attempt per user and category" rules must go before the fields they name
        migrations.AlterUniqueTogether(
            name='useranswer',
            unique_together=None,
        ),
        migrations.AlterUniqueTogether(
            name='userquiz',
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name='question',
            name='category',
        ),
        migrations.RemoveField(
            model_name='userquiz',
            name='category',
        ),
        migrations.RemoveField(
            model_name='useranswer',
            name='question',
        ),
        migrations.RemoveField(
            model_name='useranswer',
            name='selected_choice',
        ),
        migrations.RemoveField(
            model_name='useranswer',
            name='user_quiz',
        ),
        migrations.RemoveField(
            model_name='userquiz',
            name='user',
        ),
        migrations.RemoveField(
            model_name='userstatistics',
            name='user',
        ),
        migrations.DeleteModel(
            name='Category',
        ),
        migrations.DeleteModel(
            name='UserAnswer',
        ),
        migrations.DeleteModel(
            name='UserQuiz',
        ),
        migrations.DeleteModel(
            name='UserStatistics',
        ),
    ]
