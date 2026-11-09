"""Small dependency-free, metre-based route projection primitives (WGS84)."""
import hashlib
import json
import math
from functools import lru_cache
from django.conf import settings
from django.core.exceptions import ValidationError
from routes.models import validate_geometry

RADIUS = 6371008.8


def distance(a, b):
    """Points are (longitude, latitude)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 2 * RADIUS * math.asin(min(1, math.sqrt(value)))


class RoutePlan:
    def __init__(self, coordinates, stops, signature):
        self.coordinates, self.stops, self.signature = coordinates, stops, signature
        self.cumulative = [0.0]
        for a, b in zip(coordinates, coordinates[1:]):
            self.cumulative.append(self.cumulative[-1] + distance(a, b))
        self.length = self.cumulative[-1]
        if self.length < 1 or len(stops) < 2:
            raise ValueError('A nonempty route and at least two stops are required.')
        if distance(coordinates[0], stops[0]['point']) > settings.ROUTE_STOP_SNAP_METERS or distance(coordinates[-1], stops[-1]['point']) > settings.ROUTE_STOP_SNAP_METERS:
            raise ValueError('Geometry endpoints do not follow the configured stop direction.')
        previous = 0.0
        self.stop_distances = []
        for stop in stops:
            candidates = [p for p in self.projections(stop['point']) if p['along'] >= previous - .1]
            if not candidates:
                raise ValueError('Stop order is inconsistent with road geometry.')
            best = min(candidates, key=lambda p: (p['offset'], p['along']))
            if best['offset'] > settings.ROUTE_STOP_SNAP_METERS:
                raise ValueError('A stop is too far from the stored road geometry.')
            previous = best['along']
            self.stop_distances.append(previous)

    def projections(self, point):
        result = []
        lon, lat = point
        for i, (a, b) in enumerate(zip(self.coordinates, self.coordinates[1:])):
            coslat = math.cos(math.radians((a[1] + b[1] + lat) / 3))
            x, y = math.radians(b[0]-a[0])*RADIUS*coslat, math.radians(b[1]-a[1])*RADIUS
            px, py = math.radians(lon-a[0])*RADIUS*coslat, math.radians(lat-a[1])*RADIUS
            denom = x*x+y*y
            if denom < .001:
                continue
            t = max(0, min(1, (px*x+py*y)/denom))
            result.append({'along': self.cumulative[i] + t*(self.cumulative[i+1]-self.cumulative[i]),
                           'offset': math.hypot(px-t*x, py-t*y)})
        return result

    def match(self, point, previous=None, dt=0, accuracy=0, speed=0):
        candidates = self.projections(point)
        if previous is not None:
            max_advance = settings.GPS_MAX_SPEED_MPS * dt + accuracy + settings.GPS_JUMP_ALLOWANCE_METERS
            candidates = [p for p in candidates if previous-accuracy-settings.STOP_PASSED_METERS <= p['along'] <= previous+max_advance]
        if not candidates:
            return None
        minimum = min(p['offset'] for p in candidates)
        near = [p for p in candidates if p['offset'] <= minimum + min(accuracy, 20) + 3]
        predicted = previous + min(speed, settings.GPS_MAX_SPEED_MPS)*dt if previous is not None else 0
        return min(near, key=lambda p: (abs(p['along']-predicted), p['offset']))

    def at(self, metres):
        metres = max(0, min(metres, self.length))
        for i in range(len(self.coordinates)-1):
            if self.cumulative[i+1] >= metres:
                length = self.cumulative[i+1]-self.cumulative[i]
                t = (metres-self.cumulative[i])/length if length else 0
                a, b = self.coordinates[i], self.coordinates[i+1]
                return [a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])]
        return self.coordinates[-1]


@lru_cache(maxsize=64)
def cached_plan(payload, snap_tolerance):
    data = json.loads(payload)
    signature = hashlib.sha256(payload.encode()).hexdigest()
    return RoutePlan(data['geometry']['coordinates'], data['stops'], signature)


def plan_for(route, ordered_stops=None):
    if not route.geometry:
        return None, 'geometry_unavailable'
    try:
        validate_geometry(route.geometry)
        if ordered_stops is None:
            ordered_stops = getattr(route, '_prefetched_objects_cache', {}).get('route_stops')
        if ordered_stops is None:
            ordered_stops = route.route_stops.select_related('stop').order_by('stop_order')
        stops = [{'id': row.stop_id, 'name': row.stop.name, 'order': row.stop_order,
                  'point': [float(row.stop.longitude), float(row.stop.latitude)]}
                 for row in sorted(ordered_stops, key=lambda row: row.stop_order)]
        payload = json.dumps({'geometry': route.geometry, 'stops': stops, 'direction': route.direction}, sort_keys=True)
        return cached_plan(payload, settings.ROUTE_STOP_SNAP_METERS), 'tracking'
    except (ValidationError, ValueError, TypeError, KeyError):
        return None, 'geometry_invalid'
