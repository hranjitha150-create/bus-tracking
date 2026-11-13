"""Route-distance ETA with smoothed GPS speed; no real-time traffic data."""
import math
from datetime import timedelta
from django.conf import settings
from tracking.gis import plan_for
from tracking.models import TripProgress
from tracking.processing import progress_data


def unavailable(reason='not_available', message='A reliable arrival estimate is not available.'):
    return {'status': 'unavailable', 'reason': reason, 'seconds': None, 'arrival_at': None, 'message': message}


def estimate_pickup_eta(*, bus, trip, pickup_stop, location, now, context=None):
    if not trip or trip.status != 'ACTIVE':
        return unavailable('completed' if trip and trip.status == 'COMPLETED' else 'no_active_trip', 'No active trip is available for an arrival estimate.')
    if not location or location.trip_id != trip.pk or location.bus_id != bus.pk:
        return unavailable('gps_unavailable', 'Waiting for a matching GPS update.')
    if not all(0 <= (now-value).total_seconds() <= settings.GPS_STALE_SECONDS for value in (location.recorded_at, location.received_at)):
        return unavailable('gps_stale', 'A fresh GPS update is required for an arrival estimate.')
    if location.accuracy is None or location.accuracy > settings.GPS_MAX_ACCURACY_METERS:
        return unavailable('poor_accuracy', 'Waiting for a more accurate GPS fix.')
    if context is None:
        plan_state = plan_for(trip.route)
        progress = TripProgress.objects.filter(trip=trip).first()
        info = progress_data(trip, pickup_stop.pk, plan_state=plan_state, progress=progress, location=location, now=now)
    else:
        plan_state, progress, info = context
    if info['status'] != 'available':
        if info['reason'] in ('geometry_unavailable', 'geometry_invalid'):
            return unavailable(info['reason'], 'ETA and stop distances require a saved road route. Contact the transport office to configure this route; GPS position tracking can still work.')
        return unavailable(info['reason'], 'ETA unavailable: ' + str(info['reason']).replace('_', ' ') + '.')
    if not progress or progress.recorded_at != location.recorded_at:
        return unavailable('progress_pending', 'Waiting for this GPS sample to be matched to the route.')
    if info['distance_to_pickup_m'] is None:
        return unavailable('pickup_unavailable', 'Pickup stop is not configured on this route.')
    if info['pickup_passed']:
        return unavailable('pickup_passed', 'Your assigned pickup stop has been passed on this trip.')
    if progress.stationary_since and (now-progress.stationary_since).total_seconds() >= settings.ETA_STATIONARY_SECONDS:
        return unavailable('stationary', 'The bus is stationary. An estimate will resume when movement is detected.')
    speed = progress.smoothed_speed_mps
    source = 'smoothed_gps'
    if speed <= .5:
        speed, source = settings.ETA_FALLBACK_SPEED_KMH / 3.6, 'configured_fallback'
    plan, _ = plan_state
    pickup_distance = next(m for stop, m in zip(plan.stops, plan.stop_distances) if stop['id'] == pickup_stop.pk)
    dwell_count = sum(progress.distance_m + settings.STOP_PASSED_METERS < m < pickup_distance for m in plan.stop_distances)
    seconds = math.ceil(info['distance_to_pickup_m'] / speed + dwell_count * settings.ETA_STOP_DWELL_SECONDS)
    return {'status': 'available', 'reason': None, 'seconds': seconds, 'arrival_at': (now+timedelta(seconds=seconds)).isoformat(),
            'message': 'Estimated from route distance and ' + ('configured fallback speed' if source == 'configured_fallback' else 'smoothed GPS speed') + '; no live traffic data.',
            'distance_m': info['distance_to_pickup_m'], 'speed_kmh': round(speed*3.6, 1), 'speed_source': source,
            'assumed_dwell_seconds': dwell_count*settings.ETA_STOP_DWELL_SECONDS, 'is_simulated': trip.is_simulated}
