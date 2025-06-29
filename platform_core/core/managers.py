"""
Custom Django managers for EnterpriseLand platform.

Provides consistent multi-tenancy, caching, and security functionality
across all models in the platform.
"""

import logging
import hashlib
from typing import Optional, Any, Dict, List, Union
from django.db import models, transaction
from django.core.cache import cache
from django.core.exceptions import ValidationError, PermissionDenied
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import QuerySet, Q
from accounts.models import Group

User = get_user_model()
logger = logging.getLogger(__name__)


class GroupFilteredQuerySet(models.QuerySet):
    """
    Custom QuerySet that automatically filters by group for multi-tenancy.
    
    Provides consistent row-level security across all models that inherit
    from GroupFilteredModel.
    """
    
    def for_group(self, group: Union[Group, str]) -> 'GroupFilteredQuerySet':
        """
        Filter queryset to only include records for the specified group.
        
        Args:
            group: Group instance or group UUID string
            
        Returns:
            Filtered queryset
        """
        if isinstance(group, str):
            return self.filter(group_id=group)
        return self.filter(group=group)
    
    def for_user(self, user: User) -> 'GroupFilteredQuerySet':
        """
        Filter queryset to only include records accessible to the user.
        
        Args:
            user: User instance
            
        Returns:
            Filtered queryset based on user's group memberships
        """
        if not user or not user.is_authenticated:
            return self.none()
        
        # Super users can see all records
        if user.is_superuser:
            return self
        
        # Filter by user's groups
        user_groups = user.groups.all()
        if not user_groups.exists():
            return self.none()
        
        return self.filter(group__in=user_groups)
    
    def accessible_to(self, user: User) -> 'GroupFilteredQuerySet':
        """
        Alias for for_user() for backward compatibility.
        """
        return self.for_user(user)
    
    def with_audit_trail(self) -> 'GroupFilteredQuerySet':
        """
        Include audit trail information in the queryset.
        
        Returns:
            Queryset with audit fields selected
        """
        return self.select_related('created_by', 'last_modified_by')
    
    def recent(self, days: int = 30) -> 'GroupFilteredQuerySet':
        """
        Filter to records created or modified in the last N days.
        
        Args:
            days: Number of days to look back
            
        Returns:
            Filtered queryset
        """
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        return self.filter(
            Q(created_at__gte=cutoff_date) |
            Q(updated_at__gte=cutoff_date)
        )
    
    def by_status(self, status: str) -> 'GroupFilteredQuerySet':
        """
        Filter by status field if the model has one.
        
        Args:
            status: Status value to filter by
            
        Returns:
            Filtered queryset
        """
        # Check if the model has a status field
        if hasattr(self.model, 'status'):
            return self.filter(status=status)
        return self
    
    def active(self) -> 'GroupFilteredQuerySet':
        """
        Filter to active records (if model has is_active field).
        
        Returns:
            Filtered queryset
        """
        if hasattr(self.model, 'is_active'):
            return self.filter(is_active=True)
        return self
    
    def with_performance_metrics(self) -> 'GroupFilteredQuerySet':
        """
        Add performance annotations for monitoring.
        
        Returns:
            Queryset with performance annotations
        """
        from django.db.models import Count, Avg, Max
        
        return self.annotate(
            record_count=Count('id'),
            avg_created_time=Avg('created_at'),
            last_updated=Max('updated_at')
        )


class GroupFilteredManager(models.Manager):
    """
    Custom manager for GroupFilteredModel that provides consistent multi-tenancy.
    
    Features:
    - Automatic group filtering
    - Caching support
    - Audit logging
    - Performance monitoring
    - Security enforcement
    """
    
    def get_queryset(self) -> GroupFilteredQuerySet:
        """
        Return the custom queryset for this manager.
        """
        return GroupFilteredQuerySet(self.model, using=self._db)
    
    def for_group(self, group: Union[Group, str]) -> GroupFilteredQuerySet:
        """
        Get all records for a specific group.
        
        Args:
            group: Group instance or group UUID string
            
        Returns:
            Filtered queryset
        """
        return self.get_queryset().for_group(group)
    
    def for_user(self, user: User) -> GroupFilteredQuerySet:
        """
        Get all records accessible to a specific user.
        
        Args:
            user: User instance
            
        Returns:
            Filtered queryset
        """
        return self.get_queryset().for_user(user)
    
    def accessible_to(self, user: User) -> GroupFilteredQuerySet:
        """
        Alias for for_user() for backward compatibility.
        """
        return self.for_user(user)
    
    def create_for_group(self, group: Union[Group, str], **kwargs) -> models.Model:
        """
        Create a new record for a specific group.
        
        Args:
            group: Group instance or group UUID string
            **kwargs: Model field values
            
        Returns:
            Created model instance
        """
        if isinstance(group, str):
            try:
                group = Group.objects.get(id=group)
            except Group.DoesNotExist:
                raise ValidationError(f"Group with ID {group} does not exist")
        
        kwargs['group'] = group
        instance = self.create(**kwargs)
        
        # Log creation
        logger.info(
            f"Created {self.model.__name__} {instance.id} for group {group.id}",
            extra={
                'model': self.model.__name__,
                'instance_id': str(instance.id),
                'group_id': str(group.id),
                'action': 'create'
            }
        )
        
        return instance
    
    def create_for_user(self, user: User, **kwargs) -> models.Model:
        """
        Create a new record for a user's primary group.
        
        Args:
            user: User instance
            **kwargs: Model field values
            
        Returns:
            Created model instance
            
        Raises:
            ValidationError: If user has no groups or multiple groups
        """
        if not user or not user.is_authenticated:
            raise PermissionDenied("User must be authenticated")
        
        user_groups = user.groups.all()
        if not user_groups.exists():
            raise ValidationError("User must belong to at least one group")
        
        # Use the first group if multiple exist
        group = user_groups.first()
        
        # Add audit fields if model supports them
        if hasattr(self.model, 'created_by'):
            kwargs['created_by'] = user
        
        return self.create_for_group(group, **kwargs)
    
    def get_cached(self, cache_key: str, timeout: int = 300, **filter_kwargs) -> Optional[models.Model]:
        """
        Get a single record with caching support.
        
        Args:
            cache_key: Cache key for the record
            timeout: Cache timeout in seconds
            **filter_kwargs: Filter arguments
            
        Returns:
            Model instance or None
        """
        # Try cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        try:
            instance = self.get(**filter_kwargs)
            cache.set(cache_key, instance, timeout)
            return instance
        except self.model.DoesNotExist:
            # Cache the fact that the record doesn't exist
            cache.set(cache_key, None, timeout)
            return None
    
    def filter_cached(self, cache_key: str, timeout: int = 300, **filter_kwargs) -> List[models.Model]:
        """
        Filter records with caching support.
        
        Args:
            cache_key: Cache key for the result set
            timeout: Cache timeout in seconds
            **filter_kwargs: Filter arguments
            
        Returns:
            List of model instances
        """
        # Try cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        instances = list(self.filter(**filter_kwargs))
        cache.set(cache_key, instances, timeout)
        return instances
    
    def invalidate_cache(self, cache_pattern: str) -> None:
        """
        Invalidate cache entries matching a pattern.
        
        Args:
            cache_pattern: Pattern to match cache keys
        """
        # This is a simplified implementation
        # In production, you might want to use a more sophisticated cache invalidation
        # strategy with Redis or Memcached pattern matching
        pass
    
    def bulk_create_for_group(self, group: Union[Group, str], objs: List[Dict[str, Any]], batch_size: int = 1000) -> List[models.Model]:
        """
        Bulk create records for a specific group.
        
        Args:
            group: Group instance or group UUID string
            objs: List of dictionaries with model field values
            batch_size: Number of records to create per batch
            
        Returns:
            List of created model instances
        """
        if isinstance(group, str):
            try:
                group = Group.objects.get(id=group)
            except Group.DoesNotExist:
                raise ValidationError(f"Group with ID {group} does not exist")
        
        # Add group to all objects
        for obj in objs:
            obj['group'] = group
        
        # Create model instances
        instances = [self.model(**obj) for obj in objs]
        
        # Bulk create with transaction
        with transaction.atomic():
            created_instances = self.bulk_create(instances, batch_size=batch_size)
        
        # Log bulk creation
        logger.info(
            f"Bulk created {len(created_instances)} {self.model.__name__} records for group {group.id}",
            extra={
                'model': self.model.__name__,
                'count': len(created_instances),
                'group_id': str(group.id),
                'action': 'bulk_create'
            }
        )
        
        return created_instances
    
    def get_statistics(self, group: Optional[Union[Group, str]] = None) -> Dict[str, Any]:
        """
        Get statistics about records in this manager.
        
        Args:
            group: Optional group to filter statistics
            
        Returns:
            Dictionary with statistics
        """
        queryset = self.get_queryset()
        
        if group:
            queryset = queryset.for_group(group)
        
        stats = {
            'total_count': queryset.count(),
            'recent_count': queryset.recent(7).count(),
            'active_count': queryset.active().count() if hasattr(self.model, 'is_active') else None,
        }
        
        # Add status breakdown if model has status field
        if hasattr(self.model, 'status'):
            from django.db.models import Count
            status_breakdown = queryset.values('status').annotate(count=Count('id'))
            stats['status_breakdown'] = {item['status']: item['count'] for item in status_breakdown}
        
        return stats
    
    def cleanup_old_records(self, days: int = 365, group: Optional[Union[Group, str]] = None) -> int:
        """
        Clean up old records (soft delete or hard delete based on model).
        
        Args:
            days: Records older than this many days will be cleaned up
            group: Optional group to filter cleanup
            
        Returns:
            Number of records cleaned up
        """
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        queryset = self.get_queryset().filter(created_at__lt=cutoff_date)
        
        if group:
            queryset = queryset.for_group(group)
        
        # If model has soft delete, use that; otherwise hard delete
        if hasattr(self.model, 'is_active'):
            count = queryset.update(is_active=False, updated_at=timezone.now())
            action = 'soft_delete'
        else:
            count = queryset.count()
            queryset.delete()
            action = 'hard_delete'
        
        # Log cleanup
        logger.info(
            f"Cleaned up {count} old {self.model.__name__} records",
            extra={
                'model': self.model.__name__,
                'count': count,
                'days': days,
                'action': action,
                'group_id': str(group) if group else None
            }
        )
        
        return count


class CachedGroupFilteredManager(GroupFilteredManager):
    """
    Extended manager with enhanced caching capabilities.
    
    Automatically caches frequently accessed records and provides
    cache invalidation hooks.
    """
    
    def __init__(self, cache_timeout: int = 300):
        super().__init__()
        self.cache_timeout = cache_timeout
    
    def _get_cache_key(self, prefix: str, **kwargs) -> str:
        """
        Generate a cache key for the given parameters.
        
        Args:
            prefix: Cache key prefix
            **kwargs: Parameters to include in the key
            
        Returns:
            Generated cache key
        """
        key_parts = [prefix, self.model.__name__]
        
        # Sort kwargs for consistent key generation
        for key, value in sorted(kwargs.items()):
            key_parts.append(f"{key}:{value}")
        
        key_string = ":".join(str(part) for part in key_parts)
        
        # Hash long keys to avoid cache key length limits
        if len(key_string) > 200:
            key_string = hashlib.md5(key_string.encode()).hexdigest()
        
        return key_string
    
    def get(self, **kwargs) -> models.Model:
        """
        Get a single record with automatic caching.
        """
        cache_key = self._get_cache_key("get", **kwargs)
        return self.get_cached(cache_key, self.cache_timeout, **kwargs)
    
    def filter(self, **kwargs) -> GroupFilteredQuerySet:
        """
        Filter records with caching for small result sets.
        """
        # Only cache small, commonly accessed filters
        if len(kwargs) == 1 and any(key in kwargs for key in ['id', 'status', 'is_active']):
            cache_key = self._get_cache_key("filter", **kwargs)
            cached_result = cache.get(cache_key)
            
            if cached_result is not None:
                # Return a queryset-like object from cached results
                return self.get_queryset().filter(id__in=[obj.id for obj in cached_result])
        
        return super().filter(**kwargs)
    
    def create(self, **kwargs) -> models.Model:
        """
        Create a record and invalidate related caches.
        """
        instance = super().create(**kwargs)
        
        # Invalidate related caches
        self._invalidate_related_caches(instance)
        
        return instance
    
    def _invalidate_related_caches(self, instance: models.Model) -> None:
        """
        Invalidate caches related to the given instance.
        
        Args:
            instance: Model instance that was created/updated/deleted
        """
        # Basic implementation - in production you might want more sophisticated invalidation
        cache_patterns = [
            f"get:{self.model.__name__}:id:{instance.id}",
            f"filter:{self.model.__name__}:group:{instance.group_id}",
        ]
        
        for pattern in cache_patterns:
            cache.delete(pattern)
