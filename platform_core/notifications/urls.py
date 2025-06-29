app_name = 'platform_notifications'


from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    NotificationViewSet, EmailNotificationViewSet,
    WebhookEndpointViewSet, WebhookDeliveryViewSet
)

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet)
router.register(r'email-notifications', EmailNotificationViewSet)
router.register(r'webhook-endpoints', WebhookEndpointViewSet)
router.register(r'webhook-deliveries', WebhookDeliveryViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
