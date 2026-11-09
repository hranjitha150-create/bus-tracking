import getpass
import json
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from assignments.models import DriverAssignment
from tracking.gis import RoutePlan, plan_for


class Command(BaseCommand):
    help = 'DEVELOPMENT ONLY: replay actual assigned R001 coordinates through visibly simulated GPS endpoints.'

    def add_arguments(self, parser):
        parser.add_argument('--driver-email', required=True)
        parser.add_argument('--base-url', default='http://127.0.0.1:8000')
        parser.add_argument('--interval', type=int, default=10)
        parser.add_argument('--speed-kmh', type=float, default=20)
        parser.add_argument('--max-updates', type=int, default=30)

    def handle(self, *args, **options):
        if not (settings.DEBUG and settings.ENABLE_ROUTE_REPLAY):
            raise CommandError('Replay requires DJANGO_DEBUG=True and ENABLE_ROUTE_REPLAY=True. Production GPS is unchanged.')
        base = options['base_url'].rstrip('/')
        host = urlsplit(base)
        if host.hostname not in ('localhost', '127.0.0.1') or host.scheme not in ('http', 'https'):
            raise CommandError('Replay is restricted to a local development Django server.')
        if not 5 <= options['interval'] <= 30 or not 0 < options['speed_kmh'] <= settings.GPS_MAX_SPEED_MPS*3.6 or not 1 <= options['max_updates'] <= 1000:
            raise CommandError('Use interval 5–30 seconds, a positive plausible speed, and 1–1000 updates.')
        assignment = DriverAssignment.objects.select_related('route').filter(driver__user__email__iexact=options['driver_email'],
            driver__user__is_active=True, bus__is_active=True, route__is_active=True, is_active=True).first()
        if not assignment or assignment.route.route_code != 'R001':
            raise CommandError('The driver must have an active R001 assignment with the actual CSV imported.')
        rows = list(assignment.route.route_stops.select_related('stop'))
        if len(rows) != 21:
            raise CommandError('R001 must contain its 21 actual CSV stops. No fixture coordinates will be created.')
        plan, _ = plan_for(assignment.route)
        if plan is None:
            stops = [{'id': row.stop_id, 'name': row.stop.name, 'order': row.stop_order,
                      'point': [float(row.stop.longitude), float(row.stop.latitude)]} for row in rows]
            try:
                plan = RoutePlan([stop['point'] for stop in stops], stops, 'development-stop-connections')
            except ValueError as exc:
                raise CommandError('The imported stop coordinates cannot form a replay path: ' + str(exc)) from exc
            self.stdout.write('SIMULATION: approximate stop connections only; ETA will remain unavailable without stored road geometry.')
        token = None
        def post(path, payload):
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            with urlopen(Request(base + path, json.dumps(payload).encode(), headers, method='POST'), timeout=15) as response:
                return json.load(response) if response.status != 204 else None
        trip_id = None
        try:
            login = post('/api/auth/login/', {'email': options['driver_email'], 'password': getpass.getpass('Development driver password: ')})
            token = login['token']
            trip_id = post('/api/development/trips/start/', {})['trip']['id']
            speed = options['speed_kmh']/3.6
            for i in range(options['max_updates']):
                metres = min(plan.length, i*options['interval']*speed)
                lon, lat = plan.at(metres)
                post(f'/api/development/trips/{trip_id}/location/', {'latitude': lat, 'longitude': lon, 'speed': speed,
                    'accuracy': 5, 'recorded_at': timezone.now().isoformat()})
                self.stdout.write(f'SIMULATED trip {trip_id}: {metres:.0f}/{plan.length:.0f} m')
                if metres >= plan.length:
                    break
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write('Replay interrupted. Ending the simulated trip.')
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            raise CommandError('Development replay failed. Check server, assignment and simulation settings. ' + str(exc)) from exc
        finally:
            if trip_id:
                try:
                    post(f'/api/driver/trips/{trip_id}/end/', {})
                except Exception:
                    self.stderr.write('Could not confirm simulated trip completion. End it through the admin portal.')
            if token:
                try:
                    post('/api/auth/logout/', {})
                except Exception:
                    pass
