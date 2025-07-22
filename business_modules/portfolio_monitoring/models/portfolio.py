"""
Portfolio Core Models

Defines the main portfolio structure and holdings.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from django.core.validators import MinValueValidator, MaxValueValidator
from platform_core.models import BaseModel, GroupFilteredModel
from platform_core.security.fields import EncryptedJSONField


class Portfolio(GroupFilteredModel):
    """
    Represents an investment portfolio with holdings across multiple investments.
    """
    
    PORTFOLIO_TYPE_CHOICES = [
        ('FUND', 'Investment Fund'),
        ('MANAGED_ACCOUNT', 'Managed Account'),
        ('CO_INVESTMENT', 'Co-Investment Vehicle'),
        ('SPV', 'Special Purpose Vehicle'),
        ('HYBRID', 'Hybrid Structure')
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('CLOSED', 'Closed to New Investments'),
        ('LIQUIDATING', 'In Liquidation'),
        ('TERMINATED', 'Terminated')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, db_index=True)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    portfolio_type = models.CharField(max_length=20, choices=PORTFOLIO_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Fund Details
    inception_date = models.DateField()
    termination_date = models.DateField(null=True, blank=True)
    base_currency = models.CharField(max_length=3, default='USD')
    target_size = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    committed_capital = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    called_capital = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    distributed_capital = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    
    # Investment Strategy
    investment_strategy = models.TextField()
    target_sectors = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    target_geographies = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    target_return = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Management
    fund_manager = models.ForeignKey(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='managed_portfolios'
    )
    management_company = models.CharField(max_length=255)
    management_fee_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('2.00'),
        validators=[MinValueValidator(0), MaxValueValidator(10)]
    )
    carried_interest_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('20.00'),
        validators=[MinValueValidator(0), MaxValueValidator(50)]
    )
    
    # Compliance
    regulatory_registrations = JSONField(default=dict, blank=True)
    compliance_restrictions = JSONField(default=dict, blank=True)
    
    # Metadata
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    custom_fields = EncryptedJSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'portfolio_portfolios'
        verbose_name = 'Portfolio'
        verbose_name_plural = 'Portfolios'
        ordering = ['-inception_date', 'name']
        indexes = [
            models.Index(fields=['status', 'portfolio_type']),
            models.Index(fields=['fund_manager', 'status']),
            models.Index(fields=['inception_date']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.code})"
    
    @property
    def uncalled_capital(self):
        """Calculate uncalled capital."""
        return self.committed_capital - self.called_capital
    
    @property
    def net_asset_value(self):
        """Calculate current NAV from latest valuation."""
        latest_valuation = self.valuations.order_by('-valuation_date').first()
        return latest_valuation.total_value if latest_valuation else Decimal('0')
    
    @property
    def total_value_to_paid_in(self):
        """Calculate TVPI (Total Value to Paid In) ratio."""
        if self.called_capital > 0:
            return (self.net_asset_value + self.distributed_capital) / self.called_capital
        return Decimal('0')
    
    @property
    def distributions_to_paid_in(self):
        """Calculate DPI (Distributions to Paid In) ratio."""
        if self.called_capital > 0:
            return self.distributed_capital / self.called_capital
        return Decimal('0')
    
    @property
    def residual_value_to_paid_in(self):
        """Calculate RVPI (Residual Value to Paid In) ratio."""
        if self.called_capital > 0:
            return self.net_asset_value / self.called_capital
        return Decimal('0')


class PortfolioHolding(GroupFilteredModel):
    """
    Represents a holding/investment within a portfolio.
    """
    
    HOLDING_TYPE_CHOICES = [
        ('DIRECT', 'Direct Investment'),
        ('FUND', 'Fund Investment'),
        ('CO_INVEST', 'Co-Investment'),
        ('SECONDARY', 'Secondary Purchase')
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('EXITED', 'Exited'),
        ('WRITTEN_OFF', 'Written Off'),
        ('PARTIALLY_EXITED', 'Partially Exited')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='holdings'
    )
    investment = models.ForeignKey(
        'investment.Deal',
        on_delete=models.PROTECT,
        related_name='portfolio_holdings'
    )
    holding_type = models.CharField(max_length=20, choices=HOLDING_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Investment Details
    initial_investment_date = models.DateField()
    exit_date = models.DateField(null=True, blank=True)
    holding_period_months = models.IntegerField(null=True, blank=True)
    
    # Financial Details
    committed_amount = models.DecimalField(max_digits=15, decimal_places=2)
    invested_amount = models.DecimalField(max_digits=15, decimal_places=2)
    current_value = models.DecimalField(max_digits=15, decimal_places=2)
    realized_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    total_distributions = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    
    # Ownership
    ownership_percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    diluted_ownership_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Performance
    gross_multiple = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    gross_irr = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    net_multiple = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    net_irr = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    custom_fields = EncryptedJSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'portfolio_holdings'
        verbose_name = 'Portfolio Holding'
        verbose_name_plural = 'Portfolio Holdings'
        ordering = ['-initial_investment_date']
        unique_together = [['portfolio', 'investment']]
        indexes = [
            models.Index(fields=['portfolio', 'status']),
            models.Index(fields=['investment', 'status']),
            models.Index(fields=['initial_investment_date']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.investment.name}"
    
    @property
    def unrealized_value(self):
        """Calculate unrealized value."""
        return self.current_value - self.realized_value
    
    @property
    def total_value(self):
        """Calculate total value (realized + unrealized)."""
        return self.realized_value + self.current_value
    
    @property
    def multiple_on_invested_capital(self):
        """Calculate MOIC."""
        if self.invested_amount > 0:
            return self.total_value / self.invested_amount
        return Decimal('0')


class PortfolioValuation(BaseModel):
    """
    Tracks portfolio valuations over time.
    """
    
    VALUATION_TYPE_CHOICES = [
        ('QUARTERLY', 'Quarterly Valuation'),
        ('ANNUAL', 'Annual Valuation'),
        ('INTERIM', 'Interim Valuation'),
        ('EXIT', 'Exit Valuation')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='valuations'
    )
    valuation_date = models.DateField(db_index=True)
    valuation_type = models.CharField(max_length=20, choices=VALUATION_TYPE_CHOICES)
    
    # Valuation Details
    gross_asset_value = models.DecimalField(max_digits=15, decimal_places=2)
    liabilities = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    net_asset_value = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Component Values
    cash_and_equivalents = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    public_securities = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    private_holdings = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    other_assets = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    
    # Per Unit Values
    nav_per_unit = models.DecimalField(max_digits=15, decimal_places=6, null=True, blank=True)
    units_outstanding = models.DecimalField(max_digits=15, decimal_places=6, null=True, blank=True)
    
    # Valuation Metadata
    valuation_method = models.TextField()
    assumptions = JSONField(default=dict, blank=True)
    adjustments = JSONField(default=dict, blank=True)
    
    # Audit Trail
    prepared_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='prepared_valuations'
    )
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='reviewed_valuations',
        null=True, blank=True
    )
    approved_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='approved_valuations',
        null=True, blank=True
    )
    approved_date = models.DateTimeField(null=True, blank=True)
    
    # Documentation
    supporting_documents = JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'portfolio_valuations'
        verbose_name = 'Portfolio Valuation'
        verbose_name_plural = 'Portfolio Valuations'
        ordering = ['-valuation_date']
        unique_together = [['portfolio', 'valuation_date', 'valuation_type']]
        indexes = [
            models.Index(fields=['portfolio', 'valuation_date']),
            models.Index(fields=['valuation_type', 'valuation_date']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.valuation_date}"
    
    @property
    def total_value(self):
        """Calculate total portfolio value."""
        return self.net_asset_value
    
    def calculate_change_from_previous(self):
        """Calculate change from previous valuation."""
        previous = PortfolioValuation.objects.filter(
            portfolio=self.portfolio,
            valuation_date__lt=self.valuation_date
        ).order_by('-valuation_date').first()
        
        if previous:
            return {
                'amount_change': self.net_asset_value - previous.net_asset_value,
                'percentage_change': ((self.net_asset_value - previous.net_asset_value) / previous.net_asset_value * 100)
                if previous.net_asset_value > 0 else Decimal('0')
            }
        return None