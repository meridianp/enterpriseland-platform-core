"""
WebSocket URLs
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    WebSocketConnectionViewSet,
    WebSocketRoomViewSet,
    WebSocketMessageViewSet,
    WebSocketStatusView
)

# Create router
router = DefaultRouter()
router.register(r'connections', WebSocketConnectionViewSet, basename='websocket-connection')
router.register(r'rooms', WebSocketRoomViewSet, basename='websocket-room')
router.register(r'messages', WebSocketMessageViewSet, basename='websocket-message')

app_name = 'websocket'

urlpatterns = [
    # Router URLs
    path('api/', include(router.urls)),
    
    # Custom endpoints
    path('api/status/', WebSocketStatusView.as_view(), name='websocket-status'),
]