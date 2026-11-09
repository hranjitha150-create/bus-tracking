from django.urls import path
from . import views

app_name = 'students'
urlpatterns = [
    path('', views.portal, name='dashboard'),
    path('bus/', views.portal, {'section': 'bus'}, name='bus'),
    path('tracking/', views.portal, {'section': 'tracking'}, name='tracking'),
    path('route/', views.portal, {'section': 'route'}, name='route'),
    path('pickup/', views.portal, {'section': 'pickup'}, name='pickup'),
    path('profile/', views.portal, {'section': 'profile'}, name='profile'),
]
