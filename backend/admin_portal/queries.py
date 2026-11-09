from datetime import timedelta
from django.conf import settings
from django.db.models import Prefetch, prefetch_related_objects
from django.utils import timezone
from assignments.models import DriverAssignment, StudentBusAssignment
from buses.models import Bus
from drivers.models import Driver
from routes.models import Route
from students.models import Student
from tracking.models import Trip
from tracking.processing import progress_data
from tracking.gis import plan_for
from routes.models import RouteStop


def live_buses():
    now = timezone.now()
    threshold = now - timedelta(seconds=settings.GPS_STALE_SECONDS)
    buses = list(Bus.objects.select_related('latest_location', 'latest_location__trip', 'latest_location__trip__progress', 'latest_location__trip__route').prefetch_related(
        Prefetch('driver_assignments', queryset=DriverAssignment.objects.filter(is_active=True).select_related('route', 'driver__user'), to_attr='current_assignments'),
        Prefetch('trips', queryset=Trip.objects.filter(status='ACTIVE').select_related('progress', 'route'), to_attr='active_trip_records'),
    ).order_by('bus_number'))
    routes = []
    for bus in buses:
        for trip in bus.active_trip_records:
            routes.append(trip.route)
    prefetch_related_objects(routes, Prefetch('route_stops', queryset=RouteStop.objects.select_related('stop').order_by('stop_order')))
    plans = {route.pk: plan_for(route) for route in routes}
    results = []
    for bus in buses:
        loc = getattr(bus, 'latest_location', None)
        assignment = next(iter(bus.current_assignments), None)
        active_trip = next(iter(bus.active_trip_records), None)
        matches_active = loc and active_trip and loc.trip_id == active_trip.pk
        fresh = bool(matches_active and threshold <= loc.recorded_at <= now and threshold <= loc.received_at <= now)
        status = 'inactive' if not bus.is_active else ('completed' if loc and loc.trip.status == 'COMPLETED' else 'not_started') if not active_trip else 'unavailable' if not matches_active else 'live' if fresh else 'stale'
        trip = active_trip or (loc.trip if loc else None)
        info = progress_data(trip, plan_state=plans.get(trip.route_id) if trip else None,
                             progress=getattr(trip, 'progress', None) if trip else None, location=loc, now=now)
        results.append({
            'id': bus.pk, 'bus_number': bus.bus_number, 'registration_number': bus.registration_number,
            'is_active': bus.is_active, 'gps_status': status,
            'gps_label': ('SIMULATED — ' if active_trip and active_trip.is_simulated or not active_trip and loc and loc.is_simulated else '') + {'inactive': 'Inactive vehicle', 'not_started': 'Not started', 'completed': 'Trip completed', 'unavailable': 'GPS unavailable', 'live': 'Live', 'stale': 'Stale GPS'}[status],
            'trip_status': active_trip.status if active_trip else loc.trip.status if loc else 'NOT_STARTED',
            'route_id': assignment.route_id if assignment else None,
            'route_code': assignment.route.route_code if assignment else None,
            'driver_name': assignment.driver.user.full_name if assignment else None,
            'latitude': float(loc.latitude) if loc else None, 'longitude': float(loc.longitude) if loc else None,
            'recorded_at': loc.recorded_at.isoformat() if loc else None, 'received_at': loc.received_at.isoformat() if loc else None,
            'location_trip_id': loc.trip_id if loc else None, 'active_trip_id': active_trip.pk if active_trip else None,
            'is_simulated': bool(active_trip.is_simulated if active_trip else loc.is_simulated if loc else False),
            'progress': info, 'next_stop': info['next_stop'],
        })
    return results


def route_map(route):
    return {'route_code': route.route_code, 'route_name': route.route_name, 'geometry': route.geometry,
            'stops': [{'id': rs.stop_id, 'order': rs.stop_order, 'name': rs.stop.name, 'latitude': float(rs.stop.latitude),
                       'longitude': float(rs.stop.longitude)} for rs in route.route_stops.select_related('stop')]}


def dashboard_data():
    fleet = live_buses()
    events = []
    for trip in Trip.objects.select_related('bus').filter(start_time__isnull=False).order_by('-start_time')[:10]:
        events.append({'time': trip.start_time, 'label': f'{trip.bus.bus_number} · trip started', 'kind': 'Trip'})
    for trip in Trip.objects.select_related('bus').filter(end_time__isnull=False).order_by('-end_time')[:10]:
        events.append({'time': trip.end_time, 'label': f'{trip.bus.bus_number} · trip completed' if trip.status == 'COMPLETED' else f'{trip.bus.bus_number} · trip ended', 'kind': 'Trip'})
    for assignment in StudentBusAssignment.objects.select_related('student__user', 'bus').order_by('-assigned_date')[:8]:
        events.append({'time': assignment.assigned_date, 'label': f'{assignment.student.user.full_name} assigned to {assignment.bus.bus_number}', 'kind': 'Student'})
    for assignment in DriverAssignment.objects.select_related('driver__user', 'bus').order_by('-assigned_date')[:8]:
        events.append({'time': assignment.assigned_date, 'label': f'{assignment.driver.user.full_name} assigned to {assignment.bus.bus_number}', 'kind': 'Driver'})
    return {'counts': {'buses': Bus.objects.count(), 'drivers': Driver.objects.count(), 'students': Student.objects.count(),
                       'routes': Route.objects.count(), 'active_trips': Trip.objects.filter(status='ACTIVE').count(),
                       'completed_trips': Trip.objects.filter(status='COMPLETED').count()},
            'fleet': fleet, 'stale_buses': [b for b in fleet if b['gps_status'] == 'stale'],
            'recent_activity': sorted(events, key=lambda event: event['time'], reverse=True)[:10]}
