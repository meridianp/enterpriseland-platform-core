"""
Analytics Models

Models for portfolio analytics, risk metrics, and exposure analysis.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from django.core.validators import MinValueValidator, MaxValueValidator
from platform_core.models import BaseModel


class RiskMetric(BaseModel):
    """
    Portfolio risk metrics and measurements.
    """
    
    METRIC_TYPE_CHOICES = [
        ('VOLATILITY', 'Volatility'),
        ('VAR', 'Value at Risk'),
        ('CVAR', 'Conditional Value at Risk'),
        ('BETA', 'Beta'),
        ('SHARPE', 'Sharpe Ratio'),
        ('SORTINO', 'Sortino Ratio'),
        ('CALMAR', 'Calmar Ratio'),
        ('MAX_DRAWDOWN', 'Maximum Drawdown'),
        ('DOWNSIDE_DEVIATION', 'Downside Deviation'),
        ('TRACKING_ERROR', 'Tracking Error'),
        ('INFORMATION_RATIO', 'Information Ratio'),
        ('TREYNOR', 'Treynor Ratio')
    ]
    
    CALCULATION_PERIOD_CHOICES = [
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('ANNUAL', 'Annual')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='risk_metrics'
    )
    
    # Metric Details
    metric_type = models.CharField(max_length=20, choices=METRIC_TYPE_CHOICES)
    calculation_date = models.DateField()
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Values
    metric_value = models.DecimalField(
        max_digits=15, decimal_places=6,
        help_text="The calculated metric value"
    )
    
    # Risk-Specific Values
    confidence_level = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Confidence level for VaR/CVaR calculations"
    )
    
    # Calculation Parameters
    calculation_period = models.CharField(
        max_length=10, choices=CALCULATION_PERIOD_CHOICES,
        default='MONTHLY'
    )
    lookback_days = models.IntegerField(default=365)
    risk_free_rate = models.DecimalField(
        max_digits=6, decimal_places=4,
        default=Decimal('0.02'),
        help_text="Risk-free rate used in calculations"
    )
    
    # Benchmark Comparison
    benchmark_name = models.CharField(max_length=100, blank=True)
    benchmark_value = models.DecimalField(
        max_digits=15, decimal_places=6,
        null=True, blank=True
    )
    
    # Calculation Details
    calculation_method = models.CharField(max_length=50)
    calculation_details = JSONField(
        default=dict,
        help_text="Detailed calculation parameters and intermediate values"
    )
    
    # Data Quality
    data_points_used = models.IntegerField()
    data_quality_score = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Quality score of underlying data"
    )
    
    class Meta:
        db_table = 'portfolio_risk_metrics'
        verbose_name = 'Risk Metric'
        verbose_name_plural = 'Risk Metrics'
        ordering = ['-calculation_date', 'metric_type']
        indexes = [
            models.Index(fields=['portfolio', 'metric_type', 'calculation_date']),
            models.Index(fields=['calculation_date']),
        ]
        unique_together = [
            ['portfolio', 'metric_type', 'calculation_date', 'calculation_period']
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.metric_type} ({self.calculation_date})"


class ConcentrationAnalysis(BaseModel):
    """
    Portfolio concentration and diversification analysis.
    """
    
    CONCENTRATION_TYPE_CHOICES = [
        ('HOLDING', 'Individual Holding'),
        ('SECTOR', 'Sector'),
        ('GEOGRAPHY', 'Geography'),
        ('ASSET_CLASS', 'Asset Class'),
        ('CURRENCY', 'Currency'),
        ('VINTAGE', 'Vintage Year'),
        ('STRATEGY', 'Investment Strategy'),
        ('MANAGER', 'Fund Manager')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='concentration_analyses'
    )
    
    # Analysis Details
    analysis_date = models.DateField()
    concentration_type = models.CharField(
        max_length=20, choices=CONCENTRATION_TYPE_CHOICES
    )
    
    # Concentration Metrics
    herfindahl_index = models.DecimalField(
        max_digits=6, decimal_places=4,
        help_text="Herfindahl-Hirschman Index (0-1)"
    )
    gini_coefficient = models.DecimalField(
        max_digits=6, decimal_places=4,
        help_text="Gini coefficient (0-1)"
    )
    
    # Top Concentrations
    top_5_concentration = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    top_10_concentration = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Detailed Breakdown
    concentration_breakdown = JSONField(
        default=list,
        help_text="List of concentrations by category"
    )
    
    # Risk Assessment
    concentration_risk_score = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Overall concentration risk score"
    )
    risk_factors = JSONField(
        default=dict,
        help_text="Identified concentration risk factors"
    )
    
    # Recommendations
    recommended_limits = JSONField(
        default=dict,
        help_text="Recommended concentration limits"
    )
    rebalancing_suggestions = JSONField(
        default=list,
        help_text="Suggested rebalancing actions"
    )
    
    class Meta:
        db_table = 'portfolio_concentration_analysis'
        verbose_name = 'Concentration Analysis'
        verbose_name_plural = 'Concentration Analyses'
        ordering = ['-analysis_date', 'concentration_type']
        indexes = [
            models.Index(fields=['portfolio', 'analysis_date']),
            models.Index(fields=['concentration_type', 'analysis_date']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.concentration_type} ({self.analysis_date})"


class SectorExposure(BaseModel):
    """
    Portfolio exposure by sector.
    """
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='sector_exposures'
    )
    
    # Exposure Details
    analysis_date = models.DateField()
    sector_name = models.CharField(max_length=100)
    sector_code = models.CharField(max_length=50, blank=True)
    
    # Values
    market_value = models.DecimalField(max_digits=15, decimal_places=2)
    percentage_of_portfolio = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Holdings
    holding_count = models.IntegerField()
    holdings = JSONField(
        default=list,
        help_text="List of holdings in this sector"
    )
    
    # Performance Attribution
    sector_return = models.DecimalField(
        max_digits=10, decimal_places=4,
        null=True, blank=True
    )
    contribution_to_return = models.DecimalField(
        max_digits=10, decimal_places=4,
        null=True, blank=True,
        help_text="Contribution to portfolio return"
    )
    
    # Risk Metrics
    sector_volatility = models.DecimalField(
        max_digits=10, decimal_places=4,
        null=True, blank=True
    )
    sector_beta = models.DecimalField(
        max_digits=6, decimal_places=3,
        null=True, blank=True
    )
    
    # Benchmark Comparison
    benchmark_weight = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    active_weight = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True,
        help_text="Portfolio weight minus benchmark weight"
    )
    
    class Meta:
        db_table = 'portfolio_sector_exposures'
        verbose_name = 'Sector Exposure'
        verbose_name_plural = 'Sector Exposures'
        ordering = ['-analysis_date', '-percentage_of_portfolio']
        indexes = [
            models.Index(fields=['portfolio', 'analysis_date']),
            models.Index(fields=['sector_name', 'analysis_date']),
        ]
        unique_together = [['portfolio', 'sector_name', 'analysis_date']]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.sector_name} ({self.percentage_of_portfolio}%)"


class GeographicExposure(BaseModel):
    """
    Portfolio exposure by geography.
    """
    
    REGION_CHOICES = [
        ('NORTH_AMERICA', 'North America'),
        ('EUROPE', 'Europe'),
        ('ASIA_PACIFIC', 'Asia Pacific'),
        ('LATIN_AMERICA', 'Latin America'),
        ('MIDDLE_EAST', 'Middle East'),
        ('AFRICA', 'Africa'),
        ('GLOBAL', 'Global')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='geographic_exposures'
    )
    
    # Exposure Details
    analysis_date = models.DateField()
    country_code = models.CharField(max_length=2)
    country_name = models.CharField(max_length=100)
    region = models.CharField(max_length=20, choices=REGION_CHOICES)
    
    # Values
    market_value = models.DecimalField(max_digits=15, decimal_places=2)
    percentage_of_portfolio = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Currency Exposure
    local_currency = models.CharField(max_length=3)
    currency_exposure = models.DecimalField(
        max_digits=15, decimal_places=2,
        help_text="Exposure in local currency"
    )
    fx_hedged_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal('0'),
        help_text="Amount hedged against FX risk"
    )
    
    # Holdings
    holding_count = models.IntegerField()
    holdings = JSONField(
        default=list,
        help_text="List of holdings in this geography"
    )
    
    # Risk Factors
    country_risk_score = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    political_risk = models.CharField(max_length=20, blank=True)
    regulatory_risk = models.CharField(max_length=20, blank=True)
    
    # Economic Indicators
    gdp_growth = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True
    )
    inflation_rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True
    )
    
    class Meta:
        db_table = 'portfolio_geographic_exposures'
        verbose_name = 'Geographic Exposure'
        verbose_name_plural = 'Geographic Exposures'
        ordering = ['-analysis_date', '-percentage_of_portfolio']
        indexes = [
            models.Index(fields=['portfolio', 'analysis_date']),
            models.Index(fields=['country_code', 'analysis_date']),
            models.Index(fields=['region', 'analysis_date']),
        ]
        unique_together = [['portfolio', 'country_code', 'analysis_date']]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.country_name} ({self.percentage_of_portfolio}%)"