import tempfile
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from routes.management.commands.import_bus_route import read_stops
from .services import import_r001
from .services import import_route_stops


def import_upload(upload, direction):
    if upload.size > 2 * 1024 * 1024:
        raise ValidationError('CSV must be at most 2 MB.')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'route.csv'
        with path.open('wb') as target:
            for chunk in upload.chunks():
                target.write(chunk)
        try:
            rows = read_stops(path)
        except CommandError as exc:
            raise ValidationError(str(exc)) from exc
    return import_r001(rows, direction)


def import_route_upload(upload, direction, route_code='', route_name='', target=None, default_code=''):
    if upload.size > 2 * 1024 * 1024:
        raise ValidationError('CSV must be at most 2 MB.')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'route.csv'
        with path.open('wb') as output:
            for chunk in upload.chunks():
                output.write(chunk)
        try:
            # The selected destination is authoritative. Source IDs are retained
            # as metadata and must be consistent within the uploaded CSV.
            rows = read_stops(path, strict=False)
        except CommandError as exc:
            raise ValidationError(str(exc)) from exc
    metadata = {key.strip().lower().replace(' ', '_'): value.strip() for key, value in rows[0]['metadata'].items()}
    code = target.route_code if target else route_code or metadata.get('route_code') or metadata.get('route_id') or default_code
    if not code:
        raise ValidationError('Enter a route code or include a route_id / route_code column in the CSV.')
    return import_route_stops(rows, direction, code, route_name, target)
