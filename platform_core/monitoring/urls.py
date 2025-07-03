"""
Monitoring URLs
"""
from django.urls import path
from .views import (
    MetricsView, HealthView, ReadinessView, 
    LivenessView, MetricsDashboardView
)

app_name = 'monitoring'

urlpatterns = [
    path('', MetricsView.as_view(), name='metrics'),
    path('health/', HealthView.as_view(), name='health'),
    path('ready/', ReadinessView.as_view(), name='readiness'),
    path('alive/', LivenessView.as_view(), name='liveness'),
    path('dashboard/', MetricsDashboardView.as_view(), name='metrics-dashboard'),
]