"""
Portfolio Performance Models

Models for tracking and calculating portfolio performance metrics.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from django.core.validators import MinValueValidator, MaxValueValidator
from platform_core.models import BaseModel


class PortfolioPerformance(BaseModel):
    """
    Stores calculated performance metrics for a portfolio over a specific period.
    """
    
    PERIOD_TYPE_CHOICES = [
        ('MTD', 'Month to Date'),
        ('QTD', 'Quarter to Date'),
        ('YTD', 'Year to Date'),
        ('1Y', 'One Year'),
        ('3Y', 'Three Years'),
        ('5Y', 'Five Years'),
        ('10Y', 'Ten Years'),
        ('ITD', 'Inception to Date'),
        ('CUSTOM', 'Custom Period')
    ]
    
    CALCULATION_METHOD_CHOICES = [
        ('TIME_WEIGHTED', 'Time-Weighted Return'),
        ('MONEY_WEIGHTED', 'Money-Weighted Return'),
        ('MODIFIED_DIETZ', 'Modified Dietz'),
        ('SIMPLE', 'Simple Return')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='performance_records'
    )
    
    # Period Information
    period_type = models.CharField(max_length=10, choices=PERIOD_TYPE_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()
    calculation_date = models.DateTimeField(auto_now_add=True)
    
    # Return Metrics
    gross_return = models.DecimalField(
        max_digits=10, decimal_places=4,
        help_text="Gross return percentage"
    )
    net_return = models.DecimalField(
        max_digits=10, decimal_places=4,
        help_text="Net return percentage after fees"
    )
    
    # IRR Metrics
    gross_irr = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Gross Internal Rate of Return"
    )
    net_irr = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Net Internal Rate of Return"
    )
    
    # Multiple Metrics
    gross_multiple = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        help_text="Gross Multiple on Invested Capital (MOIC)"
    )
    net_multiple = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        help_text="Net Multiple on Invested Capital"
    )
    
    # Cash Flow Metrics
    total_contributions = models.DecimalField(max_digits=15, decimal_places=2)
    total_distributions = models.DecimalField(max_digits=15, decimal_places=2)
    net_cash_flow = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Value Metrics
    beginning_value = models.DecimalField(max_digits=15, decimal_places=2)
    ending_value = models.DecimalField(max_digits=15, decimal_places=2)
    average_capital = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Risk Metrics
    volatility = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Annualized standard deviation"
    )
    sharpe_ratio = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        help_text="Risk-adjusted return metric"
    )
    max_drawdown = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Maximum peak-to-trough decline"
    )
    
    # Calculation Details
    calculation_method = models.CharField(
        max_length=20, choices=CALCULATION_METHOD_CHOICES,
        default='TIME_WEIGHTED'
    )
    calculation_parameters = JSONField(default=dict, blank=True)
    
    # Metadata
    is_official = models.BooleanField(
        default=False,
        help_text="Whether this is the official performance record for reporting"
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'portfolio_performance'
        verbose_name = 'Portfolio Performance'
        verbose_name_plural = 'Portfolio Performance Records'
        ordering = ['-period_end', '-calculation_date']
        indexes = [
            models.Index(fields=['portfolio', 'period_type', 'period_end']),
            models.Index(fields=['portfolio', 'is_official']),
            models.Index(fields=['calculation_date']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.period_type} ({self.period_end})"


class PerformanceMetric(BaseModel):
    """
    Stores individual performance metrics and custom KPIs.
    """
    
    METRIC_TYPE_CHOICES = [
        ('RETURN', 'Return Metric'),
        ('RISK', 'Risk Metric'),
        ('EFFICIENCY', 'Efficiency Metric'),
        ('CUSTOM', 'Custom Metric')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='custom_metrics'
    )
    
    # Metric Definition
    metric_name = models.CharField(max_length=100)
    metric_type = models.CharField(max_length=20, choices=METRIC_TYPE_CHOICES)
    metric_code = models.CharField(max_length=50, db_index=True)
    description = models.TextField()
    
    # Metric Value
    value = models.DecimalField(max_digits=15, decimal_places=6)
    unit = models.CharField(max_length=20, default='percentage')
    calculation_date = models.DateTimeField()
    
    # Calculation Details
    formula = models.TextField(help_text="Formula or calculation method")
    inputs = JSONField(default=dict, help_text="Input values used in calculation")
    
    # Thresholds
    target_value = models.DecimalField(
        max_digits=15, decimal_places=6, null=True, blank=True
    )
    min_threshold = models.DecimalField(
        max_digits=15, decimal_places=6, null=True, blank=True
    )
    max_threshold = models.DecimalField(
        max_digits=15, decimal_places=6, null=True, blank=True
    )
    
    # Metadata
    is_kpi = models.BooleanField(default=False, help_text="Is this a Key Performance Indicator?")
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    
    class Meta:
        db_table = 'portfolio_performance_metrics'
        verbose_name = 'Performance Metric'
        verbose_name_plural = 'Performance Metrics'
        ordering = ['-calculation_date', 'metric_name']
        indexes = [
            models.Index(fields=['portfolio', 'metric_code']),
            models.Index(fields=['portfolio', 'is_kpi']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.metric_name}"


class ReturnCalculation(BaseModel):
    """
    Detailed return calculation records for audit trail.
    """
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='return_calculations'
    )
    performance_record = models.ForeignKey(
        PortfolioPerformance,
        on_delete=models.CASCADE,
        related_name='calculations',
        null=True, blank=True
    )
    
    # Calculation Details
    calculation_type = models.CharField(max_length=50)
    calculation_date = models.DateTimeField(auto_now_add=True)
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Cash Flows
    cash_flows = JSONField(
        default=list,
        help_text="List of cash flows with dates and amounts"
    )
    
    # Values
    beginning_value = models.DecimalField(max_digits=15, decimal_places=2)
    ending_value = models.DecimalField(max_digits=15, decimal_places=2)
    weighted_cash_flows = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Results
    calculated_return = models.DecimalField(max_digits=10, decimal_places=6)
    annualized_return = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    
    # Calculation Steps
    calculation_steps = JSONField(
        default=dict,
        help_text="Detailed calculation steps for audit"
    )
    
    # Validation
    is_validated = models.BooleanField(default=False)
    validation_notes = models.TextField(blank=True)
    validated_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='validated_calculations',
        null=True, blank=True
    )
    
    class Meta:
        db_table = 'portfolio_return_calculations'
        verbose_name = 'Return Calculation'
        verbose_name_plural = 'Return Calculations'
        ordering = ['-calculation_date']
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.calculation_type} ({self.calculation_date})"


class BenchmarkComparison(BaseModel):
    """
    Compares portfolio performance against benchmark indices.
    """
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='benchmark_comparisons'
    )
    performance_record = models.ForeignKey(
        PortfolioPerformance,
        on_delete=models.CASCADE,
        related_name='benchmark_comparisons'
    )
    
    # Benchmark Information
    benchmark_name = models.CharField(max_length=100)
    benchmark_code = models.CharField(max_length=50)
    benchmark_type = models.CharField(max_length=50)
    
    # Performance Comparison
    portfolio_return = models.DecimalField(max_digits=10, decimal_places=4)
    benchmark_return = models.DecimalField(max_digits=10, decimal_places=4)
    excess_return = models.DecimalField(
        max_digits=10, decimal_places=4,
        help_text="Portfolio return minus benchmark return"
    )
    
    # Risk Comparison
    portfolio_volatility = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    benchmark_volatility = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    
    # Risk-Adjusted Metrics
    information_ratio = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        help_text="Excess return divided by tracking error"
    )
    tracking_error = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Standard deviation of excess returns"
    )
    beta = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        help_text="Portfolio sensitivity to benchmark"
    )
    correlation = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(-1), MaxValueValidator(1)]
    )
    
    # Period Information
    comparison_start = models.DateField()
    comparison_end = models.DateField()
    
    class Meta:
        db_table = 'portfolio_benchmark_comparisons'
        verbose_name = 'Benchmark Comparison'
        verbose_name_plural = 'Benchmark Comparisons'
        ordering = ['-comparison_end', 'benchmark_name']
        unique_together = [
            ['portfolio', 'performance_record', 'benchmark_code']
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} vs {self.benchmark_name}"