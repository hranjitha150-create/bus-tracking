from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.is_active and request.user.role == 'ADMIN')


class IsStudent(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.is_active and request.user.role == 'STUDENT')


class IsDriver(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.is_active and request.user.role == 'DRIVER')


class CanAccessBus(BasePermission):
    def has_object_permission(self, request, view, bus):
        user = request.user
        if user.role == 'ADMIN':
            return True
        if user.role == 'STUDENT':
            return bus.student_assignments.filter(student__user=user, is_active=True).exists()
        if user.role == 'DRIVER':
            return bus.driver_assignments.filter(driver__user=user, is_active=True).exists()
        return False


class CanAccessTrip(BasePermission):
    def has_object_permission(self, request, view, trip):
        user = request.user
        if user.role == 'ADMIN':
            return True
        if user.role == 'DRIVER':
            return trip.driver.user_id == user.id and trip.bus.driver_assignments.filter(
                driver=trip.driver, route=trip.route, is_active=True).exists()
        return user.role == 'STUDENT' and request.method in ('GET', 'HEAD', 'OPTIONS') and trip.bus.student_assignments.filter(
            student__user=user, is_active=True).exists()
