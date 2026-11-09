import math
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def validate_geometry(value):
    if value == {}:
        return
    if not isinstance(value, dict) or value.get('type') != 'LineString':
        raise ValidationError('Geometry must be a GeoJSON LineString or {}.')
    coordinates = value.get('coordinates')
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValidationError('A LineString needs at least two coordinates.')
    for point in coordinates:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValidationError('Use [longitude, latitude] pairs.')
        lon, lat = point
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValidationError('Invalid geometry coordinate.')


class Route(models.Model):
    class Direction(models.TextChoices):
        TO_COLLEGE = 'TO_COLLEGE', 'To college'
        FROM_COLLEGE = 'FROM_COLLEGE', 'From college'
    route_code = models.CharField(max_length=30, unique=True)
    route_name = models.CharField(max_length=150)
    start_location = models.CharField(max_length=200)
    destination = models.CharField(max_length=200)
    direction = models.CharField(max_length=20, choices=Direction.choices)
    is_active = models.BooleanField(default=True)
    geometry = models.JSONField(default=dict, blank=True, validators=[validate_geometry])

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(direction__in=['TO_COLLEGE', 'FROM_COLLEGE']), name='route_valid_direction')]


class BusStop(models.Model):
    name = models.CharField(max_length=200)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=10, decimal_places=7, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    address = models.TextField(blank=True)
    original_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['name', 'latitude', 'longitude'], name='unique_named_stop_coordinates'),
            models.CheckConstraint(condition=models.Q(latitude__gte=-90, latitude__lte=90), name='stop_lat_range'),
            models.CheckConstraint(condition=models.Q(longitude__gte=-180, longitude__lte=180), name='stop_lon_range'),
        ]


class RouteStop(models.Model):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='route_stops')
    stop = models.ForeignKey(BusStop, on_delete=models.PROTECT, related_name='route_stops')
    stop_order = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ['stop_order']
        constraints = [
            models.UniqueConstraint(fields=['route', 'stop_order'], name='unique_route_stop_order'),
            models.UniqueConstraint(fields=['route', 'stop'], name='unique_route_stop'),
            models.CheckConstraint(condition=models.Q(stop_order__gte=1), name='positive_stop_order'),
        ]
