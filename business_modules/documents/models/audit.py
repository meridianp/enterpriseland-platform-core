"""Document audit models."""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField
from .base import TimestampedModel
from .document import Document
from .folder import Folder

User = get_user_model()


class DocumentAudit(TimestampedModel):
    """Audit trail for document operations."""
    
    ACTION_CHOICES = [
        # Document lifecycle
        ('created', 'Document Created'),
        ('uploaded', 'Document Uploaded'),
        ('updated', 'Document Updated'),
        ('deleted', 'Document Deleted'),
        ('restored', 'Document Restored'),
        ('moved', 'Document Moved'),
        ('renamed', 'Document Renamed'),
        
        # Version control
        ('version_created', 'New Version Created'),
        ('version_restored', 'Version Restored'),
        ('version_deleted', 'Version Deleted'),
        
        # Access
        ('viewed', 'Document Viewed'),
        ('downloaded', 'Document Downloaded'),
        ('previewed', 'Document Previewed'),
        ('printed', 'Document Printed'),
        
        # Sharing
        ('shared', 'Document Shared'),
        ('unshared', 'Share Revoked'),
        ('link_created', 'Share Link Created'),
        ('link_accessed', 'Share Link Accessed'),
        ('link_revoked', 'Share Link Revoked'),
        
        # Permissions
        ('permission_granted', 'Permission Granted'),
        ('permission_revoked', 'Permission Revoked'),
        ('permission_changed', 'Permission Changed'),
        
        # Locking
        ('locked', 'Document Locked'),
        ('unlocked', 'Document Unlocked'),
        
        # Processing
        ('virus_scanned', 'Virus Scan Completed'),
        ('ocr_processed', 'OCR Processed'),
        ('preview_generated', 'Preview Generated'),
        ('metadata_extracted', 'Metadata Extracted'),
        
        # Folder operations
        ('folder_created', 'Folder Created'),
        ('folder_deleted', 'Folder Deleted'),
        ('folder_moved', 'Folder Moved'),
        ('folder_renamed', 'Folder Renamed'),
        
        # Bulk operations
        ('bulk_download', 'Bulk Download'),
        ('bulk_delete', 'Bulk Delete'),
        ('bulk_move', 'Bulk Move'),
        ('bulk_permission', 'Bulk Permission Change'),
        
        # Other
        ('exported', 'Document Exported'),
        ('imported', 'Document Imported'),
        ('tagged', 'Tags Updated'),
        ('commented', 'Comment Added'),
    ]
    
    # What was affected
    document = models.ForeignKey(
        Document,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        help_text="Affected document"
    )
    
    folder = models.ForeignKey(
        Folder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        help_text="Affected folder"
    )
    
    # Action details
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
        db_index=True,
        help_text="Action performed"
    )
    
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='document_audit_logs',
        help_text="User who performed the action"
    )
    
    # Context
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the user"
    )
    
    user_agent = models.TextField(
        blank=True,
        help_text="User agent string"
    )
    
    session_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Session identifier"
    )
    
    # Details
    details = JSONField(
        default=dict,
        blank=True,
        help_text="Additional action details"
    )
    
    # For tracking changes
    old_values = JSONField(
        default=dict,
        blank=True,
        help_text="Previous values (for updates)"
    )
    
    new_values = JSONField(
        default=dict,
        blank=True,
        help_text="New values (for updates)"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('success', 'Success'),
            ('failure', 'Failure'),
            ('partial', 'Partial Success'),
        ],
        default='success',
        help_text="Action status"
    )
    
    error_message = models.TextField(
        blank=True,
        help_text="Error message if action failed"
    )
    
    # Performance
    duration_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Action duration in milliseconds"
    )
    
    # Grouping for bulk operations
    batch_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Batch identifier for bulk operations"
    )
    
    class Meta:
        verbose_name = "Document Audit Log"
        verbose_name_plural = "Document Audit Logs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document', '-created_at']),
            models.Index(fields=['folder', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
            models.Index(fields=['session_id', '-created_at']),
            models.Index(fields=['batch_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        target = self.document or self.folder
        return f"{self.action} - {target} - {self.user}"
    
    @classmethod
    def log(cls, action, user=None, document=None, folder=None, **kwargs):
        """Create an audit log entry."""
        # Extract request information if available
        request = kwargs.pop('request', None)
        if request:
            kwargs.setdefault('ip_address', cls.get_client_ip(request))
            kwargs.setdefault('user_agent', request.META.get('HTTP_USER_AGENT', ''))
            kwargs.setdefault('session_id', request.session.session_key)
        
        return cls.objects.create(
            action=action,
            user=user,
            document=document,
            folder=folder,
            **kwargs
        )
    
    @staticmethod
    def get_client_ip(request):
        """Extract client IP from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    @classmethod
    def log_document_access(cls, document, user, action='viewed', **kwargs):
        """Log document access."""
        return cls.log(
            action=action,
            user=user,
            document=document,
            details={
                'document_name': document.name,
                'document_size': document.size,
                'document_type': document.file_extension,
            },
            **kwargs
        )
    
    @classmethod
    def log_permission_change(cls, permission, action='permission_granted', **kwargs):
        """Log permission change."""
        details = {
            'permission_type': permission.permission,
            'target_user': permission.user.username if permission.user else None,
            'target_group': permission.group.name if permission.group else None,
            'expires_at': permission.expires_at.isoformat() if permission.expires_at else None,
        }
        
        document = getattr(permission, 'document', None)
        folder = getattr(permission, 'folder', None)
        
        return cls.log(
            action=action,
            user=permission.granted_by,
            document=document,
            folder=folder,
            details=details,
            **kwargs
        )
    
    @classmethod
    def log_bulk_operation(cls, action, user, documents=None, folders=None, batch_id=None, **kwargs):
        """Log bulk operation."""
        logs = []
        
        if documents:
            for document in documents:
                logs.append(cls.log(
                    action=action,
                    user=user,
                    document=document,
                    batch_id=batch_id,
                    **kwargs
                ))
        
        if folders:
            for folder in folders:
                logs.append(cls.log(
                    action=action,
                    user=user,
                    folder=folder,
                    batch_id=batch_id,
                    **kwargs
                ))
        
        return logs
    
    def get_target(self):
        """Get the target object (document or folder)."""
        return self.document or self.folder
    
    def get_target_name(self):
        """Get the name of the target object."""
        target = self.get_target()
        return target.name if target else 'Unknown'
    
    def get_changes(self):
        """Get a human-readable summary of changes."""
        if not self.old_values or not self.new_values:
            return []
        
        changes = []
        for field, old_value in self.old_values.items():
            new_value = self.new_values.get(field)
            if old_value != new_value:
                changes.append({
                    'field': field,
                    'old': old_value,
                    'new': new_value
                })
        
        return changes