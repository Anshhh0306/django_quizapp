from django.db import models
from django.contrib.auth.models import User

class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Categories"

class Question(models.Model):
    text = models.CharField(max_length=500)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='questions', null=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='question_bank')  # teacher who uploaded it
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

class UserQuiz(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    completed = models.BooleanField(default=False)
    score = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)
    total_points = models.IntegerField(default=0)
    taken_on = models.DateTimeField(null=True, blank=True)
    average_time_per_question = models.FloatField(default=0)
    # In-progress state lives here (not in the session) so restarting can't reset it
    question_ids = models.JSONField(default=list, blank=True)
    current_index = models.IntegerField(default=0)
    question_started_at = models.DateTimeField(null=True, blank=True)  # server-side timer

    class Meta:
        unique_together = ['user', 'category']

    def __str__(self):
        return f"{self.user.username} - {self.category.name} - {'done' if self.completed else 'not done'}"

class UserAnswer(models.Model):
    """Store individual user answers for review purposes"""
    user_quiz = models.ForeignKey(UserQuiz, on_delete=models.CASCADE, related_name='user_answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_choice = models.ForeignKey(Choice, on_delete=models.CASCADE, null=True, blank=True)
    is_correct = models.BooleanField(default=False)
    time_taken = models.FloatField(default=0.0)  # Time taken to answer in seconds
    
    class Meta:
        unique_together = ['user_quiz', 'question']
    
    def __str__(self):
        return f"{self.user_quiz.user.username} - Q: {self.question.text[:50]} - {'✓' if self.is_correct else '✗'}"

class UserStatistics(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    total_quizzes = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)
    total_points = models.IntegerField(default=0)
    average_score = models.FloatField(default=0)
    rank = models.IntegerField(default=0)
    last_quiz_date = models.DateTimeField(null=True, blank=True)
    
    def update_stats(self):
        # Get all completed quizzes
        quizzes = UserQuiz.objects.filter(user=self.user, completed=True)
        
        # Update basic stats
        self.total_quizzes = quizzes.count()
        self.total_questions = quizzes.aggregate(models.Sum('total_questions'))['total_questions__sum'] or 0
        self.total_points = quizzes.aggregate(models.Sum('score'))['score__sum'] or 0
        
        if self.total_questions > 0:
            self.average_score = round((self.total_points / self.total_questions) * 100, 1)
            
        # Update category breakdown
        category_counts = quizzes.values('category__name').annotate(count=models.Count('id'))
        
        # Update last quiz date
        if self.total_quizzes > 0:
            self.last_quiz_date = quizzes.latest('taken_on').taken_on
            
        self.save()
    
    def __str__(self):
        return f"{self.user.username}'s Statistics"

# Signal to create/update user statistics when a quiz is completed
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=UserQuiz)
def update_user_statistics(sender, instance, **kwargs):
    if instance.completed:
        stats, created = UserStatistics.objects.get_or_create(user=instance.user)
        stats.update_stats()
        
        # Update ranks for all users
        all_stats = UserStatistics.objects.all().order_by('-total_points')
        for rank, stats in enumerate(all_stats, 1):
            stats.rank = rank
            stats.save()


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

    class Meta:
        unique_together = ['exam', 'user']


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
