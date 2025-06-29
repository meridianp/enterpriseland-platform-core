"""
Module System Models

Defines the data models for the platform module system including:
- ModuleManifest: Module metadata and configuration
- ModuleInstallation: Per-tenant module installations
- ModuleDependency: Module dependency tracking
"""

import uuid
from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from django.core.exceptions import ValidationError
from django.utils import timezone
from platform_core.core.models import BaseModel, TenantFilteredModel


class ModuleManifest(BaseModel):
    """
    Module manifest stored in database.
    Represents a module that can be installed by tenants.
    """
    # Unique module identifier (e.g., "com.enterpriseland.investment")
    module_id = models.CharField(
        max_length=200, 
        unique=True,
        help_text="Unique identifier for the module (e.g., com.company.module)"
    )
    
    # Module metadata
    name = models.CharField(max_length=200, help_text="Human-readable module name")
    description = models.TextField(blank=True, help_text="Module description")
    version = models.CharField(max_length=20, help_text="Semantic version (e.g., 1.0.0)")
    author = models.CharField(max_length=200, blank=True)
    license = models.CharField(max_length=100, blank=True)
    homepage = models.URLField(blank=True)
    
    # Platform compatibility
    platform_version = models.CharField(
        max_length=50,
        help_text="Platform version requirement (e.g., >=2.0.0,<3.0.0)"
    )
    
    # Module capabilities
    dependencies = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
        help_text="List of required module IDs"
    )
    
    permissions = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text="List of required platform permissions"
    )
    
    # Module components
    entities = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text="Business object types provided by this module"
    )
    
    workflows = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text="Workflow types provided by this module"
    )
    
    agents = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text="AI agents provided by this module"
    )
    
    # API configuration
    apis = JSONField(
        default=dict,
        help_text="API endpoint configuration"
    )
    
    # Module configuration schema
    configuration_schema = JSONField(
        default=dict,
        blank=True,
        help_text="JSON Schema for module configuration"
    )
    
    # Resource limits
    resource_limits = JSONField(
        default=dict,
        help_text="Resource usage limits (memory, CPU, storage)"
    )
    
    # Module state
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this module is available for installation"
    )
    
    is_certified = models.BooleanField(
        default=False,
        help_text="Whether this module has been certified by platform team"
    )
    
    # Marketplace fields
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Module price (null for free modules)"
    )
    
    pricing_model = models.CharField(
        max_length=20,
        choices=[
            ('free', 'Free'),
            ('one_time', 'One-time purchase'),
            ('subscription', 'Subscription'),
            ('usage', 'Usage-based'),
        ],
        default='free'
    )
    
    # Metadata
    tags = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True,
        help_text="Module tags for categorization"
    )
    
    metadata = JSONField(
        default=dict,
        blank=True,
        help_text="Additional module metadata"
    )
    
    # Timestamps
    published_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'platform_module_manifests'
        indexes = [
            models.Index(fields=['module_id', 'version']),
            models.Index(fields=['is_active', 'is_certified']),
            models.Index(fields=['pricing_model']),
        ]
        
    def __str__(self):
        return f"{self.name} ({self.module_id}@{self.version})"
    
    def clean(self):
        """Validate module manifest"""
        super().clean()
        
        # Validate module ID format
        if not self.module_id or '.' not in self.module_id:
            raise ValidationError({
                'module_id': 'Module ID must be in format: com.company.module'
            })
        
        # Validate version format (basic semver)
        import re
        if not re.match(r'^\d+\.\d+\.\d+', self.version):
            raise ValidationError({
                'version': 'Version must be in semver format (e.g., 1.0.0)'
            })
    
    def get_resource_limit(self, resource_type):
        """Get resource limit for a specific type"""
        defaults = {
            'max_memory': '512MB',
            'max_cpu': '1.0',
            'max_storage': '1GB',
            'max_api_calls_per_minute': 100,
        }
        return self.resource_limits.get(resource_type, defaults.get(resource_type))


class ModuleInstallation(TenantFilteredModel):
    """
    Represents a module installed for a specific tenant.
    Tracks installation state and configuration.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Reference to module
    module = models.ForeignKey(
        ModuleManifest,
        on_delete=models.PROTECT,
        related_name='installations'
    )
    
    # Installation state
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending Installation'),
            ('installing', 'Installing'),
            ('active', 'Active'),
            ('disabled', 'Disabled'),
            ('failed', 'Failed'),
            ('uninstalling', 'Uninstalling'),
        ],
        default='pending'
    )
    
    # Module configuration for this tenant
    configuration = JSONField(
        default=dict,
        help_text="Module configuration specific to this tenant"
    )
    
    # License information
    license_key = models.CharField(max_length=200, blank=True)
    license_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Installation metadata
    installed_at = models.DateTimeField(null=True, blank=True)
    installed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='module_installations'
    )
    
    # State tracking
    enabled_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    last_health_check = models.DateTimeField(null=True, blank=True)
    health_status = models.CharField(
        max_length=20,
        choices=[
            ('healthy', 'Healthy'),
            ('degraded', 'Degraded'),
            ('unhealthy', 'Unhealthy'),
            ('unknown', 'Unknown'),
        ],
        default='unknown'
    )
    
    # Usage tracking
    usage_metrics = JSONField(
        default=dict,
        help_text="Module usage metrics"
    )
    
    # Error tracking
    error_message = models.TextField(blank=True)
    error_details = JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'platform_module_installations'
        unique_together = [('tenant', 'module')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['module', 'status']),
        ]
    
    def __str__(self):
        return f"{self.module.name} for {self.tenant.name}"
    
    def is_active(self):
        """Check if module is currently active"""
        return self.status == 'active'
    
    def can_be_enabled(self):
        """Check if module can be enabled"""
        return self.status in ['disabled', 'active']
    
    def can_be_disabled(self):
        """Check if module can be disabled"""
        return self.status == 'active'


class ModuleDependency(models.Model):
    """
    Tracks resolved dependencies between installed modules.
    Used for dependency management and uninstall protection.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # The module that has the dependency
    installation = models.ForeignKey(
        ModuleInstallation,
        on_delete=models.CASCADE,
        related_name='dependencies'
    )
    
    # The module that is depended upon
    required_module = models.ForeignKey(
        ModuleManifest,
        on_delete=models.PROTECT,
        related_name='dependents'
    )
    
    # Dependency metadata
    version_constraint = models.CharField(
        max_length=50,
        blank=True,
        help_text="Version constraint (e.g., >=1.0.0)"
    )
    
    is_satisfied = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'platform_module_dependencies'
        unique_together = [('installation', 'required_module')]
    
    def __str__(self):
        return f"{self.installation.module.module_id} requires {self.required_module.module_id}"


class ModuleEvent(TenantFilteredModel):
    """
    Audit log for module lifecycle events.
    Tracks all module-related actions for compliance and debugging.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Event context
    module = models.ForeignKey(
        ModuleManifest,
        on_delete=models.CASCADE,
        related_name='events'
    )
    
    installation = models.ForeignKey(
        ModuleInstallation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='events'
    )
    
    # Event details
    event_type = models.CharField(
        max_length=50,
        choices=[
            ('module.published', 'Module Published'),
            ('module.updated', 'Module Updated'),
            ('module.certified', 'Module Certified'),
            ('module.installed', 'Module Installed'),
            ('module.enabled', 'Module Enabled'),
            ('module.disabled', 'Module Disabled'),
            ('module.uninstalled', 'Module Uninstalled'),
            ('module.configured', 'Module Configured'),
            ('module.error', 'Module Error'),
            ('module.health_check', 'Health Check'),
        ]
    )
    
    # Event data
    event_data = JSONField(default=dict)
    
    # User who triggered the event
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    # Timestamps
    occurred_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'platform_module_events'
        indexes = [
            models.Index(fields=['module', 'event_type', '-occurred_at']),
            models.Index(fields=['tenant', '-occurred_at']),
        ]
        ordering = ['-occurred_at']
    
    def __str__(self):
        return f"{self.event_type} for {self.module.module_id} at {self.occurred_at}"