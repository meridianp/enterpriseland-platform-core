from django.urls import path, include
from rest_framework.routers import DefaultRouter

app_name = 'api_keys'
router = DefaultRouter()

urlpatterns = [
    path('api/api_keys/', include(router.urls)),
]
