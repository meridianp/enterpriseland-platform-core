"""
Base managers for the platform.

These managers provide automatic filtering and other common functionality.
"""

from django.db import models
from django.db.models import Q
from django.contrib.auth.models import AnonymousUser


class GroupFilteredQuerySet(models.QuerySet):
    """
    Custom QuerySet that automatically filters by group for multi-tenancy.
    """
    
    def for_user(self, user):
        """Filter queryset based on user's group membership."""
        if not user or isinstance(user, AnonymousUser):
            return self.none()
        
        if user.is_superuser:
            # Superusers can see all records
            return self
        
        # Filter by user's group
        if hasattr(user, 'group') and user.group:
            return self.filter(group=user.group)
        
        return self.none()
    
    def for_group(self, group):
        """Filter queryset for a specific group."""
        if not group:
            return self.none()
        return self.filter(group=group)


class GroupFilteredManager(models.Manager):
    """
    Custom manager that automatically filters queries by group.
    
    This manager should be used as the default manager for all models
    that inherit from GroupFilteredModel.
    """
    
    def get_queryset(self):
        """Return the custom queryset."""
        return GroupFilteredQuerySet(self.model, using=self._db)
    
    def for_user(self, user):
        """Convenience method to filter by user."""
        return self.get_queryset().for_user(user)
    
    def for_group(self, group):
        """Convenience method to filter by group."""
        return self.get_queryset().for_group(group)


class SoftDeleteQuerySet(models.QuerySet):
    """
    Custom QuerySet that excludes soft-deleted records by default.
    """
    
    def active(self):
        """Return only non-deleted records."""
        return self.filter(deleted_at__isnull=True)
    
    def deleted(self):
        """Return only deleted records."""
        return self.filter(deleted_at__isnull=False)
    
    def with_deleted(self):
        """Return all records including deleted ones."""
        return self.all()


class SoftDeleteManager(models.Manager):
    """
    Manager that excludes soft-deleted records by default.
    """
    
    def get_queryset(self):
        """Return only active records by default."""
        return SoftDeleteQuerySet(self.model, using=self._db).active()
    
    def deleted(self):
        """Return only deleted records."""
        return SoftDeleteQuerySet(self.model, using=self._db).deleted()
    
    def with_deleted(self):
        """Return all records including deleted ones."""
        return SoftDeleteQuerySet(self.model, using=self._db).with_deleted()


class VersionedQuerySet(models.QuerySet):
    """
    Custom QuerySet for versioned models.
    """
    
    def current(self):
        """Return only current versions."""
        return self.filter(is_current=True)
    
    def versions_of(self, obj_id):
        """Return all versions of a specific object."""
        return self.filter(id=obj_id).order_by('-version')
    
    def at_version(self, obj_id, version):
        """Return a specific version of an object."""
        return self.filter(id=obj_id, version=version).first()


class VersionedManager(models.Manager):
    """
    Manager for versioned models that returns current versions by default.
    """
    
    def get_queryset(self):
        """Return only current versions by default."""
        return VersionedQuerySet(self.model, using=self._db).current()
    
    def versions_of(self, obj_id):
        """Return all versions of a specific object."""
        return VersionedQuerySet(self.model, using=self._db).versions_of(obj_id)
    
    def at_version(self, obj_id, version):
        """Return a specific version of an object."""
        return VersionedQuerySet(self.model, using=self._db).at_version(obj_id, version)