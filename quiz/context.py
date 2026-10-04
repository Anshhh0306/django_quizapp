import os

from django.contrib.staticfiles import finders

from .roles import role_of


def _version(path):
    """The static file's last-change time, put on the end of its address (the stylesheet link in base.html). The server
    sends static files without saying how long a browser may keep them, so browsers guess, and can go on using an OLD
    stylesheet for hours after an update. A different address is always fetched afresh."""
    found = finders.find(path)  # ponytail: one stat() per page; cache it if pages ever get heavy
    return int(os.path.getmtime(found)) if found else 0


def role(request):
    """Makes `role` (admin / teacher / pending / student) available on every page, e.g. for the badge in the top bar,
    `two_factor_on` (has this session passed the authenticator step) for the "secure your account" note, and
    `css_version` for the stylesheet address."""
    context = {'css_version': _version('quiz/style.css')}
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return context
    return {**context, 'role': role_of(user), 'two_factor_on': bool(getattr(user, 'otp_device', None))}
