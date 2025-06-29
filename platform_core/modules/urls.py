"""
Module System URLs
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ModuleManifestViewSet,
    ModuleInstallationViewSet,
    ModuleRegistryView,
    ModuleHealthView,
)

app_name = 'modules'

router = DefaultRouter()
router.register('manifests', ModuleManifestViewSet, basename='manifest')
router.register('installations', ModuleInstallationViewSet, basename='installation')

urlpatterns = [
    path('', include(router.urls)),
    path('registry/', ModuleRegistryView.as_view(), name='registry'),
    path('health/', ModuleHealthView.as_view(), name='health'),
]