from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from .roles import TEACHERS_GROUP, is_student, role_of
from django.urls import path
from django.http import HttpResponseRedirect
from django.core.mail import send_mail
from django.conf import settings
import secrets
import string

User = get_user_model()

class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_active', 'date_joined', 'last_login', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'groups', 'date_joined')
    actions = ['approve_teachers']
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
                self.message_user(request, f'{user.username} has a student email; skipped.', level=messages.WARNING)
            else:
                user.groups.add(group)
                approved += 1
        self.message_user(request, f'{approved} user(s) approved as teachers.')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<id>/deactivate/', self.deactivate_user, name='deactivate_user'),
            path('<id>/activate/', self.activate_user, name='activate_user'),
            path('<id>/reset-password/', self.reset_user_password, name='reset_user_password'),
        ]
        return custom_urls + urls

    def deactivate_user(self, request, id):
        user = self.get_object(request, id)
        if not user:
            self.message_user(request, 'User not found.', level=messages.ERROR)
            return HttpResponseRedirect("../")
        user.is_active = False
        user.save()
        self.message_user(request, f'User {user.username} has been deactivated.')
        return HttpResponseRedirect("../")

    def activate_user(self, request, id):
        user = self.get_object(request, id)
        if not user:
            self.message_user(request, 'User not found.', level=messages.ERROR)
            return HttpResponseRedirect("../")
        user.is_active = True
        user.save()
        self.message_user(request, f'User {user.username} has been activated.')
        return HttpResponseRedirect("../")

    def reset_user_password(self, request, id):
        user = self.get_object(request, id)
        if not user:
            self.message_user(request, 'User not found.', level=messages.ERROR)
            return HttpResponseRedirect("../")
        # Generate a secure random password
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for i in range(12))
        user.set_password(password)
        user.save()

        # Send password reset email
        if user.email:
            send_mail(
                'Password Reset',
                f'Your password has been reset by an administrator. Your new password is: {password}',
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            msg = f'Password reset for {user.username}. New password has been sent to their email.'
        else:
            msg = f'Password reset for {user.username}. New password: {password}'
        
        self.message_user(request, msg, level=messages.SUCCESS)
        return HttpResponseRedirect("../")

    change_form_template = 'admin/custom_change_form.html'

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)