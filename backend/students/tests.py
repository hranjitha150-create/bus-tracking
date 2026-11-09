import csv
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from assignments.models import StudentBusAssignment, DriverAssignment
from admin_portal.services import import_r001, assign_student
from routes.geometry import geometry_for_stops
from routes.management.commands.import_bus_route import read_stops
from routes.models import Route
from routes.tests import synthetic_rows
from tracking.models import BusLocation, Trip
from tracking.tests import TransportTests
from .queries import dashboard_snapshot


def student_fixture(cls):
    """21-stop synthetic CSV fixture; never application route seed data."""
    TransportTests.setUpTestData.__func__(cls)
    StudentBusAssignment.objects.update(is_active=False)
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'test.csv'
        rows = synthetic_rows()
        with path.open('w', encoding='utf-8', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        import_r001(read_stops(path), 'TO_COLLEGE')
    cls.pickup = cls.route.route_stops.get(stop_order=7).stop
    cls.assignment = assign_student(cls.student, cls.bus, cls.pickup)


class GeometryTests(SimpleTestCase):
    stops = [{'longitude': 70, 'latitude': 10}, {'longitude': 71, 'latitude': 11}]

    def test_approximation_is_explicit(self):
        result = geometry_for_stops({}, self.stops)
        self.assertEqual(result['geometry_status'], 'approximate')
        self.assertTrue(result['is_approximate'])
        self.assertIn('not a verified driving route', result['geometry_label'])
        self.assertEqual(result['geometry']['coordinates'], [[70, 10], [71, 11]])

    def test_stored_osrm_compatible_linestring(self):
        geometry = {'type': 'LineString', 'coordinates': [[70, 10], [70.5, 10.8], [71, 11]]}
        result = geometry_for_stops(geometry, self.stops)
        self.assertEqual(result['geometry'], geometry)
        self.assertFalse(result['is_approximate'])

    def test_invalid_geometry_falls_back(self):
        for value in (None, [], {'type': 'Polygon'}, {'type': 'LineString', 'coordinates': [[999, 10], [71, 11]]}):
            result = geometry_for_stops(value, self.stops)
            self.assertEqual(result['geometry_status'], 'invalid')
            self.assertTrue(result['is_approximate'])

    def test_no_geometry_or_stop_coordinates(self):
        self.assertIsNone(geometry_for_stops({}, [])['geometry'])
        self.assertEqual(geometry_for_stops({}, [])['geometry_status'], 'unavailable')


class StudentPortalTests(TestCase):
    endpoints = ['/api/student/dashboard/', '/api/student/my-bus/', '/api/student/my-route/',
                 '/api/student/my-bus/location/', '/api/student/my-bus/eta/']
    pages = ['/dashboard/student/', '/student/', '/student/bus/', '/student/tracking/', '/student/route/', '/student/pickup/', '/student/profile/']

    @classmethod
    def setUpTestData(cls):
        student_fixture(cls)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.student_user)
        self.client.force_login(self.student_user)

    def active_trip(self):
        self.trip.status, self.trip.start_time = 'ACTIVE', timezone.now()
        self.trip.save()
        return self.trip

    def create_location(self, **extra):
        return BusLocation.objects.create(bus=self.bus, trip=self.trip, latitude=10, longitude=70, **extra)

    def test_dashboard_own_bus_and_profile(self):
        response = self.api.get('/api/student/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['bus']['id'], self.bus.pk)
        self.assertEqual(response.data['student']['enrollment_number'], 'EN1')
        self.assertEqual(response.data['pickup_stop']['id'], self.pickup.pk)
        self.assertNotIn('password', str(response.data))
        self.assertNotIn(self.driver_user.email, str(response.data))
        self.assertIn('no-store', response['Cache-Control'])

    def test_query_parameters_cannot_select_other_bus_or_route(self):
        other = Route.objects.create(route_code='OTHER', route_name='Hidden route', start_location='Hidden start', destination='Hidden end', direction='TO_COLLEGE')
        for endpoint in self.endpoints:
            response = self.api.get(endpoint, {'bus': self.other_bus.pk, 'bus_id': self.other_bus.pk, 'route_id': other.pk, 'student': 99999})
            self.assertEqual(response.status_code, 200)
            if endpoint.endswith('/eta/'):
                self.assertEqual(response.data['bus_id'], self.bus.pk)
            else:
                self.assertEqual(response.data['bus']['id'], self.bus.pk)
                self.assertEqual(response.data['route']['id'], self.route.pk)
            self.assertNotIn('Hidden route', str(response.data))
        self.assertEqual(self.api.get(f'/api/student/my-bus/{self.other_bus.pk}/location/').status_code, 404)

    def test_legacy_bus_and_trip_endpoints_still_reject_other_bus(self):
        self.assertEqual(self.api.get(f'/api/buses/{self.other_bus.pk}/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/buses/{self.other_bus.pk}/location/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/trips/{self.other_trip.pk}/').status_code, 404)
        self.assertEqual(self.api.get('/api/buses/').data['count'], 1)

    def test_all_21_csv_stops_in_correct_order(self):
        data = self.api.get('/api/student/my-route/').data['route']
        self.assertEqual(data['stop_count'], 21)
        self.assertEqual([s['order'] for s in data['stops']], list(range(1, 22)))
        self.assertEqual(data['stops'][0]['name'], 'NIE Golden Jubilee')
        self.assertEqual(data['stops'][-1]['name'], 'North Campus Last Stop')
        self.assertAlmostEqual(data['stops'][0]['latitude'], 10.1234567)
        self.assertEqual(data['start_stop_id'], data['stops'][0]['id'])
        self.assertEqual(data['destination_stop_id'], data['stops'][-1]['id'])

    def test_map_html_and_pickup_highlight(self):
        response = self.client.get('/student/route/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="student-map"')
        self.assertContains(response, 'class="route-stop', count=21)
        self.assertContains(response, 'is-pickup')
        self.assertContains(response, 'YOUR PICKUP')
        self.assertContains(response, 'NIE Golden Jubilee')
        self.assertContains(response, 'North Campus Last Stop')

    def test_no_assignment_all_endpoints_and_pages(self):
        StudentBusAssignment.objects.filter(student=self.student).update(is_active=False)
        for endpoint in self.endpoints:
            response = self.api.get(endpoint)
            self.assertEqual(response.status_code, 200)
            if endpoint.endswith('/eta/'):
                self.assertEqual(response.data['status'], 'unavailable')
                self.assertIsNone(response.data['bus_id'])
            else:
                self.assertEqual(response.data['status'], 'unassigned')
                self.assertIsNone(response.data['bus'])
        for page in self.pages:
            self.assertEqual(self.client.get(page).status_code, 200)
        self.assertContains(self.client.get('/student/'), 'No bus is assigned')

    def test_profile_missing_is_clear_and_does_not_crash(self):
        user = get_user_model().objects.create_user('no-profile@example.test', 'password123', full_name='No Profile', role='STUDENT')
        self.api.force_authenticate(user)
        response = self.api.get('/api/student/dashboard/')
        self.assertEqual(response.data['status'], 'profile_unavailable')
        self.assertIsNone(response.data['bus'])
        self.client.force_login(user)
        self.assertEqual(self.client.get('/dashboard/student/').status_code, 200)

    def test_inactive_bus_is_not_returned(self):
        self.bus.is_active = False
        self.bus.save()
        data = self.api.get('/api/student/dashboard/').data
        self.assertEqual(data['status'], 'unassigned')
        self.assertIsNone(data['bus'])
        self.assertIsNone(data['route'])

    def test_revoked_or_changed_assignment_updates_next_snapshot(self):
        assign_student(self.student, self.other_bus, self.pickup)
        data = self.api.get('/api/student/my-bus/location/').data
        self.assertEqual(data['bus']['id'], self.other_bus.pk)
        self.assertEqual(self.api.get(f'/api/buses/{self.bus.pk}/location/').status_code, 404)

    def test_route_unavailable(self):
        DriverAssignment.objects.filter(bus=self.bus).update(is_active=False)
        data = self.api.get('/api/student/dashboard/').data
        self.assertEqual(data['status'], 'assigned')
        self.assertIsNone(data['route'])
        self.assertIsNone(data['pickup_stop'])
        self.assertEqual(data['eta']['reason'], 'route_unavailable')

    def test_no_active_trip_does_not_fabricate_gps_or_eta(self):
        data = self.api.get('/api/student/dashboard/').data
        self.assertIsNone(data['location'])
        self.assertIsNone(data['active_trip'])
        self.assertEqual(data['gps']['status'], 'no_active_trip')
        self.assertEqual(data['eta']['status'], 'unavailable')
        self.assertIsNone(data['eta']['seconds'])

    def test_active_trip_waiting_for_gps(self):
        self.active_trip()
        data = self.api.get('/api/student/my-bus/location/').data
        self.assertEqual(data['trip_status'], 'ACTIVE')
        self.assertIsNone(data['location'])
        self.assertEqual(data['gps']['status'], 'unavailable')

    def test_fresh_location_and_phase5_eta_integration(self):
        self.active_trip()
        self.create_location(accuracy=5)
        data = self.api.get('/api/student/dashboard/').data
        self.assertEqual(data['gps']['status'], 'fresh')
        self.assertTrue(data['location']['is_live'])
        self.assertEqual(data['eta']['reason'], 'geometry_unavailable')
        self.assertEqual(data['eta']['status'], 'unavailable')
        with patch('eta.services.estimate_pickup_eta', return_value={'status': 'available', 'seconds': 120, 'arrival_at': None, 'message': 'Test provider'}) as provider:
            response = self.api.get('/api/student/my-bus/eta/')
            self.assertEqual(response.data['seconds'], 120)
            self.assertEqual(provider.call_args.kwargs['pickup_stop'].pk, self.pickup.pk)

    def test_stale_recorded_and_received_timestamps(self):
        self.active_trip()
        location = self.create_location()
        for field in ('recorded_at', 'received_at'):
            BusLocation.objects.filter(pk=location.pk).update(recorded_at=timezone.now(), received_at=timezone.now())
            BusLocation.objects.filter(pk=location.pk).update(**{field: timezone.now() - timedelta(minutes=5)})
            with patch('eta.services.estimate_pickup_eta') as provider:
                data = self.api.get('/api/student/my-bus/location/').data
                self.assertEqual(data['gps']['status'], 'stale')
                self.assertFalse(data['location']['is_live'])
                self.assertIsNone(data['eta']['seconds'])
                provider.assert_not_called()

    def test_future_timestamp_is_not_live(self):
        self.active_trip()
        self.create_location(recorded_at=timezone.now() + timedelta(minutes=5))
        data = self.api.get('/api/student/dashboard/').data
        self.assertEqual(data['gps']['status'], 'invalid_timestamp')
        self.assertFalse(data['gps']['is_fresh'])

    def test_completed_trip_position_is_labeled_historical(self):
        self.active_trip()
        self.create_location()
        self.trip.status, self.trip.end_time = 'COMPLETED', timezone.now()
        self.trip.save()
        data = self.api.get('/api/student/dashboard/').data
        self.assertEqual(data['trip_status'], 'COMPLETED')
        self.assertEqual(data['gps']['status'], 'completed')
        self.assertFalse(data['location']['is_live'])
        self.assertIsNone(data['eta']['seconds'])

    def test_old_trip_sample_never_becomes_new_trip_location(self):
        self.active_trip()
        self.create_location()
        self.trip.status, self.trip.end_time = 'COMPLETED', timezone.now()
        self.trip.save()
        Trip.objects.create(bus=self.bus, driver=self.driver, route=self.route, trip_type='DROP', status='ACTIVE', start_time=timezone.now())
        data = self.api.get('/api/student/my-bus/location/').data
        self.assertIsNone(data['location'])
        self.assertEqual(data['gps']['status'], 'unavailable')

    def test_geometry_corruption_is_safe(self):
        Route.objects.filter(pk=self.route.pk).update(geometry={'type': 'Polygon'})
        data = self.api.get('/api/student/my-route/').data['route']
        self.assertEqual(data['geometry_status'], 'invalid')
        self.assertTrue(data['is_approximate'])
        self.assertEqual(len(data['geometry']['coordinates']), 21)

    def test_all_student_pages_render_and_no_arbitrary_bus_selection(self):
        for page in self.pages:
            response = self.client.get(page, {'bus_id': self.other_bus.pk})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['snapshot']['bus']['id'], self.bus.pk)
            self.assertNotContains(response, self.other_bus.registration_number)
            self.assertIn('no-store', response['Cache-Control'])

    @override_settings(STUDENT_POLL_INTERVAL_SECONDS=15)
    def test_configurable_polling(self):
        self.assertEqual(self.api.get('/api/student/dashboard/').data['poll_interval_seconds'], 15)

    def test_student_api_uses_session_auth_and_is_read_only(self):
        self.assertEqual(self.client.get('/api/student/my-bus/').status_code, 200)
        for endpoint in self.endpoints:
            self.assertEqual(self.api.post(endpoint, {}).status_code, 405)

    def test_other_roles_and_anonymous_cannot_use_student_portal(self):
        for user in (None, self.admin, self.driver_user):
            self.api.force_authenticate(user)
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            for endpoint in self.endpoints:
                self.assertEqual(self.api.get(endpoint).status_code, 403 if user else 401)
            for page in self.pages:
                self.assertEqual(self.client.get(page).status_code, 403 if user else 302)

    def test_student_still_cannot_use_admin_endpoints(self):
        for endpoint in ['/api/admin/buses/', '/api/admin/students/', '/api/admin/drivers/', '/api/admin/routes/', '/api/admin/routes/import/', '/api/admin/assignments/', '/api/admin/live-buses/']:
            self.assertEqual(self.api.get(endpoint).status_code, 403)
            self.assertEqual(self.api.post(endpoint, {}).status_code, 403)
        self.assertEqual(self.client.get('/dashboard/admin/').status_code, 403)
