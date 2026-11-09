import hashlib
import time
from django.core.cache import cache
from django.conf import settings


def login_allowed(request, email):
    """Throttle both website and native login; never trust arbitrary proxy headers."""
    if not settings.LOGIN_RATE_LIMIT_ENABLED:
        return True
    bucket = int(time.time() // 60)
    for label, value, limit in [('ip', request.META.get('REMOTE_ADDR', ''), 60), ('account', email.strip().casefold(), 10)]:
        digest = hashlib.sha256(value.encode()).hexdigest()
        key = f'login:{label}:{bucket}:{digest}'
        cache.add(key, 0, timeout=90)
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=90)
            count = 1
        if count > limit:
            return False
    return True
