"""
Django app configuration for the notifications module.
"""
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """Configuration for the notifications app."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.notifications'
    verbose_name = 'Platform Notifications'
    
    def ready(self):
        """Register signal handlers when Django starts."""
        # Import signals to register them
        from . import signals