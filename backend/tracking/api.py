from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, IntegrityError
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from accounts.permissions import CanAccessTrip
from assignments.models import DriverAssignment
from buses.models import Bus
from .models import Trip, BusLocation


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusLocation
        fields = ['bus_id', 'trip_id', 'latitude', 'longitude', 'speed', 'accuracy', 'recorded_at', 'received_at', 'is_simulated']


class TripSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        # Driver personal information is deliberately omitted.
        fields = ['id', 'bus_id', 'route_id', 'trip_type', 'start_time', 'end_time', 'status', 'is_simulated']


class TripViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TripSerializer
    permission_classes = viewsets.ReadOnlyModelViewSet.permission_classes + [CanAccessTrip]

    def get_queryset(self):
        qs = Trip.objects.select_related('driver').order_by('-id')
        user = self.request.user
        if user.role == 'ADMIN':
            return qs
        if user.role == 'STUDENT':
            return qs.filter(bus__student_assignments__student__user=user, bus__student_assignments__is_active=True, bus__is_active=True)
        if user.role == 'DRIVER':
            return qs.filter(driver__user=user, bus__driver_assignments__driver__user=user,
                             bus__driver_assignments__route_id=F('route_id'),
                             bus__driver_assignments__is_active=True, bus__is_active=True, route__is_active=True)
        return qs.none()

    def transition(self, request, pk, target):
        if request.user.role not in ('ADMIN', 'DRIVER'):
            raise PermissionDenied('Only an assigned driver or administrator may change a trip.')
        try:
            with transaction.atomic():
                # Lock the bus and assignment as well as the trip before rechecking authorization.
                trip = self.get_object()
                if request.user.role == 'DRIVER':
                    from drivers.api import own_trip
                    trip = own_trip(request.user, trip.pk)
                Bus.objects.select_for_update().get(pk=trip.bus_id)
                assignment = DriverAssignment.objects.select_for_update().filter(
                    driver=trip.driver, bus=trip.bus, route=trip.route, is_active=True).first()
                trip = Trip.objects.select_for_update().get(pk=trip.pk)
                self.check_object_permissions(request, trip)
                if not assignment:
                    raise ValidationError('No matching active driver assignment.')
                expected = Trip.Status.SCHEDULED if target == Trip.Status.ACTIVE else Trip.Status.ACTIVE
                if trip.status != expected:
                    raise ValidationError(f'Trip must be {expected}.')
                if target == Trip.Status.ACTIVE:
                    if trip.is_simulated:
                        raise ValidationError('Simulation trips must use the designated development endpoints.')
                    expected_type = 'PICKUP' if trip.route.direction == 'TO_COLLEGE' else 'DROP'
                    if trip.trip_type != expected_type:
                        raise ValidationError('Trip direction does not match the configured route.')
                trip.status = target
                if target == Trip.Status.ACTIVE:
                    trip.start_time = timezone.now()
                else:
                    trip.end_time = timezone.now()
                trip.full_clean()
                trip.save()
        except (DjangoValidationError, IntegrityError) as exc:
            raise ValidationError('Trip conflicts with another active trip or fails validation.') from exc
        return Response(TripSerializer(trip).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return self.transition(request, pk, Trip.Status.ACTIVE)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        return self.transition(request, pk, Trip.Status.COMPLETED)
