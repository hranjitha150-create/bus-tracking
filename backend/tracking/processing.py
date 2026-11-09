import math
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .gis import distance, plan_for
from .models import TripProgress, BusLocation


def validate_motion(previous, data, trip):
    if data['accuracy'] > settings.GPS_MAX_ACCURACY_METERS:
        raise ValidationError({'accuracy': 'GPS accuracy is too poor. Wait for a better fix.'})
    if data['speed'] > settings.GPS_MAX_SPEED_MPS:
        raise ValidationError({'speed': 'Reported speed exceeds the configured bus GPS limit.'})
    if previous and previous.trip_id == trip.pk:
        dt = (data['recorded_at']-previous.recorded_at).total_seconds()
        moved = distance((float(previous.longitude), float(previous.latitude)), (float(data['longitude']), float(data['latitude'])))
        allowance = settings.GPS_MAX_SPEED_MPS * dt + (previous.accuracy or 0) + data['accuracy'] + settings.GPS_JUMP_ALLOWANCE_METERS
        if moved > allowance:
            raise ValidationError({'location': 'Implausible position jump. Wait for the next valid GPS fix.'})


def update_progress(trip, data):
    old = TripProgress.objects.filter(trip=trip).first()
    plan, status = plan_for(trip.route)
    expected_type = 'PICKUP' if trip.route.direction == 'TO_COLLEGE' else 'DROP'
    if trip.trip_type != expected_type:
        status = 'direction_mismatch'
    if old and plan and old.geometry_signature != plan.signature:
        status = 'geometry_changed'
    dt = max(0, (data['recorded_at']-old.recorded_at).total_seconds()) if old else 0
    along, offset = old.distance_m if old else 0, 0
    if plan and status == 'tracking':
        matching_dt = max(0, (data['recorded_at']-old.last_matched_at).total_seconds()) if old and old.last_matched_at else 0
        match = plan.match((float(data['longitude']), float(data['latitude'])), old.distance_m if old and old.last_matched_at else None, matching_dt,
                           data['accuracy'], old.smoothed_speed_mps if old else data['speed'])
        offset = match['offset'] if match else min(p['offset'] for p in plan.projections((float(data['longitude']), float(data['latitude']))))
        if match is None or offset > settings.ROUTE_CORRIDOR_METERS + data['accuracy']:
            status = 'off_route'
        else:
            # Keep established progress monotone through ordinary GNSS jitter.
            along = max(along, match['along'])
    observed = data['speed']
    if old and 0 < dt <= settings.GPS_STALE_SECONDS and status == 'tracking' and along-old.distance_m > max(5, data['accuracy']):
        observed = max(observed, min(settings.GPS_MAX_SPEED_MPS, (along-old.distance_m)/dt))
    alpha = 1-math.exp(-dt/30) if old and dt < settings.GPS_STALE_SECONDS else 1
    smoothed = old.smoothed_speed_mps + alpha*(observed-old.smoothed_speed_mps) if old else observed
    stationary = (old.stationary_since if old and old.stationary_since else data['recorded_at']) if observed <= .5 else None
    progress, _ = TripProgress.objects.update_or_create(trip=trip, defaults={
        'geometry_signature': old.geometry_signature if old and status == 'geometry_changed' else plan.signature if plan else '',
        'distance_m': along, 'off_route_distance_m': offset, 'smoothed_speed_mps': smoothed,
        'stationary_since': stationary, 'recorded_at': data['recorded_at'], 'status': status})
    progress.last_matched_at = data['recorded_at'] if status == 'tracking' else old.last_matched_at if old else None
    progress.save(update_fields=['last_matched_at'])
    return progress


_UNSET = object()


def progress_data(trip, pickup_id=None, *, plan_state=None, progress=_UNSET, location=_UNSET, now=None):
    result = {'status': 'unavailable', 'reason': 'no_progress', 'next_stop': None, 'distance_to_next_stop_m': None,
              'distance_to_pickup_m': None, 'pickup_passed': None, 'progress_m': None, 'total_distance_m': None,
              'percent': None, 'is_simulated': bool(trip and trip.is_simulated)}
    if not trip:
        return result
    if trip.status != 'ACTIVE':
        result['reason'] = 'completed' if trip.status == 'COMPLETED' else 'no_active_trip'
        return result
    plan, reason = plan_state if plan_state is not None else plan_for(trip.route)
    if progress is _UNSET:
        progress = TripProgress.objects.filter(trip=trip).first()
    now = now or timezone.now()
    if progress and not 0 <= (now-progress.recorded_at).total_seconds() <= settings.GPS_STALE_SECONDS:
        result['reason'] = 'stale_gps'
        return result
    if not plan or not progress or progress.status != 'tracking' or progress.geometry_signature != plan.signature:
        result['reason'] = progress.status if progress and progress.status != 'tracking' else reason if not plan else 'geometry_changed' if progress else 'no_progress'
        return result
    if location is _UNSET:
        location = BusLocation.objects.filter(trip=trip, bus_id=trip.bus_id, recorded_at=progress.recorded_at).first()
    if not location or location.trip_id != trip.pk or location.bus_id != trip.bus_id or location.recorded_at != progress.recorded_at:
        result['reason'] = 'progress_pending'
        return result
    pass_tolerance = max(settings.STOP_PASSED_METERS, location.accuracy if location.accuracy is not None else settings.GPS_MAX_ACCURACY_METERS)
    along = progress.distance_m
    next_index = next((i for i, metres in enumerate(plan.stop_distances) if metres + pass_tolerance >= along), None)
    pickup_index = next((i for i, stop in enumerate(plan.stops) if stop['id'] == pickup_id), None)
    result.update(status='available', reason=None, progress_m=round(along, 1), total_distance_m=round(plan.length, 1),
                  percent=round(min(100, 100*along/plan.length), 1), smoothed_speed_mps=round(progress.smoothed_speed_mps, 2),
                  off_route_distance_m=round(progress.off_route_distance_m, 1), recorded_at=progress.recorded_at.isoformat())
    if next_index is not None:
        stop = plan.stops[next_index]
        result.update(next_stop={'id': stop['id'], 'name': stop['name'], 'order': stop['order']},
                      distance_to_next_stop_m=round(max(0, plan.stop_distances[next_index]-along), 1))
    if pickup_index is not None:
        remaining = plan.stop_distances[pickup_index]-along
        result.update(distance_to_pickup_m=round(max(0, remaining), 1), pickup_passed=remaining < -pass_tolerance)
    return result
