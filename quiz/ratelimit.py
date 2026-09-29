from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse


def rate_limit(name, limit, window, field=None):
    """Cap POSTs to `limit` per `window` seconds, per client IP and (if `field`) per posted value.

    ponytail: uses the default cache (per-process LocMemCache, fixed window, REMOTE_ADDR).
    With several workers switch CACHES to redis/db; behind a proxy fix REMOTE_ADDR first.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method == 'POST':
                keys = [f'rl:{name}:ip:{request.META.get("REMOTE_ADDR")}']
                if field and request.POST.get(field):
                    keys.append(f'rl:{name}:{field}:{request.POST[field].strip().lower()}')
                for key in keys:
                    try:
                        count = cache.incr(key)
                    except ValueError:  # first hit in this window
                        cache.set(key, 1, window)
                        count = 1
                    if count > limit:
                        return HttpResponse('Too many requests. Please try again later.', status=429)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
