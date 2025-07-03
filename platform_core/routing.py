"""
Main ASGI Routing Configuration

Combines HTTP and WebSocket routing.
"""

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.core.asgi import get_asgi_application

from platform_core.websocket.routing import websocket_urlpatterns
from platform_core.websocket.middleware import WebSocketMiddlewareStack

# Get Django ASGI application
django_asgi_app = get_asgi_application()

# Main application routing
application = ProtocolTypeRouter({
    # HTTP requests are handled by Django
    'http': django_asgi_app,
    
    # WebSocket requests are handled by Channels
    'websocket': WebSocketMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})