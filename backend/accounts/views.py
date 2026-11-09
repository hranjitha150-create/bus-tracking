from django.contrib.auth import authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import AccessToken
from .rate_limit import login_allowed


def user_data(user):
    return {'id': user.id, 'full_name': user.full_name, 'email': user.email, 'role': user.role}


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=1024)


@never_cache
@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([])  # Shared account/IP budget below also protects website login.
def api_login(request):
    # SessionAuthentication only enforces CSRF for already authenticated sessions.
    # Enforce it explicitly for every session/browser login; native bearer clients
    # without cookies or Origin headers do not require CSRF tokens.
    if request.META.get('HTTP_ORIGIN') or request.COOKIES:
        SessionAuthentication().enforce_csrf(request)
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if not login_allowed(request, serializer.validated_data['email']):
        return Response({'detail': 'Too many sign-in attempts. Try again in a minute.'}, status=429, headers={'Retry-After': '60'})
    user = authenticate(request, username=serializer.validated_data['email'], password=serializer.validated_data['password'])
    if not user:
        return Response({'detail': 'Invalid email or password.'}, status=401)
    token, raw = AccessToken.issue(user)
    return Response({'token': raw, 'token_type': 'Bearer', 'expires_at': token.expires_at, 'user': user_data(user)})


@never_cache
@api_view(['POST'])
def api_logout(request):
    if isinstance(request.auth, AccessToken):
        request.auth.delete()
    logout(request)
    return Response(status=204)


@never_cache
@api_view(['GET'])
def api_me(request):
    return Response(user_data(request.user))


@method_decorator(never_cache, name='dispatch')
class WebsiteLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if not login_allowed(request, request.POST.get('username', '')):
            return HttpResponse('Too many sign-in attempts. Try again in a minute.', status=429, headers={'Retry-After': '60'})
        return super().post(request, *args, **kwargs)


@login_required
def dashboard(request):
    destinations = {'ADMIN': 'admin-dashboard', 'STUDENT': 'student-dashboard', 'DRIVER': 'driver-dashboard'}
    return redirect(destinations[request.user.role])


def role_page(request, role, template):
    if request.user.role != role:
        raise PermissionDenied
    return render(request, template)


@login_required
def admin_dashboard(request):
    from admin_portal.views import dashboard as portal_dashboard
    return portal_dashboard(request)


@login_required
def student_dashboard(request):
    from students.views import portal
    return portal(request)


@login_required
def driver_dashboard(request):
    return role_page(request, 'DRIVER', 'accounts/driver_dashboard.html')


@require_POST
def website_logout(request):
    logout(request)
    return redirect('login')
