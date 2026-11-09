import json
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from urllib.error import URLError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from routes.models import Route
from tracking.gis import plan_for
from tracking.models import Trip


class Command(BaseCommand):
    help = 'Generate and store directional OSRM road geometry once, outside the GPS request path.'

    def add_arguments(self, parser):
        parser.add_argument('route_code', nargs='?', default='R001')
        parser.add_argument('--force', action='store_true', help='Replace existing geometry explicitly.')

    def handle(self, *args, **options):
        host = urlsplit(settings.OSRM_BASE_URL)
        if host.scheme != 'https' or not host.hostname or host.username or host.query:
            raise CommandError('OSRM_BASE_URL must be a trusted HTTPS server URL without credentials/query.')
        with transaction.atomic():
            # Serialize optional routing jobs and portal changes across processes.
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(20261106, 2)')
                cursor.execute('SELECT pg_advisory_xact_lock(20261106, 5)')
            try:
                route = Route.objects.select_for_update().get(route_code=options['route_code'])
            except Route.DoesNotExist as exc:
                raise CommandError('Import the actual route stops first.') from exc
            if route.geometry and not options['force']:
                self.stdout.write('Stored geometry exists; skipped. Use --force to replace it.')
                return
            if Trip.objects.filter(route=route, status='ACTIVE').exists():
                raise CommandError('Complete active trips before changing route geometry.')
            stops = list(route.route_stops.select_related('stop'))
            if not 2 <= len(stops) <= 100:
                raise CommandError('The route needs 2–100 authoritative ordered stops.')
            if route.route_code == 'R001' and len(stops) != 21:
                raise CommandError('R001 must have all 21 actual CSV stops before routing.')
            coords = ';'.join(f'{row.stop.longitude},{row.stop.latitude}' for row in stops)
            url = settings.OSRM_BASE_URL + '/route/v1/driving/' + coords + '?geometries=geojson&overview=full&alternatives=false&steps=false'
            try:
                # One request, no automatic retries. Serialize calls and space demo use.
                import time
                time.sleep(1.1)
                with urlopen(Request(url, headers={'User-Agent': 'CollegeBusTracking/Phase5 operator-route-generation'}), timeout=20) as response:
                    raw = response.read(5*1024*1024+1)
                if len(raw) > 5*1024*1024:
                    raise ValueError('OSRM response is too large.')
                result = json.loads(raw)
                if result.get('code') != 'Ok' or not result.get('routes'):
                    raise ValueError('No routable road path was returned.')
                route.geometry = result['routes'][0]['geometry']
                route.full_clean()
                plan, reason = plan_for(route)
                if plan is None:
                    raise ValueError('Geometry does not match the configured stop order/direction: ' + reason)
                route.save(update_fields=['geometry'])
            except (URLError, TimeoutError, ValueError, KeyError, TypeError, ValidationError) as exc:
                raise CommandError('Routing failed; existing geometry is preserved. Approximate visualization remains available. ' + str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f'Stored directional road geometry for {route.route_code}; {plan.length:.0f} m. No traffic-based ETA is implied.'))
