"""Document models."""

import os
import hashlib
from django.db import models
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from .base import DocumentBaseModel, TimestampedModel
from .folder import Folder


class Document(DocumentBaseModel):
    """Main document model."""
    
    # Basic Information
    name = models.CharField(
        max_length=255,
        help_text="Document name"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Document description"
    )
    
    folder = models.ForeignKey(
        Folder,
        on_delete=models.PROTECT,
        related_name='documents',
        null=True,
        blank=True,
        help_text="Parent folder"
    )
    
    # File Information
    file_path = models.CharField(
        max_length=1000,
        help_text="Path to file in storage backend"
    )
    
    file_name = models.CharField(
        max_length=255,
        help_text="Original file name"
    )
    
    file_extension = models.CharField(
        max_length=10,
        db_index=True,
        help_text="File extension"
    )
    
    mime_type = models.CharField(
        max_length=100,
        help_text="MIME type"
    )
    
    size = models.BigIntegerField(
        help_text="File size in bytes"
    )
    
    checksum = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA256 checksum"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('archived', 'Archived'),
            ('deleted', 'Deleted'),
        ],
        default='active',
        db_index=True,
        help_text="Document status"
    )
    
    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Soft delete flag"
    )
    
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When document was deleted"
    )
    
    # Versioning
    version_number = models.PositiveIntegerField(
        default=1,
        help_text="Current version number"
    )
    
    is_locked = models.BooleanField(
        default=False,
        help_text="Prevent modifications"
    )
    
    locked_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='locked_documents',
        help_text="User who locked the document"
    )
    
    locked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When document was locked"
    )
    
    # Metadata
    tags = ArrayField(
        models.CharField(max_length=50),
        blank=True,
        default=list,
        help_text="Document tags"
    )
    
    category = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text="Document category"
    )
    
    language = models.CharField(
        max_length=10,
        default='en',
        help_text="Document language code"
    )
    
    # Search
    search_vector = SearchVectorField(
        null=True,
        help_text="Full-text search vector"
    )
    
    content_extracted = models.BooleanField(
        default=False,
        help_text="Whether content has been extracted for search"
    )
    
    # Security
    is_encrypted = models.BooleanField(
        default=False,
        help_text="Whether file is encrypted at rest"
    )
    
    encryption_key_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Encryption key identifier"
    )
    
    # Processing Status
    virus_scanned = models.BooleanField(
        default=False,
        help_text="Whether virus scan completed"
    )
    
    virus_scan_result = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('clean', 'Clean'),
            ('infected', 'Infected'),
            ('error', 'Scan Error'),
        ],
        help_text="Virus scan result"
    )
    
    preview_generated = models.BooleanField(
        default=False,
        help_text="Whether preview has been generated"
    )
    
    preview_path = models.CharField(
        max_length=1000,
        blank=True,
        help_text="Path to preview file"
    )
    
    ocr_processed = models.BooleanField(
        default=False,
        help_text="Whether OCR has been performed"
    )
    
    ocr_text = models.TextField(
        blank=True,
        help_text="Extracted OCR text"
    )
    
    # Retention
    retention_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Date after which document can be deleted"
    )
    
    # Analytics
    download_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of downloads"
    )
    
    view_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of views"
    )
    
    last_accessed = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last access time"
    )
    
    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        indexes = [
            models.Index(fields=['folder', 'name']),
            models.Index(fields=['status', 'is_deleted']),
            models.Index(fields=['file_extension', 'mime_type']),
            models.Index(fields=['category', 'created_at']),
            models.Index(fields=['retention_date']),
            GinIndex(fields=['search_vector']),
            GinIndex(fields=['tags']),
        ]
        permissions = [
            ('download_document', 'Can download documents'),
            ('lock_document', 'Can lock documents'),
            ('view_document_history', 'Can view document history'),
        ]
    
    def __str__(self):
        return self.name
    
    def clean(self):
        """Validate document data."""
        super().clean()
        
        # Extract file extension
        if self.file_name:
            _, ext = os.path.splitext(self.file_name)
            self.file_extension = ext.lower().lstrip('.')
    
    def save(self, *args, **kwargs):
        """Save document and update folder statistics."""
        is_new = not self.pk
        old_folder = None
        
        if not is_new:
            old_doc = Document.objects.get(pk=self.pk)
            old_folder = old_doc.folder
        
        super().save(*args, **kwargs)
        
        # Update folder statistics
        if is_new and self.folder:
            self.folder.update_statistics()
        elif not is_new and old_folder != self.folder:
            if old_folder:
                old_folder.update_statistics()
            if self.folder:
                self.folder.update_statistics()
    
    def get_absolute_path(self):
        """Get full path including folder hierarchy."""
        if self.folder:
            return f"{self.folder.get_absolute_path()}/{self.name}"
        return f"/{self.name}"
    
    def calculate_checksum(self, file_content):
        """Calculate SHA256 checksum of file content."""
        sha256_hash = hashlib.sha256()
        sha256_hash.update(file_content)
        return sha256_hash.hexdigest()
    
    def lock(self, user):
        """Lock document for editing."""
        if self.is_locked and self.locked_by != user:
            raise ValueError(f"Document is already locked by {self.locked_by}")
        
        self.is_locked = True
        self.locked_by = user
        self.locked_at = models.functions.Now()
        self.save(update_fields=['is_locked', 'locked_by', 'locked_at'])
    
    def unlock(self, user=None):
        """Unlock document."""
        if user and self.locked_by != user:
            raise ValueError("Only the user who locked the document can unlock it")
        
        self.is_locked = False
        self.locked_by = None
        self.locked_at = None
        self.save(update_fields=['is_locked', 'locked_by', 'locked_at'])
    
    def soft_delete(self, user=None):
        """Soft delete document."""
        self.is_deleted = True
        self.status = 'deleted'
        self.deleted_at = models.functions.Now()
        if user:
            self.modified_by = user
        self.save()
        
        # Update folder statistics
        if self.folder:
            self.folder.update_statistics()
    
    def restore(self, user=None):
        """Restore soft deleted document."""
        self.is_deleted = False
        self.status = 'active'
        self.deleted_at = None
        if user:
            self.modified_by = user
        self.save()
        
        # Update folder statistics
        if self.folder:
            self.folder.update_statistics()
    
    def increment_download_count(self):
        """Increment download counter."""
        self.download_count = models.F('download_count') + 1
        self.last_accessed = models.functions.Now()
        self.save(update_fields=['download_count', 'last_accessed'])
    
    def increment_view_count(self):
        """Increment view counter."""
        self.view_count = models.F('view_count') + 1
        self.last_accessed = models.functions.Now()
        self.save(update_fields=['view_count', 'last_accessed'])


class DocumentVersion(TimestampedModel):
    """Document version tracking."""
    
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='versions',
        help_text="Parent document"
    )
    
    version_number = models.PositiveIntegerField(
        help_text="Version number"
    )
    
    file_path = models.CharField(
        max_length=1000,
        help_text="Path to version file"
    )
    
    size = models.BigIntegerField(
        help_text="File size in bytes"
    )
    
    checksum = models.CharField(
        max_length=64,
        help_text="SHA256 checksum"
    )
    
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        help_text="User who created this version"
    )
    
    comment = models.TextField(
        blank=True,
        help_text="Version comment"
    )
    
    changes_summary = models.JSONField(
        default=dict,
        blank=True,
        help_text="Summary of changes from previous version"
    )
    
    is_major_version = models.BooleanField(
        default=False,
        help_text="Whether this is a major version"
    )
    
    class Meta:
        verbose_name = "Document Version"
        verbose_name_plural = "Document Versions"
        unique_together = [['document', 'version_number']]
        ordering = ['-version_number']
        indexes = [
            models.Index(fields=['document', '-version_number']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.document.name} v{self.version_number}"
    
    def restore(self):
        """Restore this version as the current version."""
        # Create a new version from current
        current_version = DocumentVersion.objects.create(
            document=self.document,
            version_number=self.document.version_number + 1,
            file_path=self.document.file_path,
            size=self.document.size,
            checksum=self.document.checksum,
            created_by=self.created_by,
            comment=f"Restored from version {self.version_number}"
        )
        
        # Update document with this version's data
        self.document.file_path = self.file_path
        self.document.size = self.size
        self.document.checksum = self.checksum
        self.document.version_number = current_version.version_number
        self.document.save()
        
        return current_version


class DocumentTag(models.Model):
    """Predefined document tags."""
    
    name = models.CharField(
        max_length=50,
        unique=True,
        help_text="Tag name"
    )
    
    description = models.CharField(
        max_length=200,
        blank=True,
        help_text="Tag description"
    )
    
    color = models.CharField(
        max_length=7,
        default='#000000',
        help_text="Tag color (hex format)"
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether tag is active"
    )
    
    usage_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of documents using this tag"
    )
    
    class Meta:
        verbose_name = "Document Tag"
        verbose_name_plural = "Document Tags"
        ordering = ['name']
    
    def __str__(self):
        return self.name