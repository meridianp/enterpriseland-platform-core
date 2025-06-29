app_name = 'platform_core'


from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

def root_redirect(request):
    """Redirect root URL to frontend or API docs"""
    return redirect('http://localhost:3000' if settings.DEBUG else '/api/docs/')

urlpatterns = [
    path('', root_redirect, name='root'),
    path('admin/', admin.site.urls),
    
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    # API endpoints
    path('api/auth/', include('accounts.urls')),
    path('api/', include('api_keys.urls')),
    path('api/assessments/', include('assessments.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/files/', include('files.urls')),
    path('api/', include('contacts.urls')),
    path('api/market-intelligence/', include('market_intelligence.urls')),
    path('api/leads/', include('leads.urls')),
    path('api/geographic-intelligence/', include('geographic_intelligence.urls')),
    path('api/deals/', include('deals.urls')),
    
    # Health check
    path('health/', include('core.health_urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
