import csv
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from assignments.models import StudentBusAssignment
from routes.models import Route, BusStop
from tracking.models import Trip
from tracking.tests import TransportTests
from . import services
from .uploads import import_route_upload


def upload(code='R200', count=3):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=['route_id', 'stop_order_shared', 'stop_name', 'latitude', 'longitude', 'notes'])
    writer.writeheader()
    for number in range(1, count + 1):
        writer.writerow(dict(route_id=code, stop_order_shared=number, stop_name=f'Campus stop {number}',
            latitude=f'10.{number}', longitude=f'70.{number}', notes='Source observation'))
    return SimpleUploadedFile('route.csv', output.getvalue().encode(), content_type='text/csv')


class RouteWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        TransportTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_csv_creates_any_route_and_is_idempotent(self):
        for _ in range(2):
            route = import_route_upload(upload(), 'TO_COLLEGE', route_name='Town to college')
        self.assertEqual(route.route_code, 'R200')
        self.assertEqual(route.route_name, 'Town to college')
        self.assertEqual(route.start_location, 'Campus stop 1')
        self.assertEqual(route.destination, 'Campus stop 3')
        self.assertEqual(route.route_stops.count(), 3)
        self.assertEqual(route.route_stops.first().stop.original_metadata['notes'], 'Source observation')
        self.assertEqual(Route.objects.filter(route_code='R200').count(), 1)

    def test_global_import_form_infers_route_code(self):
        response = self.client.post('/portal/routes/import/', {'file': upload(), 'direction': 'TO_COLLEGE'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '3 ordered stops')
        self.assertTrue(Route.objects.filter(route_code='R200').exists())

    def test_general_import_copies_source_r001_to_explicit_r003(self):
        original_stop_ids = list(self.route.route_stops.values_list('stop_id', flat=True))
        response = self.client.post('/portal/routes/import/', {
            'file': upload('R001'), 'direction': 'FROM_COLLEGE',
            'route_code': 'R003', 'route_name': 'NIE',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '3 ordered stops')
        route = Route.objects.get(route_code='R003')
        self.assertEqual(route.route_name, 'NIE')
        self.assertEqual(route.direction, 'FROM_COLLEGE')
        self.assertEqual(route.route_stops.count(), 3)
        self.assertEqual(route.route_stops.first().stop.original_metadata['route_id'], 'R001')
        self.assertEqual(list(self.route.route_stops.values_list('stop_id', flat=True)), original_stop_ids)

    def test_assignment_form_names_the_route_and_route_link_prefills_it(self):
        response = self.client.get('/portal/assignments/student/add/')
        self.assertContains(response, f'{self.bus.bus_number} · {self.route.route_code}')
        response = self.client.get(f'/portal/assignments/driver/add/?route={self.route.pk}')
        self.assertEqual(str(response.context['form']['route'].value()), str(self.route.pk))

    def test_import_without_code_or_csv_route_id_requires_a_code(self):
        content = b'stop_order,name,latitude,longitude\n1,Start,12,76\n2,End,12.1,76.1\n'
        with self.assertRaisesMessage(ValidationError, 'Enter a route code'):
            import_route_upload(SimpleUploadedFile('route.csv', content), 'TO_COLLEGE')

    def test_students_cannot_add_stops_or_import_routes(self):
        self.client.force_login(self.student_user)
        self.assertEqual(self.client.get(f'/portal/routes/{self.route.pk}/stops/bulk/').status_code, 403)
        self.assertEqual(self.client.post('/portal/routes/import/', {'file': upload(), 'direction': 'TO_COLLEGE'}).status_code, 403)

    def test_generic_rest_import_infers_route_id(self):
        api = APIClient()
        api.force_authenticate(self.admin)
        response = api.post('/api/admin/routes/import/', {'file': upload()}, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['route']['route_code'], 'R200')
        self.assertEqual(len(response.data['route']['stops']), 3)

    def test_selected_r002_accepts_source_r001_and_ignores_posted_destination(self):
        target = Route.objects.create(route_code='R002', route_name='NIE',
            start_location='Start', destination='End', direction='FROM_COLLEGE')
        response = self.client.post(f'/portal/routes/{target.pk}/import/', {
            'file': upload('R001'), 'direction': 'FROM_COLLEGE', 'route_code': 'R200',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '3 ordered stops')
        self.assertEqual(target.route_stops.count(), 3)
        self.assertEqual(target.route_stops.first().stop.original_metadata['route_id'], 'R001')
        self.assertEqual(self.route.route_stops.count(), 1)
        self.assertFalse(Route.objects.filter(route_code='R200').exists())

    def test_selected_route_api_accepts_other_source_id(self):
        target = Route.objects.create(route_code='R003', route_name='NIE',
            start_location='Start', destination='End', direction='FROM_COLLEGE')
        api = APIClient()
        api.force_authenticate(self.admin)
        response = api.post(f'/api/admin/routes/{target.pk}/import-stops/', {
            'file': upload('R001'), 'direction': 'FROM_COLLEGE',
        }, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['route']['route_code'], 'R003')
        self.assertEqual(target.route_stops.count(), 3)

    def test_existing_pickup_protection_rolls_back_entire_import(self):
        with self.assertRaises(ValidationError):
            import_route_upload(upload('R001'), 'TO_COLLEGE')
        self.assertEqual(self.route.route_stops.count(), 1)
        self.assertFalse(BusStop.objects.filter(name='Campus stop 1').exists())

    def test_multiple_manual_stops_are_saved_together(self):
        rows = [dict(name=f'Manual {number}', latitude=11 + number, longitude=71, address='Test address') for number in (1, 2)]
        services.append_route_stops(self.route, rows)
        self.assertEqual(list(self.route.route_stops.values_list('stop_order', flat=True)), [1, 2, 3])
        self.assertEqual(list(self.route.route_stops.values_list('stop__name', flat=True))[1:], ['Manual 1', 'Manual 2'])

    def test_duplicate_manual_rows_roll_back(self):
        row = dict(name='Duplicate', latitude=12, longitude=71, address='')
        with self.assertRaises(ValidationError):
            services.append_route_stops(self.route, [row, row])
        self.assertFalse(BusStop.objects.filter(name='Duplicate').exists())
        self.assertEqual(self.route.route_stops.count(), 1)

    def test_bulk_form_rejects_invalid_coordinates_without_partial_save(self):
        response = self.client.post(f'/portal/routes/{self.route.pk}/stops/bulk/', {
            'stops-TOTAL_FORMS': 2, 'stops-INITIAL_FORMS': 0,
            'stops-0-name': 'Valid stop', 'stops-0-latitude': '12', 'stops-0-longitude': '76',
            'stops-1-name': 'Invalid stop', 'stops-1-latitude': '91', 'stops-1-longitude': '76',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BusStop.objects.filter(name='Valid stop').exists())
        self.assertEqual(self.route.route_stops.count(), 1)

    def test_bulk_form_saves_rows_in_order(self):
        response = self.client.post(f'/portal/routes/{self.route.pk}/stops/bulk/', {
            'stops-TOTAL_FORMS': 2, 'stops-INITIAL_FORMS': 0,
            'stops-0-name': 'First added', 'stops-0-latitude': '12', 'stops-0-longitude': '76',
            'stops-1-name': 'Second added', 'stops-1-latitude': '12.1', 'stops-1-longitude': '76.1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.route.route_stops.values_list('stop__name', flat=True))[1:], ['First added', 'Second added'])

    def test_active_trip_prevents_batch_stop_changes(self):
        Trip.objects.filter(pk=self.trip.pk).update(status='ACTIVE', start_time=timezone.now())
        with self.assertRaises(ValidationError):
            services.append_route_stops(self.route, [dict(name='New', latitude=12, longitude=76, address='')])
        self.assertFalse(BusStop.objects.filter(name='New').exists())

    def test_import_assignment_driver_gps_and_student_tracking(self):
        route = import_route_upload(upload(), 'TO_COLLEGE')
        StudentBusAssignment.objects.filter(student=self.student).update(is_active=False)
        services.assign_driver(self.driver, self.bus, route)
        pickup = route.route_stops.get(stop_order=2).stop
        services.assign_student(self.student, self.bus, pickup)
        api = APIClient()
        api.force_authenticate(self.driver_user)
        response = api.post('/api/driver/trips/start/', {}, format='json')
        self.assertIn(response.status_code, (200, 201), response.data)
        trip = response.data['trip']['id']
        response = api.post(f'/api/driver/trips/{trip}/location/', dict(
            latitude=10.1, longitude=70.1, accuracy=5, speed=0, recorded_at=timezone.now().isoformat()), format='json')
        self.assertIn(response.status_code, (200, 201), response.data)
        api.force_authenticate(self.student_user)
        response = api.get('/api/student/my-bus/location/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['route']['route_code'], 'R200')
        self.assertEqual(response.data['route']['stop_count'], 3)
        self.assertEqual(response.data['pickup_stop']['id'], pickup.pk)
        self.assertEqual(response.data['bus']['id'], self.bus.pk)
        self.assertEqual(response.data['location']['latitude'], 10.1)
        self.assertTrue(response.data['gps']['is_fresh'])
        self.assertFalse(response.data['location']['is_simulated'])
        api.force_authenticate(self.admin)
        fleet = api.get('/api/admin/live-buses/').data['results']
        self.assertEqual(next(bus for bus in fleet if bus['id'] == self.bus.pk)['gps_status'], 'live')
