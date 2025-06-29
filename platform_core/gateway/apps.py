"""
Gateway App Configuration
"""

from django.apps import AppConfig


class GatewayConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.gateway'
    verbose_name = 'API Gateway'
    
    def ready(self):
        """Initialize gateway when app is ready"""
        # Import signal handlers
        from . import signals  # noqa