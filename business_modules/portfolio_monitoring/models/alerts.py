"""
Alert Models

Models for portfolio monitoring alerts and notifications.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from django.core.validators import MinValueValidator
from platform_core.models import BaseModel


class AlertRule(BaseModel):
    """
    Configurable alert rules for portfolio monitoring.
    """
    
    RULE_TYPE_CHOICES = [
        ('THRESHOLD', 'Threshold Alert'),
        ('CHANGE', 'Change Alert'),
        ('TREND', 'Trend Alert'),
        ('DEADLINE', 'Deadline Alert'),
        ('COMPLIANCE', 'Compliance Alert'),
        ('CUSTOM', 'Custom Alert')
    ]
    
    OPERATOR_CHOICES = [
        ('GT', 'Greater Than'),
        ('GTE', 'Greater Than or Equal'),
        ('LT', 'Less Than'),
        ('LTE', 'Less Than or Equal'),
        ('EQ', 'Equal To'),
        ('NEQ', 'Not Equal To'),
        ('BETWEEN', 'Between'),
        ('OUTSIDE', 'Outside Range')
    ]
    
    FREQUENCY_CHOICES = [
        ('REALTIME', 'Real-time'),
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='alert_rules',
        null=True, blank=True,
        help_text="Specific portfolio or null for all portfolios"
    )
    
    # Rule Definition
    rule_name = models.CharField(max_length=255)
    rule_type = models.CharField(max_length=20, choices=RULE_TYPE_CHOICES)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    
    # Condition Configuration
    metric = models.CharField(
        max_length=100,
        help_text="Metric to monitor (e.g., 'irr', 'nav', 'concentration')"
    )
    operator = models.CharField(max_length=10, choices=OPERATOR_CHOICES)
    threshold_value = models.DecimalField(
        max_digits=15, decimal_places=6,
        validators=[MinValueValidator(0)]
    )
    threshold_value_2 = models.DecimalField(
        max_digits=15, decimal_places=6,
        null=True, blank=True,
        help_text="Second threshold for BETWEEN/OUTSIDE operators"
    )
    
    # Additional Parameters
    comparison_period = models.CharField(
        max_length=20, blank=True,
        help_text="Period for comparison (e.g., '1M', '1Q', '1Y')"
    )
    aggregation_method = models.CharField(
        max_length=20, blank=True,
        help_text="How to aggregate data (sum, avg, max, min)"
    )
    
    # Notification Configuration
    notification_channels = ArrayField(
        models.CharField(max_length=20),
        default=list,
        help_text="Channels: email, sms, webhook, in_app"
    )
    recipients = JSONField(
        default=list,
        help_text="List of recipient configurations"
    )
    
    # Frequency and Cooldown
    frequency = models.CharField(
        max_length=20, choices=FREQUENCY_CHOICES, default='DAILY'
    )
    cooldown_hours = models.IntegerField(
        default=24,
        help_text="Minimum hours between alerts"
    )
    
    # Tracking
    last_checked = models.DateTimeField(null=True, blank=True)
    last_triggered = models.DateTimeField(null=True, blank=True)
    trigger_count = models.IntegerField(default=0)
    
    # Advanced Configuration
    condition_logic = JSONField(
        default=dict, blank=True,
        help_text="Complex condition logic in JSON format"
    )
    custom_template = models.TextField(
        blank=True,
        help_text="Custom notification template"
    )
    
    # Ownership
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_alert_rules'
    )
    
    class Meta:
        db_table = 'portfolio_alert_rules'
        verbose_name = 'Alert Rule'
        verbose_name_plural = 'Alert Rules'
        ordering = ['rule_name']
        indexes = [
            models.Index(fields=['portfolio', 'is_active']),
            models.Index(fields=['metric', 'is_active']),
            models.Index(fields=['last_checked']),
        ]
    
    def __str__(self):
        return f"{self.rule_name} ({self.portfolio.name if self.portfolio else 'All Portfolios'})"
    
    def should_check(self, current_time):
        """Determine if the rule should be checked based on frequency."""
        if not self.last_checked:
            return True
        
        time_since_check = current_time - self.last_checked
        
        if self.frequency == 'REALTIME':
            return True
        elif self.frequency == 'DAILY':
            return time_since_check.total_seconds() >= 86400
        elif self.frequency == 'WEEKLY':
            return time_since_check.days >= 7
        elif self.frequency == 'MONTHLY':
            return time_since_check.days >= 30
        elif self.frequency == 'QUARTERLY':
            return time_since_check.days >= 90
        
        return False
    
    def can_trigger(self, current_time):
        """Check if enough time has passed since last trigger."""
        if not self.last_triggered:
            return True
        
        hours_since_trigger = (current_time - self.last_triggered).total_seconds() / 3600
        return hours_since_trigger >= self.cooldown_hours


class AlertTrigger(BaseModel):
    """
    Record of alert rule triggers.
    """
    
    SEVERITY_CHOICES = [
        ('INFO', 'Information'),
        ('WARNING', 'Warning'),
        ('CRITICAL', 'Critical')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alert_rule = models.ForeignKey(
        AlertRule,
        on_delete=models.CASCADE,
        related_name='triggers'
    )
    
    # Trigger Details
    triggered_at = models.DateTimeField(auto_now_add=True)
    severity = models.CharField(
        max_length=10, choices=SEVERITY_CHOICES, default='WARNING'
    )
    
    # Trigger Data
    metric_value = models.DecimalField(
        max_digits=15, decimal_places=6,
        help_text="The metric value that triggered the alert"
    )
    threshold_value = models.DecimalField(
        max_digits=15, decimal_places=6,
        help_text="The threshold that was exceeded"
    )
    
    # Context
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        null=True, blank=True
    )
    holding = models.ForeignKey(
        'portfolio_monitoring.PortfolioHolding',
        on_delete=models.CASCADE,
        null=True, blank=True
    )
    
    # Additional Information
    details = JSONField(
        default=dict,
        help_text="Additional context about the trigger"
    )
    message = models.TextField()
    
    # Response Tracking
    acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='acknowledged_alerts'
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'portfolio_alert_triggers'
        verbose_name = 'Alert Trigger'
        verbose_name_plural = 'Alert Triggers'
        ordering = ['-triggered_at']
        indexes = [
            models.Index(fields=['alert_rule', 'triggered_at']),
            models.Index(fields=['portfolio', 'triggered_at']),
            models.Index(fields=['severity', 'acknowledged']),
        ]
    
    def __str__(self):
        return f"{self.alert_rule.rule_name} - {self.triggered_at}"


class AlertNotification(BaseModel):
    """
    Record of alert notifications sent.
    """
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('DELIVERED', 'Delivered'),
        ('FAILED', 'Failed'),
        ('BOUNCED', 'Bounced')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alert_trigger = models.ForeignKey(
        AlertTrigger,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    
    # Notification Details
    channel = models.CharField(max_length=20)
    recipient = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Content
    subject = models.CharField(max_length=255)
    message = models.TextField()
    
    # Delivery Information
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    
    # Tracking
    delivery_details = JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    
    # User Interaction
    read_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'portfolio_alert_notifications'
        verbose_name = 'Alert Notification'
        verbose_name_plural = 'Alert Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['alert_trigger', 'status']),
            models.Index(fields=['channel', 'status']),
            models.Index(fields=['sent_at']),
        ]
    
    def __str__(self):
        return f"{self.channel} to {self.recipient} - {self.status}"