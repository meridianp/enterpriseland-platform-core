"""
Core models for the EnterpriseLand platform.

Provides audit logging, system monitoring, and core platform functionality
with comprehensive security and performance tracking.
"""

import uuid
import json
import logging
from typing import Optional, Dict, Any, List, Union
from decimal import Decimal
from datetime import datetime, timedelta

from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator, MaxValueValidator
from django.conf import settings

from platform_core.accounts.models import Group
from core.managers import GroupFilteredManager

User = get_user_model()
logger = logging.getLogger(__name__)


class AuditLogQuerySet(models.QuerySet):
    """Custom QuerySet for AuditLog with specialized filtering methods."""
    
    def for_model(self, model_name: str) -> 'AuditLogQuerySet':
        """Filter audit logs for a specific model."""
        return self.filter(model_name=model_name)
    
    def for_object(self, obj: models.Model) -> 'AuditLogQuerySet':
        """Filter audit logs for a specific object instance."""
        content_type = ContentType.objects.get_for_model(obj.__class__)
        return self.filter(content_type=content_type, object_id=str(obj.pk))
    
    def for_user(self, user: User) -> 'AuditLogQuerySet':
        """Filter audit logs for a specific user."""
        return self.filter(user=user)
    
    def for_action(self, action: str) -> 'AuditLogQuerySet':
        """Filter audit logs for a specific action."""
        return self.filter(action=action)
    
    def in_date_range(self, start_date: datetime, end_date: datetime) -> 'AuditLogQuerySet':
        """Filter audit logs within a date range."""
        return self.filter(timestamp__range=[start_date, end_date])
    
    def recent(self, days: int = 7) -> 'AuditLogQuerySet':
        """Filter audit logs from recent days."""
        cutoff_date = timezone.now() - timedelta(days=days)
        return self.filter(timestamp__gte=cutoff_date)
    
    def by_ip_address(self, ip_address: str) -> 'AuditLogQuerySet':
        """Filter audit logs by IP address."""
        return self.filter(ip_address=ip_address)
    
    def critical_actions(self) -> 'AuditLogQuerySet':
        """Filter for critical security actions."""
        critical_actions = [
            'DELETE', 'BULK_DELETE', 'PERMISSION_CHANGE', 
            'PASSWORD_CHANGE', 'LOGIN_FAILED', 'ADMIN_ACCESS'
        ]
        return self.filter(action__in=critical_actions)
    
    def with_changes(self) -> 'AuditLogQuerySet':
        """Filter for logs that contain actual changes."""
        return self.exclude(changes__isnull=True).exclude(changes__exact={})


class AuditLogManager(models.Manager):
    """Custom manager for AuditLog with specialized query methods."""
    
    def get_queryset(self) -> AuditLogQuerySet:
        """Return the custom queryset."""
        return AuditLogQuerySet(self.model, using=self._db)
    
    def for_model(self, model_name: str) -> AuditLogQuerySet:
        """Get audit logs for a specific model."""
        return self.get_queryset().for_model(model_name)
    
    def for_object(self, obj: models.Model) -> AuditLogQuerySet:
        """Get audit logs for a specific object."""
        return self.get_queryset().for_object(obj)
    
    def for_user(self, user: User) -> AuditLogQuerySet:
        """Get audit logs for a specific user."""
        return self.get_queryset().for_user(user)
    
    def recent_activity(self, days: int = 7) -> AuditLogQuerySet:
        """Get recent audit activity."""
        return self.get_queryset().recent(days)
    
    def security_events(self, days: int = 30) -> AuditLogQuerySet:
        """Get security-related events."""
        return self.get_queryset().critical_actions().recent(days)
    
    def create_log(
        self,
        action: str,
        user: Optional[User] = None,
        content_object: Optional[models.Model] = None,
        changes: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        group: Optional[Group] = None,
        **kwargs
    ) -> 'AuditLog':
        """
        Create a new audit log entry.
        
        Args:
            action: Action that was performed
            user: User who performed the action
            content_object: Object that was affected
            changes: Dictionary of changes made
            ip_address: IP address of the request
            user_agent: User agent string
            group: Group context for the action
            **kwargs: Additional fields
            
        Returns:
            Created AuditLog instance
        """
        # Determine group from various sources
        if not group:
            if content_object and hasattr(content_object, 'group'):
                group = content_object.group
            elif user and user.groups.exists():
                group = user.groups.first()
        
        # Prepare log data
        log_data = {
            'action': action,
            'user': user,
            'changes': changes or {},
            'ip_address': ip_address,
            'user_agent': user_agent,
            'group': group,
            **kwargs
        }
        
        # Set content object fields if provided
        if content_object:
            log_data['content_type'] = ContentType.objects.get_for_model(content_object.__class__)
            log_data['object_id'] = str(content_object.pk)
            log_data['model_name'] = content_object.__class__.__name__
        
        return self.create(**log_data)


class AuditLog(models.Model):
    """
    Comprehensive audit logging for all system activities.
    
    Tracks user actions, data changes, security events, and system operations
    with detailed context and change tracking.
    """
    
    class Action(models.TextChoices):
        # CRUD Operations
        CREATE = 'CREATE', 'Create'
        READ = 'READ', 'Read'
        UPDATE = 'UPDATE', 'Update'
        DELETE = 'DELETE', 'Delete'
        
        # Bulk Operations
        BULK_CREATE = 'BULK_CREATE', 'Bulk Create'
        BULK_UPDATE = 'BULK_UPDATE', 'Bulk Update'
        BULK_DELETE = 'BULK_DELETE', 'Bulk Delete'
        
        # Authentication & Authorization
        LOGIN = 'LOGIN', 'Login'
        LOGOUT = 'LOGOUT', 'Logout'
        LOGIN_FAILED = 'LOGIN_FAILED', 'Login Failed'
        PASSWORD_CHANGE = 'PASSWORD_CHANGE', 'Password Change'
        PERMISSION_CHANGE = 'PERMISSION_CHANGE', 'Permission Change'
        
        # Administrative Actions
        ADMIN_ACCESS = 'ADMIN_ACCESS', 'Admin Access'
        SETTINGS_CHANGE = 'SETTINGS_CHANGE', 'Settings Change'
        USER_ACTIVATION = 'USER_ACTIVATION', 'User Activation'
        USER_DEACTIVATION = 'USER_DEACTIVATION', 'User Deactivation'
        
        # Data Operations
        EXPORT = 'EXPORT', 'Data Export'
        IMPORT = 'IMPORT', 'Data Import'
        BACKUP = 'BACKUP', 'Data Backup'
        RESTORE = 'RESTORE', 'Data Restore'
        
        # File Operations
        FILE_UPLOAD = 'FILE_UPLOAD', 'File Upload'
        FILE_DOWNLOAD = 'FILE_DOWNLOAD', 'File Download'
        FILE_DELETE = 'FILE_DELETE', 'File Delete'
        
        # API Operations
        API_ACCESS = 'API_ACCESS', 'API Access'
        API_ERROR = 'API_ERROR', 'API Error'
        RATE_LIMIT = 'RATE_LIMIT', 'Rate Limit Exceeded'
    
    # Primary identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Action details
    action = models.CharField(
        max_length=50,
        choices=Action.choices,
        db_index=True,
        help_text="Type of action performed"
    )
    
    # User context
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        help_text="User who performed the action"
    )
    
    # Object context (generic foreign key for any model)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Type of object affected"
    )
    object_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="ID of the object affected"
    )
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Model information
    model_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
        help_text="Name of the model affected"
    )
    
    # Change tracking
    changes = models.JSONField(
        default=dict,
        encoder=DjangoJSONEncoder,
        help_text="JSON object containing the changes made"
    )
    
    # Request context
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the request"
    )
    user_agent = models.TextField(
        null=True,
        blank=True,
        help_text="User agent string from the request"
    )
    
    # Multi-tenancy
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_logs',
        help_text="Group context for the action"
    )
    
    # Additional metadata
    metadata = models.JSONField(
        default=dict,
        encoder=DjangoJSONEncoder,
        help_text="Additional context and metadata"
    )
    
    # Success indicator
    success = models.BooleanField(
        default=True,
        help_text="Whether the action was successful"
    )
    
    # Error details
    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Error message if action failed"
    )
    
    objects = AuditLogManager()
    
    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp', 'action']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['model_name', 'timestamp']),
            models.Index(fields=['group', 'timestamp']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['ip_address', 'timestamp']),
            models.Index(fields=['action', 'success', 'timestamp']),
        ]
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
    
    def __str__(self) -> str:
        user_info = f"{self.user.email}" if self.user else "Anonymous"
        object_info = f"{self.model_name}:{self.object_id}" if self.model_name else "System"
        return f"{self.action} by {user_info} on {object_info} at {self.timestamp}"
    
    @property
    def formatted_changes(self) -> str:
        """Return a human-readable format of the changes."""
        if not self.changes:
            return "No changes recorded"
        
        formatted = []
        for field, change_data in self.changes.items():
            if isinstance(change_data, dict) and 'old' in change_data and 'new' in change_data:
                old_val = change_data['old']
                new_val = change_data['new']
                formatted.append(f"{field}: '{old_val}' → '{new_val}'")
            else:
                formatted.append(f"{field}: {change_data}")
        
        return "; ".join(formatted)
    
    @property
    def is_critical(self) -> bool:
        """Check if this is a critical security action."""
        critical_actions = [
            self.Action.DELETE,
            self.Action.BULK_DELETE,
            self.Action.PERMISSION_CHANGE,
            self.Action.PASSWORD_CHANGE,
            self.Action.LOGIN_FAILED,
            self.Action.ADMIN_ACCESS,
            self.Action.USER_DEACTIVATION
        ]
        return self.action in critical_actions
    
    @property
    def duration_since(self) -> str:
        """Return human-readable time since this log entry."""
        now = timezone.now()
        diff = now - self.timestamp
        
        if diff.days > 0:
            return f"{diff.days} days ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} hours ago"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} minutes ago"
        else:
            return "Just now"
    
    def get_related_logs(self, limit: int = 10) -> models.QuerySet:
        """Get related audit logs for the same object."""
        if not self.content_type or not self.object_id:
            return AuditLog.objects.none()
        
        return AuditLog.objects.filter(
            content_type=self.content_type,
            object_id=self.object_id
        ).exclude(id=self.id).order_by('-timestamp')[:limit]
    
    def mask_sensitive_data(self) -> Dict[str, Any]:
        """Return a version of changes with sensitive data masked."""
        if not self.changes:
            return {}
        
        sensitive_fields = [
            'password', 'token', 'secret', 'key', 'auth',
            'ssn', 'social_security', 'credit_card', 'bank_account'
        ]
        
        masked_changes = {}
        for field, value in self.changes.items():
            field_lower = field.lower()
            if any(sensitive in field_lower for sensitive in sensitive_fields):
                masked_changes[field] = "***MASKED***"
            else:
                masked_changes[field] = value
        
        return masked_changes


class AuditLogEntry(models.Model):
    """
    Detailed change tracking for individual field modifications.
    
    Provides granular tracking of field-level changes with old/new values
    and change metadata.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Reference to main audit log
    audit_log = models.ForeignKey(
        AuditLog,
        on_delete=models.CASCADE,
        related_name='entries'
    )
    
    # Field information
    field_name = models.CharField(
        max_length=100,
        help_text="Name of the field that changed"
    )
    field_type = models.CharField(
        max_length=50,
        help_text="Type of the field (CharField, IntegerField, etc.)"
    )
    
    # Change values
    old_value = models.TextField(
        null=True,
        blank=True,
        help_text="Previous value (JSON serialized)"
    )
    new_value = models.TextField(
        null=True,
        blank=True,
        help_text="New value (JSON serialized)"
    )
    
    # Change metadata
    is_sensitive = models.BooleanField(
        default=False,
        help_text="Whether this field contains sensitive data"
    )
    change_reason = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Reason for the change"
    )
    
    class Meta:
        db_table = 'audit_log_entries'
        ordering = ['field_name']
        indexes = [
            models.Index(fields=['audit_log', 'field_name']),
            models.Index(fields=['field_name', 'is_sensitive']),
        ]
        unique_together = ['audit_log', 'field_name']
        verbose_name = 'Audit Log Entry'
        verbose_name_plural = 'Audit Log Entries'
    
    def __str__(self) -> str:
        return f"{self.field_name} change in {self.audit_log}"
    
    @property
    def formatted_change(self) -> str:
        """Return a formatted representation of the change."""
        if self.is_sensitive:
            return f"{self.field_name}: ***SENSITIVE DATA CHANGED***"
        
        old_display = self.old_value or "None"
        new_display = self.new_value or "None"
        
        # Truncate long values
        if len(old_display) > 50:
            old_display = old_display[:47] + "..."
        if len(new_display) > 50:
            new_display = new_display[:47] + "..."
        
        return f"{self.field_name}: '{old_display}' → '{new_display}'"
    
    def get_parsed_old_value(self) -> Any:
        """Parse the old value from JSON."""
        if not self.old_value:
            return None
        try:
            return json.loads(self.old_value)
        except (json.JSONDecodeError, TypeError):
            return self.old_value
    
    def get_parsed_new_value(self) -> Any:
        """Parse the new value from JSON."""
        if not self.new_value:
            return None
        try:
            return json.loads(self.new_value)
        except (json.JSONDecodeError, TypeError):
            return self.new_value


class SystemMetrics(models.Model):
    """
    System performance and health metrics for monitoring.
    
    Tracks system health, performance metrics, and operational statistics
    for monitoring and alerting purposes.
    """
    
    class MetricType(models.TextChoices):
        PERFORMANCE = 'PERFORMANCE', 'Performance'
        SECURITY = 'SECURITY', 'Security'
        USAGE = 'USAGE', 'Usage'
        ERROR = 'ERROR', 'Error'
        BUSINESS = 'BUSINESS', 'Business'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Metric identification
    metric_type = models.CharField(
        max_length=20,
        choices=MetricType.choices,
        db_index=True
    )
    metric_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Name of the metric"
    )
    
    # Metric values
    value = models.DecimalField(
        max_digits=15,
        decimal_places=6,
        help_text="Numeric value of the metric"
    )
    unit = models.CharField(
        max_length=20,
        help_text="Unit of measurement (seconds, bytes, count, etc.)"
    )
    
    # Context
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='metrics'
    )
    metadata = models.JSONField(
        default=dict,
        help_text="Additional metric metadata and tags"
    )
    
    class Meta:
        db_table = 'system_metrics'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['metric_type', 'metric_name', 'timestamp']),
            models.Index(fields=['group', 'timestamp']),
            models.Index(fields=['timestamp', 'value']),
        ]
        verbose_name = 'System Metric'
        verbose_name_plural = 'System Metrics'
    
    def __str__(self) -> str:
        return f"{self.metric_name}: {self.value}{self.unit} at {self.timestamp}"
    
    @classmethod
    def record_metric(
        cls,
        metric_type: str,
        metric_name: str,
        value: Union[int, float, Decimal],
        unit: str = 'count',
        group: Optional[Group] = None,
        **metadata
    ) -> 'SystemMetrics':
        """
        Record a system metric.
        
        Args:
            metric_type: Type of metric (performance, security, etc.)
            metric_name: Name of the metric
            value: Numeric value
            unit: Unit of measurement
            group: Group context
            **metadata: Additional metadata
            
        Returns:
            Created SystemMetrics instance
        """
        return cls.objects.create(
            metric_type=metric_type,
            metric_name=metric_name,
            value=Decimal(str(value)),
            unit=unit,
            group=group,
            metadata=metadata
        )
    
    @classmethod
    def get_latest_metrics(
        cls,
        metric_names: List[str],
        hours: int = 24,
        group: Optional[Group] = None
    ) -> models.QuerySet:
        """Get latest metrics for specified names within time range."""
        cutoff_time = timezone.now() - timedelta(hours=hours)
        queryset = cls.objects.filter(
            metric_name__in=metric_names,
            timestamp__gte=cutoff_time
        )
        
        if group:
            queryset = queryset.filter(group=group)
        
        return queryset.order_by('metric_name', '-timestamp')