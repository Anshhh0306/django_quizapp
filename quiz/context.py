from .roles import role_of


def role(request):
    """Makes `role` (admin / teacher / pending / student) available on every page, e.g. for the badge in the top bar,
    and `two_factor_on` (has this session passed the authenticator step) for the "secure your account" note."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'role': role_of(user), 'two_factor_on': bool(getattr(user, 'otp_device', None))}
