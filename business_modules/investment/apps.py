"""
Investment Module App Configuration
"""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class InvestmentConfig(AppConfig):
    """Investment module configuration."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business_modules.investment'
    verbose_name = 'Investment Management'
    
    def ready(self):
        """Initialize module when Django starts."""
        # Import signal handlers
        from . import signals  # noqa
        
        # Register module with platform
        self._register_module()
        
        # Set up event subscriptions
        self._setup_events()
        
        # Initialize cache warming
        self._setup_cache_warming()
        
        # Register workflows
        self._register_workflows()
        
        # Connect post-migrate signal
        post_migrate.connect(self._post_migrate, sender=self)
    
    def _register_module(self):
        """Register module with platform module system."""
        try:
            from platform_core.modules import module_registry
            from pathlib import Path
            import yaml
            
            # Load manifest
            manifest_path = Path(__file__).parent / 'manifest.yaml'
            with open(manifest_path, 'r') as f:
                manifest_data = yaml.safe_load(f)
            
            # Register module
            module_registry.register_module(
                name='investment',
                manifest=manifest_data,
                module_class=self
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not register investment module: {e}")
    
    def _setup_events(self):
        """Set up event subscriptions."""
        try:
            from platform_core.events import event_manager
            from .handlers import event_handlers
            
            # Subscribe to platform events
            event_manager.subscribe('user.login', event_handlers.track_user_activity)
            event_manager.subscribe('workflow.completed', event_handlers.update_deal_status)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not set up event subscriptions: {e}")
    
    def _setup_cache_warming(self):
        """Set up cache warming for critical data."""
        try:
            from platform_core.cache import cache_warmer
            from .warming import investment_warmer
            
            # Register investment-specific warmer
            cache_warmer.register_warmer('investment_data', investment_warmer)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not set up cache warming: {e}")
    
    def _register_workflows(self):
        """Register module workflows with platform."""
        try:
            from platform_core.workflows import workflow_registry
            from .workflows import (
                LeadQualificationWorkflow,
                DealApprovalWorkflow,
                AssessmentReviewWorkflow
            )
            
            # Register workflows
            workflow_registry.register('lead_qualification', LeadQualificationWorkflow)
            workflow_registry.register('deal_approval', DealApprovalWorkflow)
            workflow_registry.register('assessment_review', AssessmentReviewWorkflow)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not register workflows: {e}")
    
    def _post_migrate(self, sender, **kwargs):
        """Run after migrations."""
        # Create default data
        from django.core.management import call_command
        
        try:
            # Create default scoring models
            call_command('create_default_scoring_models', verbosity=0)
            
            # Set up default workflows
            call_command('setup_investment_workflows', verbosity=0)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Post-migration setup: {e}")