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