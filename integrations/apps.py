"""
Django app configuration for the integrations module.
"""
from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """Configuration for the integrations app."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.integrations'
    verbose_name = 'Platform Integrations'
    
    def ready(self):
        """Initialize the provider registry when Django starts."""
        from .registry import provider_registry
        
        # Initialize the registry
        provider_registry.initialize()