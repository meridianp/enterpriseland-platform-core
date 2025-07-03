"""
Event System URLs
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    EventSchemaViewSet,
    EventSubscriptionViewSet,
    EventViewSet,
    EventProcessorViewSet,
    SagaInstanceViewSet,
    EventPublishView,
    EventStatusView,
    SubscriptionHealthView
)

# Create router
router = DefaultRouter()
router.register(r'schemas', EventSchemaViewSet, basename='event-schema')
router.register(r'subscriptions', EventSubscriptionViewSet, basename='event-subscription')
router.register(r'events', EventViewSet, basename='event')
router.register(r'processors', EventProcessorViewSet, basename='event-processor')
router.register(r'sagas', SagaInstanceViewSet, basename='saga-instance')

app_name = 'events'

urlpatterns = [
    # Router URLs
    path('api/', include(router.urls)),
    
    # Custom endpoints
    path('api/publish/', EventPublishView.as_view(), name='event-publish'),
    path('api/events/<uuid:event_id>/status/', EventStatusView.as_view(), name='event-status'),
    path('api/subscriptions/<str:name>/health/', SubscriptionHealthView.as_view(), name='subscription-health'),
]