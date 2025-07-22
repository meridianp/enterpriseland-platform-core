"""Data transformation models for the reporting module."""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField, ArrayField

from core.models.base import GroupFilteredModel

User = get_user_model()


class DataPipeline(GroupFilteredModel):
    """Data transformation pipeline."""
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('error', 'Error'),
        ('archived', 'Archived'),
    ]
    
    # Basic information
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Pipeline configuration
    source_data_sources = models.ManyToManyField('DataSource', related_name='source_pipelines')
    target_data_source = models.ForeignKey(
        'DataSource',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='target_pipelines'
    )
    
    # Schedule
    is_scheduled = models.BooleanField(default=False)
    schedule_config = JSONField(null=True, blank=True, help_text="Schedule configuration")
    
    # Performance
    batch_size = models.IntegerField(default=1000)
    timeout = models.IntegerField(default=3600, help_text="Timeout in seconds")
    parallel_execution = models.BooleanField(default=False)
    
    # Tracking
    last_run = models.DateTimeField(null=True, blank=True)
    last_success = models.DateTimeField(null=True, blank=True)
    run_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    
    # Metadata
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_pipelines')
    
    class Meta:
        ordering = ['name']
        
    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class DataTransformation(GroupFilteredModel):
    """Individual data transformation configuration."""
    
    TYPE_CHOICES = [
        ('filter', 'Filter'),
        ('aggregate', 'Aggregate'),
        ('join', 'Join'),
        ('pivot', 'Pivot'),
        ('unpivot', 'Unpivot'),
        ('calculate', 'Calculate'),
        ('rename', 'Rename'),
        ('cast', 'Type Cast'),
        ('clean', 'Clean'),
        ('enrich', 'Enrich'),
        ('custom', 'Custom'),
    ]
    
    pipeline = models.ForeignKey(
        DataPipeline,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='transformations'
    )
    
    # Transformation details
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    order = models.IntegerField(default=0)
    
    # Configuration
    configuration = JSONField(help_text="Transformation configuration")
    
    # Input/Output
    input_columns = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    output_columns = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    
    # Validation
    validation_rules = JSONField(default=list, help_text="Validation rules")
    skip_on_error = models.BooleanField(default=False)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        ordering = ['pipeline', 'order']
        
    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class TransformationStep(models.Model):
    """Individual steps within a transformation."""
    
    STEP_TYPE_CHOICES = [
        ('select', 'Select Columns'),
        ('filter_rows', 'Filter Rows'),
        ('sort', 'Sort'),
        ('limit', 'Limit'),
        ('group_by', 'Group By'),
        ('window', 'Window Function'),
        ('expression', 'Expression'),
        ('lookup', 'Lookup'),
        ('merge', 'Merge'),
        ('split', 'Split'),
        ('regex', 'Regular Expression'),
        ('date_parse', 'Date Parse'),
        ('number_parse', 'Number Parse'),
        ('string_operation', 'String Operation'),
        ('math_operation', 'Math Operation'),
        ('conditional', 'Conditional'),
        ('custom_function', 'Custom Function'),
    ]
    
    transformation = models.ForeignKey(DataTransformation, on_delete=models.CASCADE, related_name='steps')
    
    # Step details
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=50, choices=STEP_TYPE_CHOICES)
    order = models.IntegerField(default=0)
    
    # Configuration
    configuration = JSONField(help_text="Step configuration")
    
    # Error handling
    error_handling = models.CharField(
        max_length=20,
        choices=[
            ('fail', 'Fail on Error'),
            ('skip', 'Skip Row'),
            ('default', 'Use Default Value'),
            ('null', 'Set to Null'),
        ],
        default='fail'
    )
    default_value = models.CharField(max_length=255, blank=True)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['transformation', 'order']
        
    def __str__(self):
        return f"{self.name} - {self.transformation.name}"