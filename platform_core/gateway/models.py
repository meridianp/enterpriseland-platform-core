"""
API Gateway Models

Defines service registry, routes, and gateway configuration.
"""

from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.contrib.postgres.fields import ArrayField
from django.utils.translation import gettext_lazy as _

from platform_core.common.models import BaseModel, TenantFilteredModel


class ServiceRegistry(TenantFilteredModel):
    """
    Registry of backend services available through the gateway.
    """
    
    SERVICE_TYPES = [
        ('rest', 'REST API'),
        ('graphql', 'GraphQL'),
        ('grpc', 'gRPC'),
        ('websocket', 'WebSocket'),
        ('internal', 'Internal Service'),
    ]
    
    HEALTH_CHECK_TYPES = [
        ('http', 'HTTP GET'),
        ('tcp', 'TCP Connect'),
        ('custom', 'Custom Check'),
    ]
    
    # Basic Information
    name = models.CharField(
        max_length=100,
        unique=True,
        validators=[RegexValidator(r'^[a-zA-Z0-9_-]+$')],
        help_text=_("Service identifier (alphanumeric, dash, underscore)")
    )
    display_name = models.CharField(
        max_length=200,
        help_text=_("Human-readable service name")
    )
    description = models.TextField(
        blank=True,
        help_text=_("Service description")
    )
    
    # Service Configuration
    service_type = models.CharField(
        max_length=20,
        choices=SERVICE_TYPES,
        default='rest'
    )
    base_url = models.URLField(
        help_text=_("Base URL of the service (e.g., http://service:8000)")
    )
    timeout = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(300)],
        help_text=_("Request timeout in seconds")
    )
    
    # Load Balancing
    weight = models.IntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(1000)],
        help_text=_("Load balancing weight (0 = disabled)")
    )
    max_retries = models.IntegerField(
        default=3,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text=_("Maximum retry attempts on failure")
    )
    
    # Health Check
    health_check_enabled = models.BooleanField(
        default=True,
        help_text=_("Enable health checking")
    )
    health_check_type = models.CharField(
        max_length=20,
        choices=HEALTH_CHECK_TYPES,
        default='http'
    )
    health_check_path = models.CharField(
        max_length=200,
        default='/health',
        help_text=_("Health check endpoint path")
    )
    health_check_interval = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(300)],
        help_text=_("Health check interval in seconds")
    )
    
    # Circuit Breaker
    circuit_breaker_enabled = models.BooleanField(
        default=True,
        help_text=_("Enable circuit breaker pattern")
    )
    circuit_breaker_threshold = models.IntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text=_("Failure count before opening circuit")
    )
    circuit_breaker_timeout = models.IntegerField(
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(600)],
        help_text=_("Circuit open duration in seconds")
    )
    
    # Authentication
    auth_required = models.BooleanField(
        default=True,
        help_text=_("Require authentication for this service")
    )
    api_key = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("API key for service authentication")
    )
    
    # Metadata
    is_active = models.BooleanField(
        default=True,
        help_text=_("Service is active and available")
    )
    is_healthy = models.BooleanField(
        default=True,
        help_text=_("Current health status")
    )
    last_health_check = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Last successful health check")
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional service metadata")
    )
    
    class Meta:
        db_table = 'gateway_service_registry'
        verbose_name = 'Service'
        verbose_name_plural = 'Services'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active', 'is_healthy']),
            models.Index(fields=['service_type']),
        ]
    
    def __str__(self):
        return f"{self.display_name} ({self.name})"
    
    def get_full_url(self, path=''):
        """Get full URL for a given path"""
        base = self.base_url.rstrip('/')
        path = path.lstrip('/')
        return f"{base}/{path}" if path else base


class Route(TenantFilteredModel):
    """
    API Gateway route configuration.
    Maps incoming requests to backend services.
    """
    
    METHODS = [
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('PATCH', 'PATCH'),
        ('DELETE', 'DELETE'),
        ('HEAD', 'HEAD'),
        ('OPTIONS', 'OPTIONS'),
        ('*', 'Any'),
    ]
    
    TRANSFORM_TYPES = [
        ('none', 'No Transformation'),
        ('json', 'JSON Transformation'),
        ('xml', 'XML Transformation'),
        ('custom', 'Custom Transformation'),
    ]
    
    # Route Information
    path = models.CharField(
        max_length=500,
        help_text=_("Route path pattern (supports {param} placeholders)")
    )
    method = models.CharField(
        max_length=10,
        choices=METHODS,
        default='*',
        help_text=_("HTTP method")
    )
    description = models.TextField(
        blank=True,
        help_text=_("Route description")
    )
    
    # Service Mapping
    service = models.ForeignKey(
        ServiceRegistry,
        on_delete=models.CASCADE,
        related_name='routes',
        help_text=_("Target service")
    )
    service_path = models.CharField(
        max_length=500,
        blank=True,
        help_text=_("Path on target service (blank = same as route path)")
    )
    
    # Request Configuration
    strip_prefix = models.BooleanField(
        default=False,
        help_text=_("Strip route prefix from service path")
    )
    append_slash = models.BooleanField(
        default=False,
        help_text=_("Append trailing slash to service path")
    )
    
    # Transformation
    transform_request = models.CharField(
        max_length=20,
        choices=TRANSFORM_TYPES,
        default='none',
        help_text=_("Request transformation type")
    )
    transform_response = models.CharField(
        max_length=20,
        choices=TRANSFORM_TYPES,
        default='none',
        help_text=_("Response transformation type")
    )
    transform_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Transformation configuration")
    )
    
    # Headers
    add_request_headers = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Headers to add to request")
    )
    add_response_headers = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Headers to add to response")
    )
    remove_request_headers = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text=_("Headers to remove from request")
    )
    remove_response_headers = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text=_("Headers to remove from response")
    )
    
    # Security
    auth_required = models.BooleanField(
        default=True,
        help_text=_("Require authentication")
    )
    allowed_origins = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
        help_text=_("Allowed CORS origins")
    )
    
    # Rate Limiting
    rate_limit = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Rate limit (e.g., '100/hour')")
    )
    
    # Caching
    cache_enabled = models.BooleanField(
        default=False,
        help_text=_("Enable response caching")
    )
    cache_ttl = models.IntegerField(
        default=300,
        validators=[MinValueValidator(0), MaxValueValidator(86400)],
        help_text=_("Cache TTL in seconds")
    )
    cache_key_params = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text=_("Query params to include in cache key")
    )
    
    # Configuration
    priority = models.IntegerField(
        default=100,
        help_text=_("Route priority (higher = higher priority)")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Route is active")
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional route metadata")
    )
    
    class Meta:
        db_table = 'gateway_routes'
        verbose_name = 'Route'
        verbose_name_plural = 'Routes'
        ordering = ['-priority', 'path']
        unique_together = [('path', 'method')]
        indexes = [
            models.Index(fields=['is_active', 'priority']),
            models.Index(fields=['path', 'method']),
        ]
    
    def __str__(self):
        return f"{self.method} {self.path} -> {self.service.name}"
    
    def matches(self, request_path, request_method):
        """Check if route matches request"""
        # Method matching
        if self.method != '*' and self.method != request_method:
            return False
        
        # Path matching (simple for now, can be enhanced)
        import re
        pattern = self.path.replace('{', '(?P<').replace('}', '>[^/]+)')
        pattern = f"^{pattern}$"
        
        return bool(re.match(pattern, request_path))


class GatewayConfig(BaseModel):
    """
    Global gateway configuration.
    """
    
    # Request Handling
    global_timeout = models.IntegerField(
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(300)],
        help_text=_("Global request timeout in seconds")
    )
    max_request_size = models.IntegerField(
        default=10485760,  # 10MB
        validators=[MinValueValidator(1024)],
        help_text=_("Maximum request size in bytes")
    )
    
    # Security
    require_auth_default = models.BooleanField(
        default=True,
        help_text=_("Require authentication by default")
    )
    allowed_origins = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
        help_text=_("Global allowed CORS origins")
    )
    
    # Rate Limiting
    global_rate_limit = models.CharField(
        max_length=50,
        default='1000/hour',
        help_text=_("Global rate limit")
    )
    
    # Logging
    log_requests = models.BooleanField(
        default=True,
        help_text=_("Log all requests")
    )
    log_request_body = models.BooleanField(
        default=False,
        help_text=_("Log request bodies (caution: sensitive data)")
    )
    log_response_body = models.BooleanField(
        default=False,
        help_text=_("Log response bodies (caution: sensitive data)")
    )
    
    # Performance
    enable_compression = models.BooleanField(
        default=True,
        help_text=_("Enable response compression")
    )
    compression_level = models.IntegerField(
        default=6,
        validators=[MinValueValidator(1), MaxValueValidator(9)],
        help_text=_("Compression level (1-9)")
    )
    
    # Metadata
    is_active = models.BooleanField(
        default=True,
        help_text=_("Gateway is active")
    )
    maintenance_mode = models.BooleanField(
        default=False,
        help_text=_("Gateway is in maintenance mode")
    )
    maintenance_message = models.TextField(
        blank=True,
        help_text=_("Maintenance mode message")
    )
    
    class Meta:
        db_table = 'gateway_config'
        verbose_name = 'Gateway Configuration'
        verbose_name_plural = 'Gateway Configuration'
    
    def __str__(self):
        return f"Gateway Config (Active: {self.is_active})"
    
    def save(self, *args, **kwargs):
        # Ensure only one config exists
        if not self.pk and GatewayConfig.objects.exists():
            raise ValueError("Only one GatewayConfig instance allowed")
        super().save(*args, **kwargs)


class ServiceInstance(TenantFilteredModel):
    """
    Individual instances of a service for load balancing.
    """
    
    service = models.ForeignKey(
        ServiceRegistry,
        on_delete=models.CASCADE,
        related_name='instances'
    )
    
    # Instance Information
    instance_id = models.CharField(
        max_length=100,
        help_text=_("Unique instance identifier")
    )
    host = models.CharField(
        max_length=255,
        help_text=_("Instance host/IP")
    )
    port = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text=_("Instance port")
    )
    
    # Health
    is_healthy = models.BooleanField(
        default=True,
        help_text=_("Instance health status")
    )
    last_health_check = models.DateTimeField(
        null=True,
        blank=True
    )
    health_check_failures = models.IntegerField(
        default=0,
        help_text=_("Consecutive health check failures")
    )
    
    # Load Balancing
    weight = models.IntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(1000)],
        help_text=_("Instance weight for load balancing")
    )
    current_connections = models.IntegerField(
        default=0,
        help_text=_("Current active connections")
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True
    )
    
    class Meta:
        db_table = 'gateway_service_instances'
        verbose_name = 'Service Instance'
        verbose_name_plural = 'Service Instances'
        unique_together = [('service', 'instance_id')]
        indexes = [
            models.Index(fields=['service', 'is_healthy']),
        ]
    
    def __str__(self):
        return f"{self.service.name}:{self.instance_id}"
    
    def get_url(self):
        """Get instance URL"""
        return f"http://{self.host}:{self.port}"


class APIAggregation(TenantFilteredModel):
    """
    Configuration for API aggregation patterns.
    Combines multiple service calls into a single response.
    """
    
    AGGREGATION_TYPES = [
        ('parallel', 'Parallel Execution'),
        ('sequential', 'Sequential Execution'),
        ('conditional', 'Conditional Execution'),
        ('scatter_gather', 'Scatter-Gather Pattern'),
    ]
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Aggregation name")
    )
    description = models.TextField(
        blank=True
    )
    
    # Aggregation Configuration
    aggregation_type = models.CharField(
        max_length=20,
        choices=AGGREGATION_TYPES,
        default='parallel'
    )
    
    # Request mapping
    request_path = models.CharField(
        max_length=500,
        help_text=_("Incoming request path pattern")
    )
    request_method = models.CharField(
        max_length=10,
        choices=Route.METHODS,
        default='GET'
    )
    
    # Service calls configuration
    service_calls = models.JSONField(
        help_text=_("Configuration for service calls"),
        default=dict
        # Format:
        # {
        #     "calls": [
        #         {
        #             "name": "user_service",
        #             "service": "users",
        #             "path": "/users/{user_id}",
        #             "method": "GET",
        #             "depends_on": [],
        #             "transform": {}
        #         }
        #     ],
        #     "response_template": {}
        # }
    )
    
    # Response handling
    merge_responses = models.BooleanField(
        default=True,
        help_text=_("Merge service responses")
    )
    response_template = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Response transformation template")
    )
    
    # Error handling
    fail_fast = models.BooleanField(
        default=True,
        help_text=_("Fail on first error")
    )
    partial_response_allowed = models.BooleanField(
        default=False,
        help_text=_("Allow partial responses on failure")
    )
    
    # Performance
    cache_enabled = models.BooleanField(
        default=False
    )
    cache_ttl = models.IntegerField(
        default=300,
        validators=[MinValueValidator(0)]
    )
    timeout = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1)]
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'gateway_api_aggregations'
        verbose_name = 'API Aggregation'
        verbose_name_plural = 'API Aggregations'
        indexes = [
            models.Index(fields=['request_path', 'request_method']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.aggregation_type})"