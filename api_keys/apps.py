"""
API Keys app configuration.
"""

from django.apps import AppConfig


class ApiKeysConfig(AppConfig):
    """Configuration for the API Keys application."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api_keys'
    verbose_name = 'API Key Management'
    
    def ready(self):
        """Import signals when the app is ready."""
        try:
            from . import signals
        except ImportError:
            pass
