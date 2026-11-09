from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.db import connections
from rest_framework.test import APIClient
from accounts.models import AccessToken
from assignments.models import DriverAssignment
from tracking.models import Trip, BusLocation, LocationHistory
from tracking.tests import TransportTests


class DriverAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        TransportTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.driver_user)

    def start(self):
        response = self.api.post('/api/driver/trips/start/', {})
        self.assertIn(response.status_code, (200, 201), response.data)
        self.trip.refresh_from_db()
        return response.data['trip']['id']

    def sample(self, **extra):
        return {'latitude': 12.123456789, 'longitude': 77.987654321, 'speed': 5.5, 'accuracy': 4.5,
                'recorded_at': timezone.now().isoformat(), **extra}

    def upload(self, pk, **extra):
        return self.api.post(f'/api/driver/trips/{pk}/location/', self.sample(**extra), format='json')

    def test_assignment_derived_from_driver_not_bus_query(self):
        response = self.api.get('/api/driver/assignment/', {'bus_id': self.other_bus.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['bus']['id'], self.bus.pk)
        self.assertEqual(response.data['driver']['full_name'], self.driver_user.full_name)
        self.assertEqual(response.data['route']['stops'][0]['order'], 1)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn(self.student_user.email, str(response.data))

    def test_missing_assignment_and_disabled_entities(self):
        DriverAssignment.objects.filter(driver=self.driver).update(is_active=False)
        self.assertEqual(self.api.get('/api/driver/assignment/').data['status'], 'unassigned')
        self.assertEqual(self.api.post('/api/driver/trips/start/', {}).status_code, 403)

    def test_start_activates_correct_scheduled_trip_and_is_idempotent(self):
        pk = self.start()
        self.assertEqual(pk, self.trip.pk)
        self.assertEqual(self.trip.status, 'ACTIVE')
        response = self.api.post('/api/driver/trips/start/', {'bus': self.other_bus.pk})
        self.assertEqual(response.data['trip']['id'], pk)
        self.assertEqual(Trip.objects.filter(bus=self.bus, status='ACTIVE').count(), 1)

    def test_start_creates_when_no_scheduled_trip(self):
        self.trip.status = 'CANCELLED'
        self.trip.save()
        response = self.api.post('/api/driver/trips/start/', {})
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data['trip']['id'], self.trip.pk)
        self.assertEqual(response.data['trip']['trip_type'], 'PICKUP')

    def test_start_derives_drop_direction(self):
        self.route.direction = 'FROM_COLLEGE'
        self.route.save()
        response = self.api.post('/api/driver/trips/start/', {})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['trip']['trip_type'], 'DROP')

    def test_conflicting_trip_does_not_get_hijacked(self):
        Trip.objects.create(bus=self.bus, driver=self.other_driver, route=self.route, trip_type='PICKUP', status='ACTIVE', start_time=timezone.now())
        self.assertEqual(self.api.post('/api/driver/trips/start/', {}).status_code, 409)

    def test_location_updates_latest_and_history_and_student_snapshot(self):
        pk = self.start()
        response = self.upload(pk)
        self.assertEqual(response.status_code, 201, response.data)
        latest = BusLocation.objects.get(bus=self.bus)
        self.assertEqual(str(latest.latitude), '12.1234568')
        self.assertEqual(str(latest.longitude), '77.9876543')
        self.assertEqual(LocationHistory.objects.filter(trip=self.trip).count(), 1)
        self.api.force_authenticate(self.student_user)
        data = self.api.get('/api/student/my-bus/location/').data
        self.assertTrue(data['gps']['is_fresh'])
        self.assertEqual(data['location']['trip_id'], pk)

    def test_duplicate_is_safe_after_newer_sample(self):
        pk = self.start()
        sample = self.sample()
        url = f'/api/driver/trips/{pk}/location/'
        first = self.api.post(url, sample, format='json')
        self.assertEqual(first.status_code, 201)
        received = BusLocation.objects.get().received_at
        second = self.api.post(url, sample, format='json')
        self.assertEqual(second.data['status'], 'duplicate')
        self.assertEqual(LocationHistory.objects.count(), 1)
        self.assertEqual(BusLocation.objects.get().received_at, received)
        newer = self.sample(latitude=12.1234568)
        self.assertEqual(self.api.post(url, newer, format='json').status_code, 201)
        self.assertEqual(self.api.post(url, sample, format='json').data['status'], 'duplicate')
        self.assertEqual(float(BusLocation.objects.get().latitude), 12.1234568)
        self.assertEqual(LocationHistory.objects.count(), 2)

    def test_same_timestamp_different_sample_is_rejected(self):
        pk = self.start()
        sample = self.sample()
        url = f'/api/driver/trips/{pk}/location/'
        self.api.post(url, sample, format='json')
        sample['latitude'] = 14
        self.assertEqual(self.api.post(url, sample, format='json').status_code, 409)
        self.assertEqual(LocationHistory.objects.count(), 1)

    def test_older_sample_never_overwrites_newer_position(self):
        pk = self.start()
        timestamp = timezone.now()
        self.assertEqual(self.upload(pk, recorded_at=timestamp.isoformat()).status_code, 201)
        response = self.upload(pk, latitude=14, recorded_at=(timestamp - timedelta(seconds=1)).isoformat())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'out_of_order')
        self.assertEqual(LocationHistory.objects.count(), 1)

    def test_bad_gps_fields_rejected_without_writes(self):
        pk = self.start()
        for payload in [{'latitude': 91}, {'longitude': 181}, {'speed': -1}, {'accuracy': -1},
                        {'latitude': 'NaN'}, {'latitude': True}, {'speed': 'Infinity'}, {'recorded_at': '2026-11-06T12:00:00'},
                        {'recorded_at': (timezone.now() + timedelta(minutes=5)).isoformat()},
                        {'recorded_at': (timezone.now() - timedelta(minutes=5)).isoformat()}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.upload(pk, **payload).status_code, 400)
        self.assertFalse(LocationHistory.objects.exists())
        self.assertFalse(BusLocation.objects.exists())

    def test_missing_required_gps_fields(self):
        pk = self.start()
        self.assertEqual(self.api.post(f'/api/driver/trips/{pk}/location/', {}, format='json').status_code, 400)

    def test_location_predating_trip_rejected(self):
        pk = self.start()
        self.assertEqual(self.upload(pk, recorded_at=(timezone.now() - timedelta(seconds=20)).isoformat()).status_code, 400)

    def test_only_owned_active_trip_can_receive_gps_or_end(self):
        for path in [f'/api/driver/trips/{self.other_trip.pk}/location/', f'/api/driver/trips/{self.other_trip.pk}/end/']:
            self.assertEqual(self.api.post(path, self.sample(), format='json').status_code, 404)
        self.assertEqual(self.upload(self.trip.pk).status_code, 409)

    def test_revoked_assignment_stops_uploads(self):
        pk = self.start()
        DriverAssignment.objects.filter(driver=self.driver).update(is_active=False)
        self.assertEqual(self.upload(pk).status_code, 403)
        self.assertFalse(LocationHistory.objects.exists())

    def test_end_is_idempotent_and_blocks_further_gps(self):
        pk = self.start()
        self.upload(pk)
        url = f'/api/driver/trips/{pk}/end/'
        first = self.api.post(url, {})
        self.assertEqual(first.data['trip']['status'], 'COMPLETED')
        end_time = first.data['trip']['end_time']
        self.assertEqual(self.api.post(url, {}).data['trip']['end_time'], end_time)
        self.assertEqual(self.upload(pk).status_code, 409)
        self.assertEqual(LocationHistory.objects.count(), 1)
        self.assertIsNone(self.api.get('/api/driver/assignment/').data['active_trip'])

    def test_location_and_history_are_atomic(self):
        pk = self.start()
        with patch('drivers.api.BusLocation.objects.create', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                self.upload(pk)
        self.assertFalse(LocationHistory.objects.exists())

    def test_real_login_bearer_expiry_and_logout(self):
        self.api.force_authenticate(None)
        response = self.api.post('/api/auth/login/', {'email': self.driver_user.email, 'password': 'password123'})
        self.assertEqual(response.status_code, 200)
        self.api.credentials(HTTP_AUTHORIZATION='Bearer ' + response.data['token'])
        self.assertEqual(self.api.get('/api/driver/assignment/').status_code, 200)
        self.assertEqual(self.api.post('/api/auth/logout/').status_code, 204)
        self.assertEqual(self.api.post('/api/driver/trips/start/', {}).status_code, 401)

    def test_expired_token_cannot_publish(self):
        self.api.force_authenticate(None)
        token, raw = AccessToken.issue(self.driver_user)
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save()
        self.api.credentials(HTTP_AUTHORIZATION='Bearer ' + raw)
        self.assertEqual(self.api.get('/api/driver/assignment/').status_code, 401)

    def test_student_admin_anonymous_denied(self):
        for user in [None, self.student_user, self.admin]:
            self.api.force_authenticate(user)
            expected = 403 if user else 401
            self.assertEqual(self.api.get('/api/driver/assignment/').status_code, expected)
            for path in ['/api/driver/trips/start/', f'/api/driver/trips/{self.trip.pk}/location/', f'/api/driver/trips/{self.trip.pk}/end/']:
                self.assertEqual(self.api.post(path, self.sample(), format='json').status_code, expected)


class ConcurrentDriverTests(TransactionTestCase):
    def setUp(self):
        TransportTests.setUpTestData.__func__(type('Fixture', (), {}))

    def test_concurrent_starts_reuse_one_active_trip(self):
        from concurrent.futures import ThreadPoolExecutor
        from accounts.models import CustomUser
        def start():
            try:
                client = APIClient()
                client.force_authenticate(CustomUser.objects.get(email='driver@example.test'))
                response = client.post('/api/driver/trips/start/', {})
                return response.status_code, response.data['trip']['id']
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: start(), range(2)))
        self.assertTrue(all(status in (200, 201) for status, pk in results))
        self.assertEqual(len({pk for status, pk in results}), 1)
        self.assertEqual(Trip.objects.filter(status='ACTIVE').count(), 1)
