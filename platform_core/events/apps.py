"""
Events App Configuration
"""

from django.apps import AppConfig


class EventsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.events'
    verbose_name = 'Event-Driven Messaging'
    
    def ready(self):
        """Initialize event system when app is ready"""
        # Import signal handlers
        from . import signals  # noqa
        
        # Start event consumers if configured
        from django.conf import settings
        if getattr(settings, 'EVENTS_AUTO_START', True):
            from .consumers import start_consumers
            # This would be called in a management command or celery task
            # to avoid blocking Django startup
            pass