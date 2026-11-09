"""Student snapshots are scoped by the authenticated account, never URL IDs."""
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from assignments.models import StudentBusAssignment, DriverAssignment
from tracking.models import Trip, BusLocation
from routes.geometry import geometry_for_stops
from eta import services as eta_services
from .models import Student
from tracking.processing import progress_data
from tracking.gis import plan_for


def stop_data(stop, order=None):
    return {'id': stop.pk, 'name': stop.name, 'latitude': float(stop.latitude), 'longitude': float(stop.longitude),
            'address': stop.address, 'order': order}


def trip_data(trip):
    if not trip:
        return None
    return {'id': trip.pk, 'status': trip.status, 'trip_type': trip.trip_type, 'is_simulated': trip.is_simulated,
            'start_time': trip.start_time.isoformat() if trip.start_time else None,
            'end_time': trip.end_time.isoformat() if trip.end_time else None}


@transaction.atomic
def dashboard_snapshot(user):
    now = timezone.now()
    student = Student.objects.filter(user=user, user__role='STUDENT', user__is_active=True).first()
    data = {
        'status': 'unassigned' if student else 'profile_unavailable',
        'message': 'No bus is assigned to your account. Contact your college transport office.' if student else 'Your student profile is not ready. Contact your college transport office.',
        'student': {'id': student.pk if student else None, 'full_name': user.full_name, 'email': user.email,
                    'enrollment_number': student.enrollment_number if student else None,
                    'department': student.department if student else None, 'semester': student.semester if student else None,
                    'phone': student.phone if student else None},
        'assignment': None, 'bus': None, 'route': None, 'pickup_stop': None, 'active_trip': None, 'trip': None,
        'trip_status': 'NOT_STARTED', 'trip_label': 'Not started', 'location': None,
        'gps': {'status': 'unavailable', 'label': 'GPS unavailable', 'is_fresh': False, 'age_seconds': None,
                'recorded_at': None, 'received_at': None, 'freshness_seconds': settings.GPS_STALE_SECONDS},
        'eta': eta_services.unavailable('no_assignment', 'An assigned bus is required for arrival estimates.'),
        'progress': progress_data(None),
        'generated_at': now.isoformat(), 'poll_interval_seconds': settings.STUDENT_POLL_INTERVAL_SECONDS,
    }
    if not student:
        return data
    # Hold the selected assignment stable until the snapshot is materialized.
    # Portal assignment replacement/deactivation must wait for this read to finish.
    assignment = StudentBusAssignment.objects.select_for_update(of=('self',)).select_related('bus', 'pickup_stop').filter(
        student=student, student__user=user, is_active=True, bus__is_active=True).first()
    if not assignment:
        return data
    bus = assignment.bus
    data.update(status='assigned', message='', assignment={'id': assignment.pk, 'assigned_at': assignment.assigned_date.isoformat()},
                bus={'id': bus.pk, 'bus_number': bus.bus_number, 'registration_number': bus.registration_number,
                     'capacity': bus.capacity, 'description': bus.description, 'is_active': bus.is_active})
    driver_assignment = DriverAssignment.objects.select_related('route').filter(
        bus=bus, is_active=True, route__is_active=True, driver__user__is_active=True).first()
    if not driver_assignment:
        data['message'] = 'Your bus is assigned, but its route is not ready. Contact the transport office.'
        data['eta'] = eta_services.unavailable('route_unavailable', 'Your assigned bus route is not ready.')
        return data
    route = driver_assignment.route
    ordered = list(route.route_stops.select_related('stop').order_by('stop_order'))
    stops = [stop_data(row.stop, row.stop_order) for row in ordered]
    data['route'] = {'id': route.pk, 'route_code': route.route_code, 'route_name': route.route_name,
                     'start_location': route.start_location, 'destination': route.destination,
                     'direction': route.direction, 'stops': stops, 'stop_count': len(stops),
                     'start_stop_id': stops[0]['id'] if stops else None, 'destination_stop_id': stops[-1]['id'] if stops else None,
                     **geometry_for_stops(route.geometry, stops)}
    pickup = next((row for row in ordered if row.stop_id == assignment.pickup_stop_id), None)
    if pickup:
        data['pickup_stop'] = stop_data(pickup.stop, pickup.stop_order)
    else:
        data['message'] = 'Your pickup stop needs confirmation on this route. Contact the transport office.'
    trips = Trip.objects.filter(bus=bus, route=route).select_related('progress')
    active = trips.filter(driver_id=driver_assignment.driver_id, status='ACTIVE').first()
    current = active or trips.order_by('-pk').first()
    if current:
        current.route = route
    data.update(active_trip=trip_data(active), trip=trip_data(current), trip_status=current.status if current else 'NOT_STARTED',
                trip_label=current.get_status_display() if current else 'Not started')
    # Never substitute a sample from another trip for the current trip's position.
    location = BusLocation.objects.filter(bus=bus, trip=current, trip__route=route).first() if current else None
    if location and current.status not in ('ACTIVE', 'COMPLETED'):
        location = None
    gps = data['gps']
    if not active:
        gps.update(status='completed' if current and current.status == 'COMPLETED' else 'no_active_trip',
                   label='Trip completed — last known position' if location else 'Trip completed' if current and current.status == 'COMPLETED' else 'No active trip')
    elif not location:
        gps.update(status='unavailable', label='Waiting for GPS updates')
    if location:
        age = max((now - location.recorded_at).total_seconds(), (now - location.received_at).total_seconds())
        future = location.recorded_at > now or location.received_at > now
        fresh = bool(active and not future and 0 <= age <= settings.GPS_STALE_SECONDS)
        status = 'completed' if not active else 'invalid_timestamp' if future else 'fresh' if fresh else 'stale'
        labels = {'completed': 'Trip completed — last known position', 'invalid_timestamp': 'GPS timestamp needs checking',
                  'fresh': 'Live GPS', 'stale': 'GPS update is stale'}
        gps.update(status=status, label=labels[status], is_fresh=fresh, age_seconds=max(0, int(age)),
                   recorded_at=location.recorded_at.isoformat(), received_at=location.received_at.isoformat())
        data['location'] = {'latitude': float(location.latitude), 'longitude': float(location.longitude),
                            'speed': location.speed, 'accuracy': location.accuracy, 'trip_id': location.trip_id,
                            'recorded_at': gps['recorded_at'], 'received_at': gps['received_at'], 'is_live': fresh,
                            'is_simulated': location.is_simulated}
    plan_state = plan_for(route, ordered)
    progress = getattr(current, 'progress', None) if current else None
    data['progress'] = progress_data(current, assignment.pickup_stop_id, plan_state=plan_state, progress=progress, location=location, now=now)
    if current and current.is_simulated:
        gps['label'] = 'SIMULATED — ' + gps['label']
    if not pickup:
        data['eta'] = eta_services.unavailable('pickup_unavailable', 'Confirm your pickup stop with the transport office.')
    elif not active:
        data['eta'] = eta_services.unavailable('no_active_trip', 'Arrival estimates require an active trip.')
    elif not gps['is_fresh']:
        data['eta'] = eta_services.unavailable('gps_unavailable' if not location else 'gps_stale', 'A fresh GPS update is required for an arrival estimate.')
    else:
        data['eta'] = eta_services.estimate_pickup_eta(bus=bus, trip=active, pickup_stop=pickup.stop, location=location, now=now,
                                                    context=(plan_state, progress, data['progress']))
    return data
