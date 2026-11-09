import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from routes.models import Route, BusStop, RouteStop

ALIASES = {
    'name': ('name', 'stop_name', 'bus_stop', 'bus_stop_name'),
    'latitude': ('latitude', 'lat'),
    'longitude': ('longitude', 'lon', 'lng', 'long'),
    'stop_order': ('stop_order', 'stop_order_shared', 'stop_number', 'stop_no', 'sequence', 'order'),
}


def read_stops(path):
    """Validate the entire source before any database mutation. Extra columns survive."""
    try:
        with Path(path).open(encoding='utf-8-sig', newline='') as source:
            reader = csv.DictReader(source)
            headers = reader.fieldnames or []
            normalized = [h.strip().lower().replace(' ', '_') for h in headers]
            if len(set(normalized)) != len(normalized):
                raise CommandError('Duplicate CSV column names.')
            lookup = dict(zip(normalized, headers))
            columns = {}
            for field, aliases in ALIASES.items():
                matches = [lookup[a] for a in aliases if a in lookup]
                if len(matches) != 1:
                    raise CommandError(f'Required column {field}: supply exactly one of {", ".join(aliases)}.')
                columns[field] = matches[0]
            rows = []
            for line, raw in enumerate(reader, 2):
                if None in raw or any(v is None for v in raw.values()):
                    raise CommandError(f'Line {line}: column count differs from header.')
                values = {k: raw[v].strip() for k, v in columns.items()}
                try:
                    order = int(values['stop_order'])
                    lat, lon = Decimal(values['latitude']), Decimal(values['longitude'])
                    if not lat.is_finite() or not lon.is_finite() or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError('Coordinates out of range')
                    if not values['name'] or len(values['name']) > 200:
                        raise ValueError('Stop name must contain 1–200 characters')
                    if order < 1:
                        raise ValueError('Order must be positive')
                    for route_column in ('route_code', 'route_id'):
                        if route_column in lookup and raw[lookup[route_column]].strip() != 'R001':
                            raise ValueError('Only route R001 is accepted')
                except (ValueError, InvalidOperation) as exc:
                    raise CommandError(f'Line {line}: invalid stop order, name or coordinates ({exc}).') from exc
                rows.append({'name': values['name'], 'latitude': lat.quantize(Decimal('.0000001'), rounding=ROUND_HALF_UP),
                             'longitude': lon.quantize(Decimal('.0000001'), rounding=ROUND_HALF_UP),
                             'order': order, 'address': raw.get(lookup.get('address', ''), '').strip(),
                             'metadata': raw})
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CommandError(f'Cannot read CSV: {exc}') from exc
    if len(rows) != 21 or sorted(r['order'] for r in rows) != list(range(1, 22)):
        raise CommandError('R001 requires exactly 21 stops, with unique consecutive stop_order values 1–21.')
    rows.sort(key=lambda row: row['order'])
    if rows[0]['name'].casefold() != 'nie golden jubilee' or rows[-1]['name'].casefold() != 'north campus last stop':
        raise CommandError('R001 must start at NIE Golden Jubilee and end at North Campus Last Stop.')
    if len({(r['name'], r['latitude'], r['longitude']) for r in rows}) != 21:
        raise CommandError('Duplicate named stop coordinates in CSV.')
    return rows


class Command(BaseCommand):
    help = 'Atomically import the authoritative 21-stop R001 CSV, preserving metadata.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path')
        parser.add_argument('--direction', choices=Route.Direction.values, default=Route.Direction.TO_COLLEGE)

    def handle(self, *args, **options):
        path = Path(options['csv_path'])
        if not path.is_file() and not path.is_absolute():
            path = settings.BASE_DIR.parent / path
        rows = read_stops(path)
        from admin_portal.services import import_r001
        try:
            import_r001(rows, options['direction'])
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS('Imported R001: 21 stops. CSV observations and uncertain names remain provisional.'))
