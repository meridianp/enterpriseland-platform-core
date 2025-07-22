"""
Generic file models for platform-wide file management.
"""
import uuid
import os
from typing import Optional, Dict, Any
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from platform_core.core.models import TimestampedModel


def generate_upload_path(instance, filename):
    """
    Generate a secure upload path for files.
    
    Format: {app_label}/{model_name}/{object_id}/{timestamp}_{filename}
    """
    if instance.content_object:
        app_label = instance.content_type.app_label
        model_name = instance.content_type.model
        object_id = instance.object_id
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        
        # Ensure filename is safe
        safe_filename = os.path.basename(filename)
        
        return f"{app_label}/{model_name}/{object_id}/{timestamp}_{safe_filename}"
    else:
        # Fallback for unattached files
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        return f"unattached/{instance.id}/{timestamp}_{filename}"


class FileQuerySet(models.QuerySet):
    """Custom QuerySet for File with specialized filtering."""
    
    def for_object(self, obj):
        """Get files for a specific object."""
        content_type = ContentType.objects.get_for_model(obj)
        return self.filter(
            content_type=content_type,
            object_id=obj.pk
        )
    
    def by_category(self, category: str):
        """Filter files by category."""
        return self.filter(category=category)
    
    def recent(self, days: int = 7):
        """Get recently uploaded files."""
        cutoff = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff)
    
    def by_uploader(self, user):
        """Get files uploaded by a specific user."""
        return self.filter(uploaded_by=user)


class FileManager(models.Manager):
    """Custom manager for File model."""
    
    def get_queryset(self):
        return FileQuerySet(self.model, using=self._db)
    
    def for_object(self, obj):
        """Get files for a specific object."""
        return self.get_queryset().for_object(obj)


class File(TimestampedModel):
    """
    Generic file attachment that can be associated with any model.
    
    Uses GenericForeignKey to allow attachment to any model instance.
    """
    
    class Category(models.TextChoices):
        """File categories - modules can extend this."""
        DOCUMENT = 'document', 'Document'
        IMAGE = 'image', 'Image'
        VIDEO = 'video', 'Video'
        AUDIO = 'audio', 'Audio'
        ARCHIVE = 'archive', 'Archive'
        DATA = 'data', 'Data File'
        OTHER = 'other', 'Other'
    
    # Primary fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # File data
    file = models.FileField(
        upload_to=generate_upload_path,
        max_length=500,
        help_text="The actual file"
    )
    filename = models.CharField(
        max_length=255,
        help_text="Original filename"
    )
    file_size = models.BigIntegerField(
        help_text="File size in bytes"
    )
    content_type = models.CharField(
        max_length=100,
        help_text="MIME type of the file"
    )
    
    # Storage information
    storage_backend = models.CharField(
        max_length=50,
        default='default',
        help_text="Storage backend used (e.g., 'default', 's3', 'azure')"
    )
    storage_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Full path in storage backend"
    )
    
    # Generic relation to any model
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.UUIDField(
        null=True,
        blank=True
    )
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Metadata
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='uploaded_files',
        help_text="User who uploaded the file"
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of the file"
    )
    category = models.CharField(
        max_length=50,
        choices=Category.choices,
        default=Category.OTHER,
        help_text="File category"
    )
    
    # Security
    is_public = models.BooleanField(
        default=False,
        help_text="Whether this file is publicly accessible"
    )
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='accessible_files',
        help_text="Users who can access this file"
    )
    
    # Versioning
    version = models.IntegerField(
        default=1,
        help_text="Version number"
    )
    parent_file = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='versions',
        help_text="Parent file if this is a version"
    )
    
    # Additional metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata as JSON"
    )
    
    # Virus scanning
    virus_scanned = models.BooleanField(
        default=False,
        help_text="Whether virus scanning has been performed"
    )
    virus_scan_result = models.CharField(
        max_length=50,
        blank=True,
        help_text="Result of virus scan"
    )
    virus_scanned_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When virus scan was performed"
    )
    
    objects = FileManager()
    
    class Meta:
        db_table = 'platform_files'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['uploaded_by', '-created_at']),
            models.Index(fields=['category', '-created_at']),
            models.Index(fields=['is_public']),
        ]
    
    def __str__(self):
        return self.filename
    
    def clean(self):
        """Validate the model."""
        super().clean()
        
        # Validate file size limits
        max_size = getattr(settings, 'MAX_FILE_SIZE', 100 * 1024 * 1024)  # 100MB default
        if self.file_size > max_size:
            raise ValidationError(f"File size exceeds maximum allowed size of {max_size} bytes")
    
    @property
    def file_size_display(self) -> str:
        """Human-readable file size."""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    
    @property
    def is_image(self) -> bool:
        """Check if file is an image."""
        return self.content_type.startswith('image/')
    
    @property
    def is_document(self) -> bool:
        """Check if file is a document."""
        doc_types = ['application/pdf', 'application/msword', 
                     'application/vnd.openxmlformats-officedocument']
        return any(self.content_type.startswith(t) for t in doc_types)
    
    def has_access(self, user) -> bool:
        """Check if user has access to this file."""
        if self.is_public:
            return True
        
        if user == self.uploaded_by:
            return True
        
        if user in self.allowed_users.all():
            return True
        
        # Check object-level permissions if attached to an object
        if self.content_object and hasattr(self.content_object, 'has_access'):
            return self.content_object.has_access(user)
        
        return False
    
    def get_download_url(self, expiration_seconds: int = 3600) -> str:
        """
        Generate a temporary download URL.
        
        This should be overridden based on storage backend.
        """
        # For S3, this would generate a presigned URL
        # For local storage, this might generate a token-based URL
        # Default implementation just returns the file URL
        return self.file.url
    
    def create_version(self, new_file, user, description: str = "") -> 'File':
        """Create a new version of this file."""
        new_version = File.objects.create(
            file=new_file,
            filename=self.filename,
            file_size=new_file.size,
            content_type=self.content_type,
            content_object=self.content_object,
            uploaded_by=user,
            description=description or f"Version {self.version + 1}",
            category=self.category,
            parent_file=self.parent_file or self,
            version=self.version + 1,
            metadata={**self.metadata, 'previous_version': str(self.id)}
        )
        
        # Copy access permissions
        new_version.allowed_users.set(self.allowed_users.all())
        
        return new_version
    
    def delete(self, *args, **kwargs):
        """Override delete to handle file cleanup."""
        # Store file path before deletion
        file_path = self.file.path if self.file else None
        
        # Delete model instance
        super().delete(*args, **kwargs)
        
        # Delete actual file if it exists
        if file_path and os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError:
                # Log error but don't fail the deletion
                pass


class FileAccessLog(models.Model):
    """Track file access for audit purposes."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.ForeignKey(
        File,
        on_delete=models.CASCADE,
        related_name='access_logs'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    
    # Access details
    action = models.CharField(
        max_length=50,
        choices=[
            ('view', 'View'),
            ('download', 'Download'),
            ('share', 'Share'),
            ('delete', 'Delete'),
        ]
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Additional context
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'platform_file_access_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['file', '-timestamp']),
            models.Index(fields=['user', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.user} {self.action} {self.file} at {self.timestamp}"