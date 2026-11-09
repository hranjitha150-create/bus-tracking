from django.urls import path
from . import views

app_name = 'admin_portal'
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('map/', views.map_view, name='map'),
    path('routes/import/', views.import_route, name='import'),
    path('routes/<int:route_pk>/import/', views.import_route, name='route-import'),
    path('routes/<int:route_pk>/stops/bulk/', views.stops_bulk, name='stops-bulk'),
    path('routes/<int:route_pk>/stops/add/', views.stop_edit, name='stop-add'),
    path('routes/<int:route_pk>/stops/<int:pk>/edit/', views.stop_edit, name='stop-edit'),
    path('routes/<int:route_pk>/stops/<int:pk>/remove/', views.stop_remove, name='stop-remove'),
    path('routes/<int:route_pk>/stops/reorder/', views.stop_reorder, name='stop-reorder'),
    path('assignments/', views.assignments, name='assignments'),
    path('assignments/<str:kind>/add/', views.assignment_edit, name='assignment-add'),
    path('assignments/<str:kind>/<int:pk>/end/', views.assignment_end, name='assignment-end'),
    path('<str:entity>/', views.entity_list, name='list'),
    path('<str:entity>/add/', views.entity_edit, name='add'),
    path('<str:entity>/<int:pk>/', views.entity_detail, name='detail'),
    path('<str:entity>/<int:pk>/edit/', views.entity_edit, name='edit'),
    path('<str:entity>/<int:pk>/deactivate/', views.deactivate, name='deactivate'),
]
