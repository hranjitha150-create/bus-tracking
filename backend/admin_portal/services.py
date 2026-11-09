"""Validated mutations shared by HTML forms, REST endpoints and route imports."""
from functools import wraps
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q
from accounts.models import CustomUser, AccessToken
from assignments.models import StudentBusAssignment, DriverAssignment
from buses.models import Bus
from drivers.models import Driver
from students.models import Student
from routes.models import Route, BusStop, RouteStop
from tracking.models import Trip


def mutation(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with transaction.atomic():
            # Serializes portal writes, including empty-assignment races. Bus locks
            # use the same order as trip start/complete in Phase 1.
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(20261106, 2)')
            list(Bus.objects.select_for_update().order_by('pk').values_list('pk', flat=True))
            return fn(*args, **kwargs)
    return wrapped


def no_active_trip(**filters):
    if Trip.objects.filter(status=Trip.Status.ACTIVE, **filters).exists():
        raise ValidationError('An active trip uses this record. Complete the trip before making this change.')


def cancel_scheduled(**filters):
    Trip.objects.filter(status=Trip.Status.SCHEDULED, **filters).update(status=Trip.Status.CANCELLED)


@mutation
def save_bus(data, instance=None):
    bus = Bus.objects.get(pk=instance.pk) if instance else Bus()
    for key in ('bus_number', 'registration_number', 'capacity', 'description', 'is_active'):
        if key in data:
            setattr(bus, key, data[key])
    if bus.pk:
        if bus.capacity < bus.student_assignments.filter(is_active=True).count():
            raise ValidationError({'capacity': 'Capacity cannot be lower than the number of assigned students.'})
        if not bus.is_active:
            no_active_trip(bus=bus)
            bus.student_assignments.filter(is_active=True).update(is_active=False)
            bus.driver_assignments.filter(is_active=True).update(is_active=False)
            cancel_scheduled(bus=bus)
    bus.full_clean()
    bus.save()
    return bus


@mutation
def save_person(kind, data, instance=None):
    model, role, fields = (Student, 'STUDENT', ['enrollment_number', 'department', 'semester', 'phone']) if kind == 'student' else (Driver, 'DRIVER', ['license_number', 'phone'])
    profile = model.objects.select_related('user').get(pk=instance.pk) if instance else model()
    user = profile.user if instance else CustomUser(role=role)
    for key in ('full_name', 'email', 'is_active'):
        if key in data:
            setattr(user, key, data[key])
    user.email = user.email.strip().lower()
    password = data.get('password')
    if not instance and not password:
        raise ValidationError({'password': 'An initial password is required.'})
    if password:
        validate_password(password, user)
        user.set_password(password)
    if instance and not user.is_active:
        if kind == 'driver':
            no_active_trip(driver=profile)
            bus_ids = profile.bus_assignments.filter(is_active=True).values_list('bus_id', flat=True)
            if StudentBusAssignment.objects.filter(bus_id__in=bus_ids, is_active=True).exists():
                raise ValidationError('Replace this driver before deactivating: students still use the assigned bus route.')
            cancel_scheduled(driver=profile)
        profile.bus_assignments.filter(is_active=True).update(is_active=False)
    user.full_clean()
    user.save()
    if not user.is_active or password:
        AccessToken.objects.filter(user=user).delete()
    profile.user = user
    for key in fields:
        if key in data:
            setattr(profile, key, data[key])
    profile.full_clean()
    profile.save()
    return profile


@mutation
def save_route(data, instance=None):
    route = Route.objects.get(pk=instance.pk) if instance else Route()
    if instance:
        no_active_trip(route=route)
        if data.get('route_code', route.route_code) != route.route_code:
            raise ValidationError({'route_code': 'Route code is a stable identifier and cannot be changed.'})
    for key in ('route_code', 'route_name', 'start_location', 'destination', 'direction', 'is_active', 'geometry'):
        if key in data:
            setattr(route, key, data[key])
    if route.pk and not route.is_active:
        if route.driver_assignments.filter(is_active=True).exists():
            raise ValidationError('Change or end the active bus/driver assignments before deactivating this route.')
        cancel_scheduled(route=route)
    route.full_clean()
    route.save()
    return route


@mutation
def assign_student(student, bus, pickup_stop):
    student = Student.objects.select_related('user').get(pk=student.pk)
    bus = Bus.objects.get(pk=bus.pk)
    if not student.user.is_active:
        raise ValidationError('Activate the student account before assigning a bus.')
    current = StudentBusAssignment.objects.filter(student=student, is_active=True).first()
    if current and current.bus_id == bus.pk and current.pickup_stop_id == pickup_stop.pk:
        return current
    assigned = bus.student_assignments.filter(is_active=True).exclude(student=student).count()
    if assigned >= bus.capacity:
        raise ValidationError({'bus': 'This bus is at capacity.'})
    new = StudentBusAssignment(student=student, bus=bus, pickup_stop=pickup_stop)
    # Validate relationships before replacing the old assignment. Unique validation
    # happens after deactivation inside this same transaction.
    new.clean()
    StudentBusAssignment.objects.filter(student=student, is_active=True).update(is_active=False)
    new.full_clean()
    new.save()
    return new


@mutation
def assign_driver(driver, bus, route):
    driver = Driver.objects.select_related('user').get(pk=driver.pk)
    bus = Bus.objects.get(pk=bus.pk)
    route = Route.objects.get(pk=route.pk)
    if DriverAssignment.objects.filter(driver=driver, is_active=True).exclude(bus=bus).exists():
        raise ValidationError({'driver': 'This driver already has another active bus assignment. End it first.'})
    current = DriverAssignment.objects.filter(bus=bus, is_active=True).first()
    if current and current.driver_id == driver.pk and current.route_id == route.pk:
        return current
    no_active_trip(bus=bus)
    no_active_trip(driver=driver)
    stop_ids = route.route_stops.values_list('stop_id', flat=True)
    if bus.student_assignments.filter(is_active=True).exclude(pickup_stop_id__in=stop_ids).exists():
        raise ValidationError({'route': 'The new route must include every active student pickup stop on this bus.'})
    new = DriverAssignment(driver=driver, bus=bus, route=route)
    new.clean()
    DriverAssignment.objects.filter(bus=bus, is_active=True).update(is_active=False)
    cancel_scheduled(bus=bus)
    new.full_clean()
    new.save()
    return new


@mutation
def end_assignment(kind, pk):
    model = StudentBusAssignment if kind == 'student' else DriverAssignment
    assignment = model.objects.get(pk=pk)
    if kind == 'driver':
        no_active_trip(bus=assignment.bus)
        if assignment.is_active and assignment.bus.student_assignments.filter(is_active=True).exists():
            raise ValidationError('Replace the driver or end student assignments first; the bus still has assigned students.')
        if assignment.is_active:
            cancel_scheduled(bus=assignment.bus)
    assignment.is_active = False
    assignment.save(update_fields=['is_active'])
    return assignment


def validate_route_pickups(route):
    bus_ids = route.driver_assignments.filter(is_active=True).values_list('bus_id', flat=True)
    stops = route.route_stops.values_list('stop_id', flat=True)
    if StudentBusAssignment.objects.filter(bus_id__in=bus_ids, is_active=True).exclude(pickup_stop_id__in=stops).exists():
        raise ValidationError('This change would remove an assigned pickup stop. Change the student assignments first.')


def replace_order(route, stop_ids):
    RouteStop.objects.filter(route=route).delete()
    RouteStop.objects.bulk_create([RouteStop(route=route, stop_id=pk, stop_order=i) for i, pk in enumerate(stop_ids, 1)])


@mutation
def reorder_stops(route, stop_ids):
    no_active_trip(route=route)
    current = list(route.route_stops.values_list('stop_id', flat=True))
    if len(stop_ids) != len(current) or set(stop_ids) != set(current):
        raise ValidationError('Supply each route stop exactly once.')
    replace_order(route, stop_ids)


@mutation
def save_stop(route, data, instance=None):
    route = Route.objects.get(pk=route.pk)
    no_active_trip(route=route)
    if instance:
        stop = BusStop.objects.get(pk=instance.pk)
        if not RouteStop.objects.filter(route=route, stop=stop).exists():
            raise ValidationError('This stop does not belong to the selected route.')
        for related in stop.route_stops.select_related('route'):
            no_active_trip(route=related.route)
    else:
        stop = BusStop()
    for key in ('name', 'latitude', 'longitude', 'address'):
        setattr(stop, key, data[key])
    stop.full_clean()
    stop.save()
    if not instance:
        ids = list(route.route_stops.values_list('stop_id', flat=True))
        order = data.get('stop_order', len(ids) + 1)
        if not 1 <= order <= len(ids) + 1:
            raise ValidationError({'stop_order': f'Order must be between 1 and {len(ids) + 1}.'})
        ids.insert(order - 1, stop.pk)
        replace_order(route, ids)
    return stop


@mutation
def remove_stop(route, stop):
    no_active_trip(route=route)
    ids = list(route.route_stops.exclude(stop=stop).values_list('stop_id', flat=True))
    replace_order(route, ids)
    validate_route_pickups(route)


@mutation
def import_r001(rows, direction):
    route, _ = Route.objects.get_or_create(route_code='R001', defaults={
        'route_name': 'R001', 'start_location': rows[0]['name'], 'destination': rows[-1]['name'], 'direction': direction})
    no_active_trip(route=route)
    route.start_location, route.destination = rows[0]['name'], rows[-1]['name']
    route.direction = direction
    route.full_clean()
    route.save()
    RouteStop.objects.filter(route=route).delete()
    for row in rows:
        stop, _ = BusStop.objects.update_or_create(name=row['name'], latitude=row['latitude'], longitude=row['longitude'],
            defaults={'address': row['address'], 'original_metadata': row['metadata']})
        RouteStop.objects.create(route=route, stop=stop, stop_order=row['order'])
    validate_route_pickups(route)
    return route
