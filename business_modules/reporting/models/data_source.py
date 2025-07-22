"""Data source models for the reporting module."""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField, ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator
from encrypted_model_fields.fields import EncryptedCharField

from core.models.base import GroupFilteredModel

User = get_user_model()


class DataSource(GroupFilteredModel):
    """External data source configuration."""
    
    TYPE_CHOICES = [
        ('postgresql', 'PostgreSQL'),
        ('mysql', 'MySQL'),
        ('mongodb', 'MongoDB'),
        ('elasticsearch', 'Elasticsearch'),
        ('api', 'REST API'),
        ('graphql', 'GraphQL API'),
        ('csv', 'CSV File'),
        ('excel', 'Excel File'),
        ('google_sheets', 'Google Sheets'),
        ('internal', 'Internal Database'),
        ('redis', 'Redis'),
        ('influxdb', 'InfluxDB'),
        ('prometheus', 'Prometheus'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('error', 'Error'),
        ('testing', 'Testing'),
    ]
    
    # Basic information
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Connection details
    host = models.CharField(max_length=255, blank=True)
    port = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(65535)])
    database = models.CharField(max_length=255, blank=True)
    schema = models.CharField(max_length=255, blank=True, help_text="Database schema or namespace")
    
    # Authentication
    username = models.CharField(max_length=255, blank=True)
    password = EncryptedCharField(max_length=255, blank=True)
    api_key = EncryptedCharField(max_length=500, blank=True)
    
    # Connection options
    connection_options = JSONField(default=dict, help_text="Additional connection parameters")
    ssl_enabled = models.BooleanField(default=True)
    ssl_config = JSONField(null=True, blank=True, help_text="SSL configuration")
    
    # Query settings
    timeout = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(300)],
        help_text="Query timeout in seconds"
    )
    max_rows = models.IntegerField(
        default=10000,
        validators=[MinValueValidator(1), MaxValueValidator(1000000)],
        help_text="Maximum rows to return"
    )
    
    # Metadata
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    test_query = models.TextField(blank=True, help_text="Query to test connection")
    
    # Access control
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_data_sources')
    allowed_users = models.ManyToManyField(User, related_name='allowed_data_sources', blank=True)
    allowed_groups = models.ManyToManyField('accounts.UserGroup', related_name='allowed_data_sources', blank=True)
    
    # Performance
    enable_caching = models.BooleanField(default=True)
    cache_duration = models.IntegerField(
        default=3600,
        validators=[MinValueValidator(0), MaxValueValidator(86400)],
        help_text="Cache duration in seconds"
    )
    
    # Health check
    last_tested = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    is_healthy = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['name']
        permissions = [
            ('can_test_data_source', 'Can test data source connection'),
            ('can_manage_data_sources', 'Can manage all data sources'),
        ]
        
    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"
    
    def get_connection_string(self):
        """Generate connection string based on type."""
        if self.type == 'postgresql':
            return f"postgresql://{self.username}:***@{self.host}:{self.port}/{self.database}"
        elif self.type == 'mysql':
            return f"mysql://{self.username}:***@{self.host}:{self.port}/{self.database}"
        elif self.type == 'mongodb':
            return f"mongodb://{self.username}:***@{self.host}:{self.port}/{self.database}"
        elif self.type in ['api', 'graphql']:
            return f"{self.host}"
        return "N/A"


class DataSourceConnection(models.Model):
    """Active connections to data sources."""
    
    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='connections')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='data_connections')
    
    # Connection details
    connection_id = models.CharField(max_length=100, unique=True)
    established_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(auto_now=True)
    
    # Session data
    session_data = JSONField(null=True, blank=True, help_text="Connection session data")
    is_active = models.BooleanField(default=True)
    
    # Metrics
    query_count = models.IntegerField(default=0)
    total_rows_fetched = models.BigIntegerField(default=0)
    total_duration = models.FloatField(default=0, help_text="Total query duration in seconds")
    
    class Meta:
        ordering = ['-last_used']
        
    def __str__(self):
        return f"{self.user.username} - {self.data_source.name}"


class QueryDefinition(GroupFilteredModel):
    """Saved query definitions."""
    
    QUERY_TYPE_CHOICES = [
        ('sql', 'SQL'),
        ('nosql', 'NoSQL'),
        ('api', 'API'),
        ('graphql', 'GraphQL'),
        ('aggregation', 'Aggregation Pipeline'),
    ]
    
    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='queries')
    
    # Query information
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=20, choices=QUERY_TYPE_CHOICES, default='sql')
    
    # Query content
    query = models.TextField(help_text="Query text or API endpoint")
    parameters = JSONField(default=dict, help_text="Query parameters")
    
    # Transformation
    transformations = JSONField(default=list, help_text="Post-query transformations")
    
    # Metadata
    tags = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    is_template = models.BooleanField(default=False, help_text="Can be used as template")
    
    # Performance
    estimated_duration = models.FloatField(null=True, blank=True, help_text="Estimated query duration in seconds")
    estimated_rows = models.IntegerField(null=True, blank=True)
    
    # Usage tracking
    usage_count = models.IntegerField(default=0)
    last_used = models.DateTimeField(null=True, blank=True)
    
    # Access control
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_queries')
    is_public = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['name']
        
    def __str__(self):
        return f"{self.name} ({self.data_source.name})"