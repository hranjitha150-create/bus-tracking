from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from accounts.permissions import CanAccessBus
from .models import Bus


class BusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bus
        fields = ['id', 'bus_number', 'registration_number', 'capacity', 'description', 'is_active']


class BusViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BusSerializer
    permission_classes = viewsets.ReadOnlyModelViewSet.permission_classes + [CanAccessBus]

    def get_queryset(self):
        qs = Bus.objects.order_by('bus_number')
        user = self.request.user
        if user.role == 'ADMIN':
            return qs
        if user.role == 'STUDENT':
            return qs.filter(student_assignments__student__user=user, student_assignments__is_active=True, is_active=True)
        if user.role == 'DRIVER':
            return qs.filter(driver_assignments__driver__user=user, driver_assignments__is_active=True, is_active=True)
        return qs.none()

    @action(detail=True, methods=['get'])
    def location(self, request, pk=None):
        from tracking.api import LocationSerializer
        from tracking.models import BusLocation
        bus = self.get_object()
        location = BusLocation.objects.filter(bus=bus).first()
        if not location:
            return Response({'detail': 'No location recorded.'}, status=404)
        return Response(LocationSerializer(location).data)
