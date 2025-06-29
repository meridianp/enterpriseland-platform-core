from django.urls import path, include
from rest_framework.routers import DefaultRouter

app_name = 'encryption'
router = DefaultRouter()

urlpatterns = [
    path('api/encryption/', include(router.urls)),
]
