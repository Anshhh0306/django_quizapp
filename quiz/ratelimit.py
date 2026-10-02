from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse

# ponytail: everything here uses the default cache (per-process LocMemCache, fixed windows, REMOTE_ADDR).
# With several workers switch CACHES to redis/db; behind a proxy fix REMOTE_ADDR first.


def _bump(key, window):
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
                    if _bump(key, window) > cap:
                        return HttpResponse('Too many requests. Please try again later.', status=429)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


# ---- login: only FAILED attempts count, so a class logging in at once is never slowed down ----
LOGIN_WINDOW = 15 * 60
LOGIN_PAIR_LIMIT = 5     # wrong passwords for one account from one address
LOGIN_IP_LIMIT = 100     # wrong passwords from one address overall (a spray across many accounts)


def _login_keys(username, ip):
    return f'lf:pair:{(username or "").lower()[:150]}:{ip}', f'lf:ip:{ip}'


def login_blocked(username, ip):
    pair, per_ip = _login_keys(username, ip)
    return (cache.get(pair, 0) >= LOGIN_PAIR_LIMIT) or (cache.get(per_ip, 0) >= LOGIN_IP_LIMIT)


def login_failed(username, ip):
    for key in _login_keys(username, ip):
        _bump(key, LOGIN_WINDOW)


def login_succeeded(username, ip):
    cache.delete(_login_keys(username, ip)[0])  # a correct password clears that account's strikes from this address
