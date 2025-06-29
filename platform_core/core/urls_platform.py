"""
Platform Core URL Configuration
Only includes core platform services, not business modules
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from django.http import JsonResponse
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView


def root_redirect(request):
    """Redirect root URL to API docs"""
    return redirect('/api/docs/')


def health_check(request):
    """Health check endpoint"""
    return JsonResponse({
        'status': 'healthy',
        'service': 'platform-core',
        'version': '1.0.0'
    })


app_name = 'platform_core'

urlpatterns = [
    path('', root_redirect, name='root'),
    path('admin/', admin.site.urls),
    
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    # Core platform endpoints
    path('api/auth/', include('platform_core.accounts.urls')),
    path('api/files/', include('platform_core.files.urls')),
    path('api/notifications/', include('platform_core.notifications.urls')),
    path('api/integrations/', include('platform_core.integrations.urls')),
    
    # Health check
    path('health/', health_check, name='health'),
    path('api/health/', health_check, name='api_health'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)