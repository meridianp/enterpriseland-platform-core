"""
Audit Log Models

Models for comprehensive audit logging.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from platform_core.core.models import BaseModel, TenantFilteredModel


User = get_user_model()


class AuditLog(TenantFilteredModel):
    """
    Main audit log model for tracking all system changes.
    """
    
    # Event identification
    event_type = models.CharField(
        max_length=50,
        db_index=True,
        choices=[
            # Data events
            ('create', _('Create')),
            ('update', _('Update')),
            ('delete', _('Delete')),
            ('bulk_create', _('Bulk Create')),
            ('bulk_update', _('Bulk Update')),
            ('bulk_delete', _('Bulk Delete')),
            
            # Access events
            ('view', _('View')),
            ('download', _('Download')),
            ('export', _('Export')),
            ('import', _('Import')),
            
            # Auth events
            ('login', _('Login')),
            ('logout', _('Logout')),
            ('login_failed', _('Login Failed')),
            ('password_change', _('Password Change')),
            ('password_reset', _('Password Reset')),
            ('mfa_enabled', _('MFA Enabled')),
            ('mfa_disabled', _('MFA Disabled')),
            
            # Security events
            ('permission_granted', _('Permission Granted')),
            ('permission_revoked', _('Permission Revoked')),
            ('role_assigned', _('Role Assigned')),
            ('role_removed', _('Role Removed')),
            ('security_alert', _('Security Alert')),
            
            # System events
            ('config_change', _('Configuration Change')),
            ('system_error', _('System Error')),
            ('maintenance', _('Maintenance')),
        ]
    )
    
    # Who performed the action
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )
    user_agent = models.TextField(
        blank=True
    )
    
    # What was affected
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    object_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True
    )
    content_object = GenericForeignKey('content_type', 'object_id')
    object_repr = models.CharField(
        max_length=200,
        help_text=_("String representation of the object")
    )
    
    # When it happened
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )
    
    # Additional context
    changes = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Field changes in format {field: [old, new]}")
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional event metadata")
    )
    
    # Request information
    request_id = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text=_("Correlation ID for request tracking")
    )
    session_key = models.CharField(
        max_length=255,
        blank=True
    )
    
    # Compliance fields
    data_classification = models.CharField(
        max_length=20,
        choices=[
            ('public', _('Public')),
            ('internal', _('Internal')),
            ('confidential', _('Confidential')),
            ('restricted', _('Restricted')),
        ],
        default='internal'
    )
    retention_date = models.DateField(
        null=True,
        blank=True,
        help_text=_("Date after which log can be deleted")
    )
    
    class Meta:
        db_table = 'security_audit_logs'
        indexes = [
            models.Index(fields=['event_type', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['request_id']),
            models.Index(fields=['timestamp']),
        ]
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.event_type} by {self.user or 'System'} on {self.object_repr}"
    
    @property
    def is_sensitive(self):
        """Check if this log contains sensitive data"""
        return self.data_classification in ['confidential', 'restricted']
    
    def get_changes_display(self):
        """Get human-readable changes"""
        if not self.changes:
            return {}
        
        display = {}
        for field, (old_value, new_value) in self.changes.items():
            # Mask sensitive fields
            if field in ['password', 'secret', 'token', 'key']:
                display[field] = ['***', '***']
            else:
                display[field] = [str(old_value), str(new_value)]
        
        return display


class APIAccessLog(BaseModel):
    """
    Detailed API access logging for security monitoring.
    """
    
    # Request details
    method = models.CharField(
        max_length=10,
        db_index=True
    )
    path = models.CharField(
        max_length=500,
        db_index=True
    )
    query_params = models.JSONField(
        default=dict,
        blank=True
    )
    request_body_size = models.IntegerField(
        default=0
    )
    
    # User information
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(
        blank=True
    )
    
    # Response details
    status_code = models.IntegerField()
    response_size = models.IntegerField(
        default=0
    )
    response_time_ms = models.IntegerField(
        help_text=_("Response time in milliseconds")
    )
    
    # Security context
    authentication_method = models.CharField(
        max_length=50,
        blank=True,
        choices=[
            ('jwt', 'JWT Token'),
            ('session', 'Session'),
            ('api_key', 'API Key'),
            ('oauth', 'OAuth'),
            ('none', 'None'),
        ]
    )
    rate_limited = models.BooleanField(
        default=False
    )
    
    # Timestamps
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )
    
    # Error tracking
    error_message = models.TextField(
        blank=True
    )
    
    class Meta:
        db_table = 'security_api_access_logs'
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['path', 'method']),
            models.Index(fields=['status_code']),
        ]
    
    def __str__(self):
        return f"{self.method} {self.path} - {self.status_code}"
    
    @property
    def is_error(self):
        """Check if request resulted in error"""
        return self.status_code >= 400
    
    @property
    def is_slow(self):
        """Check if request was slow"""
        threshold = getattr(settings, 'SLOW_REQUEST_THRESHOLD_MS', 1000)
        return self.response_time_ms > threshold


class DataAccessLog(TenantFilteredModel):
    """
    Log sensitive data access for compliance.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    
    # What was accessed
    model_name = models.CharField(
        max_length=100,
        db_index=True
    )
    record_id = models.CharField(
        max_length=255,
        db_index=True
    )
    fields_accessed = models.JSONField(
        default=list,
        help_text=_("List of fields that were accessed")
    )
    
    # Access context
    access_type = models.CharField(
        max_length=20,
        choices=[
            ('view', _('View')),
            ('export', _('Export')),
            ('api', _('API Access')),
            ('report', _('Report')),
        ]
    )
    purpose = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("Business purpose for access")
    )
    
    # Security context
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )
    
    # Compliance
    data_subject_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text=_("ID of person whose data was accessed (for GDPR)")
    )
    legal_basis = models.CharField(
        max_length=50,
        blank=True,
        choices=[
            ('consent', _('Consent')),
            ('contract', _('Contract')),
            ('legal', _('Legal Obligation')),
            ('vital', _('Vital Interests')),
            ('public', _('Public Task')),
            ('legitimate', _('Legitimate Interests')),
        ]
    )
    
    class Meta:
        db_table = 'security_data_access_logs'
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['model_name', 'record_id']),
            models.Index(fields=['data_subject_id']),
        ]


class SecurityEvent(BaseModel):
    """
    Log security-related events for monitoring and alerting.
    """
    
    event_type = models.CharField(
        max_length=50,
        db_index=True,
        choices=[
            # Authentication
            ('auth_failure', _('Authentication Failure')),
            ('auth_anomaly', _('Authentication Anomaly')),
            ('brute_force', _('Brute Force Attempt')),
            
            # Authorization
            ('unauthorized_access', _('Unauthorized Access')),
            ('privilege_escalation', _('Privilege Escalation')),
            ('permission_abuse', _('Permission Abuse')),
            
            # Data security
            ('data_breach', _('Data Breach')),
            ('data_exfiltration', _('Data Exfiltration')),
            ('suspicious_download', _('Suspicious Download')),
            
            # System security
            ('malware_detected', _('Malware Detected')),
            ('vulnerability_exploit', _('Vulnerability Exploit')),
            ('config_tampering', _('Configuration Tampering')),
            
            # Compliance
            ('compliance_violation', _('Compliance Violation')),
            ('audit_tampering', _('Audit Log Tampering')),
        ]
    )
    
    severity = models.CharField(
        max_length=20,
        choices=[
            ('info', _('Information')),
            ('low', _('Low')),
            ('medium', _('Medium')),
            ('high', _('High')),
            ('critical', _('Critical')),
        ],
        db_index=True
    )
    
    # Event details
    title = models.CharField(
        max_length=200
    )
    description = models.TextField()
    
    # Context
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_events'
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )
    
    # Additional data
    details = models.JSONField(
        default=dict,
        blank=True
    )
    
    # Response
    handled = models.BooleanField(
        default=False,
        db_index=True
    )
    handled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='handled_security_events'
    )
    handled_at = models.DateTimeField(
        null=True,
        blank=True
    )
    response_notes = models.TextField(
        blank=True
    )
    
    # Timestamps
    detected_at = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )
    
    class Meta:
        db_table = 'security_events'
        indexes = [
            models.Index(fields=['event_type', 'severity']),
            models.Index(fields=['detected_at']),
            models.Index(fields=['handled', 'severity']),
        ]
        ordering = ['-detected_at']
    
    def __str__(self):
        return f"{self.get_severity_display()}: {self.title}"
    
    def mark_handled(self, user, notes=''):
        """Mark event as handled"""
        self.handled = True
        self.handled_by = user
        self.handled_at = timezone.now()
        self.response_notes = notes
        self.save()