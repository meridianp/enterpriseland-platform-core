from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ReportingConfig(AppConfig):
    """Configuration for the Reporting and Business Intelligence module."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business_modules.reporting'
    verbose_name = 'Reporting & Business Intelligence'
    
    def ready(self):
        """Initialize the reporting module."""
        # Import signal handlers
        from . import signals
        
        # Import and register visualization types
        from .visualizations import registry
        registry.autodiscover()
        
        # Import and register data source connectors
        from .data_sources import connectors
        connectors.autodiscover()
        
        # Import and register export formats
        from .exports import formats
        formats.autodiscover()
        
        # Connect post-migrate signal to create default templates
        post_migrate.connect(self.create_default_templates, sender=self)
    
    def create_default_templates(self, sender, **kwargs):
        """Create default report templates after migration."""
        from .models import ReportTemplate
        
        default_templates = [
            {
                'name': 'Executive Summary',
                'description': 'High-level overview for executives',
                'category': 'executive',
                'template_config': {
                    'sections': ['kpi_summary', 'trend_analysis', 'key_insights'],
                    'theme': 'professional'
                }
            },
            {
                'name': 'Financial Analysis',
                'description': 'Detailed financial metrics and analysis',
                'category': 'financial',
                'template_config': {
                    'sections': ['revenue', 'expenses', 'profitability', 'cash_flow'],
                    'theme': 'financial'
                }
            },
            {
                'name': 'Operational Dashboard',
                'description': 'Real-time operational metrics',
                'category': 'operational',
                'template_config': {
                    'sections': ['performance_metrics', 'resource_utilization', 'alerts'],
                    'theme': 'modern'
                }
            },
            {
                'name': 'Investment Performance',
                'description': 'Investment portfolio analysis',
                'category': 'investment',
                'template_config': {
                    'sections': ['portfolio_overview', 'returns', 'risk_metrics', 'allocation'],
                    'theme': 'investment'
                }
            },
            {
                'name': 'Market Intelligence',
                'description': 'Market trends and competitor analysis',
                'category': 'market',
                'template_config': {
                    'sections': ['market_trends', 'competitor_analysis', 'opportunities'],
                    'theme': 'analytical'
                }
            }
        ]
        
        for template_data in default_templates:
            ReportTemplate.objects.get_or_create(
                name=template_data['name'],
                defaults=template_data
            )