from django.urls import path, include
from rest_framework.routers import DefaultRouter

app_name = 'workflows'
router = DefaultRouter()

urlpatterns = [
    path('api/workflows/', include(router.urls)),
]
