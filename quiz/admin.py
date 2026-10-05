from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe
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
        # Choice text is typed by teachers: every piece is escaped before it is joined (format_html with a ready-made
        # string would treat the whole string as safe HTML and as a format string).
        return format_html_join(mark_safe('<br>'), '{}{}',
                                (('✓ ' if choice.is_correct else '✗ ', choice.text) for choice in obj.choices.all()))
    view_choices.short_description = 'Choices'

admin.site.login_form = AdminLoginForm  # failed admin logins are counted and locked like the normal login
