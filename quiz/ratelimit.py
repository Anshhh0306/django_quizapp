import math
import time
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

# ponytail: everything here uses the default cache (per-process LocMemCache, fixed windows, REMOTE_ADDR).
# With several workers switch CACHES to redis/db; behind a proxy fix REMOTE_ADDR first (deployment must do both).


def bump(key, window):
    """Add one to a counter that expires `window` seconds after its first hit. Returns the new count."""
    try:
        return cache.incr(key)
    except ValueError:  # first hit in this window
        cache.set(key, 1, window)
        return 1


def rate_limit(name, limit, window, field=None, field_limit=None):
    """Cap POSTs to `limit` per `window` seconds per client IP, and (if `field`) `field_limit` per posted value.

    The per-value limit protects one mailbox from being flooded; the per-IP limit is looser so a whole class
    behind one campus address is not locked out by a few mistakes."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method == 'POST':
                keys = [(f'rl:{name}:ip:{request.META.get("REMOTE_ADDR")}', limit)]
                if field and request.POST.get(field):
                    keys.append((f'rl:{name}:{field}:{request.POST[field].strip().lower()[:254]}', field_limit or limit))
                for key, cap in keys:
                    if bump(key, window) > cap:
                        return HttpResponse('Too many requests. Please try again later.', status=429)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def user_rate_limit(name, limit, window=60):
    """Cap a signed-in student to `limit` requests per `window` seconds on one exam (any method). The answer is
    JSON, because the exam page reads it: it shows "retrying" and tries again, nothing is lost. Put it BELOW
    @login_required (it needs request.user) and below @require_POST (a wrong method is not counted)."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if bump(f'rl:{name}:{request.user.pk}:{kwargs.get("token", "")}', window) > limit:
                return JsonResponse({'ok': False, 'reason': 'slow_down'}, status=429, headers={'Retry-After': str(window)})
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


# ---- login: only FAILED attempts count, so a class logging in at once is never slowed down ----
# A wrong password is counted against the ACCOUNT, from wherever it comes, so guessing from many addresses does
# not help. The lock is short and grows (2, 4, 8, then 15 minutes) so someone typing a stranger's name five times
# only holds that student out for a couple of minutes.
LOGIN_FREE_TRIES = 5            # wrong passwords before the first lock
LOGIN_LOCK_FIRST = 2 * 60       # seconds; every further wrong password doubles it
LOGIN_LOCK_MAX = 15 * 60
LOGIN_MEMORY = 60 * 60          # wrong passwords are forgotten this long after the first one
LOGIN_IP_LIMIT = 300            # wrong passwords from one address overall in LOGIN_IP_WINDOW: a spray across many accounts.
LOGIN_IP_WINDOW = 15 * 60       # high on purpose: a whole campus can share one address


def _login_keys(username, ip):
    name = (username or '').lower()[:150]
    return f'lf:acct:{name}', f'lf:lock:{name}', f'lf:ip:{ip}'


def login_blocked(username, ip):
    """Seconds this login must still wait (0 = free to try). Never reveals whether the account exists."""
    _, lock, per_ip = _login_keys(username, ip)
    wait = (cache.get(lock) or 0) - time.time()
    if cache.get(per_ip, 0) >= LOGIN_IP_LIMIT:
        wait = max(wait, LOGIN_IP_WINDOW)  # the exact end of a counter window is not known: say the longest
    return max(0, math.ceil(wait))


def login_failed(username, ip):
    """Count one wrong password. Returns how many seconds the account is now locked for (0 = not locked)."""
    acct, lock, per_ip = _login_keys(username, ip)
    bump(per_ip, LOGIN_IP_WINDOW)
    n = bump(acct, LOGIN_MEMORY)  # ponytail: fixed window from the first failure, so the count restarts after an hour
    seconds = 0
    if n >= LOGIN_FREE_TRIES:
        seconds = min(LOGIN_LOCK_MAX, LOGIN_LOCK_FIRST * 2 ** (n - LOGIN_FREE_TRIES))
        cache.set(lock, time.time() + seconds, seconds)
    return seconds


def login_succeeded(username, ip):
    acct, lock, _ = _login_keys(username, ip)
    cache.delete_many([acct, lock])  # a correct password forgives the account's earlier wrong ones
