from django.urls import include, path
from rest_framework.routers import DefaultRouter
from accounts import views
from buses.api import BusViewSet
from tracking.api import TripViewSet
from admin_portal import api as admin_api
from students import api as student_api
from drivers import api as driver_api

admin_router = DefaultRouter()
admin_router.register('buses', admin_api.BusViewSet, basename='admin-bus')
admin_router.register('students', admin_api.StudentViewSet, basename='admin-student')
admin_router.register('drivers', admin_api.DriverViewSet, basename='admin-driver')
admin_router.register('routes', admin_api.RouteViewSet, basename='admin-route')

router = DefaultRouter()
router.register('buses', BusViewSet, basename='bus')
router.register('trips', TripViewSet, basename='trip')
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.WebsiteLoginView.as_view(), name='login'),
    path('logout/', views.website_logout, name='logout'),
    path('dashboard/admin/', views.admin_dashboard, name='admin-dashboard'),
    path('dashboard/student/', views.student_dashboard, name='student-dashboard'),
    path('dashboard/driver/', views.driver_dashboard, name='driver-dashboard'),
    path('api/auth/login/', views.api_login),
    path('api/auth/logout/', views.api_logout),
    path('api/auth/me/', views.api_me),
    path('portal/', include('admin_portal.urls')),
    path('student/', include('students.urls')),
    path('api/driver/assignment/', driver_api.AssignmentAPI.as_view()),
    path('api/driver/trips/start/', driver_api.StartTripAPI.as_view()),
    path('api/driver/trips/<int:trip_id>/location/', driver_api.LocationAPI.as_view()),
    path('api/driver/trips/<int:trip_id>/end/', driver_api.EndTripAPI.as_view()),
    path('api/development/trips/start/', driver_api.ReplayStartAPI.as_view()),
    path('api/development/trips/<int:trip_id>/location/', driver_api.ReplayLocationAPI.as_view()),
    path('api/student/dashboard/', student_api.StudentAPI.as_view()),
    path('api/student/my-bus/', student_api.StudentAPI.as_view()),
    path('api/student/my-route/', student_api.MyRouteAPI.as_view()),
    path('api/student/my-bus/location/', student_api.StudentAPI.as_view()),
    path('api/student/my-bus/eta/', student_api.MyETAAPI.as_view()),
    path('api/admin/assignments/', admin_api.AssignmentAPI.as_view()),
    path('api/admin/assignments/<str:kind>/<int:pk>/end/', admin_api.EndAssignmentAPI.as_view()),
    path('api/admin/live-buses/', admin_api.LiveBusesAPI.as_view()),
    path('api/admin/pickup-stops/', admin_api.PickupStopsAPI.as_view()),
    path('api/admin/', include(admin_router.urls)),
    path('api/', include(router.urls)),
]
