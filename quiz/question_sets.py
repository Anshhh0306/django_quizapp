"""Question sets: every upload becomes a named set that the teacher can open, hide or delete as a whole."""
import os

from django.db import IntegrityError, transaction

from .models import Exam, QuestionSet

SET_NAME_MAX = 100
UNTITLED = 'Untitled set'


def clean_set_name(text):
    """One tidy line: control and invisible characters become spaces, runs of spaces collapse, at most 100 characters."""
    text = ''.join(ch if ch.isprintable() else ' ' for ch in text)
    return ' '.join(text.split())[:SET_NAME_MAX].strip()


def name_for_upload(typed, filename):
    """What the teacher typed, else the file name without its extension (Unit 1.xlsx -> Unit 1)."""
    return clean_set_name(typed) or clean_set_name(os.path.splitext(filename)[0]) or UNTITLED


def unique_name(owner, wanted):
    """The wanted name, or 'Name (2)', 'Name (3)'... if the teacher already has a set called that (any letter case)."""
    taken = {name.lower() for name in QuestionSet.objects.filter(owner=owner).values_list('name', flat=True)}
    if wanted.lower() not in taken:
        return wanted
    n = 2
    while True:
        suffix = f' ({n})'
        candidate = wanted[:SET_NAME_MAX - len(suffix)].rstrip() + suffix
        if candidate.lower() not in taken:
            return candidate
        n += 1


def create_set(owner, wanted):
    """A new set for this teacher. If two uploads grab the same name at the same moment, the loser takes the next free one."""
    for attempt in range(5):
        try:
            with transaction.atomic():
                return QuestionSet.objects.create(owner=owner, name=unique_name(owner, wanted))
        except IntegrityError:
            if attempt == 4:
                raise


def exams_using(qset):
    """Exams (any state, drafts included) that contain at least one question of this set."""
    return Exam.objects.filter(questions__question_set=qset).distinct().order_by('title')


def delete_set(qset):
    """Delete the set with its questions, unless an exam uses any of them: that would shrink the exam or break its
    results. Returns the titles of the exams in the way (empty = deleted)."""
    with transaction.atomic():
        titles = [title for _, title in exams_using(qset).values_list('pk', 'title')]  # pk keeps same-titled exams apart
        if not titles:
            qset.delete()
    return titles
