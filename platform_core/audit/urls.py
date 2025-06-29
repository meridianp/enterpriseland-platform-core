from django.urls import path, include
from rest_framework.routers import DefaultRouter

app_name = 'audit'
router = DefaultRouter()

urlpatterns = [
    path('api/audit/', include(router.urls)),
]
