"""The superadmin's view of locked logins (someone typing wrong passwords for an account locks it for a while), with an
Unlock button, so a teacher kept out by a prankster does not have to wait. The same page shows how the site sees the superadmin's
own address, which is how settings.TRUSTED_PROXY_COUNT is checked on a host."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .ratelimit import locked_accounts, login_succeeded
from .roles import role_of
from .util import address_report


@never_cache
@login_required
def locks(request):
    if not request.user.is_superuser:
        return redirect('home')
    rows = []
    for name, seconds in locked_accounts():
        user = User.objects.filter(username__iexact=name).first()
        rows.append({'name': name, 'seconds': seconds, 'email': user.email if user else '',
                     'role': role_of(user) if user else 'no such account'})
    return render(request, 'quiz/admin_locks.html', {'rows': rows, 'address': address_report(request)})


@never_cache
@login_required
@require_POST
def unlock(request):
    if request.user.is_superuser:
        login_succeeded(request.POST.get('name', ''), None)
    return redirect('login_locks' if request.user.is_superuser else 'home')
