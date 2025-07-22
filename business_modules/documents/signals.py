"""Signal handlers for document management."""

from django.db.models.signals import post_save, pre_delete, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from .models import Document, Folder, DocumentPermission, FolderPermission


@receiver(post_save, sender=Document)
def handle_document_save(sender, instance, created, **kwargs):
    """Handle document save signal."""
    if created:
        # Clear permission cache for the user who created it
        if instance.created_by:
            cache_pattern = f"accessible_docs:{instance.created_by.id}"
            cache.delete(cache_pattern)
        
        # Update folder statistics
        if instance.folder:
            instance.folder.update_statistics()


@receiver(pre_delete, sender=Document)
def handle_document_pre_delete(sender, instance, **kwargs):
    """Handle document pre-delete signal."""
    # Store folder reference for post-delete
    instance._folder_to_update = instance.folder


@receiver(post_delete, sender=Document)
def handle_document_delete(sender, instance, **kwargs):
    """Handle document delete signal."""
    # Update folder statistics
    if hasattr(instance, '_folder_to_update') and instance._folder_to_update:
        instance._folder_to_update.update_statistics()
    
    # Clear permission caches
    cache.delete_pattern("accessible_docs:*")


@receiver(post_save, sender=Folder)
def handle_folder_save(sender, instance, created, **kwargs):
    """Handle folder save signal."""
    if created:
        # Clear permission cache for the user who created it
        if instance.created_by:
            cache_pattern = f"accessible_docs:{instance.created_by.id}"
            cache.delete(cache_pattern)


@receiver([post_save, post_delete], sender=DocumentPermission)
def handle_document_permission_change(sender, instance, **kwargs):
    """Handle document permission changes."""
    # Clear permission cache for affected user
    if instance.user:
        cache.delete_pattern(f"*:{instance.user.id}:*")
        cache.delete(f"accessible_docs:{instance.user.id}")
    
    # Clear for all users in group
    if instance.group:
        for user in instance.group.user_set.all():
            cache.delete_pattern(f"*:{user.id}:*")
            cache.delete(f"accessible_docs:{user.id}")


@receiver([post_save, post_delete], sender=FolderPermission)
def handle_folder_permission_change(sender, instance, **kwargs):
    """Handle folder permission changes."""
    # Clear permission cache for affected user
    if instance.user:
        cache.delete_pattern(f"*:{instance.user.id}:*")
        cache.delete(f"accessible_docs:{instance.user.id}")
    
    # Clear for all users in group
    if instance.group:
        for user in instance.group.user_set.all():
            cache.delete_pattern(f"*:{user.id}:*")
            cache.delete(f"accessible_docs:{user.id}")