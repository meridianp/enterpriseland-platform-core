"""Folder models for hierarchical document organization."""

from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from mptt.models import MPTTModel, TreeForeignKey
from .base import DocumentBaseModel


class Folder(MPTTModel, DocumentBaseModel):
    """Hierarchical folder structure for organizing documents."""
    
    name = models.CharField(
        max_length=255,
        help_text="Folder name"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Folder description"
    )
    
    parent = TreeForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        help_text="Parent folder"
    )
    
    path = models.CharField(
        max_length=1000,
        blank=True,
        db_index=True,
        help_text="Full path from root"
    )
    
    is_system = models.BooleanField(
        default=False,
        help_text="System folder that cannot be deleted"
    )
    
    color = models.CharField(
        max_length=7,
        blank=True,
        help_text="Folder color for UI (hex format)"
    )
    
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="Icon identifier for UI"
    )
    
    # Metadata
    document_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of documents in this folder"
    )
    
    total_size = models.BigIntegerField(
        default=0,
        help_text="Total size of documents in bytes"
    )
    
    # Settings
    inherit_permissions = models.BooleanField(
        default=True,
        help_text="Inherit permissions from parent folder"
    )
    
    default_retention_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Default retention period for documents in days"
    )
    
    class MPTTMeta:
        order_insertion_by = ['name']
    
    class Meta:
        verbose_name = "Folder"
        verbose_name_plural = "Folders"
        unique_together = [['parent', 'name', 'group']]
        indexes = [
            models.Index(fields=['path', 'group']),
            models.Index(fields=['parent', 'name']),
        ]
        permissions = [
            ('manage_system_folders', 'Can manage system folders'),
        ]
    
    def __str__(self):
        return self.path or self.name
    
    def clean(self):
        """Validate folder data."""
        super().clean()
        
        # Check for circular reference
        if self.parent and self.parent.pk == self.pk:
            raise ValidationError(_("A folder cannot be its own parent"))
        
        # Check for duplicate names in same parent
        if self.parent:
            siblings = Folder.objects.filter(
                parent=self.parent,
                name=self.name,
                group=self.group
            ).exclude(pk=self.pk)
            if siblings.exists():
                raise ValidationError(
                    _("A folder with this name already exists in the parent folder")
                )
    
    def save(self, *args, **kwargs):
        """Save folder and update path."""
        # Update path
        if self.parent:
            self.path = f"{self.parent.path}/{self.name}"
        else:
            self.path = f"/{self.name}"
        
        super().save(*args, **kwargs)
        
        # Update paths of all descendants
        if self.pk:
            for child in self.get_descendants():
                child.save(update_fields=['path'])
    
    def get_absolute_path(self):
        """Get the full path from root."""
        return self.path
    
    def get_ancestors_with_self(self):
        """Get all ancestors including self."""
        return self.get_ancestors(include_self=True)
    
    def get_document_count_recursive(self):
        """Get total document count including subfolders."""
        count = self.document_count
        for child in self.get_descendants():
            count += child.document_count
        return count
    
    def get_total_size_recursive(self):
        """Get total size including subfolders."""
        size = self.total_size
        for child in self.get_descendants():
            size += child.total_size
        return size
    
    def update_statistics(self):
        """Update document count and total size."""
        from .document import Document
        
        documents = Document.objects.filter(folder=self, is_deleted=False)
        self.document_count = documents.count()
        self.total_size = documents.aggregate(
            total=models.Sum('size')
        )['total'] or 0
        self.save(update_fields=['document_count', 'total_size'])
    
    def can_delete(self):
        """Check if folder can be deleted."""
        if self.is_system:
            return False
        if self.get_document_count_recursive() > 0:
            return False
        return True
    
    def move_to(self, new_parent):
        """Move folder to a new parent."""
        if new_parent and new_parent.is_descendant_of(self):
            raise ValidationError(
                _("Cannot move a folder to one of its descendants")
            )
        
        self.parent = new_parent
        self.save()
    
    @classmethod
    def get_or_create_user_root(cls, user, group):
        """Get or create user's root folder."""
        folder, created = cls.objects.get_or_create(
            name=f"user_{user.id}",
            group=group,
            parent=None,
            defaults={
                'description': f"Personal folder for {user.get_full_name()}",
                'is_system': True,
                'created_by': user,
            }
        )
        return folder
    
    @classmethod
    def get_or_create_shared_root(cls, group):
        """Get or create shared root folder."""
        folder, created = cls.objects.get_or_create(
            name="Shared",
            group=group,
            parent=None,
            defaults={
                'description': "Shared documents",
                'is_system': True,
            }
        )
        return folder