from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import Question, Choice, UserQuiz, Category, UserStatistics
from . import user_admin
from .forms import AdminLoginForm

class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 1
    fields = ('text', 'is_correct', 'explanation')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'question_count')
    search_fields = ('name', 'description')

    def question_count(self, obj):
        return obj.questions.count()
    question_count.short_description = 'Number of Questions'

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    inlines = [ChoiceInline]
    list_display = ('text', 'category', 'points', 'time_limit', 'view_choices')
    list_filter = ('category', 'points', 'time_limit')
    search_fields = ('text', 'category__name')
    ordering = ('category', 'text')

    def view_choices(self, obj):
        choices = obj.choices.all()
        return format_html('<br>'.join([
            f"{'✓ ' if choice.is_correct else '✗ '}{choice.text}"
            for choice in choices
        ]))
    view_choices.short_description = 'Choices'

@admin.register(UserQuiz)
class UserQuizAdmin(admin.ModelAdmin):
    list_display = ('user', 'category', 'score', 'total_points', 'completed', 'taken_on', 'completion_status')
    list_filter = ('completed', 'category', 'taken_on')
    search_fields = ('user__username', 'user__email', 'category__name')
    ordering = ('-taken_on',)

    def completion_status(self, obj):
        if obj.completed:
            return format_html(
                '<span style="color: green;">✓ Completed</span>'
            )
        return format_html(
            '<span style="color: orange;">⌛ In Progress</span>'
        )
    completion_status.short_description = 'Status'

@admin.register(UserStatistics)
class UserStatisticsAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_quizzes', 'total_questions', 'total_points', 
                   'average_score', 'rank', 'last_quiz_date')
    list_filter = ('rank', 'last_quiz_date')
    search_fields = ('user__username', 'user__email')
    ordering = ('rank',)
    readonly_fields = ('total_quizzes', 'total_questions', 'total_points', 
                      'average_score', 'rank', 'last_quiz_date')

    def has_add_permission(self, request):
        return False  # Statistics are created automatically

admin.site.login_form = AdminLoginForm  # failed admin logins are counted and locked like the normal login
