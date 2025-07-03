"""
Cache Signal Handlers

Automatic cache invalidation based on model signals.
"""

import logging
from typing import List, Optional
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.core.cache import cache
from django.dispatch import receiver
from django.conf import settings

from .cache import cache_manager

logger = logging.getLogger(__name__)


# Model-based cache invalidation

def invalidate_model_cache(sender, instance, **kwargs):
    """
    Invalidate cache entries related to a model instance.
    
    This is a generic handler that can be connected to any model.
    """
    model_name = sender.__name__.lower()
    app_label = sender._meta.app_label
    
    # Invalidate by model tags
    tags = [
        f"model:{app_label}.{model_name}",
        f"pk:{app_label}.{model_name}:{instance.pk}",
    ]
    
    # Add custom tags from model
    if hasattr(instance, 'get_cache_tags'):
        tags.extend(instance.get_cache_tags())
    
    # Invalidate all tags
    for tag in tags:
        count = cache_manager.invalidate_tag(tag)
        if count > 0:
            logger.debug(f"Invalidated {count} cache entries for tag: {tag}")


def invalidate_related_cache(sender, instance, **kwargs):
    """
    Invalidate cache for related models.
    
    This handles foreign key and many-to-many relationships.
    """
    model_name = sender.__name__.lower()
    app_label = sender._meta.app_label
    
    # Check for related fields
    for field in sender._meta.get_fields():
        if field.is_relation:
            related_model = field.related_model
            if related_model:
                related_name = related_model.__name__.lower()
                related_app = related_model._meta.app_label
                
                # Invalidate related model cache
                tag = f"related:{related_app}.{related_name}"
                count = cache_manager.invalidate_tag(tag)
                if count > 0:
                    logger.debug(
                        f"Invalidated {count} related cache entries for {tag}"
                    )


# Specific model handlers

@receiver(post_save)
def handle_model_save(sender, instance, created, **kwargs):
    """Handle model save for cache invalidation."""
    # Skip if cache invalidation is disabled
    if not getattr(settings, 'CACHE_INVALIDATE_ON_SAVE', True):
        return
    
    # Skip for models that opt out
    if hasattr(sender, 'cache_invalidate_on_save'):
        if not sender.cache_invalidate_on_save:
            return
    
    invalidate_model_cache(sender, instance, **kwargs)
    
    # Invalidate list views on create
    if created:
        model_name = sender.__name__.lower()
        app_label = sender._meta.app_label
        list_tag = f"list:{app_label}.{model_name}"
        cache_manager.invalidate_tag(list_tag)


@receiver(post_delete)
def handle_model_delete(sender, instance, **kwargs):
    """Handle model delete for cache invalidation."""
    # Skip if cache invalidation is disabled
    if not getattr(settings, 'CACHE_INVALIDATE_ON_DELETE', True):
        return
    
    invalidate_model_cache(sender, instance, **kwargs)
    
    # Invalidate list views
    model_name = sender.__name__.lower()
    app_label = sender._meta.app_label
    list_tag = f"list:{app_label}.{model_name}"
    cache_manager.invalidate_tag(list_tag)


@receiver(m2m_changed)
def handle_m2m_change(sender, instance, action, pk_set, **kwargs):
    """Handle many-to-many changes for cache invalidation."""
    # Skip if cache invalidation is disabled
    if not getattr(settings, 'CACHE_INVALIDATE_ON_M2M', True):
        return
    
    # Only invalidate on add/remove/clear
    if action in ['post_add', 'post_remove', 'post_clear']:
        # Get the models involved
        model = instance.__class__
        model_name = model.__name__.lower()
        app_label = model._meta.app_label
        
        # Invalidate the instance
        invalidate_model_cache(model, instance, **kwargs)
        
        # Invalidate related objects
        if pk_set:
            through_model = sender
            
            # Find the other model in the relationship
            for field in through_model._meta.get_fields():
                if field.related_model and field.related_model != model:
                    related_model = field.related_model
                    related_name = related_model.__name__.lower()
                    related_app = related_model._meta.app_label
                    
                    # Invalidate each related object
                    for pk in pk_set:
                        tag = f"pk:{related_app}.{related_name}:{pk}"
                        cache_manager.invalidate_tag(tag)


# Custom cache invalidation signals

def register_cache_invalidation(model_class, tags: Optional[List[str]] = None):
    """
    Register a model for automatic cache invalidation.
    
    Args:
        model_class: The model class to register
        tags: Additional tags to invalidate
    """
    def invalidate_handler(sender, instance, **kwargs):
        # Standard invalidation
        invalidate_model_cache(sender, instance, **kwargs)
        
        # Additional tags
        if tags:
            for tag in tags:
                cache_manager.invalidate_tag(tag)
    
    # Connect to signals
    post_save.connect(invalidate_handler, sender=model_class, weak=False)
    post_delete.connect(invalidate_handler, sender=model_class, weak=False)
    
    logger.info(f"Registered cache invalidation for {model_class.__name__}")


# Cache warming signals

def warm_cache_on_save(sender, instance, created, **kwargs):
    """
    Warm cache after model save.
    
    This can be connected to specific models that benefit from cache warming.
    """
    # Only warm cache for updates, not creates
    if not created and hasattr(instance, 'warm_cache'):
        from .warming import cache_warmer
        
        try:
            # Model-specific warming
            instance.warm_cache()
        except Exception as e:
            logger.error(f"Error warming cache for {instance}: {e}")


# Utility functions

def connect_cache_signals():
    """
    Connect cache invalidation signals for configured models.
    
    This should be called during app initialization.
    """
    # Get models from settings
    invalidate_models = getattr(settings, 'CACHE_INVALIDATE_MODELS', {})
    
    for model_path, config in invalidate_models.items():
        try:
            # Import model
            app_label, model_name = model_path.rsplit('.', 1)
            model_module = __import__(app_label, fromlist=[model_name])
            model_class = getattr(model_module, model_name)
            
            # Register invalidation
            tags = config.get('tags', [])
            register_cache_invalidation(model_class, tags)
            
            # Register warming if configured
            if config.get('warm_on_save', False):
                post_save.connect(
                    warm_cache_on_save,
                    sender=model_class,
                    weak=False
                )
                
        except Exception as e:
            logger.error(f"Error connecting cache signals for {model_path}: {e}")


# Call this when the app is ready
# This is done in apps.py ready() method