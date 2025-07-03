"""
Cache App Configuration
"""

from django.apps import AppConfig


class CacheConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.cache'
    verbose_name = 'Caching Layer'
    
    def ready(self):
        """Initialize cache system when app is ready"""
        # Import signal handlers
        from . import signals  # noqa
        
        # Initialize cache warming if configured
        from django.conf import settings
        if getattr(settings, 'CACHE_WARMING_ENABLED', False):
            from .warming import start_cache_warming
            start_cache_warming()