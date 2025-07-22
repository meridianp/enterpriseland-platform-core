"""
Performance Monitoring URLs
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api import PerformanceMonitoringViewSet, PerformanceDashboardViewSet

app_name = 'performance'

# Create router
router = DefaultRouter()
router.register('monitoring', PerformanceMonitoringViewSet, basename='monitoring')
router.register('dashboard', PerformanceDashboardViewSet, basename='dashboard')

urlpatterns = [
    path('', include(router.urls)),
]