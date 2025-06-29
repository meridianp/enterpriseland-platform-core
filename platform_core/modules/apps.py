from django.apps import AppConfig


class ModulesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.modules'
    verbose_name = 'Platform Modules'
    
    def ready(self):
        # Import signal handlers
        from . import signals