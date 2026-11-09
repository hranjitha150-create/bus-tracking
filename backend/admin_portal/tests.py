import csv
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import AccessToken
from assignments.models import StudentBusAssignment, DriverAssignment
from buses.models import Bus
from drivers.models import Driver
from students.models import Student
from routes.models import Route, BusStop, RouteStop
from routes.tests import synthetic_rows
from tracking.models import Trip, BusLocation
from tracking.tests import TransportTests
from . import services, queries


def csv_upload(rows=None):
    rows = rows if rows is not None else synthetic_rows()
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return SimpleUploadedFile('route.csv', stream.getvalue().encode(), content_type='text/csv')


class AdminPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        TransportTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.client.force_login(self.admin)

    def driver_payload(self, **extra):
        return {'full_name': 'New Driver', 'email': 'newdriver@example.test', 'password': 'XyZ!not-common-pass-483',
                'phone': '9876543210', 'license_number': 'NEWLICENSE', 'is_active': True, **extra}

    def student_payload(self, **extra):
        return {'full_name': 'New Student', 'email': 'newstudent@example.test', 'password': 'XyZ!not-common-pass-483',
                'phone': '9876543210', 'enrollment_number': 'NEWEN', 'department': 'ECE', 'semester': 2, 'is_active': True, **extra}

    def route_payload(self, **extra):
        return {'route_code': 'R002', 'route_name': 'Second route', 'start_location': 'Start', 'destination': 'Campus', 'direction': 'TO_COLLEGE', 'is_active': True, **extra}

    def test_bus_api_create_read_search_update_and_deactivate(self):
        response = self.api.post('/api/admin/buses/', {'bus_number': 'B3', 'registration_number': 'REG3', 'capacity': 30})
        self.assertEqual(response.status_code, 201, response.data)
        url = f'/api/admin/buses/{response.data["id"]}/'
        self.assertEqual(self.api.get(url).data['capacity'], 30)
        self.assertEqual(self.api.get('/api/admin/buses/?search=B3').data['count'], 1)
        self.assertEqual(self.api.patch(url, {'capacity': 35, 'is_active': False}).status_code, 200)
        self.assertFalse(Bus.objects.get(pk=response.data['id']).is_active)
        self.assertEqual(self.api.delete(url).status_code, 405)

    def test_bus_invalid_fields_and_duplicates(self):
        for payload in [{'bus_number': 'B3', 'registration_number': 'REG3', 'capacity': 0}, {'bus_number': 'B1', 'registration_number': 'REG3', 'capacity': 20}]:
            response = self.api.post('/api/admin/buses/', payload)
            self.assertEqual(response.status_code, 400)
            self.assertIn('detail', response.data)
            self.assertIn('errors', response.data)

    def test_driver_create_edit_deactivate_and_password_hidden(self):
        response = self.api.post('/api/admin/drivers/', self.driver_payload())
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('password', response.data)
        driver = Driver.objects.get(pk=response.data['id'])
        self.assertEqual(driver.user.role, 'DRIVER')
        self.assertTrue(driver.user.check_password(self.driver_payload()['password']))
        response = self.api.patch(f'/api/admin/drivers/{driver.pk}/', {'full_name': 'Edited Driver', 'is_active': False})
        self.assertEqual(response.status_code, 200, response.data)
        driver.refresh_from_db()
        self.assertFalse(driver.user.is_active)

    def test_student_registration_validation_and_atomic_account_creation(self):
        response = self.api.post('/api/admin/students/', self.student_payload())
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Student.objects.get(pk=response.data['id']).user.role, 'STUDENT')
        for payload in [self.student_payload(email='other@example.test'), self.student_payload(email='STUDENT@example.test', enrollment_number='OTHER'), self.student_payload(password='123')]:
            self.assertEqual(self.api.post('/api/admin/students/', payload).status_code, 400)
        self.assertFalse(get_user_model().objects.filter(email='other@example.test').exists())

    def test_failed_profile_save_rolls_back_user(self):
        with patch('students.models.Student.save', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                services.save_person('student', self.student_payload())
        self.assertFalse(get_user_model().objects.filter(email='newstudent@example.test').exists())

    def test_account_password_change_revokes_tokens(self):
        AccessToken.issue(self.student_user)
        response = self.api.patch(f'/api/admin/students/{self.student.pk}/', {'password': 'Different!secure-password483'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(AccessToken.objects.filter(user=self.student_user).exists())

    def test_student_assignment_invalid_stop_preserves_old_assignment(self):
        stop = BusStop.objects.create(name='Not on route', latitude=12, longitude=72)
        response = self.api.post('/api/admin/assignments/', {'kind': 'student', 'student': self.student.pk, 'bus': self.other_bus.pk, 'pickup_stop': stop.pk})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertTrue(StudentBusAssignment.objects.get(pk=self.assignment.pk).is_active)
        self.assertEqual(StudentBusAssignment.objects.filter(student=self.student, is_active=True).count(), 1)

    def test_student_assignment_change_retains_history(self):
        response = self.api.post('/api/admin/assignments/', {'kind': 'student', 'student': self.student.pk, 'bus': self.other_bus.pk, 'pickup_stop': self.stop.pk})
        self.assertEqual(response.status_code, 201, response.data)
        self.assignment.refresh_from_db()
        self.assertFalse(self.assignment.is_active)
        self.assertEqual(StudentBusAssignment.objects.get(student=self.student, is_active=True).bus, self.other_bus)

    def test_capacity_and_inactive_students(self):
        self.other_bus.capacity = 1
        self.other_bus.save()
        extra = services.save_person('student', self.student_payload())
        services.assign_student(extra, self.other_bus, self.stop)
        with self.assertRaises(ValidationError):
            services.assign_student(self.student, self.other_bus, self.stop)
        self.student_user.is_active = False
        self.student_user.save()
        with self.assertRaises(ValidationError):
            services.assign_student(self.student, self.bus, self.stop)

    def test_driver_assignment_conflict_and_replacement(self):
        response = self.api.post('/api/admin/assignments/', {'kind': 'driver', 'driver': self.driver.pk, 'bus': self.other_bus.pk, 'route': self.route.pk})
        self.assertEqual(response.status_code, 400)
        replacement = services.save_person('driver', self.driver_payload())
        response = self.api.post('/api/admin/assignments/', {'kind': 'driver', 'driver': replacement.pk, 'bus': self.bus.pk, 'route': self.route.pk})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.bus.driver_assignments.filter(is_active=True).get().driver, replacement)
        self.assertEqual(self.bus.driver_assignments.count(), 2)

    def test_route_change_cannot_orphan_pickups(self):
        route = services.save_route(self.route_payload())
        response = self.api.post('/api/admin/assignments/', {'kind': 'driver', 'driver': self.driver.pk, 'bus': self.bus.pk, 'route': route.pk})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(DriverAssignment.objects.get(pk=self.driver_assignment.pk).is_active)

    def test_assignment_required_relationships(self):
        response = self.api.post('/api/admin/assignments/', {'kind': 'student', 'bus': self.bus.pk})
        self.assertEqual(response.status_code, 400)
        self.assertIn('pickup_stop', response.data['errors'])

    def test_driver_deactivation_protected_until_replaced(self):
        response = self.api.patch(f'/api/admin/drivers/{self.driver.pk}/', {'is_active': False})
        self.assertEqual(response.status_code, 400)
        self.driver_user.refresh_from_db()
        self.assertTrue(self.driver_user.is_active)

    def test_bus_deactivation_ends_assignments_cancels_scheduled(self):
        response = self.api.patch(f'/api/admin/buses/{self.bus.pk}/', {'is_active': False})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(self.bus.student_assignments.filter(is_active=True).exists())
        self.assertFalse(self.bus.driver_assignments.filter(is_active=True).exists())
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'CANCELLED')

    def test_active_trip_protects_bus_driver_route_and_stops(self):
        self.trip.status, self.trip.start_time = 'ACTIVE', timezone.now()
        self.trip.save()
        for url in [f'/api/admin/buses/{self.bus.pk}/', f'/api/admin/drivers/{self.driver.pk}/', f'/api/admin/routes/{self.route.pk}/']:
            self.assertEqual(self.api.patch(url, {'is_active': False}).status_code, 400)
        with self.assertRaises(ValidationError):
            services.reorder_stops(self.route, [self.stop.pk])
        with self.assertRaises(ValidationError):
            services.remove_stop(self.route, self.stop)

    def test_pickup_endpoint_and_form_scope(self):
        outsider = BusStop.objects.create(name='Outside', latitude=12, longitude=72)
        response = self.api.get(f'/api/admin/pickup-stops/?bus={self.bus.pk}')
        self.assertEqual([s['id'] for s in response.data['results']], [self.stop.pk])
        response = self.client.post('/portal/assignments/student/add/', {'student': self.student.pk, 'bus': self.bus.pk, 'pickup_stop': outsider.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)

    def test_route_crud_stable_code_and_deactivation_protection(self):
        response = self.api.post('/api/admin/routes/', self.route_payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        pk = response.data['id']
        self.assertEqual(self.api.patch(f'/api/admin/routes/{pk}/', {'route_code': 'RENAMED'}).status_code, 400)
        self.assertEqual(self.api.patch(f'/api/admin/routes/{pk}/', {'route_name': 'Edited'}).status_code, 200)
        self.assertEqual(self.api.patch(f'/api/admin/routes/{self.route.pk}/', {'is_active': False}).status_code, 400)
        self.assertEqual(self.api.patch(f'/api/admin/routes/{pk}/', {'is_active': False}).status_code, 200)

    def test_stop_create_edit_reorder_and_remove(self):
        data = {'name': 'Second test stop', 'latitude': '11.0000000', 'longitude': '71.0000000', 'address': 'Test address', 'stop_order': 1}
        response = self.client.post(f'/portal/routes/{self.route.pk}/stops/add/', data)
        self.assertEqual(response.status_code, 302)
        stop = BusStop.objects.get(name=data['name'])
        self.assertEqual(list(self.route.route_stops.values_list('stop_id', flat=True)), [stop.pk, self.stop.pk])
        response = self.client.post(f'/portal/routes/{self.route.pk}/stops/{stop.pk}/edit/', {**data, 'name': 'Edited stop'})
        self.assertEqual(response.status_code, 302)
        self.client.post(f'/portal/routes/{self.route.pk}/stops/reorder/', {f'order_{self.stop.pk}': 1, f'order_{stop.pk}': 2})
        self.assertEqual(list(self.route.route_stops.values_list('stop_id', flat=True)), [self.stop.pk, stop.pk])
        self.assertEqual(self.client.post(f'/portal/routes/{self.route.pk}/stops/{stop.pk}/remove/').status_code, 302)
        self.assertEqual(self.route.route_stops.count(), 1)
        self.assertTrue(BusStop.objects.filter(pk=stop.pk).exists())

    def test_remove_assigned_stop_rolls_back(self):
        with self.assertRaises(ValidationError):
            services.remove_stop(self.route, self.stop)
        self.assertTrue(self.route.route_stops.filter(stop=self.stop).exists())

    def test_invalid_reordering_preserves_order(self):
        with self.assertRaises(ValidationError):
            services.reorder_stops(self.route, [])
        self.assertEqual(self.route.route_stops.count(), 1)

    def test_csv_api_import_idempotent(self):
        # Existing fixture assignment would be orphaned by the authoritative import;
        # end it before replacing R001's stop list.
        StudentBusAssignment.objects.update(is_active=False)
        for _ in range(2):
            response = self.api.post('/api/admin/routes/import/', {'file': csv_upload()}, format='multipart')
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Route.objects.filter(route_code='R001').count(), 1)
        self.assertEqual(self.route.route_stops.count(), 21)
        self.assertEqual(BusStop.objects.count(), 22)  # old referenced fixture stop retained
        self.assertEqual(self.route.route_stops.first().stop.name, 'NIE Golden Jubilee')

    def test_csv_api_rejects_invalid_and_orphaning_imports(self):
        response = self.api.post('/api/admin/routes/import/', {'file': csv_upload()}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.route.route_stops.count(), 1)
        rows = synthetic_rows()
        rows[5]['latitude'] = 'invalid'
        response = self.api.post('/api/admin/routes/import/', {'file': csv_upload(rows)}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.route.route_stops.count(), 1)

    def test_csv_web_import_feedback(self):
        StudentBusAssignment.objects.update(is_active=False)
        response = self.client.post('/portal/routes/import/', {'file': csv_upload(), 'direction': 'TO_COLLEGE'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '21 ordered stops')

    def test_shared_csv_headers_import_through_api_and_admin_form(self):
        StudentBusAssignment.objects.update(is_active=False)
        rows = [dict(route_id='R001', stop_order_shared=row['stop_order'], stop_name=row['name'],
                     latitude=row['latitude'], longitude=row['longitude'], notes='Source observation')
                for row in synthetic_rows()]
        response = self.api.post('/api/admin/routes/import/', {'file': csv_upload(rows)}, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post('/portal/routes/import/', {
            'file': csv_upload(rows), 'direction': 'FROM_COLLEGE',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '21 ordered stops')
        self.route.refresh_from_db()
        self.assertEqual(self.route.direction, 'FROM_COLLEGE')
        self.assertEqual(self.route.route_stops.count(), 21)
        self.assertEqual(self.route.route_stops.first().stop.original_metadata['notes'], 'Source observation')

    def test_live_map_uses_only_recorded_positions(self):
        response = self.api.get('/api/admin/live-buses/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        self.assertIsNone(response.data['results'][0]['latitude'])
        self.assertEqual(response.data['results'][0]['gps_status'], 'not_started')
        self.trip.status, self.trip.start_time = 'ACTIVE', timezone.now()
        self.trip.save()
        self.assertEqual(queries.live_buses()[0]['gps_status'], 'unavailable')
        location = BusLocation.objects.create(bus=self.bus, trip=self.trip, latitude=10, longitude=70)
        self.assertEqual(queries.live_buses()[0]['gps_status'], 'live')
        BusLocation.objects.filter(pk=location.pk).update(recorded_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(queries.live_buses()[0]['gps_status'], 'stale')
        self.assertEqual(queries.dashboard_data()['stale_buses'][0]['id'], self.bus.pk)

    def test_old_trip_position_cannot_appear_live_for_new_trip(self):
        self.trip.status, self.trip.start_time, self.trip.end_time = 'COMPLETED', timezone.now() - timedelta(hours=1), timezone.now()
        self.trip.save()
        BusLocation.objects.create(bus=self.bus, trip=self.trip, latitude=10, longitude=70)
        Trip.objects.create(bus=self.bus, driver=self.driver, route=self.route, trip_type='PICKUP', status='ACTIVE', start_time=timezone.now())
        self.assertEqual(queries.live_buses()[0]['gps_status'], 'unavailable')

    def test_dashboard_real_statistics(self):
        response = self.client.get('/dashboard/admin/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['counts'], {'buses': 2, 'drivers': 2, 'students': 1, 'routes': 1, 'active_trips': 0, 'completed_trips': 0})
        self.assertContains(response, 'Fleet status')

    def test_all_admin_html_pages_render(self):
        urls = ['/portal/', '/portal/map/', f'/portal/map/?route={self.route.pk}', '/portal/assignments/', '/portal/assignments/student/add/', '/portal/assignments/driver/add/', '/portal/routes/import/', f'/portal/routes/{self.route.pk}/stops/add/', f'/portal/routes/{self.route.pk}/stops/{self.stop.pk}/edit/']
        for entity, obj in [('buses', self.bus), ('drivers', self.driver), ('students', self.student), ('routes', self.route)]:
            urls.extend([f'/portal/{entity}/', f'/portal/{entity}/add/', f'/portal/{entity}/{obj.pk}/', f'/portal/{entity}/{obj.pk}/edit/', f'/portal/{entity}/{obj.pk}/deactivate/'])
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_bus_and_person_html_creation_and_invalid_feedback(self):
        self.assertEqual(self.client.post('/portal/buses/add/', {'bus_number': 'WEB', 'registration_number': 'WEBREG', 'capacity': 40, 'is_active': 'on'}).status_code, 302)
        self.assertEqual(self.client.post('/portal/students/add/', self.student_payload()).status_code, 302)
        response = self.client.post('/portal/drivers/add/', self.driver_payload(password='123'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(get_user_model().objects.filter(email='newdriver@example.test').exists())

    def test_api_pagination_search(self):
        response = self.api.get('/api/admin/students/?search=CSE')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)

    def test_end_assignment_api_and_history(self):
        response = self.api.post(f'/api/admin/assignments/driver/{self.driver_assignment.pk}/end/')
        self.assertEqual(response.status_code, 400)
        response = self.api.post(f'/api/admin/assignments/student/{self.assignment.pk}/end/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_active'])
        self.assertEqual(self.api.post(f'/api/admin/assignments/driver/{self.driver_assignment.pk}/end/').status_code, 200)

    def test_cross_role_all_admin_apis(self):
        endpoints = ['/api/admin/buses/', '/api/admin/students/', '/api/admin/drivers/', '/api/admin/routes/', '/api/admin/routes/import/', '/api/admin/assignments/', '/api/admin/live-buses/', '/api/admin/pickup-stops/']
        for user in [None, self.student_user, self.driver_user]:
            client = APIClient()
            if user:
                client.force_authenticate(user)
            expected = 403 if user else 401
            for endpoint in endpoints:
                for method in ('get', 'post'):
                    with self.subTest(user=user, endpoint=endpoint, method=method):
                        self.assertEqual(getattr(client, method)(endpoint, {}).status_code, expected)
            for endpoint in [f'/api/admin/buses/{self.bus.pk}/', f'/api/admin/students/{self.student.pk}/', f'/api/admin/drivers/{self.driver.pk}/', f'/api/admin/routes/{self.route.pk}/']:
                self.assertEqual(client.patch(endpoint, {'is_active': False}).status_code, expected)

    def test_cross_role_html_pages(self):
        for user in [self.student_user, self.driver_user]:
            self.client.force_login(user)
            for url in ['/portal/', '/dashboard/admin/', '/portal/buses/', '/portal/students/add/', '/portal/drivers/add/', '/portal/routes/import/', '/portal/assignments/student/add/', '/portal/map/']:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/portal/').status_code, 302)

    def test_admin_session_posts_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post('/portal/buses/add/', {}).status_code, 403)
        self.assertEqual(client.post('/api/admin/buses/', {}, content_type='application/json').status_code, 403)
