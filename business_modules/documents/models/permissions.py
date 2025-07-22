"""Permission models for documents and folders."""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .base import TimestampedModel
from .document import Document
from .folder import Folder

User = get_user_model()


class BasePermission(TimestampedModel):
    """Base permission model."""
    
    PERMISSION_CHOICES = [
        ('view', 'View'),
        ('download', 'Download'),
        ('edit', 'Edit'),
        ('delete', 'Delete'),
        ('share', 'Share'),
        ('manage', 'Manage Permissions'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="User with permission"
    )
    
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Group with permission"
    )
    
    permission = models.CharField(
        max_length=20,
        choices=PERMISSION_CHOICES,
        help_text="Permission type"
    )
    
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='%(class)s_granted',
        help_text="User who granted permission"
    )
    
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When permission expires"
    )
    
    is_inherited = models.BooleanField(
        default=False,
        help_text="Whether permission is inherited from parent"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Permission notes"
    )
    
    class Meta:
        abstract = True
    
    def clean(self):
        """Validate permission data."""
        super().clean()
        
        # Ensure either user or group is set, but not both
        if not self.user and not self.group:
            raise ValidationError(_("Either user or group must be specified"))
        
        if self.user and self.group:
            raise ValidationError(_("Cannot specify both user and group"))
    
    def is_active(self):
        """Check if permission is currently active."""
        if self.expires_at:
            from django.utils import timezone
            return timezone.now() < self.expires_at
        return True
    
    def has_permission(self, requested_permission):
        """Check if this permission grants the requested permission."""
        permission_hierarchy = {
            'view': ['view'],
            'download': ['view', 'download'],
            'edit': ['view', 'download', 'edit'],
            'delete': ['view', 'download', 'edit', 'delete'],
            'share': ['view', 'download', 'share'],
            'manage': ['view', 'download', 'edit', 'delete', 'share', 'manage'],
        }
        
        return requested_permission in permission_hierarchy.get(self.permission, [])


class DocumentPermission(BasePermission):
    """Document-specific permissions."""
    
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='permissions',
        help_text="Document this permission applies to"
    )
    
    class Meta:
        verbose_name = "Document Permission"
        verbose_name_plural = "Document Permissions"
        unique_together = [
            ['document', 'user', 'permission'],
            ['document', 'group', 'permission'],
        ]
        indexes = [
            models.Index(fields=['document', 'user']),
            models.Index(fields=['document', 'group']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        target = self.user or self.group
        return f"{target} - {self.permission} - {self.document}"


class FolderPermission(BasePermission):
    """Folder-specific permissions."""
    
    folder = models.ForeignKey(
        Folder,
        on_delete=models.CASCADE,
        related_name='permissions',
        help_text="Folder this permission applies to"
    )
    
    apply_to_subfolders = models.BooleanField(
        default=True,
        help_text="Apply permission to all subfolders"
    )
    
    apply_to_documents = models.BooleanField(
        default=True,
        help_text="Apply permission to all documents in folder"
    )
    
    class Meta:
        verbose_name = "Folder Permission"
        verbose_name_plural = "Folder Permissions"
        unique_together = [
            ['folder', 'user', 'permission'],
            ['folder', 'group', 'permission'],
        ]
        indexes = [
            models.Index(fields=['folder', 'user']),
            models.Index(fields=['folder', 'group']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        target = self.user or self.group
        return f"{target} - {self.permission} - {self.folder}"
    
    def propagate_to_children(self):
        """Propagate permissions to child folders and documents."""
        if self.apply_to_subfolders:
            for child_folder in self.folder.get_descendants():
                FolderPermission.objects.update_or_create(
                    folder=child_folder,
                    user=self.user,
                    group=self.group,
                    permission=self.permission,
                    defaults={
                        'granted_by': self.granted_by,
                        'expires_at': self.expires_at,
                        'is_inherited': True,
                        'apply_to_subfolders': self.apply_to_subfolders,
                        'apply_to_documents': self.apply_to_documents,
                    }
                )
        
        if self.apply_to_documents:
            # Apply to documents in this folder
            for document in self.folder.documents.filter(is_deleted=False):
                DocumentPermission.objects.update_or_create(
                    document=document,
                    user=self.user,
                    group=self.group,
                    permission=self.permission,
                    defaults={
                        'granted_by': self.granted_by,
                        'expires_at': self.expires_at,
                        'is_inherited': True,
                    }
                )
            
            # Apply to documents in subfolders if applicable
            if self.apply_to_subfolders:
                for child_folder in self.folder.get_descendants():
                    for document in child_folder.documents.filter(is_deleted=False):
                        DocumentPermission.objects.update_or_create(
                            document=document,
                            user=self.user,
                            group=self.group,
                            permission=self.permission,
                            defaults={
                                'granted_by': self.granted_by,
                                'expires_at': self.expires_at,
                                'is_inherited': True,
                            }
                        )