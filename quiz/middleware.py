from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve

class AdminAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if the request is for the admin interface
        if request.path.startswith('/admin/'):
            # Allow the admin login page so superusers can authenticate
            if request.path.rstrip('/') == '/admin/login':
                return self.get_response(request)

            # For all other admin pages, require authenticated superuser
            if not request.user.is_authenticated or not request.user.is_superuser:
                messages.error(request, "Access Denied: You must be a superuser to access the admin interface.")
                return redirect('home')

        response = self.get_response(request)
        return response

class DeviceCookieMiddleware:
    """Gives every browser a random, long-lived marker on exam pages so we can tell two devices apart."""
    COOKIE_AGE = 365 * 24 * 3600

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/exam/'):
            return self.get_response(request)
        from django.conf import settings
        from .exam_device import COOKIE, new_device_id, valid_device_id
        current = request.COOKIES.get(COOKIE)
        request.device_id = current if valid_device_id(current) else new_device_id()
        response = self.get_response(request)
        if request.device_id != current:
            response.set_cookie(COOKIE, request.device_id, max_age=self.COOKIE_AGE, httponly=True,
                                samesite='Lax', secure=not settings.DEBUG)
        return response
