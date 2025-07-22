"""
Reporting Models

Models for portfolio reporting and document generation.
"""
import uuid
from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from platform_core.models import BaseModel


class ReportTemplate(BaseModel):
    """
    Configurable report templates for different report types.
    """
    
    REPORT_TYPE_CHOICES = [
        ('ILPA_QUARTERLY', 'ILPA Quarterly Report'),
        ('GIPS_COMPLIANCE', 'GIPS Compliance Report'),
        ('LIMITED_PARTNER', 'Limited Partner Report'),
        ('MANAGEMENT', 'Management Report'),
        ('REGULATORY', 'Regulatory Filing'),
        ('CUSTOM', 'Custom Report')
    ]
    
    FORMAT_CHOICES = [
        ('PDF', 'PDF Document'),
        ('EXCEL', 'Excel Spreadsheet'),
        ('WORD', 'Word Document'),
        ('HTML', 'HTML Report'),
        ('JSON', 'JSON Data')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    report_type = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    
    # Template Configuration
    template_file = models.FileField(
        upload_to='report_templates/', null=True, blank=True
    )
    template_config = JSONField(
        default=dict,
        help_text="Template configuration and parameters"
    )
    
    # Sections and Components
    sections = JSONField(
        default=list,
        help_text="List of report sections and their configuration"
    )
    required_data = ArrayField(
        models.CharField(max_length=100),
        default=list,
        help_text="Required data points for this report"
    )
    
    # Output Configuration
    supported_formats = ArrayField(
        models.CharField(max_length=10, choices=FORMAT_CHOICES),
        default=list
    )
    default_format = models.CharField(
        max_length=10, choices=FORMAT_CHOICES, default='PDF'
    )
    
    # Compliance and Standards
    compliance_standards = ArrayField(
        models.CharField(max_length=50),
        default=list,
        help_text="Compliance standards this template adheres to"
    )
    
    # Versioning
    version = models.CharField(max_length=20, default='1.0')
    
    class Meta:
        db_table = 'portfolio_report_templates'
        verbose_name = 'Report Template'
        verbose_name_plural = 'Report Templates'
        ordering = ['name']
        indexes = [
            models.Index(fields=['report_type', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.report_type})"


class GeneratedReport(BaseModel):
    """
    Generated portfolio reports.
    """
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending Generation'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('EXPIRED', 'Expired')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='generated_reports'
    )
    template = models.ForeignKey(
        ReportTemplate,
        on_delete=models.PROTECT,
        null=True, blank=True
    )
    
    # Report Details
    report_type = models.CharField(max_length=20)
    report_name = models.CharField(max_length=255)
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Generation Details
    generation_date = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='generated_reports'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # File Information
    file_url = models.URLField(max_length=500, blank=True)
    file_path = models.CharField(max_length=500, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    format = models.CharField(max_length=10)
    
    # Report Parameters
    parameters = JSONField(
        default=dict,
        help_text="Parameters used for report generation"
    )
    
    # Metadata
    metadata = JSONField(
        default=dict,
        help_text="Additional report metadata"
    )
    error_message = models.TextField(blank=True)
    processing_time_seconds = models.FloatField(null=True, blank=True)
    
    # Access Control
    is_public = models.BooleanField(default=False)
    access_expires_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'portfolio_generated_reports'
        verbose_name = 'Generated Report'
        verbose_name_plural = 'Generated Reports'
        ordering = ['-generation_date']
        indexes = [
            models.Index(fields=['portfolio', 'status']),
            models.Index(fields=['report_type', 'generation_date']),
            models.Index(fields=['generated_by', 'generation_date']),
        ]
    
    def __str__(self):
        return f"{self.report_name} - {self.portfolio.name}"
    
    def get_download_url(self):
        """Generate a pre-signed download URL."""
        # This would integrate with S3 or other storage backend
        # For now, return the file_url
        return self.file_url


class ReportSchedule(BaseModel):
    """
    Scheduled report generation configuration.
    """
    
    FREQUENCY_CHOICES = [
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('ANNUAL', 'Annual'),
        ('CUSTOM', 'Custom Schedule')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(
        'portfolio_monitoring.Portfolio',
        on_delete=models.CASCADE,
        related_name='report_schedules'
    )
    template = models.ForeignKey(
        ReportTemplate,
        on_delete=models.CASCADE
    )
    
    # Schedule Configuration
    schedule_name = models.CharField(max_length=255)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    is_active = models.BooleanField(default=True)
    
    # Timing
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    next_run_date = models.DateField()
    last_run_date = models.DateField(null=True, blank=True)
    
    # Custom Schedule (cron expression)
    cron_expression = models.CharField(
        max_length=100, blank=True,
        help_text="Cron expression for custom schedules"
    )
    
    # Report Parameters
    report_parameters = JSONField(
        default=dict,
        help_text="Default parameters for scheduled reports"
    )
    
    # Distribution
    recipients = JSONField(
        default=list,
        help_text="List of email recipients"
    )
    distribution_channels = ArrayField(
        models.CharField(max_length=20),
        default=list,
        help_text="Distribution channels: email, sftp, api"
    )
    
    # Tracking
    run_count = models.IntegerField(default=0)
    last_status = models.CharField(max_length=20, blank=True)
    last_error = models.TextField(blank=True)
    
    class Meta:
        db_table = 'portfolio_report_schedules'
        verbose_name = 'Report Schedule'
        verbose_name_plural = 'Report Schedules'
        ordering = ['portfolio', 'schedule_name']
        indexes = [
            models.Index(fields=['portfolio', 'is_active']),
            models.Index(fields=['next_run_date', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.schedule_name} - {self.portfolio.name}"


class ReportDistribution(BaseModel):
    """
    Track report distribution history.
    """
    
    CHANNEL_CHOICES = [
        ('EMAIL', 'Email'),
        ('SFTP', 'SFTP'),
        ('API', 'API'),
        ('PORTAL', 'Portal Upload'),
        ('WEBHOOK', 'Webhook')
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('DELIVERED', 'Delivered'),
        ('FAILED', 'Failed')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(
        GeneratedReport,
        on_delete=models.CASCADE,
        related_name='distributions'
    )
    
    # Distribution Details
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    recipient = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Timing
    scheduled_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    # Tracking
    delivery_details = JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    
    # User Interaction
    accessed_at = models.DateTimeField(null=True, blank=True)
    download_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'portfolio_report_distributions'
        verbose_name = 'Report Distribution'
        verbose_name_plural = 'Report Distributions'
        ordering = ['-scheduled_at']
        indexes = [
            models.Index(fields=['report', 'status']),
            models.Index(fields=['channel', 'status']),
        ]
    
    def __str__(self):
        return f"{self.report.report_name} to {self.recipient} via {self.channel}"