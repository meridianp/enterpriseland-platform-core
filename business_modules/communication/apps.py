"""Communication module Django app configuration."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CommunicationConfig(AppConfig):
    """Configuration for the Communication module."""
    
    default_auto_field = "django.db.models.BigAutoField"
    name = "communication"
    verbose_name = "Communication Hub"
    
    def ready(self):
        """Initialize the app when Django starts."""
        # Import signal handlers
        from . import signals  # noqa
        
        # Import WebSocket consumers
        try:
            from . import consumers  # noqa
        except ImportError:
            pass  # WebSocket support is optional
        
        # Register module with platform
        try:
            from platform_core.module_registry import ModuleRegistry
            ModuleRegistry.register(self)
        except ImportError:
            pass
        
        # Connect post-migrate signal
        post_migrate.connect(self.post_migrate_handler, sender=self)
    
    def post_migrate_handler(self, sender, **kwargs):
        """Handle post-migration tasks."""
        # Create default notification templates
        from .models import NotificationTemplate
        from .utils import create_default_templates
        
        if not NotificationTemplate.objects.exists():
            create_default_templates()