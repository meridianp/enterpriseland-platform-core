"""
URL configuration for the files app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import FileViewSet

router = DefaultRouter()
router.register(r'files', FileViewSet, basename='file')

urlpatterns = [
    path('', include(router.urls)),
]