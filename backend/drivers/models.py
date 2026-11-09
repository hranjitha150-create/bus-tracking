from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Driver(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='driver', limit_choices_to={'role': 'DRIVER'})
    license_number = models.CharField(max_length=50, unique=True)
    phone = models.CharField(max_length=20)

    def clean(self):
        if self.user_id and self.user.role != 'DRIVER':
            raise ValidationError({'user': 'Driver profile requires the DRIVER role.'})
