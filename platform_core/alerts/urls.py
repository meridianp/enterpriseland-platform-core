"""
Alert API URLs
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AlertRuleViewSet, AlertChannelViewSet,
    AlertViewSet, AlertSilenceViewSet
)

router = DefaultRouter()
router.register(r'rules', AlertRuleViewSet)
router.register(r'channels', AlertChannelViewSet)
router.register(r'alerts', AlertViewSet)
router.register(r'silences', AlertSilenceViewSet)

app_name = 'alerts'

urlpatterns = [
    path('', include(router.urls)),
]