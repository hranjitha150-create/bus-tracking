import csv
import io
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from admin_portal.services import import_r001, assign_student
from routes.management.commands.import_bus_route import read_stops
from routes.models import RouteStop
from routes.tests import synthetic_rows
from tracking.tests import TransportTests
from tracking.models import Trip, BusLocation, LocationHistory, TripProgress
from assignments.models import StudentBusAssignment
from tracking.gis import plan_for, RoutePlan


class RouteProjectionTests(SimpleTestCase):
    def test_loop_crossing_uses_continuity_instead_of_nearest_stop(self):
        coordinates = [[0,0], [.001,0], [.001,.001], [0,.001], [0,0], [.002,0]]
        stops = [{'id': 1, 'order': 1, 'name': 'Test start', 'point': [0,0]},
                 {'id': 2, 'order': 2, 'name': 'Test middle', 'point': [.001,.001]},
                 {'id': 3, 'order': 3, 'name': 'Test end', 'point': [.002,0]}]
        plan = RoutePlan(coordinates, stops, 'synthetic-loop')
        self.assertAlmostEqual(plan.match((0,0))['along'], 0)
        crossing = plan.match((0,0), previous=300, dt=30, accuracy=5, speed=5)
        self.assertGreater(crossing['along'], 400)
        second_pass = plan.match((.001,0), previous=crossing['along'], dt=20, accuracy=5, speed=5)
        self.assertGreater(second_pass['along'], 500)

    def test_reversed_geometry_requires_explicit_order_configuration(self):
        stops = [{'id':1, 'order':1, 'name':'Start', 'point':[77,12]}, {'id':2, 'order':2, 'name':'End', 'point':[77.02,12]}]
        with self.assertRaises(ValueError):
            RoutePlan([[77.02,12], [77,12]], stops, 'wrong-direction')


class LiveIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        TransportTests.setUpTestData.__func__(cls)
        StudentBusAssignment.objects.update(is_active=False)
        rows = synthetic_rows()
        for i, row in enumerate(rows):
            row.update(latitude='12.0000000', longitude=f'{77+(i+1)*.001:.7f}')
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic-test-stops.csv'
            with path.open('w', newline='', encoding='utf-8') as out:
                writer = csv.DictWriter(out, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            import_r001(read_stops(path), 'TO_COLLEGE')
        cls.pickup = cls.route.route_stops.get(stop_order=7).stop
        assign_student(cls.student, cls.bus, cls.pickup)
        cls.route.geometry = {'type': 'LineString', 'coordinates': [[float(row.stop.longitude), float(row.stop.latitude)] for row in cls.route.route_stops.select_related('stop')]}
        cls.route.save()

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.driver_user)
        self.now = timezone.now()

    def start(self, simulated=False):
        self.api.force_authenticate(self.driver_user)
        with patch('django.utils.timezone.now', return_value=self.now):
            response = self.api.post('/api/development/trips/start/' if simulated else '/api/driver/trips/start/', {})
        self.assertIn(response.status_code, (200, 201), response.data)
        return response.data['trip']['id']

    def gps(self, pk, elapsed, lon, *, lat=12, speed=5, accuracy=5, simulated=False):
        self.api.force_authenticate(self.driver_user)
        stamp = self.now+timedelta(seconds=elapsed)
        with patch('django.utils.timezone.now', return_value=stamp):
            return self.api.post(f'/api/{"development" if simulated else "driver"}/trips/{pk}/location/',
                {'latitude': lat, 'longitude': lon, 'speed': speed, 'accuracy': accuracy, 'recorded_at': stamp.isoformat()}, format='json')

    def student_data(self, elapsed=0):
        self.api.force_authenticate(self.student_user)
        with patch('django.utils.timezone.now', return_value=self.now+timedelta(seconds=elapsed)):
            return self.api.get('/api/student/my-bus/location/').data

    def test_end_to_end_motion_eta_next_stop_and_completion(self):
        pk = self.start()
        first = self.gps(pk, 0, 77.001)
        self.assertEqual(first.status_code, 201, first.data)
        before = self.student_data()
        self.assertEqual(before['eta']['status'], 'available', before['eta'])
        self.assertEqual(before['progress']['next_stop']['order'], 1)
        self.assertEqual(before['bus']['id'], self.bus.pk)
        self.assertEqual(self.gps(pk, 20, 77.002).status_code, 201)
        after = self.student_data(20)
        self.assertLess(after['eta']['seconds'], before['eta']['seconds'])
        self.assertEqual(after['progress']['next_stop']['order'], 2)
        self.api.force_authenticate(self.admin)
        with patch('django.utils.timezone.now', return_value=self.now+timedelta(seconds=20)):
            fleet = self.api.get('/api/admin/live-buses/').data['results']
        bus = next(bus for bus in fleet if bus['id'] == self.bus.pk)
        self.assertEqual(bus['gps_status'], 'live')
        self.assertEqual(bus['next_stop']['order'], 2)
        self.assertEqual(BusLocation.objects.get(bus=self.bus).recorded_at, self.now+timedelta(seconds=20))
        self.assertEqual(LocationHistory.objects.filter(trip_id=pk).count(), 2)
        self.api.force_authenticate(self.driver_user)
        with patch('django.utils.timezone.now', return_value=self.now+timedelta(seconds=25)):
            self.assertEqual(self.api.post(f'/api/driver/trips/{pk}/end/', {}).status_code, 200)
        complete = self.student_data(25)
        self.assertEqual(complete['trip_status'], 'COMPLETED')
        self.assertFalse(complete['gps']['is_fresh'])
        self.assertEqual(complete['eta']['status'], 'unavailable')
        self.assertEqual(self.gps(pk, 30, 77.003).status_code, 409)

    def test_noise_does_not_reverse_next_stop_and_pickup_is_passed(self):
        pk = self.start()
        self.gps(pk, 0, 77.001)
        self.assertEqual(self.gps(pk, 40, 77.0085).status_code, 201)
        data = self.student_data(40)
        self.assertTrue(data['progress']['pickup_passed'])
        self.assertEqual(data['eta']['reason'], 'pickup_passed')
        order, metres = data['progress']['next_stop']['order'], data['progress']['progress_m']
        self.gps(pk, 50, 77.0084)
        jitter = self.student_data(50)
        self.assertEqual(jitter['progress']['next_stop']['order'], order)
        self.assertGreaterEqual(jitter['progress']['progress_m'], metres)

    def test_off_route_recovery_and_stationary_behavior(self):
        pk = self.start()
        self.gps(pk, 0, 77.001)
        self.assertEqual(self.gps(pk, 30, 77.001, lat=12.002).status_code, 201)
        self.assertEqual(self.student_data(30)['eta']['reason'], 'off_route')
        self.assertEqual(self.gps(pk, 60, 77.002).status_code, 201)
        self.assertEqual(self.student_data(60)['eta']['status'], 'available')
        self.gps(pk, 80, 77.002, speed=0)
        self.gps(pk, 120, 77.002, speed=0)
        self.assertEqual(self.student_data(120)['eta']['reason'], 'stationary')

    def test_fallback_speed_is_explicit_before_confirmed_stationary(self):
        pk = self.start()
        self.gps(pk, 0, 77.001, speed=0)
        eta = self.student_data()['eta']
        self.assertEqual(eta['status'], 'available')
        self.assertEqual(eta['speed_source'], 'configured_fallback')
        self.assertIn('no live traffic', eta['message'])
        self.assertEqual(self.student_data(31)['eta']['reason'], 'stationary')

    def test_poor_accuracy_and_implausible_jump_are_atomic_rejections(self):
        pk = self.start()
        self.gps(pk, 0, 77.001)
        self.assertEqual(self.gps(pk, 1, 78).status_code, 400)
        self.assertEqual(self.gps(pk, 10, 77.002, accuracy=101).status_code, 400)
        self.assertEqual(LocationHistory.objects.count(), 1)
        self.assertEqual(TripProgress.objects.get(trip_id=pk).recorded_at, self.now)
        self.assertEqual(float(BusLocation.objects.get().longitude), 77.001)

    def test_stale_gps_suppresses_eta_and_progress(self):
        pk = self.start()
        self.gps(pk, 0, 77.001)
        data = self.student_data(180)
        self.assertEqual(data['eta']['reason'], 'gps_stale')
        self.assertEqual(data['progress']['status'], 'unavailable')
        self.assertEqual(data['gps']['status'], 'stale')

    def test_unconfigured_reverse_travel_is_not_assumed(self):
        pk = self.start()
        Trip.objects.filter(pk=pk).update(trip_type='DROP')
        self.gps(pk, 0, 77.001)
        self.assertEqual(self.student_data()['eta']['reason'], 'direction_mismatch')

    def test_configured_drop_direction_uses_its_own_order_and_geometry(self):
        self.route.direction = 'FROM_COLLEGE'
        self.route.geometry['coordinates'].reverse()
        self.route.save()
        stops = list(self.route.route_stops.values_list('stop_id', flat=True))
        self.route.route_stops.all().delete()
        RouteStop.objects.bulk_create([RouteStop(route=self.route, stop_id=pk, stop_order=i) for i, pk in enumerate(reversed(stops), 1)])
        pk = self.start()
        self.assertEqual(self.gps(pk, 0, 77.021).status_code, 201)
        self.assertEqual(self.gps(pk, 20, 77.020).status_code, 201)
        data = self.student_data(20)
        self.assertEqual(data['trip']['trip_type'], 'DROP')
        self.assertEqual(data['progress']['next_stop']['order'], 2)
        self.assertEqual(data['eta']['status'], 'available')

    def test_missing_and_invalid_road_geometry_do_not_produce_eta(self):
        from routes.models import Route
        pk = self.start()
        Route.objects.filter(pk=self.route.pk).update(geometry={})
        self.gps(pk, 0, 77.001)
        data = self.student_data()
        self.assertEqual(data['eta']['reason'], 'geometry_unavailable')
        self.assertIn('saved road route', data['eta']['message'])
        self.assertTrue(data['route']['is_approximate'])
        Route.objects.filter(pk=self.route.pk).update(geometry={'type': 'Polygon'})
        self.gps(pk, 10, 77.001)
        self.assertEqual(self.student_data(10)['eta']['reason'], 'geometry_invalid')

    def test_changed_geometry_never_reuses_old_progress(self):
        from routes.models import Route
        pk = self.start()
        self.gps(pk, 0, 77.001)
        changed = dict(self.route.geometry)
        changed['coordinates'] = list(changed['coordinates'])
        changed['coordinates'].insert(1, [77.0015,12.00001])
        Route.objects.filter(pk=self.route.pk).update(geometry=changed)
        self.gps(pk, 20, 77.002)
        self.assertEqual(self.student_data(20)['eta']['reason'], 'geometry_changed')

    @override_settings(LOCATION_HISTORY_MIN_INTERVAL_SECONDS=30)
    def test_history_sampling_does_not_throttle_live_location_or_progress(self):
        pk = self.start()
        for elapsed, lon in [(0,77.001), (20,77.002), (40,77.003)]:
            self.assertEqual(self.gps(pk, elapsed, lon).status_code, 201)
        self.assertEqual(LocationHistory.objects.count(), 2)
        self.assertEqual(float(BusLocation.objects.get().longitude), 77.003)
        self.assertEqual(self.student_data(40)['progress']['next_stop']['order'], 3)

    @override_settings(LOCATION_HISTORY_ENABLED=False)
    def test_optional_history_preserves_latest_and_eta(self):
        pk = self.start()
        self.gps(pk, 0, 77.001)
        self.assertEqual(self.gps(pk, 0, 77.001).data['status'], 'duplicate')
        self.assertFalse(LocationHistory.objects.exists())
        self.assertEqual(self.student_data()['eta']['status'], 'available')

    def test_retention_prunes_only_history(self):
        pk = self.start()
        self.gps(pk, 0, 77.001)
        LocationHistory.objects.update(received_at=self.now-timedelta(days=40))
        call_command('prune_location_history', stdout=io.StringIO())
        self.assertFalse(LocationHistory.objects.exists())
        self.assertTrue(BusLocation.objects.exists())
        self.assertTrue(TripProgress.objects.exists())

    @override_settings(DEBUG=True, ENABLE_ROUTE_REPLAY=True)
    def test_development_replay_cannot_masquerade_as_real_gps(self):
        pk = self.start(simulated=True)
        self.assertEqual(self.gps(pk, 0, 77.001).status_code, 409)
        self.assertEqual(self.gps(pk, 0, 77.001, simulated=True).status_code, 201)
        data = self.student_data()
        self.assertTrue(data['trip']['is_simulated'])
        self.assertTrue(data['location']['is_simulated'])
        self.assertTrue(data['eta']['is_simulated'])
        self.assertIn('SIMULATED', data['gps']['label'])
        self.api.force_authenticate(self.driver_user)
        self.assertEqual(self.api.post('/api/driver/trips/start/', {}).status_code, 409)

    @override_settings(DEBUG=False, ENABLE_ROUTE_REPLAY=True)
    def test_production_cannot_enable_replay_with_one_flag(self):
        self.assertEqual(self.api.post('/api/development/trips/start/', {}).status_code, 404)
        with self.assertRaises(CommandError):
            call_command('replay_bus_route', driver_email=self.driver_user.email)

    @override_settings(DEBUG=True, ENABLE_ROUTE_REPLAY=True)
    def test_replay_cannot_write_an_existing_real_trip(self):
        pk = self.start()
        self.assertEqual(self.gps(pk, 0, 77.001, simulated=True).status_code, 409)

    def test_unauthorized_student_cannot_follow_other_bus_or_publish(self):
        pk = self.start()
        self.gps(pk, 0, 77.001)
        self.api.force_authenticate(self.student_user)
        self.assertEqual(self.api.get(f'/api/buses/{self.other_bus.pk}/location/').status_code, 404)
        self.assertEqual(self.api.post(f'/api/driver/trips/{pk}/location/', {}, format='json').status_code, 403)
        self.assertEqual(self.api.get('/api/admin/live-buses/').status_code, 403)

    def test_geometry_generation_is_operator_only_single_request_and_cached(self):
        import json
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'code': 'Ok', 'routes': [{'geometry': self.route.geometry}]}).encode()
        with patch('routes.management.commands.generate_route_geometry.urlopen', return_value=response) as http, patch('time.sleep'):
            call_command('generate_route_geometry', 'R001', force=True, stdout=io.StringIO())
            self.assertEqual(http.call_count, 1)
            self.assertIn('overview=full', http.call_args.args[0].full_url)
            call_command('generate_route_geometry', 'R001', stdout=io.StringIO())
            self.assertEqual(http.call_count, 1)
        self.route.refresh_from_db()
        self.assertIsNotNone(plan_for(self.route)[0])

    def test_generating_missing_geometry_enables_next_trip_distances_and_eta(self):
        import json
        from routes.models import Route

        geometry = self.route.geometry
        Route.objects.filter(pk=self.route.pk).update(geometry={})
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {'code': 'Ok', 'routes': [{'geometry': geometry}]}).encode()
        with patch('routes.management.commands.generate_route_geometry.urlopen', return_value=response), patch('time.sleep'):
            call_command('generate_route_geometry', 'R001', stdout=io.StringIO())
        pk = self.start()
        self.assertEqual(self.gps(pk, 0, 77.001).status_code, 201)
        data = self.student_data()
        self.assertEqual(data['gps']['status'], 'fresh')
        self.assertEqual(data['progress']['status'], 'available')
        self.assertIsNotNone(data['progress']['distance_to_next_stop_m'])
        self.assertGreater(data['progress']['distance_to_pickup_m'], 0)
        self.assertEqual(data['eta']['status'], 'available')

    def test_geometry_failure_preserves_stored_path_and_active_trip_protects_it(self):
        with patch('routes.management.commands.generate_route_geometry.urlopen', side_effect=URLError('test offline')), patch('time.sleep'):
            with self.assertRaises(CommandError):
                call_command('generate_route_geometry', 'R001', force=True)
        self.route.refresh_from_db()
        self.assertTrue(self.route.geometry)
        self.start()
        with patch('routes.management.commands.generate_route_geometry.urlopen') as http:
            with self.assertRaises(CommandError):
                call_command('generate_route_geometry', 'R001', force=True)
            http.assert_not_called()
