from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q, Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from assignments.models import StudentBusAssignment, DriverAssignment
from buses.models import Bus
from drivers.models import Driver
from students.models import Student
from routes.models import Route, BusStop, RouteStop
from . import forms, services, queries
from .uploads import import_upload

ENTITIES = {
    'buses': (Bus, 'Buses', forms.BusForm), 'drivers': (Driver, 'Drivers', forms.PersonForm),
    'students': (Student, 'Students', forms.PersonForm), 'routes': (Route, 'Routes', forms.RouteForm),
}


def admin_required(view):
    @never_cache
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.user.role != 'ADMIN':
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def config(entity):
    if entity not in ENTITIES:
        raise Http404
    return ENTITIES[entity]


def page_for(request, qs, key='page'):
    return Paginator(qs, 20).get_page(request.GET.get(key))


def error_on(form, exc):
    if isinstance(exc, ValidationError):
        if hasattr(exc, 'message_dict'):
            for field, errors in exc.message_dict.items():
                form.add_error(field if field in form.fields else None, errors)
        else:
            form.add_error(None, exc.messages)
    else:
        form.add_error(None, 'This change conflicts with an existing record. Review the values and try again.')


@admin_required
def dashboard(request):
    return render(request, 'admin_portal/dashboard.html', {**queries.dashboard_data(), 'title': 'Transport overview', 'section': 'dashboard'})


@admin_required
def entity_list(request, entity):
    model, label, _ = config(entity)
    search = request.GET.get('q', '').strip()
    qs = model.objects.all()
    if entity in ('students', 'drivers'):
        qs = qs.select_related('user').order_by('user__full_name', 'pk')
        if search:
            qs = qs.filter(Q(user__full_name__icontains=search) | Q(user__email__icontains=search) | Q(**{('enrollment_number' if entity == 'students' else 'license_number') + '__icontains': search}))
        if request.GET.get('status') in ('active', 'inactive'):
            qs = qs.filter(user__is_active=request.GET['status'] == 'active')
        headers = ['Name', 'Email', 'Enrollment' if entity == 'students' else 'License', 'Phone', 'Status']
    else:
        qs = qs.order_by('bus_number' if entity == 'buses' else 'route_code')
        if search:
            fields = ('bus_number', 'registration_number') if entity == 'buses' else ('route_code', 'route_name', 'start_location', 'destination')
            condition = Q()
            for field in fields:
                condition |= Q(**{field + '__icontains': search})
            qs = qs.filter(condition)
        if request.GET.get('status') in ('active', 'inactive'):
            qs = qs.filter(is_active=request.GET['status'] == 'active')
        headers = ['Bus', 'Registration', 'Capacity', 'Status'] if entity == 'buses' else ['Code', 'Route', 'Direction', 'Status']
    page = page_for(request, qs)
    rows = []
    for obj in page:
        if entity == 'buses':
            cells, active = [obj.bus_number, obj.registration_number, obj.capacity], obj.is_active
        elif entity == 'routes':
            cells, active = [obj.route_code, obj.route_name, obj.get_direction_display()], obj.is_active
        else:
            cells = [obj.user.full_name, obj.user.email, obj.enrollment_number if entity == 'students' else obj.license_number, obj.phone]
            active = obj.user.is_active
        rows.append({'pk': obj.pk, 'cells': cells, 'active': active})
    return render(request, 'admin_portal/list.html', {'title': label, 'section': entity, 'entity': entity, 'headers': headers,
        'rows': rows, 'page_obj': page, 'q': search, 'status_filter': request.GET.get('status', '')})


@admin_required
def entity_edit(request, entity, pk=None):
    model, label, form_class = config(entity)
    instance = get_object_or_404(model, pk=pk) if pk else None
    if entity in ('students', 'drivers'):
        form = form_class(request.POST or None, kind=entity[:-1], instance=instance)
    else:
        form = form_class(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        try:
            if entity in ('students', 'drivers'):
                obj = services.save_person(entity[:-1], form.cleaned_data, instance)
            else:
                obj = (services.save_bus if entity == 'buses' else services.save_route)(form.cleaned_data, instance)
        except (ValidationError, IntegrityError) as exc:
            error_on(form, exc)
        else:
            messages.success(request, 'Record saved successfully.')
            return redirect('admin_portal:detail', entity=entity, pk=obj.pk)
    singular = {'buses': 'bus', 'drivers': 'driver', 'students': 'student', 'routes': 'route'}[entity]
    return render(request, 'admin_portal/form.html', {'form': form, 'title': ('Edit ' if pk else 'Add ') + singular,
        'section': entity, 'back_url': reverse('admin_portal:list', args=[entity]),
        'intro': 'Changes are validated against current assignments and trips. Deactivation preserves historical records.'})


@admin_required
def entity_detail(request, entity, pk):
    model, label, _ = config(entity)
    obj = get_object_or_404(model, pk=pk)
    context = {'entity': entity, 'section': entity, 'obj': obj}
    if entity == 'buses':
        context.update(title=obj.bus_number, active=obj.is_active, details=[('Registration', obj.registration_number), ('Capacity', obj.capacity), ('Description', obj.description or '—')],
            driver_assignments=obj.driver_assignments.select_related('driver__user', 'route').order_by('-assigned_date'),
            student_assignments=obj.student_assignments.select_related('student__user', 'pickup_stop').order_by('-assigned_date'),
            trips=obj.trips.select_related('route', 'driver__user').order_by('-id')[:20])
    elif entity == 'routes':
        context.update(title=f'{obj.route_code} · {obj.route_name}', active=obj.is_active,
            details=[('Start', obj.start_location), ('Destination', obj.destination), ('Direction', obj.get_direction_display())],
            stops=obj.route_stops.select_related('stop'), route_map=queries.route_map(obj),
            driver_assignments=obj.driver_assignments.select_related('driver__user', 'bus').order_by('-assigned_date'))
    else:
        details = [('Email', obj.user.email), ('Phone', obj.phone)]
        details += [('Enrollment', obj.enrollment_number), ('Department', obj.department), ('Semester', obj.semester)] if entity == 'students' else [('License', obj.license_number)]
        context.update(title=obj.user.full_name, active=obj.user.is_active, details=details)
        if entity == 'students':
            context['student_assignments'] = obj.bus_assignments.select_related('bus', 'pickup_stop', 'student__user').order_by('-assigned_date')
        else:
            context['driver_assignments'] = obj.bus_assignments.select_related('bus', 'route', 'driver__user').order_by('-assigned_date')
    return render(request, 'admin_portal/detail.html', context)


@admin_required
@require_http_methods(['GET', 'POST'])
def deactivate(request, entity, pk):
    model, label, _ = config(entity)
    obj = get_object_or_404(model, pk=pk)
    error = None
    if request.method == 'POST':
        try:
            if entity in ('students', 'drivers'):
                services.save_person(entity[:-1], {'is_active': False}, obj)
            else:
                (services.save_bus if entity == 'buses' else services.save_route)({'is_active': False}, obj)
        except (ValidationError, IntegrityError) as exc:
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'This record is still in use.'
        else:
            messages.success(request, 'Record deactivated. Historical records have been preserved.')
            return redirect('admin_portal:detail', entity=entity, pk=pk)
    return render(request, 'admin_portal/confirm.html', {'title': 'Deactivate record', 'section': entity,
        'description': 'Active trips prevent deactivation. Deactivating a bus ends its current assignments and cancels scheduled trips. Reactivation does not restore old assignments.',
        'error': error, 'back_url': reverse('admin_portal:detail', args=[entity, pk])})


@admin_required
def assignments(request):
    q = request.GET.get('q', '').strip()
    students = StudentBusAssignment.objects.select_related('student__user', 'bus', 'pickup_stop').order_by('-assigned_date')
    drivers = DriverAssignment.objects.select_related('driver__user', 'bus', 'route').order_by('-assigned_date')
    if q:
        students = students.filter(Q(student__user__full_name__icontains=q) | Q(bus__bus_number__icontains=q))
        drivers = drivers.filter(Q(driver__user__full_name__icontains=q) | Q(bus__bus_number__icontains=q) | Q(route__route_code__icontains=q))
    return render(request, 'admin_portal/assignments.html', {'title': 'Assignments', 'section': 'assignments', 'q': q,
        'students': page_for(request, students, 'student_page'), 'drivers': page_for(request, drivers, 'driver_page')})


@admin_required
def assignment_edit(request, kind):
    if kind not in ('student', 'driver'):
        raise Http404
    form = (forms.StudentAssignmentForm if kind == 'student' else forms.DriverAssignmentForm)(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            (services.assign_student if kind == 'student' else services.assign_driver)(**form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            error_on(form, exc)
        else:
            messages.success(request, 'Assignment saved. Previous assignment history has been retained.')
            return redirect('admin_portal:assignments')
    return render(request, 'admin_portal/form.html', {'title': 'Assign student to bus' if kind == 'student' else 'Assign driver and route',
        'section': 'assignments', 'form': form, 'assignment_kind': kind,
        'intro': 'Select a bus to load its route pickup stops.' if kind == 'student' else 'A driver can have one active bus. Replacing this bus’s assignment also validates every student pickup stop.',
        'back_url': reverse('admin_portal:assignments')})


@admin_required
@require_http_methods(['GET', 'POST'])
def assignment_end(request, kind, pk):
    if kind not in ('student', 'driver'):
        raise Http404
    get_object_or_404(StudentBusAssignment if kind == 'student' else DriverAssignment, pk=pk)
    error = None
    if request.method == 'POST':
        try:
            services.end_assignment(kind, pk)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        else:
            messages.success(request, 'Assignment ended.')
            return redirect('admin_portal:assignments')
    return render(request, 'admin_portal/confirm.html', {'title': 'End assignment', 'section': 'assignments',
        'description': 'This ends the active assignment and preserves its history. A driver assignment cannot end during an active trip or while student pickups depend on it.',
        'error': error, 'back_url': reverse('admin_portal:assignments')})


@admin_required
def stop_edit(request, route_pk, pk=None):
    route = get_object_or_404(Route, pk=route_pk)
    stop = get_object_or_404(BusStop, pk=pk, route_stops__route=route) if pk else None
    form = forms.StopForm(request.POST or None, instance=stop)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data.copy()
        if data.get('stop_order') is None:
            data.pop('stop_order', None)
        try:
            services.save_stop(route, data, stop)
        except (ValidationError, IntegrityError) as exc:
            error_on(form, exc)
        else:
            messages.success(request, 'Stop saved.')
            return redirect('admin_portal:detail', entity='routes', pk=route.pk)
    return render(request, 'admin_portal/form.html', {'title': 'Edit stop' if stop else 'Add stop', 'section': 'routes', 'form': form,
        'intro': 'Enter verified coordinates. Editing a shared stop updates it on every route that uses it. Original CSV metadata is retained.',
        'back_url': reverse('admin_portal:detail', args=['routes', route.pk])})


@admin_required
@require_http_methods(['POST'])
def stop_reorder(request, route_pk):
    route = get_object_or_404(Route, pk=route_pk)
    stops = list(route.route_stops.all())
    try:
        ordered = sorted([(int(request.POST.get(f'order_{row.stop_id}', '')), row.stop_id) for row in stops])
        if [order for order, pk in ordered] != list(range(1, len(stops) + 1)):
            raise ValidationError('Order must contain every number from 1 to the stop count exactly once.')
        services.reorder_stops(route, [pk for order, pk in ordered])
    except (ValueError, ValidationError) as exc:
        messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Enter a valid order for every stop.')
    else:
        messages.success(request, 'Stop order updated.')
    return redirect('admin_portal:detail', entity='routes', pk=route.pk)


@admin_required
@require_http_methods(['GET', 'POST'])
def stop_remove(request, route_pk, pk):
    route = get_object_or_404(Route, pk=route_pk)
    stop = get_object_or_404(BusStop, pk=pk, route_stops__route=route)
    error = None
    if request.method == 'POST':
        try:
            services.remove_stop(route, stop)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        else:
            messages.success(request, 'Stop removed from route. The stop record and history are retained.')
            return redirect('admin_portal:detail', entity='routes', pk=route.pk)
    return render(request, 'admin_portal/confirm.html', {'title': 'Remove route stop', 'section': 'routes', 'description': f'Remove {stop.name} from {route.route_code}? Active pickup stops cannot be removed.',
        'error': error, 'back_url': reverse('admin_portal:detail', args=['routes', route.pk])})


@admin_required
def import_route(request):
    form = forms.ImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            route = import_upload(form.cleaned_data['file'], form.cleaned_data['direction'])
        except (ValidationError, IntegrityError) as exc:
            error_on(form, exc)
        else:
            messages.success(request, 'R001 imported: 21 ordered stops. Observations and uncertain names remain provisional.')
            return redirect('admin_portal:detail', entity='routes', pk=route.pk)
    return render(request, 'admin_portal/form.html', {'form': form, 'title': 'Import R001 route', 'section': 'routes',
        'intro': 'Upload the college CSV (maximum 2 MB). Required columns: stop_order or stop_order_shared, name or stop_name, latitude, longitude. Exactly 21 stops, starting at NIE Golden Jubilee and ending at North Campus Last Stop. Import replaces R001’s stop list; existing student pickup assignments must remain valid.',
        'back_url': reverse('admin_portal:list', args=['routes'])})


@admin_required
def map_view(request):
    routes = Route.objects.order_by('route_code')
    selected = get_object_or_404(Route, pk=request.GET['route']) if request.GET.get('route', '').isdigit() else None
    fleet = queries.live_buses()
    return render(request, 'admin_portal/map.html', {'title': 'Fleet map', 'section': 'map', 'routes': routes, 'selected_route': selected,
        'route_map': queries.route_map(selected) if selected else None, 'fleet': fleet, 'active_bus_count': sum(bus['is_active'] for bus in fleet),
        'poll_interval_seconds': settings.ADMIN_POLL_INTERVAL_SECONDS})
