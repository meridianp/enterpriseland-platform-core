"""Analytics models for the reporting module."""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField, ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator

from core.models.base import GroupFilteredModel

User = get_user_model()


class Metric(GroupFilteredModel):
    """Business metrics and KPIs."""
    
    TYPE_CHOICES = [
        ('simple', 'Simple Metric'),
        ('calculated', 'Calculated Metric'),
        ('composite', 'Composite Metric'),
        ('derived', 'Derived Metric'),
        ('predictive', 'Predictive Metric'),
    ]
    
    AGGREGATION_CHOICES = [
        ('sum', 'Sum'),
        ('avg', 'Average'),
        ('min', 'Minimum'),
        ('max', 'Maximum'),
        ('count', 'Count'),
        ('distinct', 'Count Distinct'),
        ('median', 'Median'),
        ('stddev', 'Standard Deviation'),
        ('variance', 'Variance'),
        ('percentile', 'Percentile'),
        ('custom', 'Custom'),
    ]
    
    FORMAT_CHOICES = [
        ('number', 'Number'),
        ('currency', 'Currency'),
        ('percentage', 'Percentage'),
        ('duration', 'Duration'),
        ('boolean', 'Boolean'),
        ('rating', 'Rating'),
        ('custom', 'Custom'),
    ]
    
    # Basic information
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='simple')
    
    # Data configuration
    data_source = models.ForeignKey('DataSource', on_delete=models.SET_NULL, null=True, blank=True)
    table_name = models.CharField(max_length=255, blank=True)
    column_name = models.CharField(max_length=255, blank=True)
    
    # Calculation
    aggregation = models.CharField(max_length=20, choices=AGGREGATION_CHOICES, default='sum')
    formula = models.TextField(blank=True, help_text="Formula for calculated metrics")
    filters = JSONField(default=list, help_text="Metric-specific filters")
    
    # Formatting
    format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default='number')
    decimals = models.IntegerField(default=2, validators=[MinValueValidator(0), MaxValueValidator(10)])
    prefix = models.CharField(max_length=10, blank=True)
    suffix = models.CharField(max_length=10, blank=True)
    
    # Targets and thresholds
    target_value = models.FloatField(null=True, blank=True)
    min_threshold = models.FloatField(null=True, blank=True)
    max_threshold = models.FloatField(null=True, blank=True)
    warning_threshold = models.FloatField(null=True, blank=True)
    
    # Display options
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=20, blank=True)
    show_trend = models.BooleanField(default=True)
    show_sparkline = models.BooleanField(default=False)
    
    # Metadata
    category = models.CharField(max_length=100, blank=True)
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    is_key_metric = models.BooleanField(default=False)
    
    # Ownership
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='owned_metrics')
    is_public = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['category', 'name']
        
    def __str__(self):
        return self.display_name


class MetricCalculation(models.Model):
    """Historical metric calculations."""
    
    metric = models.ForeignKey(Metric, on_delete=models.CASCADE, related_name='calculations')
    
    # Calculation details
    timestamp = models.DateTimeField()
    value = models.FloatField()
    
    # Context
    dimensions = JSONField(default=dict, help_text="Dimension values for this calculation")
    period = models.CharField(max_length=20, blank=True, help_text="Time period (day, week, month, etc.)")
    
    # Comparison values
    previous_value = models.FloatField(null=True, blank=True)
    change_value = models.FloatField(null=True, blank=True)
    change_percentage = models.FloatField(null=True, blank=True)
    
    # Metadata
    calculation_time = models.FloatField(help_text="Calculation duration in seconds")
    is_estimated = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['metric', '-timestamp']),
            models.Index(fields=['metric', 'period', '-timestamp']),
        ]
        
    def __str__(self):
        return f"{self.metric.name} - {self.timestamp}"


class Alert(GroupFilteredModel):
    """Metric-based alerts and notifications."""
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('triggered', 'Triggered'),
        ('acknowledged', 'Acknowledged'),
        ('resolved', 'Resolved'),
        ('disabled', 'Disabled'),
    ]
    
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]
    
    NOTIFICATION_CHOICES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('webhook', 'Webhook'),
        ('in_app', 'In-App'),
        ('slack', 'Slack'),
        ('teams', 'Microsoft Teams'),
    ]
    
    # Basic information
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    
    # Alert conditions
    metric = models.ForeignKey(Metric, on_delete=models.CASCADE, related_name='alerts')
    conditions = models.ManyToManyField('AlertCondition', related_name='alerts')
    
    # Notification settings
    notification_channels = ArrayField(
        models.CharField(max_length=20, choices=NOTIFICATION_CHOICES),
        default=list
    )
    recipients = JSONField(default=list, help_text="Email addresses, phone numbers, webhook URLs, etc.")
    
    # Timing
    check_interval = models.IntegerField(
        default=300,
        validators=[MinValueValidator(60), MaxValueValidator(86400)],
        help_text="Check interval in seconds"
    )
    cooldown_period = models.IntegerField(
        default=3600,
        validators=[MinValueValidator(0), MaxValueValidator(86400)],
        help_text="Cooldown period between alerts in seconds"
    )
    
    # Tracking
    last_checked = models.DateTimeField(null=True, blank=True)
    last_triggered = models.DateTimeField(null=True, blank=True)
    trigger_count = models.IntegerField(default=0)
    
    # Metadata
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_alerts')
    
    class Meta:
        ordering = ['severity', 'name']
        
    def __str__(self):
        return f"{self.name} ({self.get_severity_display()})"


class AlertCondition(models.Model):
    """Individual conditions for alerts."""
    
    OPERATOR_CHOICES = [
        ('eq', 'Equal to'),
        ('ne', 'Not equal to'),
        ('gt', 'Greater than'),
        ('gte', 'Greater than or equal to'),
        ('lt', 'Less than'),
        ('lte', 'Less than or equal to'),
        ('between', 'Between'),
        ('not_between', 'Not between'),
        ('in', 'In list'),
        ('not_in', 'Not in list'),
        ('contains', 'Contains'),
        ('not_contains', 'Does not contain'),
        ('change_gt', 'Change greater than'),
        ('change_lt', 'Change less than'),
        ('trend_up', 'Trending up'),
        ('trend_down', 'Trending down'),
    ]
    
    TIMEFRAME_CHOICES = [
        ('current', 'Current value'),
        ('1h', 'Last 1 hour'),
        ('24h', 'Last 24 hours'),
        ('7d', 'Last 7 days'),
        ('30d', 'Last 30 days'),
        ('custom', 'Custom timeframe'),
    ]
    
    # Condition details
    field = models.CharField(max_length=100, default='value')
    operator = models.CharField(max_length=20, choices=OPERATOR_CHOICES)
    value = models.CharField(max_length=255)
    value2 = models.CharField(max_length=255, blank=True, help_text="Second value for between operators")
    
    # Timeframe
    timeframe = models.CharField(max_length=20, choices=TIMEFRAME_CHOICES, default='current')
    custom_timeframe = models.CharField(max_length=50, blank=True)
    
    # Logic
    combine_with = models.CharField(
        max_length=10,
        choices=[('and', 'AND'), ('or', 'OR')],
        default='and'
    )
    
    class Meta:
        ordering = ['id']
        
    def __str__(self):
        return f"{self.field} {self.get_operator_display()} {self.value}"