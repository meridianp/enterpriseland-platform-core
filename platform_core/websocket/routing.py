"""
WebSocket Routing

Django Channels routing configuration.
"""

from django.urls import re_path, path
from channels.routing import URLRouter, ProtocolTypeRouter
from channels.auth import AuthMiddlewareStack

from .consumers import (
    NotificationConsumer,
    EventConsumer,
    ChatConsumer,
    PresenceConsumer
)
from .middleware import WebSocketMiddlewareStack

# WebSocket URL patterns
websocket_urlpatterns = [
    # Notification WebSocket
    re_path(r'ws/notifications/$', NotificationConsumer.as_asgi()),
    
    # Event streaming WebSocket
    re_path(r'ws/events/$', EventConsumer.as_asgi()),
    
    # Chat WebSocket
    re_path(r'ws/chat/$', ChatConsumer.as_asgi()),
    re_path(r'ws/chat/(?P<room_name>\w+)/$', ChatConsumer.as_asgi()),
    
    # Presence WebSocket
    re_path(r'ws/presence/$', PresenceConsumer.as_asgi()),
]

# Main application routing
application = ProtocolTypeRouter({
    'websocket': WebSocketMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})