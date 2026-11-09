from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import IsStudent
from .queries import dashboard_snapshot


class StudentAPI(APIView):
    permission_classes = [IsStudent]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response

    def get(self, request):
        # Deliberately ignore all bus/route identifiers in query parameters.
        return Response(dashboard_snapshot(request.user))


class MyRouteAPI(StudentAPI):
    def get(self, request):
        data = dashboard_snapshot(request.user)
        return Response({key: data[key] for key in ('status', 'message', 'bus', 'route', 'pickup_stop', 'generated_at')})


class MyETAAPI(StudentAPI):
    def get(self, request):
        data = dashboard_snapshot(request.user)
        return Response({**data['eta'], 'assignment_status': data['status'],
                         'bus_id': data['bus']['id'] if data['bus'] else None,
                         'pickup_stop_id': data['pickup_stop']['id'] if data['pickup_stop'] else None,
                         'generated_at': data['generated_at']})
