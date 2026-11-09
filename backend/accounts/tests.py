from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, SimpleTestCase, Client
from django.utils import timezone
from rest_framework.test import APIClient
from .models import AccessToken
from .permissions import IsAdmin

User = get_user_model()


class RoleUnitTests(SimpleTestCase):
    def test_roles(self):
        self.assertEqual(set(User.Role.values), {'ADMIN', 'STUDENT', 'DRIVER'})

    def test_password_is_hashed(self):
        user = User(email='person@example.test', role='STUDENT')
        user.set_password('safe-password-123')
        self.assertNotEqual(user.password, 'safe-password-123')
        self.assertTrue(user.check_password('safe-password-123'))

    def test_role_permission(self):
        from types import SimpleNamespace
        for role in User.Role.values:
            request = SimpleNamespace(user=User(role=role))
            self.assertEqual(IsAdmin().has_permission(request, None), role == 'ADMIN')


class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('Student@example.test', 'safe-password-123', full_name='Student', role='STUDENT')
        self.api = APIClient()

    def login(self):
        response = self.api.post('/api/auth/login/', {'email': self.user.email, 'password': 'safe-password-123'})
        self.assertEqual(response.status_code, 200)
        self.api.credentials(HTTP_AUTHORIZATION='Bearer ' + response.data['token'])
        return response

    def test_login_me_logout_revocation(self):
        response = self.login()
        self.assertNotIn('password', str(response.data))
        self.assertNotEqual(AccessToken.objects.get().digest, response.data['token'])
        self.assertEqual(self.api.get('/api/auth/me/').data['role'], 'STUDENT')
        self.assertEqual(self.api.post('/api/auth/logout/').status_code, 204)
        self.assertEqual(self.api.get('/api/auth/me/').status_code, 401)

    def test_invalid_credentials_and_anonymous(self):
        self.assertEqual(self.api.get('/api/auth/me/').status_code, 401)
        self.assertEqual(self.api.post('/api/auth/login/', {'email': self.user.email, 'password': 'wrong'}).status_code, 401)

    def test_expired_and_inactive_tokens(self):
        self.login()
        AccessToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.api.get('/api/auth/me/').status_code, 401)
        self.api.credentials()
        self.login()
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.api.get('/api/auth/me/').status_code, 401)
        self.api.credentials()
        self.assertEqual(self.api.post('/api/auth/login/', {'email': self.user.email, 'password': 'safe-password-123'}).status_code, 401)

    def test_browser_api_login_requires_csrf(self):
        browser = APIClient(enforce_csrf_checks=True)
        response = browser.post('/api/auth/login/', {'email': self.user.email, 'password': 'safe-password-123'}, HTTP_ORIGIN='http://testserver')
        self.assertEqual(response.status_code, 403)

    def test_session_role_redirects_and_pages(self):
        for role, destination in [('ADMIN', 'admin'), ('STUDENT', 'student'), ('DRIVER', 'driver')]:
            self.user.role = role
            self.user.save()
            self.client.logout()
            response = self.client.post('/login/', {'username': self.user.email, 'password': 'safe-password-123'})
            self.assertRedirects(response, '/', fetch_redirect_response=False)
            self.assertRedirects(self.client.get('/'), f'/dashboard/{destination}/', fetch_redirect_response=False)
            self.assertEqual(self.client.get(f'/dashboard/{destination}/').status_code, 200)
            other = 'student' if role == 'ADMIN' else 'admin'
            self.assertEqual(self.client.get(f'/dashboard/{other}/').status_code, 403)
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertEqual(self.client.post('/logout/').status_code, 302)

    def test_anonymous_pages_and_csrf(self):
        self.assertEqual(self.client.get('/dashboard/admin/').status_code, 302)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/login/', {'username': self.user.email, 'password': 'safe-password-123'}).status_code, 403)

    def test_email_uniqueness_and_role_database_constraint(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user('STUDENT@example.test', 'password', full_name='Duplicate', role='ADMIN')
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.user.pk).update(role='UNKNOWN')
