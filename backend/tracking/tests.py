from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from students.models import Student
from drivers.models import Driver
from buses.models import Bus
from routes.models import Route, BusStop, RouteStop
from assignments.models import StudentBusAssignment, DriverAssignment
from .models import Trip, BusLocation, LocationHistory


class TransportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('admin@example.test', 'password123', full_name='Admin', role='ADMIN')
        cls.student_user = User.objects.create_user('student@example.test', 'password123', full_name='Student', role='STUDENT')
        cls.student = Student.objects.create(user=cls.student_user, enrollment_number='EN1', department='CSE', semester=1, phone='123')
        cls.driver_user = User.objects.create_user('driver@example.test', 'password123', full_name='Driver', role='DRIVER')
        cls.driver = Driver.objects.create(user=cls.driver_user, license_number='LICENSE1', phone='123')
        cls.other_driver_user = User.objects.create_user('driver2@example.test', 'password123', full_name='Driver 2', role='DRIVER')
        cls.other_driver = Driver.objects.create(user=cls.other_driver_user, license_number='LICENSE2', phone='123')
        cls.bus = Bus.objects.create(bus_number='B1', registration_number='REG1', capacity=40)
        cls.other_bus = Bus.objects.create(bus_number='B2', registration_number='REG2', capacity=40)
        cls.route = Route.objects.create(route_code='R001', route_name='Test route', start_location='Start', destination='End', direction='TO_COLLEGE')
        # These are synthetic test fixtures, not the mentor's route data.
        cls.stop = BusStop.objects.create(name='Synthetic Stop', latitude=10, longitude=70)
        RouteStop.objects.create(route=cls.route, stop=cls.stop, stop_order=1)
        cls.driver_assignment = DriverAssignment.objects.create(driver=cls.driver, bus=cls.bus, route=cls.route)
        DriverAssignment.objects.create(driver=cls.other_driver, bus=cls.other_bus, route=cls.route)
        cls.assignment = StudentBusAssignment.objects.create(student=cls.student, bus=cls.bus, pickup_stop=cls.stop)
        cls.trip = Trip.objects.create(bus=cls.bus, driver=cls.driver, route=cls.route, trip_type='PICKUP')
        cls.other_trip = Trip.objects.create(bus=cls.other_bus, driver=cls.other_driver, route=cls.route, trip_type='PICKUP')

    def setUp(self):
        self.api = APIClient()

    def test_student_only_assigned_bus(self):
        self.api.force_authenticate(self.student_user)
        response = self.api.get('/api/buses/')
        self.assertEqual([b['id'] for b in response.data['results']], [self.bus.id])
        self.assertEqual(self.api.get(f'/api/buses/{self.other_bus.pk}/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/buses/{self.other_bus.pk}/location/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/trips/{self.other_trip.pk}/').status_code, 404)
        self.assertEqual(self.api.post(f'/api/trips/{self.trip.pk}/start/').status_code, 403)
        self.assignment.is_active = False
        self.assignment.save()
        self.assertEqual(self.api.get('/api/buses/').data['count'], 0)

    def test_driver_authorization_and_transitions(self):
        self.api.force_authenticate(self.driver_user)
        self.assertEqual(self.api.post(f'/api/trips/{self.other_trip.pk}/start/').status_code, 404)
        self.assertEqual(self.api.patch(f'/api/trips/{self.trip.pk}/', {'bus': self.other_bus.pk}).status_code, 405)
        response = self.api.post(f'/api/trips/{self.trip.pk}/start/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'ACTIVE')
        self.assertEqual(self.api.post(f'/api/trips/{self.trip.pk}/start/').status_code, 400)
        self.assertEqual(self.api.post(f'/api/trips/{self.trip.pk}/complete/').data['status'], 'COMPLETED')

    def test_revoked_driver_assignment(self):
        self.api.force_authenticate(self.driver_user)
        self.driver_assignment.is_active = False
        self.driver_assignment.save()
        self.assertEqual(self.api.post(f'/api/trips/{self.trip.pk}/start/').status_code, 404)

    def test_admin_can_read_all_buses(self):
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.get('/api/buses/').data['count'], 2)

    def test_assignment_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentBusAssignment.objects.create(student=self.student, bus=self.other_bus, pickup_stop=self.stop)
        StudentBusAssignment.objects.create(student=self.student, bus=self.other_bus, pickup_stop=self.stop, is_active=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DriverAssignment.objects.create(driver=self.driver, bus=self.other_bus, route=self.route)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DriverAssignment.objects.create(driver=self.other_driver, bus=self.bus, route=self.route)

    def test_model_relationship_validation(self):
        self.assertEqual(self.student.user.role, 'STUDENT')
        self.assignment.full_clean()
        invalid = Student(user=self.driver_user, enrollment_number='BAD', department='CSE', semester=1, phone='123')
        with self.assertRaises(ValidationError):
            invalid.clean()
        self.trip.driver = self.other_driver
        with self.assertRaises(ValidationError):
            self.trip.clean()
        wrong_stop = BusStop.objects.create(name='Other synthetic stop', latitude=11, longitude=71)
        self.assignment.pickup_stop = wrong_stop
        with self.assertRaises(ValidationError):
            self.assignment.clean()

    def test_conflicting_active_trips_database(self):
        self.trip.status = 'ACTIVE'
        self.trip.start_time = timezone.now()
        self.trip.save()
        # Test bus and driver conflicts independently.
        for bus, driver in [(self.bus, self.other_driver), (self.other_bus, self.driver)]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Trip.objects.create(bus=bus, driver=driver, route=self.route, trip_type='DROP', status='ACTIVE', start_time=timezone.now())

    def test_trip_times_database(self):
        for fields in [{'status': 'ACTIVE'}, {'status': 'COMPLETED'}, {'status': 'GARBAGE'}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Trip.objects.filter(pk=self.trip.pk).update(**fields)

    def test_latest_location_uniqueness_and_history(self):
        data = dict(bus=self.bus, trip=self.trip, latitude=10, longitude=70, speed=5, accuracy=2)
        location = BusLocation.objects.create(**data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            BusLocation.objects.create(**data)
        for _ in range(2):
            LocationHistory.objects.create(**data)
        self.assertEqual(self.trip.location_history.count(), 2)
        self.assertTrue(timezone.is_aware(location.recorded_at))
        self.assertTrue(timezone.is_aware(location.received_at))
        location.bus = self.other_bus
        with self.assertRaises(ValidationError):
            location.clean()

    def test_location_ranges_database(self):
        for values in [{'latitude': 91, 'longitude': 70}, {'latitude': 10, 'longitude': 181}, {'latitude': 10, 'longitude': 70, 'speed': -1}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                LocationHistory.objects.create(bus=self.bus, trip=self.trip, **values)

    def test_location_trip_bus_integrity_database(self):
        for model in (BusLocation, LocationHistory):
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.create(bus=self.other_bus, trip=self.trip, latitude=10, longitude=70)

    def test_stop_order_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            RouteStop.objects.create(route=self.route, stop=self.stop, stop_order=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RouteStop.objects.create(route=self.route, stop=self.stop, stop_order=0)
