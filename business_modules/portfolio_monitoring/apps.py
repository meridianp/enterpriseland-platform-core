"""
Portfolio Monitoring Module Configuration
"""
from django.apps import AppConfig
from django.db.models.signals import post_migrate
from platform_core.modules import ModuleConfig, register_module


class PortfolioMonitoringConfig(ModuleConfig):
    """Configuration for the Portfolio Monitoring module."""
    
    name = 'platform_core.business_modules.portfolio_monitoring'
    label = 'portfolio_monitoring'
    verbose_name = 'Portfolio Monitoring & Analytics'
    
    # Module metadata
    module_id = 'portfolio_monitoring'
    version = '1.0.0'
    description = 'Comprehensive portfolio analytics and performance tracking'
    author = 'EnterpriseLand Team'
    
    # Module capabilities
    provides = [
        'portfolio.performance_tracking',
        'portfolio.return_calculations',
        'portfolio.risk_analysis',
        'portfolio.benchmark_comparison',
        'portfolio.regulatory_reporting',
        'portfolio.real_time_alerts',
        'portfolio.custom_kpi_builder'
    ]
    
    # Required dependencies
    requires = [
        'platform_core.security',
        'platform_core.workflow',
        'business_modules.investment',
        'business_modules.reporting'
    ]
    
    # API endpoints provided
    api_endpoints = [
        'portfolios',
        'portfolio-performance',
        'portfolio-holdings',
        'portfolio-analytics',
        'portfolio-reports',
        'portfolio-alerts'
    ]
    
    def ready(self):
        """Initialize the module when Django starts."""
        super().ready()
        
        # Register the module
        register_module(self)
        
        # Import and register models
        from . import models
        
        # Import and register API
        from . import api
        
        # Import and register services
        from . import services
        
        # Import and register workflows
        from . import workflows
        
        # Connect signals
        self._connect_signals()
        
        # Register performance calculators
        self._register_calculators()
        
        # Register report templates
        self._register_report_templates()
    
    def _connect_signals(self):
        """Connect module signals."""
        from django.db.models.signals import post_save, post_delete
        from platform_core.business_modules.investment.models import Deal, Assessment
        from .services import PortfolioUpdateService
        
        # Update portfolio when deals change
        post_save.connect(
            PortfolioUpdateService.handle_deal_update,
            sender=Deal,
            dispatch_uid='portfolio_monitoring_deal_update'
        )
        
        # Update portfolio when assessments change
        post_save.connect(
            PortfolioUpdateService.handle_assessment_update,
            sender=Assessment,
            dispatch_uid='portfolio_monitoring_assessment_update'
        )
    
    def _register_calculators(self):
        """Register performance calculation methods."""
        from .services.calculations import (
            TimeWeightedReturnCalculator,
            MoneyWeightedReturnCalculator,
            ModifiedDietzCalculator,
            IRRCalculator,
            MOICCalculator,
            DPICalculator,
            TVPICalculator
        )
        from .services import CalculationRegistry
        
        registry = CalculationRegistry()
        registry.register('time_weighted', TimeWeightedReturnCalculator)
        registry.register('money_weighted', MoneyWeightedReturnCalculator)
        registry.register('modified_dietz', ModifiedDietzCalculator)
        registry.register('irr', IRRCalculator)
        registry.register('moic', MOICCalculator)
        registry.register('dpi', DPICalculator)
        registry.register('tvpi', TVPICalculator)
    
    def _register_report_templates(self):
        """Register ILPA/GIPS compliant report templates."""
        from .services.reporting import ReportTemplateRegistry
        from .services.reporting.templates import (
            ILPAQuarterlyReport,
            GIPSComplianceReport,
            LimitedPartnerReport,
            ManagementReport,
            RegulatoryFilingReport
        )
        
        registry = ReportTemplateRegistry()
        registry.register('ilpa_quarterly', ILPAQuarterlyReport)
        registry.register('gips_compliance', GIPSComplianceReport)
        registry.register('limited_partner', LimitedPartnerReport)
        registry.register('management', ManagementReport)
        registry.register('regulatory_filing', RegulatoryFilingReport)
    
    def get_module_info(self):
        """Return module information for the module registry."""
        return {
            'id': self.module_id,
            'name': self.verbose_name,
            'version': self.version,
            'description': self.description,
            'status': 'active',
            'provides': self.provides,
            'requires': self.requires,
            'api_endpoints': self.api_endpoints,
            'configuration': self.get_configuration_schema()
        }
    
    def get_configuration_schema(self):
        """Return the configuration schema for this module."""
        return {
            'performance_calculation_method': {
                'type': 'choice',
                'choices': ['time_weighted', 'money_weighted', 'modified_dietz'],
                'default': 'time_weighted',
                'description': 'Default method for calculating portfolio returns'
            },
            'reporting_currency': {
                'type': 'string',
                'default': 'USD',
                'description': 'Default currency for portfolio reporting'
            },
            'benchmark_indices': {
                'type': 'list',
                'default': ['SP500', 'MSCI_WORLD', 'FTSE_100'],
                'description': 'Benchmark indices for performance comparison'
            },
            'alert_thresholds': {
                'type': 'dict',
                'default': {
                    'irr_decline': 5.0,
                    'concentration_risk': 25.0,
                    'liquidity_warning': 10.0
                },
                'description': 'Thresholds for automated alerts'
            },
            'reporting_periods': {
                'type': 'list',
                'default': ['quarterly', 'annual'],
                'description': 'Standard reporting periods'
            }
        }