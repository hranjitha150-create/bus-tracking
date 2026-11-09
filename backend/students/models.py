from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Student(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student', limit_choices_to={'role': 'STUDENT'})
    enrollment_number = models.CharField(max_length=50, unique=True)
    department = models.CharField(max_length=100)
    semester = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    phone = models.CharField(max_length=20)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(semester__gte=1, semester__lte=12), name='student_semester_range')]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.user_id and self.user.role != 'STUDENT':
            raise ValidationError({'user': 'Student profile requires the STUDENT role.'})
