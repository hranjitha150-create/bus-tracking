"""Presentation contract for stored GeoJSON and honest stop-sequence fallbacks.

An OSRM response's routes[0].geometry (geometries=geojson) fits Route.geometry.
No public routing service is contacted while serving student requests.
"""
from django.core.exceptions import ValidationError
from .models import validate_geometry


def geometry_for_stops(stored_geometry, stops):
    invalid = False
    if stored_geometry != {}:
        try:
            validate_geometry(stored_geometry)
        except (ValidationError, TypeError, ValueError):
            invalid = True
        else:
            return {'geometry': stored_geometry, 'geometry_status': 'stored', 'is_approximate': False,
                    'geometry_label': 'Stored route geometry'}
    coordinates = [[stop['longitude'], stop['latitude']] for stop in stops]
    fallback = {'type': 'LineString', 'coordinates': coordinates} if len(coordinates) >= 2 else None
    return {'geometry': fallback, 'geometry_status': 'invalid' if invalid else 'approximate' if fallback else 'unavailable',
            'is_approximate': bool(fallback), 'geometry_label':
                ('Stored geometry is invalid. ' if invalid else '') +
                ('Approximate stop connections — not a verified driving route.' if fallback else 'Route geometry is unavailable.')}
