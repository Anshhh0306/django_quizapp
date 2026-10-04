from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve, reverse

from . import two_factor
from .ratelimit import bump


class TwoFactorGateMiddleware:
    """Whoever is signed in but has not passed the second step can reach only the two-factor pages, logout and static
    files: everything else, the exam endpoints and the admin site included, sends them to the code page (or, for a role
    that must have an authenticator and has none, to the setup page). Deny by default, so a page added later is covered
    too. Also where a browser the account has not used before is noticed (two_factor.note_browser)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        signed_in = user.is_authenticated
        fully = signed_in and user.is_verified()
        if signed_in and not fully and not request.path.startswith(two_factor.EXEMPT_PREFIXES):
            step = two_factor.pending_step(request)
            if step:
                return redirect(f'{reverse("two_factor_" + step)}?{urlencode({"next": request.get_full_path()})}')
            fully = True  # nothing more is asked of this person
        response = self.get_response(request)
        if fully:
            two_factor.note_browser(request, response)
        return response


class RequestCapMiddleware:
    """Catch-all against one script (or one runaway page) hammering the site: a cap per network address, checked first
    and without touching the database, then a cap per signed-in user. Both are per minute and far above real use
    (settings.REQUEST_CAPS; empty = off, which is how the test suite runs). The tighter caps on saving answers, pings
    and login stay as they are. It cannot stop a flood from many machines: that has to be stopped in front of Django."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        caps = settings.REQUEST_CAPS
        if caps and (bump(f'rc:ip:{request.META.get("REMOTE_ADDR")}', 60) > caps['address']
                     or (request.user.is_authenticated and bump(f'rc:user:{request.user.pk}', 60) > caps['user'])):
            if request.path.startswith('/exam/'):  # the exam page reads JSON from its background calls
                response = JsonResponse({'ok': False, 'reason': 'slow_down'}, status=429)
            else:
                response = HttpResponse('Too many requests. Please slow down and try again in a minute.', status=429)
            response['Retry-After'] = '60'
            return response
        return self.get_response(request)


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
