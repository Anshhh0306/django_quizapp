from django.db import migrations

EARLIER_UPLOADS = 'Earlier uploads'


def group_old_questions(apps, schema_editor):
    """Questions uploaded before sets existed go into one set per teacher, so nothing is left outside a set."""
    Question = apps.get_model('quiz', 'Question')
    QuestionSet = apps.get_model('quiz', 'QuestionSet')
    owners = (Question.objects.filter(owner__isnull=False, question_set__isnull=True)
              .values_list('owner_id', flat=True).distinct())
    for owner_id in list(owners):
        qset, _ = QuestionSet.objects.get_or_create(owner_id=owner_id, name=EARLIER_UPLOADS)
        Question.objects.filter(owner_id=owner_id, question_set__isnull=True).update(question_set=qset)


class Migration(migrations.Migration):
    dependencies = [
        ('quiz', '0013_question_sets'),
    ]
    # Going back needs no work: dropping the question_set column in 0013 removes the link, and the questions stay.
    operations = [migrations.RunPython(group_old_questions, migrations.RunPython.noop)]
