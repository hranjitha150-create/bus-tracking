import tempfile
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from routes.management.commands.import_bus_route import read_stops
from .services import import_r001


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
