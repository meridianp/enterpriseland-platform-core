"""
Transitional URL configuration for Cloud Run deployment
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from rest_framework import routers
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

def health_check(request):
    return JsonResponse({'status': 'healthy', 'service': 'platform-core', 'version': 'transitional'})

# Create a router for API endpoints
router = routers.DefaultRouter()

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # Health checks
    path('health/', health_check),
    path('api/health/', health_check),
    
    # API documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    
    # API router (will add ViewSets here as we enable apps)
    path('api/', include(router.urls)),
    
    # Root endpoint
    path('', health_check),
]