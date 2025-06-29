"""
Gateway URL Configuration
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ServiceRegistryViewSet, RouteViewSet, GatewayConfigViewSet,
    ServiceInstanceViewSet, APIAggregationViewSet, GatewayHealthView
)

app_name = 'gateway'

# Create router
router = DefaultRouter()
router.register(r'services', ServiceRegistryViewSet, basename='service')
router.register(r'routes', RouteViewSet, basename='route')
router.register(r'config', GatewayConfigViewSet, basename='config')
router.register(r'instances', ServiceInstanceViewSet, basename='instance')
router.register(r'aggregations', APIAggregationViewSet, basename='aggregation')
router.register(r'health', GatewayHealthView, basename='health')

urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),
    
    # Gateway proxy endpoint would be handled by middleware
    # path('proxy/', gateway_proxy_view, name='proxy'),
]