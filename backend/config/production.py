"""Explicit, fail-closed production profile. No provider/domain is assumed."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403

DEBUG = False
LOGIN_RATE_LIMIT_ENABLED = True
ENABLE_ROUTE_REPLAY = False
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith(('django-insecure-', 'replace-')):
    raise ImproperlyConfigured('Production requires a strong, unique DJANGO_SECRET_KEY.')
if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('Production requires explicit DJANGO_ALLOWED_HOSTS.')
if any(not origin.startswith('https://') or '*' in origin for origin in CORS_ALLOWED_ORIGINS + CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured('Production CORS/CSRF origins must be explicit HTTPS origins.')
if DATABASES['default']['OPTIONS'].get('sslmode') not in ('require', 'verify-ca', 'verify-full'):
    raise ImproperlyConfigured('Production PostgreSQL must require TLS.')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('DJANGO_HSTS_INCLUDE_SUBDOMAINS', 'False').lower() == 'true'
SECURE_HSTS_PRELOAD = os.getenv('DJANGO_HSTS_PRELOAD', 'False').lower() == 'true'
SESSION_COOKIE_AGE = 43200
# Only enable behind a proxy that strips/replaces client-forwarded headers.
if os.getenv('DJANGO_TRUST_PROXY_HTTPS', 'False').lower() == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
MIDDLEWARE.append('config.middleware.ProductionHeaders')
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
WHITENOISE_MAX_AGE = 31536000
# One college host: shared on-disk cache; no Redis/distributed service required.
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
    'LOCATION': os.getenv('DJANGO_CACHE_DIR', str(BASE_DIR / 'runtime' / 'cache')),
    'OPTIONS': {'MAX_ENTRIES': 10000}}}
LOGGING = {'version': 1, 'disable_existing_loggers': False,
    'filters': {'redact': {'()': 'config.logging.RedactSecrets'}},
    'formatters': {'safe': {'format': '{levelname} {name}: {message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'filters': ['redact'], 'formatter': 'safe'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
                'django.db.backends': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False}}}
