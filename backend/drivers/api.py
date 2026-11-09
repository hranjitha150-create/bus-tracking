import math
from datetime import datetime, timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import IsDriver
from assignments.models import DriverAssignment
from buses.models import Bus
from routes.geometry import geometry_for_stops
from students.queries import stop_data, trip_data
from tracking.models import Trip, BusLocation, LocationHistory
from .models import Driver
from tracking.processing import validate_motion, update_progress, progress_data
from django.http import Http404


class Conflict(APIException):
    status_code = 409
    default_detail = 'Trip or GPS state changed. Refresh your assignment.'


def current_assignment(user):
    return DriverAssignment.objects.select_related('driver__user', 'bus', 'route').filter(
        driver__user=user, driver__user__is_active=True, is_active=True, bus__is_active=True, route__is_active=True).first()


def assignment_data(user):
    assignment = current_assignment(user)
    profile = Driver.objects.filter(user=user).first()
    result = {'status': 'unassigned', 'message': 'No active bus and route assignment. Contact your college transport office.',
              'driver': {'id': profile.pk if profile else None, 'full_name': user.full_name},
              'bus': None, 'route': None, 'active_trip': None, 'trip': None,
              'gps_interval_seconds': settings.DRIVER_GPS_INTERVAL_SECONDS}
    if not assignment:
        return result
    bus, route = assignment.bus, assignment.route
    stops = [stop_data(row.stop, row.stop_order) for row in route.route_stops.select_related('stop')]
    active = Trip.objects.filter(driver=assignment.driver, bus=bus, route=route, status='ACTIVE').first()
    latest = active or Trip.objects.filter(driver=assignment.driver, bus=bus, route=route).order_by('-pk').first()
    result.update(status='assigned', message='', bus={'id': bus.pk, 'bus_number': bus.bus_number,
        'registration_number': bus.registration_number, 'capacity': bus.capacity, 'description': bus.description},
        route={'id': route.pk, 'route_code': route.route_code, 'route_name': route.route_name,
            'start_location': route.start_location, 'destination': route.destination, 'direction': route.direction,
            'stops': stops, **geometry_for_stops(route.geometry, stops)}, active_trip=trip_data(active), trip=trip_data(latest))
    return result


def locked_assignment(user, bus_id=None):
    assignment = current_assignment(user)
    if not assignment or (bus_id is not None and assignment.bus_id != bus_id):
        raise PermissionDenied('No matching active driver, bus and route assignment.')
    Bus.objects.select_for_update().get(pk=assignment.bus_id)
    locked_bus_id = assignment.bus_id
    # Re-read after the bus lock: the portal uses the same bus lock before mutations.
    assignment = current_assignment(user)
    if not assignment or assignment.bus_id != locked_bus_id or (bus_id is not None and assignment.bus_id != bus_id):
        raise PermissionDenied('Your assignment changed. Refresh the dashboard.')
    Driver.objects.select_for_update().get(pk=assignment.driver_id)
    return assignment


class DriverAPI(APIView):
    permission_classes = [IsDriver]

    def handle_exception(self, exc):
        if isinstance(exc, ModelValidationError):
            exc = ValidationError(getattr(exc, 'message_dict', {'detail': exc.messages}))
        if isinstance(exc, IntegrityError):
            exc = Conflict('This operation conflicts with another active trip. Refresh your assignment.')
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response


class AssignmentAPI(DriverAPI):
    def get(self, request):
        return Response(assignment_data(request.user))


class StartTripAPI(DriverAPI):
    simulated = False

    @transaction.atomic
    def post(self, request):
        if self.simulated and not (settings.DEBUG and settings.ENABLE_ROUTE_REPLAY):
            raise Http404
        assignment = locked_assignment(request.user)
        active = Trip.objects.filter(status='ACTIVE').filter(
            Q(bus=assignment.bus) | Q(driver=assignment.driver)).first()
        if active:
            if active.is_simulated != self.simulated:
                raise Conflict('End the existing trip before switching between real GPS and development replay.')
            if (active.bus_id, active.driver_id, active.route_id) == (assignment.bus_id, assignment.driver_id, assignment.route_id):
                return Response({'trip': trip_data(active), 'created': False})
            raise Conflict('This bus or driver already has a different active trip.')
        kind = 'PICKUP' if assignment.route.direction == 'TO_COLLEGE' else 'DROP'
        trip = Trip.objects.select_for_update().filter(bus=assignment.bus, driver=assignment.driver,
            route=assignment.route, trip_type=kind, status='SCHEDULED').order_by('pk').first()
        created = trip is None
        trip = trip or Trip(bus=assignment.bus, driver=assignment.driver, route=assignment.route, trip_type=kind)
        trip.status, trip.start_time, trip.end_time = 'ACTIVE', timezone.now(), None
        trip.is_simulated = self.simulated
        trip.full_clean()
        trip.save()
        return Response({'trip': trip_data(trip), 'created': created}, status=201 if created else 200)


def own_trip(user, pk):
    trip = get_object_or_404(Trip, pk=pk, driver__user=user)
    assignment = locked_assignment(user, trip.bus_id)
    if trip.route_id != assignment.route_id or trip.driver_id != assignment.driver_id:
        raise PermissionDenied('This trip does not match your current assignment.')
    return Trip.objects.select_for_update().get(pk=trip.pk)


class EndTripAPI(DriverAPI):
    @transaction.atomic
    def post(self, request, trip_id):
        trip = own_trip(request.user, trip_id)
        if trip.status == 'COMPLETED':
            return Response({'trip': trip_data(trip)})
        if trip.status != 'ACTIVE':
            raise Conflict('Only an active trip can be ended.')
        trip.status, trip.end_time = 'COMPLETED', timezone.now()
        trip.full_clean()
        trip.save(update_fields=['status', 'end_time'])
        return Response({'trip': trip_data(trip)})


class AwareTimestamp(serializers.DateTimeField):
    def to_internal_value(self, value):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
            if not isinstance(parsed, datetime) or timezone.is_naive(parsed):
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError('Use an ISO-8601 timestamp with a timezone offset.')
        return super().to_internal_value(value)


class GPSInput(serializers.Serializer):
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    speed = serializers.FloatField(min_value=0)
    accuracy = serializers.FloatField(min_value=0)
    recorded_at = AwareTimestamp()

    def validate(self, data):
        if any(isinstance(self.initial_data.get(field), bool) for field in ('latitude', 'longitude', 'speed', 'accuracy')):
            raise ValidationError('GPS values must be numbers, not booleans.')
        if any(not math.isfinite(data[field]) for field in ('latitude', 'longitude', 'speed', 'accuracy')):
            raise ValidationError('GPS values must be finite numbers.')
        for field in ('latitude', 'longitude'):
            data[field] = Decimal(str(data[field])).quantize(Decimal('0.0000001'))
        return data


class LocationAPI(DriverAPI):
    simulated = False

    @transaction.atomic
    def post(self, request, trip_id):
        if self.simulated and not (settings.DEBUG and settings.ENABLE_ROUTE_REPLAY):
            raise Http404
        trip = own_trip(request.user, trip_id)
        if trip.is_simulated != self.simulated:
            raise Conflict('Real GPS and development replay use separate trip modes.')
        if trip.status != 'ACTIVE':
            raise Conflict('Trip is no longer active. Stop location sharing.')
        serializer = GPSInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        data['is_simulated'] = self.simulated
        recorded, now = data['recorded_at'], timezone.now()
        # Retrying an acknowledged sample is safe, even after a newer sample.
        latest = BusLocation.objects.filter(bus=trip.bus).first()
        duplicate = latest if latest and latest.trip_id == trip.pk and latest.recorded_at == recorded else LocationHistory.objects.filter(trip=trip, recorded_at=recorded).first()
        if duplicate:
            if any(getattr(duplicate, field) != data[field] for field in ('latitude', 'longitude', 'speed', 'accuracy')):
                raise Conflict('A different GPS sample already uses this timestamp.')
            return Response({'status': 'duplicate', 'recorded_at': recorded, 'received_at': duplicate.received_at})
        if recorded > now + timedelta(seconds=30) or recorded < now - timedelta(seconds=settings.DRIVER_LOCATION_MAX_AGE_SECONDS):
            raise ValidationError({'recorded_at': 'GPS sample is too old or in the future. Check the device clock.'})
        if recorded < trip.start_time - timedelta(seconds=5):
            raise ValidationError({'recorded_at': 'GPS sample predates this trip.'})
        if latest and recorded <= latest.recorded_at:
            return Response({'detail': 'GPS sample is older than the latest accepted position.', 'code': 'out_of_order'}, status=409)
        validate_motion(latest, data, trip)
        last_history = LocationHistory.objects.filter(trip=trip).order_by('-recorded_at').first()
        if settings.LOCATION_HISTORY_ENABLED and (not last_history or (recorded-last_history.recorded_at).total_seconds() >= settings.LOCATION_HISTORY_MIN_INTERVAL_SECONDS):
            history = LocationHistory(bus=trip.bus, trip=trip, **data)
            history.full_clean()
            history.save()
        if latest:
            BusLocation.objects.filter(pk=latest.pk).update(trip=trip, **data, received_at=now)
        else:
            BusLocation.objects.create(bus=trip.bus, trip=trip, **data)
        update_progress(trip, data)
        return Response({'status': 'accepted', 'recorded_at': recorded, 'received_at': now,
                         'is_simulated': self.simulated, 'progress': progress_data(trip)}, status=201)


class ReplayStartAPI(StartTripAPI):
    simulated = True


class ReplayLocationAPI(LocationAPI):
    simulated = True
