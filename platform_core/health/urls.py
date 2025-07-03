"""
Health Check URLs
"""
from django.urls import path

from .views import (
    HealthCheckView,
    ReadinessProbeView,
    LivenessProbeView,
    HealthDetailView
)

app_name = 'health'

urlpatterns = [
    path('', HealthCheckView.as_view(), name='health'),
    path('ready/', ReadinessProbeView.as_view(), name='ready'),
    path('live/', LivenessProbeView.as_view(), name='live'),
    path('check/<str:check_name>/', HealthDetailView.as_view(), name='health-detail'),
]