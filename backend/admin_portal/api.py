from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.utils import timezone
from rest_framework import serializers, viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import IsAdmin
from buses.models import Bus
from students.models import Student
from drivers.models import Driver
from routes.models import Route, BusStop
from assignments.models import StudentBusAssignment, DriverAssignment
from . import services, queries
from .uploads import import_upload, import_route_upload


class AdminErrors:
    permission_classes = [IsAdmin]

    def handle_exception(self, exc):
        if isinstance(exc, ModelValidationError):
            exc = ValidationError(getattr(exc, 'message_dict', {'non_field_errors': exc.messages}))
        elif isinstance(exc, IntegrityError):
            exc = ValidationError('This change conflicts with existing records. Refresh and review the values.')
        response = super().handle_exception(exc)
        if isinstance(response.data, dict) and 'detail' in response.data:
            response.data = {'detail': response.data['detail'], 'errors': {}}
        else:
            response.data = {'detail': 'Validation failed.', 'errors': response.data}
        return response


class PersonSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, required=False, max_length=128, trim_whitespace=False)
    phone = serializers.CharField(max_length=20)
    is_active = serializers.BooleanField(default=True)
    kind = None

    def validate(self, attrs):
        if not self.instance and not attrs.get('password'):
            raise ValidationError({'password': 'An initial password is required.'})
        return attrs

    def create(self, validated_data):
        return services.save_person(self.kind, validated_data)

    def update(self, instance, validated_data):
        return services.save_person(self.kind, validated_data, instance)

    def to_representation(self, obj):
        result = {'id': obj.pk, 'user_id': obj.user_id, 'full_name': obj.user.full_name, 'email': obj.user.email,
                  'phone': obj.phone, 'is_active': obj.user.is_active}
        for field in (['enrollment_number', 'department', 'semester'] if self.kind == 'student' else ['license_number']):
            result[field] = getattr(obj, field)
        return result


class StudentSerializer(PersonSerializer):
    kind = 'student'
    enrollment_number = serializers.CharField(max_length=50)
    department = serializers.CharField(max_length=100)
    semester = serializers.IntegerField(min_value=1, max_value=12)


class DriverSerializer(PersonSerializer):
    kind = 'driver'
    license_number = serializers.CharField(max_length=50)


class BusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bus
        fields = ['id', 'bus_number', 'registration_number', 'capacity', 'description', 'is_active']

    def create(self, data):
        return services.save_bus(data)

    def update(self, instance, data):
        return services.save_bus(data, instance)


class RouteSerializer(serializers.ModelSerializer):
    stops = serializers.SerializerMethodField()
    class Meta:
        model = Route
        fields = ['id', 'route_code', 'route_name', 'start_location', 'destination', 'direction', 'is_active', 'geometry', 'stops']

    def get_stops(self, obj):
        return queries.route_map(obj)['stops']

    def create(self, data):
        return services.save_route(data)

    def update(self, instance, data):
        return services.save_route(data, instance)


class AdminViewSet(AdminErrors, viewsets.ModelViewSet):
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    filter_backends = [filters.SearchFilter]


class BusViewSet(AdminViewSet):
    queryset = Bus.objects.order_by('bus_number')
    serializer_class = BusSerializer
    search_fields = ['bus_number', 'registration_number']


class StudentViewSet(AdminViewSet):
    queryset = Student.objects.select_related('user').order_by('user__full_name', 'pk')
    serializer_class = StudentSerializer
    search_fields = ['user__full_name', 'user__email', 'enrollment_number', 'department']


class DriverViewSet(AdminViewSet):
    queryset = Driver.objects.select_related('user').order_by('user__full_name', 'pk')
    serializer_class = DriverSerializer
    search_fields = ['user__full_name', 'user__email', 'license_number']


class RouteViewSet(AdminViewSet):
    queryset = Route.objects.prefetch_related('route_stops__stop').order_by('route_code')
    serializer_class = RouteSerializer
    search_fields = ['route_code', 'route_name', 'start_location', 'destination']

    @action(detail=False, methods=['post'], url_path='import', parser_classes=[MultiPartParser, FormParser])
    def import_csv(self, request):
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        route = import_route_upload(data['file'], data['direction'], data.get('route_code', ''),
            data.get('route_name', ''), default_code='R001')
        return Response({'detail': f'{route.route_code} imported: {route.route_stops.count()} stops. Source metadata retained.', 'route': RouteSerializer(route).data})

    @action(detail=True, methods=['post'], url_path='import-stops', parser_classes=[MultiPartParser, FormParser])
    def import_stops(self, request, pk=None):
        target = self.get_object()
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        route = import_route_upload(data['file'], data['direction'], route_name=data.get('route_name', ''), target=target)
        return Response({'detail': f'{route.route_stops.count()} stops imported.', 'route': RouteSerializer(route).data})


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    route_code = serializers.CharField(max_length=30, required=False)
    route_name = serializers.CharField(max_length=150, required=False)
    direction = serializers.ChoiceField(choices=Route.Direction.choices, default='TO_COLLEGE')


class AssignmentSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['student', 'driver'])
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all(), required=False)
    driver = serializers.PrimaryKeyRelatedField(queryset=Driver.objects.all(), required=False)
    bus = serializers.PrimaryKeyRelatedField(queryset=Bus.objects.all())
    route = serializers.PrimaryKeyRelatedField(queryset=Route.objects.all(), required=False)
    pickup_stop = serializers.PrimaryKeyRelatedField(queryset=BusStop.objects.all(), required=False)

    def validate(self, data):
        required = ['student', 'pickup_stop'] if data['kind'] == 'student' else ['driver', 'route']
        missing = {name: 'This field is required.' for name in required if name not in data}
        if missing:
            raise ValidationError(missing)
        return data


def assignment_data(obj):
    student = isinstance(obj, StudentBusAssignment)
    return {'id': obj.pk, 'kind': 'student' if student else 'driver', 'bus': obj.bus_id,
            'student': obj.student_id if student else None, 'driver': None if student else obj.driver_id,
            'pickup_stop': obj.pickup_stop_id if student else None, 'route': None if student else obj.route_id,
            'is_active': obj.is_active, 'assigned_date': obj.assigned_date}


class AssignmentAPI(AdminErrors, APIView):
    def post(self, request):
        serializer = AssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data['kind'] == 'student':
            obj = services.assign_student(data['student'], data['bus'], data['pickup_stop'])
        else:
            obj = services.assign_driver(data['driver'], data['bus'], data['route'])
        return Response(assignment_data(obj), status=status.HTTP_201_CREATED)


class EndAssignmentAPI(AdminErrors, APIView):
    def post(self, request, kind, pk):
        if kind not in ('student', 'driver'):
            raise ValidationError('Unknown assignment kind.')
        model = StudentBusAssignment if kind == 'student' else DriverAssignment
        get_object_or_404(model, pk=pk)
        return Response(assignment_data(services.end_assignment(kind, pk)))


class LiveBusesAPI(AdminErrors, APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response

    def get(self, request):
        rows = queries.live_buses()
        return Response({'count': len(rows), 'active_count': sum(row['is_active'] for row in rows), 'results': rows,
                         'generated_at': timezone.now().isoformat(), 'stale_after_seconds': settings.GPS_STALE_SECONDS,
                         'poll_interval_seconds': settings.ADMIN_POLL_INTERVAL_SECONDS})


class PickupStopsAPI(AdminErrors, APIView):
    def get(self, request):
        bus = get_object_or_404(Bus, pk=request.query_params.get('bus') if str(request.query_params.get('bus', '')).isdigit() else 0, is_active=True)
        assignment = bus.driver_assignments.filter(is_active=True, route__is_active=True).first()
        stops = queries.route_map(assignment.route)['stops'] if assignment else []
        return Response({'results': stops})
