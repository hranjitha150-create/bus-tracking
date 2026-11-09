import io
import logging
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import AccessToken
from config.logging import RedactSecrets
from eta.tests import LiveIntegrationTests
from tracking.tests import TransportTests
from tracking.models import Trip, BusLocation, TripProgress
from buses.models import Bus
from drivers.models import Driver
from assignments.models import DriverAssignment


@override_settings(LOGIN_RATE_LIMIT_ENABLED=True)
class LoginRateTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_website_and_api_share_account_budget(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/login/', {'username': 'nobody@example.test', 'password':'wrong'}).status_code, 200)
        response = self.client.post('/api/auth/login/', {'email':'nobody@example.test', 'password':'wrong'}, content_type='application/json')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '60')

    def test_authenticated_session_does_not_bypass_login_throttle(self):
        user = get_user_model().objects.create_user('actor@example.test', 'test123pass', full_name='Actor', role='ADMIN')
        self.client.force_login(user)
        # CSRF-enforced browser login remains protected before any throttle change.
        from django.test import RequestFactory
        from accounts.rate_limit import login_allowed
        request = RequestFactory().post('/', REMOTE_ADDR='192.0.2.1')
        request.user = user
        self.assertTrue(all(login_allowed(request, 'target@example.test') for _ in range(10)))
        self.assertFalse(login_allowed(request, 'TARGET@example.test'))


class LoggingSafetyTests(SimpleTestCase):
    def test_redacts_bearer_and_database_credentials(self):
        with patch.dict('os.environ', {'DJANGO_SECRET_KEY': 'secret-test-key', 'DATABASE_URL': 'postgresql://user:pass%21@host/db'}):
            record = logging.LogRecord('test', logging.ERROR, '', 0, 'Bearer abc-123 postgresql://user:pass%%21@host/db secret-test-key pass!', (), None)
            RedactSecrets().filter(record)
            self.assertNotIn('abc-123', record.getMessage())
            self.assertNotIn('secret-test-key', record.getMessage())
            self.assertNotIn('pass!', record.getMessage())


class ObjectSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        TransportTests.setUpTestData.__func__(cls)

    def test_student_id_enumeration_never_returns_other_bus(self):
        client = APIClient()
        client.force_authenticate(self.student_user)
        for pk in [self.other_bus.pk, 0, 999999]:
            for path in [f'/api/buses/{pk}/', f'/api/buses/{pk}/location/', f'/api/trips/{self.other_trip.pk}/']:
                self.assertEqual(client.get(path).status_code, 404)
            own = client.get('/api/student/my-bus/location/', {'bus_id':pk, 'student_id':999, 'route_id':999})
            self.assertEqual(own.data['bus']['id'], self.bus.pk)
        for entity in ['buses','drivers','students','routes']:
            self.assertEqual(client.patch(f'/api/admin/{entity}/1/', {'is_active':False}).status_code, 403)

    def test_driver_id_enumeration_and_legacy_actions(self):
        client = APIClient()
        client.force_authenticate(self.driver_user)
        for pk in [self.other_trip.pk, 999999]:
            for suffix in ['location','end']:
                self.assertEqual(client.post(f'/api/driver/trips/{pk}/{suffix}/', {}, format='json').status_code, 404)
            self.assertEqual(client.post(f'/api/trips/{pk}/start/', {}).status_code, 404)
        self.trip.is_simulated = True
        self.trip.save()
        self.assertEqual(client.post(f'/api/trips/{self.trip.pk}/start/', {}).status_code, 400)
        self.trip.is_simulated, self.trip.trip_type = False, 'DROP'
        self.trip.save()
        self.assertEqual(client.post(f'/api/trips/{self.trip.pk}/start/', {}).status_code, 400)

    def test_login_and_identity_responses_are_not_cached(self):
        client = APIClient()
        client.force_authenticate(self.student_user)
        self.assertIn('no-store', client.get('/api/auth/me/')['Cache-Control'])

    def test_database_browser_grants_can_be_removed_without_breaking_backend(self):
        # Cluster-local role creation is rolled back with this isolated test case.
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='anon'")
            if cursor.fetchone() is None:
                cursor.execute('CREATE ROLE anon NOLOGIN')
            cursor.execute('GRANT SELECT ON buses_bus TO anon')
        from accounts.management.commands.audit_database_access import inspect_access
        self.assertTrue(any(row['table']=='buses_bus' and row['role']=='anon' for row in inspect_access()['issues']))
        call_command('audit_database_access', apply=True, stdout=io.StringIO())
        self.assertFalse(inspect_access()['issues'])
        self.assertEqual(Bus.objects.count(), 2)


class QueryBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        LiveIntegrationTests.setUpTestData.__func__(cls)
        client = APIClient()
        client.force_authenticate(cls.driver_user)
        pk = client.post('/api/driver/trips/start/', {}).data['trip']['id']
        client.post(f'/api/driver/trips/{pk}/location/', {'latitude':12, 'longitude':77.001, 'speed':5, 'accuracy':5,
                    'recorded_at':timezone.now().isoformat()}, format='json')

    def selects(self, fn):
        with CaptureQueriesContext(connection) as captured:
            result = fn()
        return result, sum(q['sql'].lstrip().upper().startswith('SELECT') for q in captured)

    def test_student_live_snapshot_budget(self):
        from students.queries import dashboard_snapshot
        data, queries = self.selects(lambda: dashboard_snapshot(self.student_user))
        self.assertEqual(data['eta']['status'], 'available')
        self.assertLessEqual(queries, 8, f'Live snapshot executed {queries} SELECT queries')

    def test_fleet_query_count_does_not_grow_per_bus(self):
        from admin_portal.queries import live_buses
        _, baseline = self.selects(live_buses)
        original = TripProgress.objects.get(trip__bus=self.bus)
        for i in range(6):
            user = get_user_model().objects.create_user(f'budget{i}@example.test', 'test123pass', full_name=f'Driver {i}', role='DRIVER')
            driver = Driver.objects.create(user=user, license_number=f'BUDGET{i}', phone='123')
            bus = Bus.objects.create(bus_number=f'QB{i}', registration_number=f'QBREG{i}', capacity=30)
            DriverAssignment.objects.create(driver=driver, bus=bus, route=self.route)
            trip = Trip.objects.create(bus=bus, driver=driver, route=self.route, trip_type='PICKUP', status='ACTIVE', start_time=timezone.now())
            stamp = timezone.now()
            BusLocation.objects.create(bus=bus, trip=trip, latitude=12, longitude=77.001, speed=5, accuracy=5, recorded_at=stamp)
            TripProgress.objects.create(trip=trip, geometry_signature=original.geometry_signature, distance_m=0, status='tracking', recorded_at=stamp, smoothed_speed_mps=5)
        rows, grown = self.selects(live_buses)
        self.assertEqual(len(rows), 8)
        self.assertLessEqual(grown, baseline+1, f'Fleet query count grew from {baseline} to {grown}')
        self.assertLessEqual(grown, 6)
