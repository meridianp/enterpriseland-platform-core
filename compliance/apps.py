"""
Compliance App Configuration
"""
from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    """Configuration for the Compliance module."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.compliance'
    verbose_name = 'Compliance & AML/KYC'
    
    def ready(self):
        """Initialize the compliance module."""
        # Import signal handlers
        from . import signals
        
        # Register compliance providers
        from .providers import register_providers
        register_providers()