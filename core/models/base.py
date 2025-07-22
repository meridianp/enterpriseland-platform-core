"""
Base models for the platform.

These abstract models provide common functionality that can be inherited
by models in both the platform core and business modules.

This integrates the existing base models from the monolithic structure
to ensure backward compatibility during migration.
"""

import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError


class UUIDModel(models.Model):
    """
    Abstract model that uses UUID as primary key instead of auto-incrementing integer.
    
    This provides better security and allows for distributed ID generation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    """
    Abstract model that provides created and updated timestamp fields.
    
    These fields are automatically managed and provide audit trail capabilities.
    """
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    
    class Meta:
        abstract = True
        ordering = ['-created_at']


class GroupFilteredModel(UUIDModel, TimestampedModel):
    """
    Abstract model that provides automatic group-based filtering for multi-tenancy.
    
    All models that inherit from this will automatically be filtered by the
    user's group, ensuring data isolation between tenants.
    
    This model integrates functionality from the existing assessments.base_models
    to ensure backward compatibility.
    """
    group = models.ForeignKey(
        'accounts.Group',
        on_delete=models.CASCADE,
        related_name='%(app_label)s_%(class)s_set',
        help_text="The tenant group this object belongs to",
        db_index=True
    )
    
    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['group', 'created_at']),
            models.Index(fields=['group']),  # Single field index for compatibility
        ]
    
    def __init_subclass__(cls, **kwargs):
        """
        Set up the custom manager when a model inherits from GroupFilteredModel.
        This ensures backward compatibility with existing code.
        """
        super().__init_subclass__(**kwargs)
        
        # Only set up manager for concrete models (not abstract ones)
        if not cls._meta.abstract:
            # Import here to avoid circular imports
            from platform_core.core.managers import GroupFilteredManager
            cls.add_to_class('objects', GroupFilteredManager())
    
    def save(self, *args, **kwargs):
        """
        Override save to ensure group is set and validate permissions.
        
        This combines functionality from both the new and legacy implementations.
        """
        # Validate that group is set
        if not self.group_id:
            # Try to get from request context (new implementation)
            if hasattr(self, '_request'):
                user = getattr(self._request, 'user', None)
                if user and hasattr(user, 'group'):
                    self.group = user.group
            
            # If still no group, raise error (legacy behavior)
            if not self.group_id:
                raise ValidationError("Group must be set for all GroupFilteredModel instances")
        
        # Call parent save
        super().save(*args, **kwargs)
        
        # Invalidate related caches if using cached manager (legacy behavior)
        if hasattr(self.__class__.objects, '_invalidate_related_caches'):
            self.__class__.objects._invalidate_related_caches(self)
    
    def delete(self, *args, **kwargs):
        """
        Override delete to handle cache invalidation.
        Maintains backward compatibility with legacy caching behavior.
        """
        # Store values before deletion for cache invalidation
        group_id = self.group_id
        instance_id = self.id
        
        # Call parent delete
        result = super().delete(*args, **kwargs)
        
        # Invalidate related caches if using cached manager
        if hasattr(self.__class__.objects, '_invalidate_related_caches'):
            # Create a temporary object for cache invalidation
            temp_instance = self.__class__(id=instance_id, group_id=group_id)
            self.__class__.objects._invalidate_related_caches(temp_instance)
        
        return result


class SoftDeleteModel(models.Model):
    """
    Abstract model that provides soft delete functionality.
    
    Instead of actually deleting records, this marks them as deleted
    and excludes them from default queries.
    """
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_deleted_set'
    )
    
    class Meta:
        abstract = True
    
    def delete(self, using=None, keep_parents=False):
        """Mark the record as deleted instead of actually deleting it."""
        self.deleted_at = timezone.now()
        self.save(using=using)
    
    def hard_delete(self, using=None, keep_parents=False):
        """Actually delete the record from the database."""
        super().delete(using=using, keep_parents=keep_parents)
    
    def restore(self):
        """Restore a soft-deleted record."""
        self.deleted_at = None
        self.deleted_by = None
        self.save()


class VersionedModel(models.Model):
    """
    Abstract model that provides versioning capabilities.
    
    Useful for tracking changes to important business objects over time.
    """
    version = models.IntegerField(default=1)
    version_created_at = models.DateTimeField(auto_now_add=True)
    version_created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_versions_created'
    )
    is_current = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['is_current', 'version']),
        ]
    
    def create_new_version(self, user=None):
        """Create a new version of this object."""
        # Mark current version as not current
        self.__class__.objects.filter(
            id=self.id,
            is_current=True
        ).update(is_current=False)
        
        # Create new version
        self.pk = None  # Force creation of new record
        self.version += 1
        self.version_created_at = timezone.now()
        self.version_created_by = user
        self.is_current = True
        self.save()
        
        return self