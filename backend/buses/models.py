from django.db import models
from django.core.validators import MinValueValidator


class Bus(models.Model):
    bus_number = models.CharField(max_length=30, unique=True)
    registration_number = models.CharField(max_length=30, unique=True)
    capacity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(capacity__gte=1), name='bus_positive_capacity')]

    def __str__(self):
        return self.bus_number
