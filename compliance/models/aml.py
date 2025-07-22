"""
AML (Anti-Money Laundering) Models

Models for AML screening, monitoring, and reporting.
"""
import uuid
from decimal import Decimal
from datetime import datetime
from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from django.core.validators import MinValueValidator, MaxValueValidator
from platform_core.models import BaseModel, GroupFilteredModel
from platform_core.security.fields import EncryptedCharField, EncryptedJSONField


class AMLScreening(GroupFilteredModel):
    """
    AML screening results for individuals and entities.
    """
    
    SCREENING_TYPE_CHOICES = [
        ('INITIAL', 'Initial Screening'),
        ('PERIODIC', 'Periodic Review'),
        ('TRIGGERED', 'Event Triggered'),
        ('ENHANCED', 'Enhanced Due Diligence')
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending Screening'),
        ('IN_PROGRESS', 'In Progress'),
        ('CLEAR', 'Clear - No Matches'),
        ('POTENTIAL_MATCH', 'Potential Match Found'),
        ('CONFIRMED_MATCH', 'Confirmed Match'),
        ('FALSE_POSITIVE', 'False Positive'),
        ('ESCALATED', 'Escalated for Review')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=100, db_index=True)
    kyc_verification = models.ForeignKey(
        'KYCVerification',
        on_delete=models.CASCADE,
        related_name='aml_screenings',
        null=True, blank=True
    )
    
    # Screening Details
    screening_type = models.CharField(max_length=20, choices=SCREENING_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Provider Information
    provider = models.CharField(max_length=50)
    provider_reference = models.CharField(max_length=255, blank=True)
    screening_date = models.DateTimeField(auto_now_add=True)
    
    # Screening Parameters
    search_parameters = JSONField(default=dict)
    datasets_searched = ArrayField(
        models.CharField(max_length=50),
        default=list,
        help_text="Sanctions lists, PEP databases, etc."
    )
    
    # Results Summary
    total_matches = models.IntegerField(default=0)
    high_risk_matches = models.IntegerField(default=0)
    medium_risk_matches = models.IntegerField(default=0)
    low_risk_matches = models.IntegerField(default=0)
    
    # Risk Assessment
    overall_risk_score = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        null=True, blank=True
    )
    risk_factors = JSONField(default=list)
    
    # Review Status
    requires_manual_review = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='aml_reviews'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_decision = models.CharField(max_length=50, blank=True)
    review_notes = models.TextField(blank=True)
    
    # Metadata
    raw_response = EncryptedJSONField(default=dict, blank=True)
    next_review_date = models.DateField(null=True, blank=True)
    
    class Meta:
        db_table = 'compliance_aml_screenings'
        verbose_name = 'AML Screening'
        verbose_name_plural = 'AML Screenings'
        ordering = ['-screening_date']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['status', 'requires_manual_review']),
            models.Index(fields=['next_review_date']),
        ]
    
    def __str__(self):
        return f"AML Screening for {self.entity_type} {self.entity_id}"
    
    def calculate_risk_score(self):
        """Calculate overall risk score based on matches."""
        if self.total_matches == 0:
            return 0
        
        # Weighted scoring
        score = (
            self.high_risk_matches * 40 +
            self.medium_risk_matches * 20 +
            self.low_risk_matches * 5
        )
        
        # Normalize to 0-100
        return min(100, score)


class WatchlistMatch(BaseModel):
    """
    Individual watchlist match details.
    """
    
    MATCH_TYPE_CHOICES = [
        ('SANCTIONS', 'Sanctions List'),
        ('PEP', 'Politically Exposed Person'),
        ('ADVERSE_MEDIA', 'Adverse Media'),
        ('LAW_ENFORCEMENT', 'Law Enforcement List'),
        ('REGULATORY', 'Regulatory Action'),
        ('OTHER', 'Other Watchlist')
    ]
    
    MATCH_QUALITY_CHOICES = [
        ('EXACT', 'Exact Match'),
        ('STRONG', 'Strong Match'),
        ('POSSIBLE', 'Possible Match'),
        ('WEAK', 'Weak Match')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    screening = models.ForeignKey(
        AMLScreening,
        on_delete=models.CASCADE,
        related_name='matches'
    )
    
    # Match Details
    match_type = models.CharField(max_length=20, choices=MATCH_TYPE_CHOICES)
    match_quality = models.CharField(max_length=20, choices=MATCH_QUALITY_CHOICES)
    match_score = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Matched Entity Information
    matched_name = models.CharField(max_length=255)
    matched_aliases = ArrayField(models.CharField(max_length=255), default=list)
    matched_date_of_birth = models.DateField(null=True, blank=True)
    matched_countries = ArrayField(models.CharField(max_length=2), default=list)
    
    # List Information
    list_name = models.CharField(max_length=255)
    list_provider = models.CharField(max_length=100)
    listing_date = models.DateField(null=True, blank=True)
    
    # Risk Information
    risk_level = models.CharField(max_length=20)
    risk_categories = ArrayField(models.CharField(max_length=50), default=list)
    
    # Additional Details
    match_details = EncryptedJSONField(default=dict)
    source_url = models.URLField(max_length=500, blank=True)
    
    # Review Status
    is_false_positive = models.BooleanField(default=False)
    false_positive_reason = models.TextField(blank=True)
    confirmed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='confirmed_matches'
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'compliance_watchlist_matches'
        verbose_name = 'Watchlist Match'
        verbose_name_plural = 'Watchlist Matches'
        ordering = ['-match_score', 'match_type']
    
    def __str__(self):
        return f"{self.match_type} match: {self.matched_name}"


class RiskProfile(GroupFilteredModel):
    """
    Comprehensive risk profile for entities.
    """
    
    RISK_LEVEL_CHOICES = [
        ('LOW', 'Low Risk'),
        ('MEDIUM', 'Medium Risk'),
        ('HIGH', 'High Risk'),
        ('UNACCEPTABLE', 'Unacceptable Risk')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=100, db_index=True)
    
    # Risk Assessment
    risk_level = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES)
    risk_score = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Risk Factors
    geographic_risk = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    industry_risk = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    product_risk = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    channel_risk = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Specific Risk Indicators
    pep_exposure = models.BooleanField(default=False)
    sanctions_exposure = models.BooleanField(default=False)
    adverse_media = models.BooleanField(default=False)
    complex_structure = models.BooleanField(default=False)
    cash_intensive = models.BooleanField(default=False)
    high_risk_jurisdiction = models.BooleanField(default=False)
    
    # Risk Mitigation
    enhanced_due_diligence_required = models.BooleanField(default=False)
    transaction_monitoring_level = models.CharField(
        max_length=20,
        choices=[('STANDARD', 'Standard'), ('ENHANCED', 'Enhanced'), ('INTENSIVE', 'Intensive')],
        default='STANDARD'
    )
    review_frequency = models.CharField(
        max_length=20,
        choices=[('ANNUAL', 'Annual'), ('SEMI_ANNUAL', 'Semi-Annual'), ('QUARTERLY', 'Quarterly'), ('MONTHLY', 'Monthly')],
        default='ANNUAL'
    )
    
    # Additional Information
    risk_narrative = models.TextField(blank=True)
    mitigating_factors = JSONField(default=list)
    
    # Review Information
    last_review_date = models.DateTimeField(auto_now=True)
    next_review_date = models.DateField()
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='risk_profile_reviews'
    )
    
    class Meta:
        db_table = 'compliance_risk_profiles'
        verbose_name = 'Risk Profile'
        verbose_name_plural = 'Risk Profiles'
        ordering = ['-risk_score']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['risk_level', 'next_review_date']),
        ]
        unique_together = [['entity_type', 'entity_id']]
    
    def __str__(self):
        return f"Risk Profile for {self.entity_type} {self.entity_id} - {self.risk_level}"
    
    def calculate_composite_risk(self):
        """Calculate composite risk score."""
        # Base risk components
        risk_components = [
            self.geographic_risk * 0.25,
            self.industry_risk * 0.20,
            self.product_risk * 0.20,
            self.channel_risk * 0.15
        ]
        
        base_score = sum(risk_components)
        
        # Add penalty for specific indicators
        if self.pep_exposure:
            base_score += 10
        if self.sanctions_exposure:
            base_score += 15
        if self.adverse_media:
            base_score += 10
        if self.complex_structure:
            base_score += 5
        if self.cash_intensive:
            base_score += 5
        if self.high_risk_jurisdiction:
            base_score += 10
        
        return min(100, int(base_score))


class TransactionMonitoring(BaseModel):
    """
    Transaction monitoring rules and alerts.
    """
    
    ALERT_TYPE_CHOICES = [
        ('LARGE_TRANSACTION', 'Large Transaction'),
        ('RAPID_MOVEMENT', 'Rapid Movement of Funds'),
        ('UNUSUAL_PATTERN', 'Unusual Pattern'),
        ('HIGH_RISK_GEOGRAPHY', 'High Risk Geography'),
        ('STRUCTURING', 'Potential Structuring'),
        ('ROUND_AMOUNT', 'Round Amount Transaction'),
        ('DORMANT_ACTIVITY', 'Dormant Account Activity')
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('INVESTIGATING', 'Under Investigation'),
        ('CLEARED', 'Cleared'),
        ('SUSPICIOUS', 'Suspicious Activity'),
        ('REPORTED', 'Reported to Authorities')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=100)
    
    # Alert Details
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPE_CHOICES)
    alert_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Transaction Information
    transaction_id = models.CharField(max_length=255, blank=True)
    transaction_date = models.DateTimeField()
    transaction_amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_currency = models.CharField(max_length=3)
    
    # Pattern Information
    pattern_description = models.TextField()
    risk_score = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Related Transactions
    related_transactions = JSONField(default=list)
    pattern_start_date = models.DateTimeField(null=True, blank=True)
    pattern_end_date = models.DateTimeField(null=True, blank=True)
    
    # Investigation
    assigned_to = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_alerts'
    )
    investigation_notes = models.TextField(blank=True)
    supporting_documents = JSONField(default=list)
    
    # Resolution
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=255, blank=True)
    sar_filed = models.BooleanField(default=False)
    sar_reference = models.CharField(max_length=255, blank=True)
    
    class Meta:
        db_table = 'compliance_transaction_monitoring'
        verbose_name = 'Transaction Monitoring Alert'
        verbose_name_plural = 'Transaction Monitoring Alerts'
        ordering = ['-alert_date']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['status', 'alert_date']),
            models.Index(fields=['alert_type', 'risk_score']),
        ]
    
    def __str__(self):
        return f"{self.alert_type} - {self.entity_type} {self.entity_id}"


class SuspiciousActivity(BaseModel):
    """
    Suspicious Activity Reports (SARs).
    """
    
    ACTIVITY_TYPE_CHOICES = [
        ('MONEY_LAUNDERING', 'Suspected Money Laundering'),
        ('TERRORIST_FINANCING', 'Suspected Terrorist Financing'),
        ('FRAUD', 'Suspected Fraud'),
        ('STRUCTURING', 'Structuring'),
        ('UNUSUAL_ACTIVITY', 'Unusual Activity'),
        ('OTHER', 'Other Suspicious Activity')
    ]
    
    FILING_STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_REVIEW', 'Pending Review'),
        ('APPROVED', 'Approved for Filing'),
        ('FILED', 'Filed'),
        ('ACKNOWLEDGED', 'Acknowledged by Authority')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    monitoring_alert = models.ForeignKey(
        TransactionMonitoring,
        on_delete=models.CASCADE,
        related_name='suspicious_activities',
        null=True, blank=True
    )
    
    # SAR Details
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_TYPE_CHOICES)
    filing_status = models.CharField(
        max_length=20, choices=FILING_STATUS_CHOICES, default='DRAFT'
    )
    
    # Subject Information (Encrypted)
    subject_name = EncryptedCharField(max_length=255)
    subject_identifier = EncryptedCharField(max_length=100)
    subject_type = models.CharField(max_length=50)
    
    # Activity Details
    activity_date_start = models.DateField()
    activity_date_end = models.DateField()
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=3)
    
    # Narrative
    activity_description = models.TextField()
    suspicious_elements = JSONField(default=list)
    
    # Filing Information
    filing_deadline = models.DateField()
    filed_date = models.DateTimeField(null=True, blank=True)
    filing_reference = models.CharField(max_length=255, blank=True)
    filing_jurisdiction = models.CharField(max_length=50)
    
    # Internal Review
    prepared_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.PROTECT,
        related_name='prepared_sars'
    )
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_sars'
    )
    approved_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_sars'
    )
    
    # Metadata
    supporting_documentation = JSONField(default=list)
    law_enforcement_contact = models.BooleanField(default=False)
    follow_up_required = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'compliance_suspicious_activities'
        verbose_name = 'Suspicious Activity Report'
        verbose_name_plural = 'Suspicious Activity Reports'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['filing_status', 'filing_deadline']),
            models.Index(fields=['activity_type', 'filed_date']),
        ]
    
    def __str__(self):
        return f"SAR - {self.activity_type} - {self.subject_name}"