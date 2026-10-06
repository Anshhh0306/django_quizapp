from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from .roles import STUDENTS_GROUP, TEACHERS_GROUP, is_student, role_of
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST
from django.http import HttpResponseRedirect
from django.core.mail import send_mail
from django.conf import settings

User = get_user_model()

class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_active', 'date_joined', 'last_login', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'groups', 'date_joined')
    actions = ['approve_teachers', 'make_students']
    search_fields = ('username', 'email')
    ordering = ('-date_joined',)
    
    @admin.display(description='Role')
    def role(self, obj):
        return role_of(obj)

    @admin.action(description='Approve selected users as teachers')
    def approve_teachers(self, request, queryset):
        group, _ = Group.objects.get_or_create(name=TEACHERS_GROUP)
        approved = 0
        for user in queryset:
            if is_student(user):
                self.message_user(request, f'{user.username} is a student (register-number address or Students group); skipped.', level=messages.WARNING)
            else:
                user.groups.add(group)
                approved += 1
        self.message_user(request, f'{approved} user(s) approved as teachers.')

    @admin.action(description='Make selected users students (any address; ends their teacher status)')
    def make_students(self, request, queryset):
        students, teachers = (Group.objects.get_or_create(name=name)[0] for name in (STUDENTS_GROUP, TEACHERS_GROUP))
        made = 0
        for user in queryset:
            if user.is_superuser:
                self.message_user(request, f'{user.username} is a superadmin, whose role does not come from a group; skipped.', level=messages.WARNING)
            else:
                user.groups.add(students)
                user.groups.remove(teachers)  # the two roles never overlap
                made += 1
        self.message_user(request, f'{made} user(s) made students.')

    def get_urls(self):
        # These change data, so they are POST-only (a plain link click cannot trigger them) and go through the
        # admin's own permission check.
        wrap = lambda view: self.admin_site.admin_view(require_POST(view))
        custom_urls = [
            path('<id>/deactivate/', wrap(self.deactivate_user), name='deactivate_user'),
            path('<id>/activate/', wrap(self.activate_user), name='activate_user'),
            path('<id>/reset-password/', wrap(self.reset_user_password), name='reset_user_password'),
        ]
        return custom_urls + super().get_urls()

    def _target(self, request, id):
        user = self.get_object(request, id)
        if not user:
            self.message_user(request, 'User not found.', level=messages.ERROR)
        return user

    def deactivate_user(self, request, id):
        user = self._target(request, id)
        if user and user == request.user:
            self.message_user(request, 'You cannot deactivate your own account.', level=messages.ERROR)
        elif user:
            user.is_active = False
            user.save(update_fields=['is_active'])
            self.message_user(request, f'User {user.username} has been deactivated.')
        return HttpResponseRedirect("../")

    def activate_user(self, request, id):
        user = self._target(request, id)
        if user:
            user.is_active = True
            user.save(update_fields=['is_active'])
            self.message_user(request, f'User {user.username} has been activated.')
        return HttpResponseRedirect("../")

    def reset_user_password(self, request, id):
        """Emails the user a one-time link to choose a new password. No password is ever generated or emailed."""
        user = self._target(request, id)
        if not user:
            return HttpResponseRedirect("../")
        if not user.email:
            self.message_user(request, f'{user.username} has no email address, so no link can be sent.', level=messages.ERROR)
            return HttpResponseRedirect("../")
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        link = request.build_absolute_uri(reverse('password_reset_confirm', args=[uid, default_token_generator.make_token(user)]))
        message = render_to_string('quiz/email/password_reset_email.txt', {
            'user': user, 'reset_url': link, 'site_name': 'SRMIST Quiz Platform'})
        try:
            send_mail('Password Reset - SRMIST Quiz Platform', message, settings.DEFAULT_FROM_EMAIL,
                      [user.email], fail_silently=False)
        except OSError:
            self.message_user(request, 'The email could not be sent. Check the email settings.', level=messages.ERROR)
        else:
            self.message_user(request, f'A password reset link was emailed to {user.username}.', level=messages.SUCCESS)
        return HttpResponseRedirect("../")

    change_form_template = 'admin/custom_change_form.html'

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)