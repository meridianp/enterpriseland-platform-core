"""
Cash Flow Models

Models for tracking portfolio cash flows, distributions, and capital calls.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.contrib.postgres.fields import JSONField
from platform_core.models import BaseModel


class CashFlow(BaseModel):
    """
    Generic cash flow record for portfolios and holdings.
    """
    
    FLOW_TYPE_CHOICES = [
        ('CAPITAL_CALL', 'Capital Call'),
        ('DISTRIBUTION', 'Distribution'),
        ('MANAGEMENT_FEE', 'Management Fee'),
        ('CARRIED_INTEREST', 'Carried Interest'),
        ('EXPENSE', 'Expense'),
        ('INCOME', 'Income'),
        ('REBALANCING', 'Rebalancing'),
        ('OTHER', 'Other')
    ]
    
    FLOW_DIRECTION_CHOICES = [
        ('INFLOW', 'Inflow'),
        ('OUTFLOW', 'Outflow')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='cash_flows'
    )
    holding = models.ForeignKey(
        'portfolio_monitoring.PortfolioHolding',
        on_delete=models.CASCADE,
        related_name='cash_flows',
        null=True, blank=True
    )
    
    # Flow Details
    flow_type = models.CharField(max_length=20, choices=FLOW_TYPE_CHOICES)
    flow_direction = models.CharField(max_length=10, choices=FLOW_DIRECTION_CHOICES)
    flow_date = models.DateField(db_index=True)
    settlement_date = models.DateField(null=True, blank=True)
    
    # Amounts
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    fx_rate = models.DecimalField(
        max_digits=10, decimal_places=6, default=Decimal('1.000000'),
        help_text="Exchange rate to portfolio base currency"
    )
    base_currency_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        help_text="Amount in portfolio base currency"
    )
    
    # Reference Information
    reference_number = models.CharField(max_length=100, blank=True)
    description = models.TextField()
    
    # Metadata
    is_estimated = models.BooleanField(
        default=False,
        help_text="Whether this is an estimated/projected cash flow"
    )
    is_reconciled = models.BooleanField(default=False)
    reconciliation_date = models.DateTimeField(null=True, blank=True)
    metadata = JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'portfolio_cash_flows'
        verbose_name = 'Cash Flow'
        verbose_name_plural = 'Cash Flows'
        ordering = ['-flow_date', '-created_at']
        indexes = [
            models.Index(fields=['portfolio', 'flow_date']),
            models.Index(fields=['portfolio', 'flow_type']),
            models.Index(fields=['holding', 'flow_date']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.flow_type} - {self.amount}"
    
    def save(self, *args, **kwargs):
        """Calculate base currency amount before saving."""
        self.base_currency_amount = self.amount * self.fx_rate
        super().save(*args, **kwargs)


class CapitalCall(BaseModel):
    """
    Capital call notices and tracking.
    """
    
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ISSUED', 'Issued'),
        ('PARTIALLY_FUNDED', 'Partially Funded'),
        ('FULLY_FUNDED', 'Fully Funded'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='capital_calls'
    )
    call_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Call Details
    call_date = models.DateField()
    due_date = models.DateField()
    notice_date = models.DateField()
    
    # Amounts
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    amount_funded = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0')
    )
    
    # Purpose
    purpose = models.TextField()
    breakdown = JSONField(
        default=dict,
        help_text="Breakdown of capital call by purpose/investment"
    )
    
    # Documentation
    notice_document = models.FileField(
        upload_to='capital_calls/notices/', null=True, blank=True
    )
    supporting_documents = JSONField(default=list, blank=True)
    
    # Compliance
    is_compliant = models.BooleanField(default=True)
    compliance_notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'portfolio_capital_calls'
        verbose_name = 'Capital Call'
        verbose_name_plural = 'Capital Calls'
        ordering = ['-call_date']
        indexes = [
            models.Index(fields=['portfolio', 'status']),
            models.Index(fields=['due_date']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - Call #{self.call_number}"
    
    @property
    def amount_outstanding(self):
        """Calculate outstanding amount."""
        return self.total_amount - self.amount_funded
    
    @property
    def funding_percentage(self):
        """Calculate funding percentage."""
        if self.total_amount > 0:
            return (self.amount_funded / self.total_amount) * 100
        return Decimal('0')


class Distribution(BaseModel):
    """
    Distribution notices and tracking.
    """
    
    DISTRIBUTION_TYPE_CHOICES = [
        ('INCOME', 'Income Distribution'),
        ('CAPITAL_GAIN', 'Capital Gain Distribution'),
        ('RETURN_OF_CAPITAL', 'Return of Capital'),
        ('CARRIED_INTEREST', 'Carried Interest Distribution'),
        ('LIQUIDATION', 'Liquidation Distribution'),
        ('OTHER', 'Other Distribution')
    ]
    
    STATUS_CHOICES = [
        ('ANNOUNCED', 'Announced'),
        ('DECLARED', 'Declared'),
        ('PAID', 'Paid'),
        ('CANCELLED', 'Cancelled')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='distributions'
    )
    holding = models.ForeignKey(
        'portfolio_monitoring.PortfolioHolding',
        on_delete=models.CASCADE,
        related_name='distributions',
        null=True, blank=True
    )
    
    # Distribution Details
    distribution_number = models.CharField(max_length=50, unique=True)
    distribution_type = models.CharField(
        max_length=20, choices=DISTRIBUTION_TYPE_CHOICES
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ANNOUNCED')
    
    # Dates
    announcement_date = models.DateField()
    record_date = models.DateField()
    payment_date = models.DateField()
    
    # Amounts
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    amount_per_unit = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    tax_withheld = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0')
    )
    net_amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Source Information
    source_investment = models.CharField(max_length=255, blank=True)
    transaction_description = models.TextField()
    
    # Tax Information
    tax_classification = JSONField(
        default=dict,
        help_text="Tax classification breakdown"
    )
    
    # Documentation
    distribution_notice = models.FileField(
        upload_to='distributions/notices/', null=True, blank=True
    )
    
    class Meta:
        db_table = 'portfolio_distributions'
        verbose_name = 'Distribution'
        verbose_name_plural = 'Distributions'
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['portfolio', 'status']),
            models.Index(fields=['payment_date']),
            models.Index(fields=['holding', 'payment_date']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - Distribution #{self.distribution_number}"
    
    def save(self, *args, **kwargs):
        """Calculate net amount before saving."""
        self.net_amount = self.total_amount - self.tax_withheld
        super().save(*args, **kwargs)