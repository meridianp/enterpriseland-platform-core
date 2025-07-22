"""URL configuration for document management API v1."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DocumentViewSet, FolderViewSet, DocumentTemplateViewSet,
    SharedLinkViewSet, DocumentAuditViewSet
)

app_name = 'documents_api_v1'

# Create router
router = DefaultRouter()

# Register viewsets
router.register(r'documents', DocumentViewSet, basename='document')
router.register(r'folders', FolderViewSet, basename='folder')
router.register(r'templates', DocumentTemplateViewSet, basename='template')
router.register(r'shared-links', SharedLinkViewSet, basename='sharedlink')
router.register(r'audit', DocumentAuditViewSet, basename='audit')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
]