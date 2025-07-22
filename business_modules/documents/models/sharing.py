"""Document sharing models."""

import secrets
from datetime import timedelta
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
from .base import TimestampedModel
from .document import Document
from .folder import Folder

User = get_user_model()


class SharedLink(TimestampedModel):
    """Shareable links for documents and folders."""
    
    # Unique token for the link
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Unique token for the shared link"
    )
    
    # What is being shared
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_links',
        help_text="Shared document"
    )
    
    folder = models.ForeignKey(
        Folder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_links',
        help_text="Shared folder"
    )
    
    # Sharing settings
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_shared_links',
        help_text="User who created the link"
    )
    
    title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional title for the shared link"
    )
    
    message = models.TextField(
        blank=True,
        help_text="Optional message to recipients"
    )
    
    # Permissions
    allow_view = models.BooleanField(
        default=True,
        help_text="Allow viewing"
    )
    
    allow_download = models.BooleanField(
        default=False,
        help_text="Allow downloading"
    )
    
    allow_edit = models.BooleanField(
        default=False,
        help_text="Allow editing (for authenticated users only)"
    )
    
    require_authentication = models.BooleanField(
        default=False,
        help_text="Require authentication to access"
    )
    
    allowed_emails = ArrayField(
        models.EmailField(),
        blank=True,
        default=list,
        help_text="List of allowed email addresses (if authentication required)"
    )
    
    # Access control
    password = models.CharField(
        max_length=128,
        blank=True,
        help_text="Optional password protection (hashed)"
    )
    
    max_downloads = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of downloads allowed"
    )
    
    max_views = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of views allowed"
    )
    
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the link expires"
    )
    
    # Usage tracking
    view_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times viewed"
    )
    
    download_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times downloaded"
    )
    
    last_accessed = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last access time"
    )
    
    last_accessed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accessed_shared_links',
        help_text="Last user who accessed (if authenticated)"
    )
    
    # Status
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether link is active"
    )
    
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When link was revoked"
    )
    
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revoked_shared_links',
        help_text="User who revoked the link"
    )
    
    revoke_reason = models.TextField(
        blank=True,
        help_text="Reason for revoking"
    )
    
    class Meta:
        verbose_name = "Shared Link"
        verbose_name_plural = "Shared Links"
        indexes = [
            models.Index(fields=['token', 'is_active']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['created_by', '-created_at']),
        ]
    
    def __str__(self):
        if self.document:
            return f"Share: {self.document.name}"
        elif self.folder:
            return f"Share: {self.folder.name}"
        return f"Share: {self.token[:8]}..."
    
    def save(self, *args, **kwargs):
        """Generate token on creation."""
        if not self.token:
            self.token = self.generate_token()
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_token():
        """Generate a secure random token."""
        return secrets.urlsafe_token_hex(32)
    
    def clean(self):
        """Validate shared link data."""
        super().clean()
        
        # Ensure either document or folder is set, but not both
        if not self.document and not self.folder:
            raise ValidationError("Either document or folder must be specified")
        
        if self.document and self.folder:
            raise ValidationError("Cannot share both document and folder")
        
        # Edit permission requires authentication
        if self.allow_edit and not self.require_authentication:
            raise ValidationError("Edit permission requires authentication")
    
    def is_valid(self):
        """Check if link is still valid."""
        if not self.is_active:
            return False
        
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        
        if self.max_views and self.view_count >= self.max_views:
            return False
        
        if self.max_downloads and self.download_count >= self.max_downloads:
            return False
        
        return True
    
    def can_access(self, user=None, email=None):
        """Check if user/email can access the shared content."""
        if not self.is_valid():
            return False
        
        if self.require_authentication:
            if not user or not user.is_authenticated:
                return False
            
            if self.allowed_emails:
                user_email = email or user.email
                if user_email not in self.allowed_emails:
                    return False
        
        return True
    
    def record_access(self, user=None, is_download=False):
        """Record an access to the shared link."""
        self.view_count += 1
        if is_download:
            self.download_count += 1
        
        self.last_accessed = timezone.now()
        if user and user.is_authenticated:
            self.last_accessed_by = user
        
        self.save(update_fields=[
            'view_count', 'download_count', 
            'last_accessed', 'last_accessed_by'
        ])
        
        # Also update the document/folder statistics
        if self.document:
            if is_download:
                self.document.increment_download_count()
            else:
                self.document.increment_view_count()
    
    def revoke(self, user, reason=''):
        """Revoke the shared link."""
        self.is_active = False
        self.revoked_at = timezone.now()
        self.revoked_by = user
        self.revoke_reason = reason
        self.save(update_fields=[
            'is_active', 'revoked_at', 'revoked_by', 'revoke_reason'
        ])
    
    def get_absolute_url(self):
        """Get the full URL for the shared link."""
        from django.urls import reverse
        return reverse('documents:shared-link', args=[self.token])
    
    @classmethod
    def create_for_document(cls, document, user, days=30, **kwargs):
        """Create a shared link for a document."""
        expires_at = timezone.now() + timedelta(days=days) if days else None
        
        return cls.objects.create(
            document=document,
            created_by=user,
            expires_at=expires_at,
            **kwargs
        )
    
    @classmethod
    def create_for_folder(cls, folder, user, days=30, **kwargs):
        """Create a shared link for a folder."""
        expires_at = timezone.now() + timedelta(days=days) if days else None
        
        return cls.objects.create(
            folder=folder,
            created_by=user,
            expires_at=expires_at,
            **kwargs
        )