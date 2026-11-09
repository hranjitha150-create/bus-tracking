from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class StudentBusAssignment(models.Model):
    student = models.ForeignKey('students.Student', on_delete=models.PROTECT, related_name='bus_assignments')
    bus = models.ForeignKey('buses.Bus', on_delete=models.PROTECT, related_name='student_assignments')
    pickup_stop = models.ForeignKey('routes.BusStop', on_delete=models.PROTECT, related_name='student_assignments')
    assigned_date = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student'], condition=models.Q(is_active=True), name='one_active_bus_per_student')]
        indexes = [models.Index(fields=['bus', 'is_active'])]

    def clean(self):
        if self.is_active and self.bus_id and not self.bus.is_active:
            raise ValidationError({'bus': 'Cannot assign an inactive bus.'})
        if self.is_active and self.bus_id and self.pickup_stop_id:
            if not DriverAssignment.objects.filter(bus_id=self.bus_id, is_active=True, route__is_active=True,
                                                   route__route_stops__stop_id=self.pickup_stop_id).exists():
                raise ValidationError({'pickup_stop': 'Pickup must belong to the active route assigned to this bus.'})


class DriverAssignment(models.Model):
    driver = models.ForeignKey('drivers.Driver', on_delete=models.PROTECT, related_name='bus_assignments')
    bus = models.ForeignKey('buses.Bus', on_delete=models.PROTECT, related_name='driver_assignments')
    route = models.ForeignKey('routes.Route', on_delete=models.PROTECT, related_name='driver_assignments')
    assigned_date = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['driver'], condition=models.Q(is_active=True), name='one_active_bus_per_driver'),
            models.UniqueConstraint(fields=['bus'], condition=models.Q(is_active=True), name='one_active_driver_per_bus'),
        ]

    def clean(self):
        if self.is_active and (not self.bus.is_active or not self.route.is_active or not self.driver.user.is_active):
            raise ValidationError('Active assignments require an active bus, route and driver account.')
