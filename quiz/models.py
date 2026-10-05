from django.db import models
from django.contrib.auth.models import User

class QuestionSet(models.Model):
    """One teacher upload: a named group of questions the teacher can open, hide or delete as a whole."""
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='question_sets')
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    hidden = models.BooleanField(default=False)  # still works for exams that use it, but is not offered for new ones

    class Meta:
        unique_together = ['owner', 'name']

    def __str__(self):
        return self.name


class Question(models.Model):
    text = models.CharField(max_length=500)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='question_bank')  # teacher who uploaded it
    question_set = models.ForeignKey(QuestionSet, on_delete=models.CASCADE, null=True, blank=True, related_name='questions')  # the upload it came from
    time_limit = models.IntegerField(default=30)  # Time limit in seconds
    points = models.IntegerField(default=1)  # Points awarded for correct answer
    
    def __str__(self):
        return self.text[:75]

class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)
    explanation = models.TextField(blank=True, null=True)  # shown when chosen and wrong

    def __str__(self):
        return self.text[:80]

# ---- Exams (teacher-created, shared by link) ----
import secrets

from django.utils import timezone


def new_exam_token():
    return secrets.token_urlsafe(16)  # 128 bits: unguessable


class Exam(models.Model):
    SCHEDULED, OPEN = 'scheduled', 'open'
    MODES = [(SCHEDULED, 'Scheduled (teacher starts it, fixed time)'), (OPEN, 'Open (anytime, no timer)')]
    DRAFT, LOBBY, RUNNING, ENDED = 'draft', 'lobby', 'running', 'ended'

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exams')
    title = models.CharField(max_length=200)
    mode = models.CharField(max_length=10, choices=MODES, default=SCHEDULED)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)  # scheduled only
    seat_limit = models.PositiveIntegerField()  # compulsory
    token = models.CharField(max_length=32, unique=True, default=new_exam_token, editable=False)
    status = models.CharField(max_length=10, default=DRAFT)
    questions = models.ManyToManyField(Question, related_name='exams')
    created_at = models.DateTimeField(auto_now_add=True)
    starts_at = models.DateTimeField(null=True, blank=True)  # scheduled: set when the teacher presses Start (+countdown)
    ends_at = models.DateTimeField(null=True, blank=True)    # scheduled: starts_at + duration

    def __str__(self):
        return self.title

    def phase(self, now=None):
        """draft / lobby / countdown / running / ended, from the status and the server clock."""
        if self.status == self.RUNNING and self.starts_at:  # scheduled exam after Start
            now = now or timezone.now()
            if now < self.starts_at:
                return 'countdown'
            return 'ended' if now >= self.ends_at else 'running'
        return self.status  # open exams have no clock; draft/lobby/ended are explicit


class ExamAllowed(models.Model):
    """Optional class list: if an exam has any rows here, only these emails may enter."""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='allowed')
    email = models.CharField(max_length=254)  # stored lowercase

    class Meta:
        unique_together = ['exam', 'email']


DEVICE_TAG = 4  # characters of a device id that make up its short code


class ExamAttempt(models.Model):
    """One row per student who took a seat (after consent). Grows in step 2c with timing and score."""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='attempts')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exam_attempts')
    consented_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    rejoins = models.PositiveIntegerField(default=0)  # times they came back through the link (wifi drop, etc.)
    last_rejoin_at = models.DateTimeField(null=True, blank=True)
    # --- taking the exam (step 2c) ---
    question_ids = models.JSONField(default=list, blank=True)  # this student's shuffled question order
    started_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)       # personal deadline (the exam's end; extra time later)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveIntegerField(null=True, blank=True)
    total_points = models.PositiveIntegerField(default=0)
    # --- device lock and freeze (step 3) ---
    device_id = models.CharField(max_length=64, blank=True)       # browser the exam is locked to
    device_label = models.CharField(max_length=100, blank=True)   # e.g. "Chrome on Windows"
    device_ip = models.GenericIPAddressField(null=True, blank=True)
    frozen_at = models.DateTimeField(null=True, blank=True)       # set while the teacher has to look at it
    freezes = models.PositiveIntegerField(default=0)
    challenger_id = models.CharField(max_length=64, blank=True)   # the other browser that tried to get in
    challenger_label = models.CharField(max_length=100, blank=True)
    challenger_ip = models.GenericIPAddressField(null=True, blank=True)
    blocked_devices = models.JSONField(default=list, blank=True)  # browsers the teacher turned away
    device_seen_at = models.DateTimeField(null=True, blank=True)  # last time the locked browser checked in
    # other browsers turned away while the student's own browser was active (the student is never interrupted)
    intrusions = models.PositiveIntegerField(default=0)
    last_intruder_id = models.CharField(max_length=64, blank=True)
    last_intruder_label = models.CharField(max_length=100, blank=True)
    last_intruder_ip = models.GenericIPAddressField(null=True, blank=True)
    last_intrusion_at = models.DateTimeField(null=True, blank=True)
    extra_seconds = models.PositiveIntegerField(default=0)        # extra time the teacher granted
    # --- leaving the exam window (scheduled exams) ---
    strikes = models.PositiveIntegerField(default=0)              # counted warnings; the third submits the exam
    leaves = models.PositiveIntegerField(default=0)               # every time the window was left, strikes on or off
    last_leave_at = models.DateTimeField(null=True, blank=True)   # the last report that counted (also used to ignore duplicates)
    away_since = models.DateTimeField(null=True, blank=True)      # set while the student is away, cleared when they come back
    away_seconds = models.PositiveIntegerField(default=0)         # total time away, as reported by the page (bounded by the server)
    strikes_off = models.BooleanField(default=False)              # the teacher switched strikes and the fullscreen rule off for this student
    submit_reason = models.CharField(max_length=20, blank=True)   # 'strikes' when the server submitted the exam for leaving it
    # --- evidence for the teacher ---
    mismatches = models.PositiveIntegerField(default=0)           # the locked device code was used from a different kind of browser
    last_mismatch_at = models.DateTimeField(null=True, blank=True)
    freeze_silent_seconds = models.PositiveIntegerField(null=True, blank=True)  # how long the original device had been silent when the seat froze

    class Meta:
        unique_together = ['exam', 'user']

    # A short code for a browser, shown on that browser's screen and in the teacher's unfreeze list, so in a lab
    # full of identical "Chrome on Windows" machines the teacher can tell which device is which.
    @property
    def device_tag(self):
        return self.device_id[:DEVICE_TAG]

    @property
    def challenger_tag(self):
        return self.challenger_id[:DEVICE_TAG]


class ExamEvent(models.Model):
    """Audit log: who froze, unfroze or gave extra time, and when. Only the teacher ever sees this."""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='events')
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, null=True, blank=True, related_name='events')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)  # the teacher; empty = the system
    kind = models.CharField(max_length=20)
    detail = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class ExamAnswer(models.Model):
    """The student's current choice for one question; overwritten as they change their mind (autosave)."""
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    choice = models.ForeignKey(Choice, on_delete=models.CASCADE)
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['attempt', 'question']


class ExamDenied(models.Model):
    """Students turned away at the door (not on class list / no seats). One row per student, with a counter."""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='denied')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.CharField(max_length=20)
    tries = models.PositiveIntegerField(default=1)
    last_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['exam', 'user']
