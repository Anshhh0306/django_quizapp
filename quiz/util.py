import ipaddress

from django.conf import settings


def to_int(value, max_value=10**9):
    """A whole number from user input, or None.

    'x'.isdigit() is True for characters like '²' that int() cannot read, and a 30-digit number overflows the
    database. This accepts only plain ASCII digits and a sane size."""
    text = str(value).strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 10:
        return None
    number = int(text)
    return number if number <= max_value else None


def client_ip(request):
    """The visitor's address as a valid IP string (or None). Every place that needs an address uses this, never REMOTE_ADDR.

    Behind a proxy REMOTE_ADDR is the proxy's own address. When settings.TRUSTED_PROXY_COUNT says how many proxies are ours,
    the visitor is read from X-Forwarded-For counting from the RIGHT: each of our proxies appends the address it saw, and
    everything to the left was written by the visitor and can be faked ("take the first address" would let anyone choose
    theirs). A missing, too short or malformed header falls back to REMOTE_ADDR, so the result is always safe to store in a
    database address column and to put in a cache key."""
    direct = request.META.get('REMOTE_ADDR') or None
    count = settings.TRUSTED_PROXY_COUNT
    if count > 0:
        entries = [part.strip() for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()]
        if len(entries) >= count:
            try:
                return str(ipaddress.ip_address(entries[-count]))
            except ValueError:
                pass
    return direct


def address_report(request):
    """How the site sees THIS request's address: only the few headers that decide it, never the rest, and only for the superadmin who
    asks. Their real address is on any "what is my IP" site; the row that shows it tells which number settings.TRUSTED_PROXY_COUNT needs."""
    forwarded = [part.strip()[:60] for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()][-10:]
    return {'seen_as': client_ip(request) or '-', 'trusted': settings.TRUSTED_PROXY_COUNT,
            'remote_addr': request.META.get('REMOTE_ADDR') or '-', 'cloudflare': request.META.get('HTTP_CF_CONNECTING_IP', '')[:60],
            'from_the_right': [(n, forwarded[-n]) for n in range(1, len(forwarded) + 1)]}
