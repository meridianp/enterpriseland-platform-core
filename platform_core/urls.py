from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('platform_core.accounts.urls')),
    path('api/files/', include('platform_core.files.urls')),
    path('api/notifications/', include('platform_core.notifications.urls')),
    path('api/workflows/', include('platform_core.workflows.urls')),
    path('api/agents/', include('platform_core.agents.urls')),
    path('api/audit/', include('platform_core.audit.urls')),
    path('api/api-keys/', include('platform_core.api_keys.urls')),
    path('api/modules/', include('platform_core.modules.urls')),
    path('api/gateway/', include('platform_core.gateway.urls')),
    path('api/events/', include('platform_core.events.urls')),
    path('api/websocket/', include('platform_core.websocket.urls')),
    path('api/alerts/', include('platform_core.alerts.urls')),
    path('metrics/', include('platform_core.monitoring.urls')),
    path('health/', include('platform_core.health.urls')),
]
