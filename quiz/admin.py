from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import Question, Choice
from . import user_admin
from .forms import AdminLoginForm

class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 1
    fields = ('text', 'is_correct', 'explanation')

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    inlines = [ChoiceInline]
    list_display = ('text', 'owner', 'points', 'time_limit', 'view_choices')
    list_filter = ('points', 'time_limit')
    search_fields = ('text', 'owner__username')
    ordering = ('text',)

    def view_choices(self, obj):
        choices = obj.choices.all()
        return format_html('<br>'.join([
            f"{'✓ ' if choice.is_correct else '✗ '}{choice.text}"
            for choice in choices
        ]))
    view_choices.short_description = 'Choices'

admin.site.login_form = AdminLoginForm  # failed admin logins are counted and locked like the normal login
