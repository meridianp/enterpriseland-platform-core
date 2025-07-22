"""
URL configuration for the notifications app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    NotificationViewSet, NotificationPreferenceViewSet,
    NotificationTemplateViewSet
)

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'notification-preferences', NotificationPreferenceViewSet, basename='notification-preference')
router.register(r'notification-templates', NotificationTemplateViewSet, basename='notification-template')

urlpatterns = [
    path('', include(router.urls)),
]