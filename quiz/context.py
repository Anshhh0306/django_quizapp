from .roles import role_of


def role(request):
    """Makes `role` (admin / teacher / pending / student) available on every page, e.g. for the badge in the top bar."""
    user = getattr(request, 'user', None)
    return {'role': role_of(user)} if user is not None and user.is_authenticated else {}
