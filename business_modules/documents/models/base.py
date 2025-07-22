"""Base models for document management."""

from django.db import models
from django.contrib.auth import get_user_model
from core.models import BaseModel, GroupFilteredModel

User = get_user_model()


class DocumentBaseModel(GroupFilteredModel):
    """Base model for all document-related models."""
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='%(app_label)s_%(class)s_created',
        help_text="User who created this item"
    )
    
    modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='%(app_label)s_%(class)s_modified',
        help_text="User who last modified this item"
    )
    
    class Meta:
        abstract = True
        
    def save(self, *args, **kwargs):
        """Override save to track modifications."""
        user = kwargs.pop('user', None)
        if user:
            if not self.pk:
                self.created_by = user
            self.modified_by = user
        super().save(*args, **kwargs)


class TimestampedModel(models.Model):
    """Abstract model with timestamp fields."""
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this item was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this item was last updated"
    )
    
    class Meta:
        abstract = True