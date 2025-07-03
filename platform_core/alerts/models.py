"""
Alert Models
"""
import json
from enum import Enum
from typing import Optional, Dict, Any
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

User = get_user_model()


class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'


class AlertStatus(Enum):
    """Alert status"""
    PENDING = 'pending'
    FIRING = 'firing'
    RESOLVED = 'resolved'
    ACKNOWLEDGED = 'acknowledged'
    SILENCED = 'silenced'


class AlertChannelType(Enum):
    """Alert channel types"""
    EMAIL = 'email'
    SLACK = 'slack'
    PAGERDUTY = 'pagerduty'
    WEBHOOK = 'webhook'
    SMS = 'sms'


class AlertRule(models.Model):
    """Alert rule configuration"""
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    
    # Rule configuration
    metric_name = models.CharField(max_length=200)
    condition = models.CharField(
        max_length=10,
        choices=[
            ('>', 'Greater than'),
            ('>=', 'Greater than or equal'),
            ('<', 'Less than'),
            ('<=', 'Less than or equal'),
            ('==', 'Equal to'),
            ('!=', 'Not equal to'),
        ]
    )
    threshold = models.FloatField()
    
    # Time configuration
    evaluation_interval = models.IntegerField(default=60, help_text='Seconds between evaluations')
    for_duration = models.IntegerField(default=300, help_text='Seconds condition must be true')
    
    # Alert configuration
    severity = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in AlertSeverity],
        default=AlertSeverity.WARNING.value
    )
    
    # Additional configuration
    labels = JSONField(default=dict, blank=True)
    annotations = JSONField(default=dict, blank=True)
    
    # Status
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Notification settings
    cooldown_period = models.IntegerField(
        default=3600,
        help_text='Seconds before re-alerting'
    )
    max_alerts_per_day = models.IntegerField(
        default=10,
        help_text='Maximum alerts per day'
    )
    
    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['enabled', 'metric_name']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.metric_name} {self.condition} {self.threshold})"
    
    def evaluate(self, value: float) -> bool:
        """Evaluate if alert should fire"""
        if self.condition == '>':
            return value > self.threshold
        elif self.condition == '>=':
            return value >= self.threshold
        elif self.condition == '<':
            return value < self.threshold
        elif self.condition == '<=':
            return value <= self.threshold
        elif self.condition == '==':
            return value == self.threshold
        elif self.condition == '!=':
            return value != self.threshold
        return False


class AlertChannel(models.Model):
    """Alert notification channel"""
    name = models.CharField(max_length=200, unique=True)
    type = models.CharField(
        max_length=20,
        choices=[(t.value, t.name) for t in AlertChannelType]
    )
    
    # Channel configuration
    configuration = JSONField(
        default=dict,
        help_text='Channel-specific configuration'
    )
    
    # Routing rules
    severities = JSONField(
        default=list,
        help_text='List of severities to route to this channel'
    )
    labels = JSONField(
        default=dict,
        help_text='Label filters for routing'
    )
    
    # Status
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Rate limiting
    rate_limit = models.IntegerField(
        default=100,
        help_text='Maximum notifications per hour'
    )
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.type})"
    
    def should_route(self, alert: 'Alert') -> bool:
        """Check if alert should be routed to this channel"""
        if not self.enabled:
            return False
        
        # Check severity
        if self.severities and alert.severity not in self.severities:
            return False
        
        # Check labels
        if self.labels:
            for key, value in self.labels.items():
                if alert.labels.get(key) != value:
                    return False
        
        return True


class Alert(models.Model):
    """Alert instance"""
    rule = models.ForeignKey(
        AlertRule,
        on_delete=models.CASCADE,
        related_name='alerts'
    )
    
    # Alert details
    severity = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in AlertSeverity]
    )
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in AlertStatus],
        default=AlertStatus.PENDING.value
    )
    
    # Alert data
    value = models.FloatField()
    message = models.TextField()
    labels = JSONField(default=dict)
    annotations = JSONField(default=dict)
    
    # Timestamps
    fired_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_alerts'
    )
    
    # Notification tracking
    notified_channels = JSONField(default=list)
    notification_count = models.IntegerField(default=0)
    last_notification_at = models.DateTimeField(null=True, blank=True)
    
    # Grouping
    fingerprint = models.CharField(
        max_length=64,
        db_index=True,
        help_text='Unique identifier for deduplication'
    )
    
    class Meta:
        ordering = ['-fired_at']
        indexes = [
            models.Index(fields=['status', 'severity']),
            models.Index(fields=['rule', 'status']),
            models.Index(fields=['fingerprint', 'status']),
        ]
    
    def __str__(self):
        return f"{self.rule.name} - {self.status} ({self.fired_at})"
    
    def acknowledge(self, user: User) -> None:
        """Acknowledge alert"""
        self.status = AlertStatus.ACKNOWLEDGED.value
        self.acknowledged_at = timezone.now()
        self.acknowledged_by = user
        self.save()
    
    def resolve(self) -> None:
        """Resolve alert"""
        self.status = AlertStatus.RESOLVED.value
        self.resolved_at = timezone.now()
        self.save()
    
    def silence(self, duration: int) -> None:
        """Silence alert for duration in seconds"""
        self.status = AlertStatus.SILENCED.value
        # Additional logic for silence expiration
        self.save()


class AlertNotification(models.Model):
    """Alert notification history"""
    alert = models.ForeignKey(
        Alert,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    channel = models.ForeignKey(
        AlertChannel,
        on_delete=models.CASCADE
    )
    
    # Notification details
    sent_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    
    # Response tracking
    response_data = JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['alert', 'channel']),
            models.Index(fields=['sent_at', 'success']),
        ]


class AlertSilence(models.Model):
    """Alert silence rules"""
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Silence criteria
    matchers = JSONField(
        default=dict,
        help_text='Label matchers for silencing'
    )
    
    # Time range
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    
    # Creator
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='alert_silences'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Status
    active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['active', 'starts_at', 'ends_at']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.starts_at} - {self.ends_at})"
    
    def matches(self, alert: Alert) -> bool:
        """Check if alert matches silence criteria"""
        if not self.active:
            return False
        
        now = timezone.now()
        if now < self.starts_at or now > self.ends_at:
            return False
        
        for key, value in self.matchers.items():
            if alert.labels.get(key) != value:
                return False
        
        return True