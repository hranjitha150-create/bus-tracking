import csv
import tempfile
from pathlib import Path
from unittest.mock import patch
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from .management.commands.import_bus_route import read_stops
from .models import Route, RouteStop, BusStop, validate_geometry
from django.core.exceptions import ValidationError


def synthetic_rows():
    # Deliberately synthetic coordinates for tests only; never a production seed.
    return [{'stop_order': i, 'name': 'NIE Golden Jubilee' if i == 1 else 'North Campus Last Stop' if i == 21 else f'Synthetic Stop {i}',
             'latitude': '10.1234567', 'longitude': str(70 + i / 100), 'observation': 'provisional test fixture'} for i in range(1, 22)]


class CSVFileMixin:
    def make_csv(self, rows=None, fields=None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'stops.csv'
        rows = synthetic_rows() if rows is None else rows
        with path.open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fields or list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path


class CSVValidationTests(CSVFileMixin, SimpleTestCase):
    def test_valid_file_preserves_actual_values_and_metadata(self):
        rows = read_stops(self.make_csv(list(reversed(synthetic_rows()))))
        self.assertEqual(str(rows[0]['latitude']), '10.1234567')
        self.assertEqual(rows[0]['order'], 1)
        self.assertEqual(rows[0]['metadata']['observation'], 'provisional test fixture')

    def test_missing_columns(self):
        with self.assertRaisesMessage(CommandError, 'Required column'):
            read_stops(self.make_csv([{'name': 'Only a name'}]))

    def test_invalid_values(self):
        for field, value in [('latitude', 'NaN'), ('longitude', '181'), ('latitude', ''), ('stop_order', '1.5'), ('name', '')]:
            with self.subTest(field=field, value=value):
                rows = synthetic_rows()
                rows[5][field] = value
                with self.assertRaises(CommandError):
                    read_stops(self.make_csv(rows))

    def test_wrong_count_order_and_endpoints(self):
        for change in ('count', 'order', 'endpoint'):
            rows = synthetic_rows()
            if change == 'count':
                rows.pop()
            elif change == 'order':
                rows[4]['stop_order'] = 1
            else:
                rows[0]['name'] = 'Wrong start'
            with self.assertRaises(CommandError):
                read_stops(self.make_csv(rows))

    def test_missing_source(self):
        with self.assertRaises(CommandError):
            read_stops(Path(tempfile.gettempdir()) / 'missing-college-stops-file.csv')

    def test_geometry(self):
        validate_geometry({'type': 'LineString', 'coordinates': [[70, 10], [71, 11]]})
        for value in [{'type': 'Polygon'}, {'type': 'LineString', 'coordinates': [[181, 10], [71, 11]]}]:
            with self.assertRaises(ValidationError):
                validate_geometry(value)


class CSVImportTests(CSVFileMixin, TestCase):
    def test_idempotent_import(self):
        path = self.make_csv()
        for _ in range(2):
            call_command('import_bus_route', str(path), stdout=StringIO())
        self.assertEqual(Route.objects.count(), 1)
        self.assertEqual(BusStop.objects.count(), 21)
        self.assertEqual(RouteStop.objects.count(), 21)
        self.assertEqual(list(RouteStop.objects.values_list('stop_order', flat=True)), list(range(1, 22)))
        stop = BusStop.objects.get(name='NIE Golden Jubilee')
        self.assertEqual(stop.original_metadata['observation'], 'provisional test fixture')

    def test_bad_input_leaves_existing_data_unchanged(self):
        call_command('import_bus_route', str(self.make_csv()), stdout=StringIO())
        rows = synthetic_rows()
        rows[20]['latitude'] = 'invalid'
        with self.assertRaises(CommandError):
            call_command('import_bus_route', str(self.make_csv(rows)), stdout=StringIO())
        self.assertEqual(RouteStop.objects.count(), 21)

    def test_transaction_rolls_back_partial_database_writes(self):
        with patch('routes.management.commands.import_bus_route.RouteStop.objects.create', side_effect=RuntimeError('Simulated database failure')):
            with self.assertRaises(RuntimeError):
                call_command('import_bus_route', str(self.make_csv()), stdout=StringIO())
        self.assertEqual(Route.objects.count(), 0)
        self.assertEqual(BusStop.objects.count(), 0)
