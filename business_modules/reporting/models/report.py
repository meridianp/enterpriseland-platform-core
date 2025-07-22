"""Report models for the reporting module."""

import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField, ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django_fsm import FSMField, transition

from core.models.base import BaseModel, GroupFilteredModel

User = get_user_model()


class ReportTemplate(BaseModel):
    """Pre-defined report templates for common use cases."""
    
    CATEGORY_CHOICES = [
        ('executive', 'Executive'),
        ('financial', 'Financial'),
        ('operational', 'Operational'),
        ('investment', 'Investment'),
        ('market', 'Market Intelligence'),
        ('custom', 'Custom'),
    ]
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='custom')
    template_config = JSONField(default=dict, help_text="Template configuration")
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False, help_text="System templates cannot be modified")
    preview_image = models.URLField(blank=True, null=True)
    
    class Meta:
        ordering = ['category', 'name']
        
    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class Report(GroupFilteredModel):
    """Main report model."""
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]
    
    TYPE_CHOICES = [
        ('standard', 'Standard Report'),
        ('dashboard', 'Dashboard Report'),
        ('analytical', 'Analytical Report'),
        ('real_time', 'Real-time Report'),
        ('scheduled', 'Scheduled Report'),
    ]
    
    # Basic information
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES, default='standard')
    status = FSMField(default='draft', choices=STATUS_CHOICES)
    
    # Template and configuration
    template = models.ForeignKey(
        ReportTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reports'
    )
    configuration = JSONField(default=dict, help_text="Report configuration including layout, filters, etc.")
    
    # Data sources and queries
    data_sources = models.ManyToManyField('DataSource', related_name='reports')
    queries = JSONField(default=list, help_text="Query definitions for the report")
    
    # Visualizations and metrics
    visualizations = models.ManyToManyField('Visualization', related_name='reports', blank=True)
    metrics = models.ManyToManyField('Metric', related_name='reports', blank=True)
    
    # Metadata
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    version = models.IntegerField(default=1)
    is_favorite = models.BooleanField(default=False)
    
    # Permissions and sharing
    is_public = models.BooleanField(default=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_reports')
    collaborators = models.ManyToManyField(User, related_name='collaborative_reports', blank=True)
    
    # Performance settings
    cache_duration = models.IntegerField(
        default=3600,
        validators=[MinValueValidator(0), MaxValueValidator(86400)],
        help_text="Cache duration in seconds"
    )
    enable_real_time = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-updated_at']
        permissions = [
            ('can_publish_report', 'Can publish reports'),
            ('can_export_report', 'Can export reports'),
            ('can_schedule_report', 'Can schedule reports'),
            ('can_share_report', 'Can share reports'),
        ]
        
    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"
    
    @transition(field=status, source='draft', target='published')
    def publish(self):
        """Publish the report."""
        self.version += 1
        
    @transition(field=status, source=['draft', 'published'], target='archived')
    def archive(self):
        """Archive the report."""
        pass
        
    @transition(field=status, source='archived', target='draft')
    def restore(self):
        """Restore the report from archive."""
        pass
    
    def clone(self, user=None):
        """Create a copy of this report."""
        report_copy = Report.objects.create(
            name=f"{self.name} (Copy)",
            description=self.description,
            type=self.type,
            template=self.template,
            configuration=self.configuration,
            queries=self.queries,
            tags=self.tags,
            owner=user or self.owner,
            group=self.group
        )
        
        # Copy relationships
        report_copy.data_sources.set(self.data_sources.all())
        report_copy.visualizations.set(self.visualizations.all())
        report_copy.metrics.set(self.metrics.all())
        
        return report_copy


class ReportSchedule(GroupFilteredModel):
    """Schedule for automatic report generation and distribution."""
    
    FREQUENCY_CHOICES = [
        ('once', 'Once'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
        ('custom', 'Custom'),
    ]
    
    DELIVERY_CHOICES = [
        ('email', 'Email'),
        ('webhook', 'Webhook'),
        ('storage', 'Cloud Storage'),
        ('dashboard', 'Dashboard'),
    ]
    
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='schedules')
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    
    # Schedule configuration
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='daily')
    cron_expression = models.CharField(max_length=100, blank=True, help_text="Cron expression for custom schedules")
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=50, default='UTC')
    
    # Delivery configuration
    delivery_method = models.CharField(max_length=20, choices=DELIVERY_CHOICES, default='email')
    delivery_config = JSONField(default=dict, help_text="Delivery configuration (recipients, webhook URL, etc.)")
    export_format = models.CharField(max_length=20, default='pdf')
    
    # Execution tracking
    last_run = models.DateTimeField(null=True, blank=True)
    next_run = models.DateTimeField(null=True, blank=True)
    run_count = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['next_run']
        
    def __str__(self):
        return f"{self.name} - {self.get_frequency_display()}"


class ReportExecution(BaseModel):
    """Track report execution history."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='executions')
    schedule = models.ForeignKey(
        ReportSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='executions'
    )
    
    # Execution details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True, help_text="Execution duration in seconds")
    
    # Execution context
    executed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='report_executions')
    parameters = JSONField(default=dict, help_text="Execution parameters")
    
    # Results
    row_count = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    result_data = JSONField(null=True, blank=True, help_text="Cached result data")
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.report.name} - {self.status} ({self.created_at})"


class ReportExport(BaseModel):
    """Track report exports."""
    
    FORMAT_CHOICES = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('csv', 'CSV'),
        ('json', 'JSON'),
        ('png', 'PNG Image'),
        ('html', 'HTML'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='exports')
    execution = models.ForeignKey(
        ReportExecution,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='exports'
    )
    
    # Export details
    format = models.CharField(max_length=20, choices=FORMAT_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Export configuration
    include_visualizations = models.BooleanField(default=True)
    include_raw_data = models.BooleanField(default=False)
    filters = JSONField(default=dict, help_text="Applied filters for export")
    
    # Results
    file_path = models.CharField(max_length=500, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    download_url = models.URLField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    exported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='report_exports')
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.report.name} - {self.get_format_display()} ({self.status})"