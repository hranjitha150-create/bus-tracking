import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
from .hosts import deployment_hosts

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

def csv_env(name, default=''):
    return [v.strip() for v in os.getenv(name, default).split(',') if v.strip()]

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY in backend/.env or the environment.')
DEBUG = os.getenv('DJANGO_DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = deployment_hosts(
    csv_env('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1'), os.environ
)
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL or not DATABASE_URL.startswith(('postgres://', 'postgresql://')):
    raise ImproperlyConfigured('DATABASE_URL must be a PostgreSQL URL. SQLite is not supported.')
DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=60)}
DATABASES['default'].setdefault('OPTIONS', {}).setdefault('sslmode', 'require')
DATABASES['default']['OPTIONS']['prepare_threshold'] = None
DATABASES['default']['OPTIONS'].setdefault('connect_timeout', 5)
DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
INSTALLED_APPS = [
    'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'corsheaders', 'accounts', 'students', 'drivers', 'buses',
    'routes', 'assignments', 'tracking', 'eta', 'admin_portal',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'
AUTH_USER_MODEL = 'accounts.CustomUser'
LOGIN_RATE_LIMIT_ENABLED = True
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['accounts.authentication.ExpiringTokenAuthentication', 'rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.AnonRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {'anon': '30/min', 'login': '10/min'},
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination', 'PAGE_SIZE': 50,
}
CORS_ALLOWED_ORIGINS = csv_env('CORS_ALLOWED_ORIGINS')
CSRF_TRUSTED_ORIGINS = csv_env('CSRF_TRUSTED_ORIGINS')
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_TZ = True
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
# OSM tiles require a Referer. Send only our origin on cross-origin requests.
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'
GPS_STALE_SECONDS = 120
DRIVER_GPS_INTERVAL_SECONDS = 10
DRIVER_LOCATION_MAX_AGE_SECONDS = 120

def number_env(name, default, minimum=0):
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ImproperlyConfigured(f'{name} must be numeric.') from exc
    import math
    if not math.isfinite(value) or value < minimum:
        raise ImproperlyConfigured(f'{name} must be finite and >= {minimum}.')
    return value

GPS_MAX_ACCURACY_METERS = number_env('GPS_MAX_ACCURACY_METERS', 100, 1)
GPS_MAX_SPEED_MPS = number_env('GPS_MAX_SPEED_MPS', 45, 1)
GPS_JUMP_ALLOWANCE_METERS = number_env('GPS_JUMP_ALLOWANCE_METERS', 50)
ROUTE_CORRIDOR_METERS = number_env('ROUTE_CORRIDOR_METERS', 50, 1)
ROUTE_STOP_SNAP_METERS = number_env('ROUTE_STOP_SNAP_METERS', 150, 1)
STOP_PASSED_METERS = number_env('STOP_PASSED_METERS', 25, 1)
ETA_FALLBACK_SPEED_KMH = number_env('ETA_FALLBACK_SPEED_KMH', 20, 1)
ETA_STATIONARY_SECONDS = number_env('ETA_STATIONARY_SECONDS', 30, 1)
ETA_STOP_DWELL_SECONDS = number_env('ETA_STOP_DWELL_SECONDS', 15)
LOCATION_HISTORY_ENABLED = os.getenv('LOCATION_HISTORY_ENABLED', 'True').lower() == 'true'
LOCATION_HISTORY_MIN_INTERVAL_SECONDS = number_env('LOCATION_HISTORY_MIN_INTERVAL_SECONDS', 0)
LOCATION_HISTORY_RETENTION_DAYS = number_env('LOCATION_HISTORY_RETENTION_DAYS', 30, 1)
ADMIN_POLL_INTERVAL_SECONDS = int(number_env('ADMIN_POLL_INTERVAL_SECONDS', 10, 5))
ENABLE_ROUTE_REPLAY = os.getenv('ENABLE_ROUTE_REPLAY', 'False').lower() == 'true'
OSRM_BASE_URL = os.getenv('OSRM_BASE_URL', 'https://router.project-osrm.org').rstrip('/')
try:
    STUDENT_POLL_INTERVAL_SECONDS = int(os.getenv('STUDENT_POLL_INTERVAL_SECONDS', '10'))
except ValueError as exc:
    raise ImproperlyConfigured('STUDENT_POLL_INTERVAL_SECONDS must be an integer.') from exc
if not 2 <= STUDENT_POLL_INTERVAL_SECONDS <= 300:
    raise ImproperlyConfigured('STUDENT_POLL_INTERVAL_SECONDS must be between 2 and 300.')
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
