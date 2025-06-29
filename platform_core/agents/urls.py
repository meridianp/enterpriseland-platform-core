from django.urls import path, include
from rest_framework.routers import DefaultRouter

app_name = 'agents'
router = DefaultRouter()

urlpatterns = [
    path('api/agents/', include(router.urls)),
]
