"""PostgreSQL-only test settings. No production credentials or SQLite fallback."""
import os
os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-secret-not-for-deployment')
os.environ.setdefault('DJANGO_DEBUG', 'True')
os.environ['DATABASE_URL'] = os.getenv('TEST_DATABASE_URL', 'postgresql://postgres@127.0.0.1:55432/college_bus_test?sslmode=disable')
from .settings import *  # noqa: F403
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
LOGIN_RATE_LIMIT_ENABLED = False
