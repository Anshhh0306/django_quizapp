import hashlib
import math
import time
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

from .util import client_ip

# ponytail: everything here uses the default cache (per-process LocMemCache, fixed windows, client_ip).
# The host must run ONE process (gunicorn.conf.py says workers = 1) or the counters are not shared between processes;
# with several, switch CACHES to a database or Redis cache.


def key_part(text):
    """User-typed text as part of a cache key: a short fixed-length hash. Names, posted values and URL pieces can be long,
    hold spaces or control characters (not allowed in a key), or be sent by an attacker to fill the cache with huge keys."""
    return hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:32]


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
                keys = [(f'rl:{name}:ip:{client_ip(request)}', limit)]
                if field and request.POST.get(field):
                    keys.append((f'rl:{name}:{field}:{key_part(request.POST[field].strip().lower()[:254])}', field_limit or limit))
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
            if bump(f'rl:{name}:{request.user.pk}:{key_part(kwargs.get("token", ""))}', window) > limit:
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


LOCKED_LIST = 'lf:locked'  # name -> when its lock ends: only so a superadmin can SEE the locks (the lock itself is lf:lock:)


def _name(username):
    return (username or '').lower()[:150]


def _login_keys(username, ip):
    name = key_part(_name(username))
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
        cache.set(LOCKED_LIST, {**cache.get(LOCKED_LIST, {}), _name(username): time.time() + seconds}, 24 * 3600)
    return seconds


def login_succeeded(username, ip):
    """Forgive the account's wrong passwords and end its lock: after a correct login, a password reset by email (only the
    inbox owner can do that) or a superadmin's Unlock button."""
    acct, lock, _ = _login_keys(username, ip)
    cache.delete_many([acct, lock])
    listed = cache.get(LOCKED_LIST, {})
    if listed.pop(_name(username), None) is not None:
        cache.set(LOCKED_LIST, listed, 24 * 3600)


def locked_accounts():
    """[(name, seconds left)] for the accounts locked right now, longest first. Only what this server process knows:
    # ponytail: the cache is per process; a shared cache (needed anyway for several workers) makes this complete."""
    now = time.time()
    return sorted(((name, math.ceil(until - now)) for name, until in cache.get(LOCKED_LIST, {}).items() if until > now),
                  key=lambda item: -item[1])
