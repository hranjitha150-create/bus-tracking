"""Offline production/security/static smoke check with ephemeral test-only config."""
import os
import secrets
import sys
from pathlib import Path
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.update(DJANGO_SETTINGS_MODULE='config.production', DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
    DATABASE_URL='postgresql://offline@127.0.0.1:55432/offline?sslmode=require',
    DJANGO_ALLOWED_HOSTS='college.example,testserver', CORS_ALLOWED_ORIGINS='', CSRF_TRUSTED_ORIGINS='',
    DJANGO_DEBUG='True', ENABLE_ROUTE_REPLAY='True')
import django
django.setup()
from django.conf import settings
from django.core.checks import run_checks
from django.core.management import call_command
from django.test import Client
from django.contrib.staticfiles.storage import staticfiles_storage
from config.middleware import ProductionHeaders
from django.http import HttpResponse
assert not settings.DEBUG and not settings.ENABLE_ROUTE_REPLAY
messages = run_checks(include_deployment_checks=True)
expected = {'security.W005', 'security.W021'}
unexpected = [message for message in messages if message.id not in expected]
if unexpected:
    for message in unexpected:
        print(message)
    raise SystemExit('Unexpected production system check findings.')
print('Production checks: secure profile enforced. HSTS subdomain/preload choices remain explicit operator decisions.')
call_command('collectstatic', interactive=False, verbosity=0)
client = Client()
response = client.get('/login/', secure=True)
assert response.status_code == 200
assert 'no-store' in response['Cache-Control']
assert "frame-ancestors 'none'" in response['Content-Security-Policy']
asset = staticfiles_storage.url('js/student.js')
response = client.get(asset, secure=True)
assert response.status_code == 200
if response.has_header('Content-Encoding'):
    assert response['Content-Encoding'] in ('gzip', 'br')
assert client.get('/login/').status_code == 301
response = client.get('/api/student/my-bus/location/', secure=True)
assert response.status_code == 401 and 'no-store' in response['Cache-Control']
import subprocess
invalid_configs = [
    {'DJANGO_SECRET_KEY': 'short'},
    {'DJANGO_ALLOWED_HOSTS': '*'},
    {'CORS_ALLOWED_ORIGINS': 'http://unsafe.example'},
    {'DATABASE_URL': 'postgresql://offline@127.0.0.1:55432/offline?sslmode=disable'},
]
for overrides in invalid_configs:
    env = {**os.environ, **overrides}
    result = subprocess.run([sys.executable, '-c', 'import django; django.setup()'],
        cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    assert result.returncode != 0, 'Invalid production configuration was accepted.'
print('Production negative checks: weak secret, wildcard host, insecure CORS and insecure database configuration rejected.')
print('Production static smoke: hashed static assets served by WhiteNoise; HTTPS redirect, login and security headers passed. No database connection used.')
