import hashlib
import secrets
from datetime import timedelta
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('Email is required.')
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.full_clean(exclude=['password'])
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra):
        extra.setdefault('role', CustomUser.Role.ADMIN)
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        if extra['role'] != 'ADMIN' or not extra['is_staff'] or not extra['is_superuser']:
            raise ValueError('Superusers must be staff ADMIN users with is_superuser=True.')
        return self.create_user(email, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrator'
        STUDENT = 'STUDENT', 'Student'
        DRIVER = 'DRIVER', 'Driver'

    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    objects = UserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('email'), name='unique_email_case_insensitive'),
            models.CheckConstraint(condition=models.Q(role__in=['ADMIN', 'STUDENT', 'DRIVER']), name='valid_user_role'),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.lower().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class AccessToken(models.Model):
    # Only a SHA-256 digest is stored. The bearer secret is returned once at login.
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='access_tokens')
    digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)

    @classmethod
    def issue(cls, user):
        raw = secrets.token_urlsafe(32)
        token = cls.objects.create(user=user, digest=hashlib.sha256(raw.encode()).hexdigest(),
                                   expires_at=timezone.now() + timedelta(hours=12))
        return token, raw
