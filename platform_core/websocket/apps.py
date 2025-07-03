"""
WebSocket App Configuration
"""

from django.apps import AppConfig


class WebSocketConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.websocket'
    verbose_name = 'WebSocket Support'
    
    def ready(self):
        """Initialize WebSocket system when app is ready"""
        # Import signal handlers
        from . import signals  # noqa
        
        # Register default consumers
        from .registry import consumer_registry
        from .consumers import (
            NotificationConsumer,
            EventConsumer,
            ChatConsumer,
            PresenceConsumer
        )
        
        # Register built-in consumers
        consumer_registry.register('notifications', NotificationConsumer)
        consumer_registry.register('events', EventConsumer)
        consumer_registry.register('chat', ChatConsumer)
        consumer_registry.register('presence', PresenceConsumer)