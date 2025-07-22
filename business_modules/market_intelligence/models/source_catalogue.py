"""
Source Catalogue Models

Models for managing and tracking news sources, accuracy metrics,
and source health monitoring.
"""
import uuid
from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from core.models.base import BaseModel, GroupFilteredModel


class SourceCategory(BaseModel):
    """Categories for organizing news sources."""
    
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'market_intel_source_categories'
        verbose_name_plural = 'Source Categories'
        ordering = ['name']
    
    def __str__(self):
        return self.name


class NewsSource(BaseModel):
    """News source in the catalogue."""
    
    SOURCE_TYPE_CHOICES = [
        ('NEWS', 'News Website'),
        ('BLOG', 'Blog'),
        ('SOCIAL', 'Social Media'),
        ('PRESS', 'Press Release'),
        ('RESEARCH', 'Research Publication'),
        ('REGULATORY', 'Regulatory Filing'),
        ('API', 'API Feed'),
        ('RSS', 'RSS Feed')
    ]
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    url = models.URLField(max_length=500)
    feed_url = models.URLField(max_length=500, blank=True)
    api_key = models.CharField(max_length=255, blank=True)
    
    # Source Details
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        default='NEWS'
    )
    language = models.CharField(max_length=10, default='en')
    country = models.CharField(max_length=2, default='US')
    timezone = models.CharField(max_length=50, default='UTC')
    
    # Categorization
    categories = models.ManyToManyField(
        SourceCategory,
        related_name='sources',
        blank=True
    )
    tags = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True
    )
    
    # Configuration
    is_active = models.BooleanField(default=True)
    crawl_frequency = models.IntegerField(
        default=3600,
        validators=[MinValueValidator(60)],
        help_text="Crawl frequency in seconds"
    )
    configuration = JSONField(
        default=dict,
        help_text="Source-specific configuration"
    )
    
    # Quality Metrics
    quality_score = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    reliability_rating = models.IntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    
    # Metadata
    discovered_at = models.DateTimeField(default=timezone.now)
    last_crawled = models.DateTimeField(null=True, blank=True)
    article_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'market_intel_news_sources'
        verbose_name = 'News Source'
        verbose_name_plural = 'News Sources'
        ordering = ['-quality_score', 'name']
        indexes = [
            models.Index(fields=['source_type', 'is_active']),
            models.Index(fields=['quality_score', 'is_active']),
            models.Index(fields=['language', 'country']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.source_type})"


class SourceAccuracy(BaseModel):
    """Track accuracy metrics for each source."""
    
    source = models.OneToOneField(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='accuracy'
    )
    
    # Accuracy Metrics (0-100)
    entity_accuracy = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Entity extraction accuracy percentage"
    )
    sentiment_accuracy = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Sentiment analysis accuracy percentage"
    )
    classification_accuracy = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Article classification accuracy percentage"
    )
    relevance_score = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Content relevance score"
    )
    
    # Volume Metrics
    total_articles = models.IntegerField(default=0)
    total_entities = models.IntegerField(default=0)
    verified_samples = models.IntegerField(default=0)
    
    # Temporal Metrics
    last_accuracy_check = models.DateTimeField(null=True, blank=True)
    accuracy_trend = models.CharField(
        max_length=20,
        choices=[
            ('IMPROVING', 'Improving'),
            ('STABLE', 'Stable'),
            ('DECLINING', 'Declining'),
            ('UNKNOWN', 'Unknown')
        ],
        default='UNKNOWN'
    )
    
    class Meta:
        db_table = 'market_intel_source_accuracy'
        verbose_name = 'Source Accuracy'
        verbose_name_plural = 'Source Accuracy Records'
    
    def __str__(self):
        return f"{self.source.name} - Accuracy"


class SourceHealth(BaseModel):
    """Monitor health and availability of sources."""
    
    STATUS_CHOICES = [
        ('HEALTHY', 'Healthy'),
        ('WARNING', 'Warning'),
        ('DEGRADED', 'Degraded'),
        ('FAILED', 'Failed'),
        ('UNKNOWN', 'Unknown')
    ]
    
    source = models.OneToOneField(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='health'
    )
    
    # Health Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='UNKNOWN'
    )
    uptime_percentage = models.FloatField(
        default=100.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Crawl Metrics
    last_successful_crawl = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.IntegerField(default=0)
    total_checks = models.IntegerField(default=0)
    successful_checks = models.IntegerField(default=0)
    
    # Performance Metrics
    average_response_time = models.FloatField(
        null=True,
        blank=True,
        help_text="Average response time in seconds"
    )
    last_response_time = models.FloatField(
        null=True,
        blank=True,
        help_text="Last response time in seconds"
    )
    
    # Error Tracking
    last_error = models.TextField(blank=True)
    last_error_time = models.DateTimeField(null=True, blank=True)
    error_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'market_intel_source_health'
        verbose_name = 'Source Health'
        verbose_name_plural = 'Source Health Records'
        indexes = [
            models.Index(fields=['status', 'source']),
            models.Index(fields=['last_successful_crawl']),
        ]
    
    def __str__(self):
        return f"{self.source.name} - {self.status}"


class EntityExtraction(BaseModel):
    """Track entity extraction results for accuracy monitoring."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='extractions'
    )
    article_id = models.CharField(max_length=255, db_index=True)
    
    # Extraction Data
    extracted_entities = JSONField(
        default=list,
        help_text="Entities extracted by the system"
    )
    verified_entities = JSONField(
        default=list,
        blank=True,
        help_text="Manually verified entities for accuracy calculation"
    )
    entity_count = models.IntegerField(default=0)
    
    # Accuracy Metrics
    accuracy_score = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    precision_score = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    recall_score = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Metadata
    extraction_timestamp = models.DateTimeField(default=timezone.now)
    processing_time = models.FloatField(
        null=True,
        blank=True,
        help_text="Processing time in seconds"
    )
    
    class Meta:
        db_table = 'market_intel_entity_extractions'
        verbose_name = 'Entity Extraction'
        verbose_name_plural = 'Entity Extractions'
        ordering = ['-extraction_timestamp']
        indexes = [
            models.Index(fields=['source', 'extraction_timestamp']),
            models.Index(fields=['accuracy_score', 'extraction_timestamp']),
        ]
    
    def __str__(self):
        return f"{self.source.name} - {self.article_id}"
    
    def save(self, *args, **kwargs):
        # Update entity count
        self.entity_count = len(self.extracted_entities)
        super().save(*args, **kwargs)


class SourceMetrics(BaseModel):
    """Daily aggregated metrics for sources."""
    
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='daily_metrics'
    )
    date = models.DateField()
    
    # Volume Metrics
    articles_crawled = models.IntegerField(default=0)
    entities_extracted = models.IntegerField(default=0)
    unique_entities = models.IntegerField(default=0)
    
    # Accuracy Metrics (daily averages)
    avg_entity_accuracy = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    avg_sentiment_accuracy = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Performance Metrics
    avg_response_time = models.FloatField(
        null=True,
        blank=True,
        help_text="Average response time in seconds"
    )
    uptime_percentage = models.FloatField(
        default=100.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    error_count = models.IntegerField(default=0)
    
    # Entity Type Distribution
    entity_distribution = JSONField(
        default=dict,
        help_text="Distribution of entity types extracted"
    )
    
    class Meta:
        db_table = 'market_intel_source_metrics'
        verbose_name = 'Source Metrics'
        verbose_name_plural = 'Source Metrics'
        unique_together = [['source', 'date']]
        ordering = ['-date', 'source']
        indexes = [
            models.Index(fields=['date', 'source']),
            models.Index(fields=['source', 'date']),
        ]
    
    def __str__(self):
        return f"{self.source.name} - {self.date}"


class SourceAlert(BaseModel):
    """Alerts for source issues."""
    
    ALERT_TYPE_CHOICES = [
        ('ACCURACY_DROP', 'Accuracy Drop'),
        ('HEALTH_DEGRADED', 'Health Degraded'),
        ('CRAWL_FAILURE', 'Crawl Failure'),
        ('RESPONSE_SLOW', 'Slow Response'),
        ('CONTENT_CHANGE', 'Content Structure Change'),
        ('RATE_LIMITED', 'Rate Limited')
    ]
    
    SEVERITY_CHOICES = [
        ('INFO', 'Information'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='alerts'
    )
    
    # Alert Details
    alert_type = models.CharField(
        max_length=30,
        choices=ALERT_TYPE_CHOICES
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default='WARNING'
    )
    message = models.TextField()
    details = JSONField(default=dict)
    
    # Status
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_source_alerts'
    )
    resolution_notes = models.TextField(blank=True)
    
    # Notification
    notifications_sent = models.IntegerField(default=0)
    last_notification = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'market_intel_source_alerts'
        verbose_name = 'Source Alert'
        verbose_name_plural = 'Source Alerts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['source', 'is_resolved']),
            models.Index(fields=['alert_type', 'severity']),
            models.Index(fields=['created_at', 'is_resolved']),
        ]
    
    def __str__(self):
        return f"{self.source.name} - {self.alert_type}"