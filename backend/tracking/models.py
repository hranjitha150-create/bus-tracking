from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class Trip(models.Model):
    class Type(models.TextChoices):
        PICKUP = 'PICKUP', 'Pickup'
        DROP = 'DROP', 'Drop'
    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        ACTIVE = 'ACTIVE', 'Active'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    bus = models.ForeignKey('buses.Bus', on_delete=models.PROTECT, related_name='trips')
    driver = models.ForeignKey('drivers.Driver', on_delete=models.PROTECT, related_name='trips')
    route = models.ForeignKey('routes.Route', on_delete=models.PROTECT, related_name='trips')
    trip_type = models.CharField(max_length=10, choices=Type.choices)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    is_simulated = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=['bus', 'status']), models.Index(fields=['driver', 'status'])]
        constraints = [
            models.UniqueConstraint(fields=['bus'], condition=Q(status='ACTIVE'), name='one_active_trip_per_bus'),
            models.UniqueConstraint(fields=['driver'], condition=Q(status='ACTIVE'), name='one_active_trip_per_driver'),
            models.CheckConstraint(condition=Q(status__in=['SCHEDULED', 'ACTIVE', 'COMPLETED', 'CANCELLED']), name='valid_trip_status'),
            models.CheckConstraint(condition=Q(trip_type__in=['PICKUP', 'DROP']), name='valid_trip_type'),
            models.CheckConstraint(condition=Q(end_time__isnull=True) | Q(start_time__isnull=False, end_time__gte=F('start_time')), name='trip_time_order'),
            models.CheckConstraint(condition=~Q(status='ACTIVE') | Q(start_time__isnull=False, end_time__isnull=True), name='active_trip_times'),
            models.CheckConstraint(condition=~Q(status='COMPLETED') | Q(start_time__isnull=False, end_time__isnull=False), name='completed_trip_times'),
        ]

    def clean(self):
        from assignments.models import DriverAssignment
        if self.status in [self.Status.SCHEDULED, self.Status.ACTIVE] and not DriverAssignment.objects.filter(
            driver_id=self.driver_id, bus_id=self.bus_id, route_id=self.route_id, is_active=True,
            bus__is_active=True, route__is_active=True, driver__user__is_active=True,
        ).exists():
            raise ValidationError('Trip requires the matching active driver, bus and route assignment.')


class LocationBase(models.Model):
    is_simulated = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=10, decimal_places=7, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    speed = models.FloatField(default=0, validators=[MinValueValidator(0)], help_text='Metres per second')
    accuracy = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0)], help_text='Metres')
    recorded_at = models.DateTimeField(default=timezone.now)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(condition=Q(latitude__gte=-90, latitude__lte=90), name='%(class)s_lat_range'),
            models.CheckConstraint(condition=Q(longitude__gte=-180, longitude__lte=180), name='%(class)s_lon_range'),
            models.CheckConstraint(condition=Q(speed__gte=0, speed__lt=float('inf')), name='%(class)s_speed_range'),
            models.CheckConstraint(condition=Q(accuracy__isnull=True) | Q(accuracy__gte=0, accuracy__lt=float('inf')), name='%(class)s_accuracy_range'),
        ]

    def clean(self):
        if self.trip_id and self.bus_id != self.trip.bus_id:
            raise ValidationError({'bus': 'Location bus must match the trip bus.'})


class BusLocation(LocationBase):
    bus = models.OneToOneField('buses.Bus', on_delete=models.CASCADE, related_name='latest_location')
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name='latest_locations')


class LocationHistory(LocationBase):
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name='location_history')
    bus = models.ForeignKey('buses.Bus', on_delete=models.PROTECT, related_name='location_history')

    class Meta(LocationBase.Meta):
        abstract = False
        indexes = [models.Index(fields=['trip', 'recorded_at']), models.Index(fields=['bus', 'recorded_at'])]


class TripProgress(models.Model):
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name='progress')
    geometry_signature = models.CharField(max_length=64)
    distance_m = models.FloatField(default=0)
    off_route_distance_m = models.FloatField(default=0)
    smoothed_speed_mps = models.FloatField(default=0)
    stationary_since = models.DateTimeField(null=True, blank=True)
    last_matched_at = models.DateTimeField(null=True, blank=True)
    recorded_at = models.DateTimeField()
    status = models.CharField(max_length=30, choices=[(v, v) for v in ('tracking', 'off_route', 'geometry_unavailable', 'geometry_invalid', 'direction_mismatch', 'geometry_changed')])

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(distance_m__gte=0, distance_m__lt=float('inf'),
            off_route_distance_m__gte=0, off_route_distance_m__lt=float('inf'), smoothed_speed_mps__gte=0,
            smoothed_speed_mps__lt=float('inf')), name='progress_finite_nonnegative')]
