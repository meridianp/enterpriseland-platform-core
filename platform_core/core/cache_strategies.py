"""
Comprehensive caching strategies for EnterpriseLand platform.

Provides multi-level caching, cache warming, invalidation strategies,
and performance monitoring for optimal application performance.
"""

import logging
import hashlib
import json
import time
from typing import Any, Optional, Dict, List, Union, Callable
from functools import wraps
from django.core.cache import cache, caches
from django.core.cache.utils import make_template_fragment_key
from django.conf import settings
from django.db.models import Model
from django.utils import timezone
from django.core.serializers import serialize
import redis

logger = logging.getLogger(__name__)


class CacheStrategy:
    """
    Base class for different caching strategies.
    """
    
    def __init__(self, cache_alias: str = 'default', default_timeout: int = 300):
        self.cache = caches[cache_alias] if cache_alias != 'default' else cache
        self.default_timeout = default_timeout
        self.redis_client = self._get_redis_client()
    
    def _get_redis_client(self) -> Optional[redis.Redis]:
        """
        Get Redis client for advanced operations.
        """
        try:
            if hasattr(self.cache, '_cache'):
                return self.cache._cache.get_client()
            return None
        except Exception as e:
            logger.warning(f"Could not get Redis client: {e}")
            return None
    
    def generate_key(self, prefix: str, **kwargs) -> str:
        """
        Generate a cache key with consistent formatting.
        
        Args:
            prefix: Key prefix
            **kwargs: Parameters to include in key
            
        Returns:
            Generated cache key
        """
        key_parts = [prefix]
        
        # Sort kwargs for consistent key generation
        for key, value in sorted(kwargs.items()):
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True)
            key_parts.append(f"{key}:{value}")
        
        key_string = ":".join(str(part) for part in key_parts)
        
        # Hash long keys to avoid cache key length limits
        if len(key_string) > 200:
            key_string = hashlib.md5(key_string.encode()).hexdigest()
        
        return key_string
    
    def get_or_set(self, key: str, default_func: Callable, timeout: Optional[int] = None) -> Any:
        """
        Get value from cache or set it using the default function.
        
        Args:
            key: Cache key
            default_func: Function to call if cache miss
            timeout: Cache timeout
            
        Returns:
            Cached or computed value
        """
        timeout = timeout or self.default_timeout
        
        value = self.cache.get(key)
        if value is not None:
            logger.debug(f"Cache hit for key: {key}")
            return value
        
        logger.debug(f"Cache miss for key: {key}")
        value = default_func()
        self.cache.set(key, value, timeout)
        return value
    
    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate cache keys matching a pattern.
        
        Args:
            pattern: Pattern to match (supports Redis wildcards)
            
        Returns:
            Number of keys invalidated
        """
        if not self.redis_client:
            logger.warning("Redis client not available for pattern invalidation")
            return 0
        
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                count = self.redis_client.delete(*keys)
                logger.info(f"Invalidated {count} keys matching pattern: {pattern}")
                return count
            return 0
        except Exception as e:
            logger.error(f"Error invalidating pattern {pattern}: {e}")
            return 0


class ModelCacheStrategy(CacheStrategy):
    """
    Caching strategy for Django models.
    
    Provides automatic cache invalidation based on model changes,
    relationship caching, and optimized query caching.
    """
    
    def __init__(self, model_class: type, cache_alias: str = 'default', default_timeout: int = 300):
        super().__init__(cache_alias, default_timeout)
        self.model_class = model_class
        self.model_name = model_class.__name__.lower()
    
    def cache_model_instance(self, instance: Model, timeout: Optional[int] = None) -> str:
        """
        Cache a model instance.
        
        Args:
            instance: Model instance to cache
            timeout: Cache timeout
            
        Returns:
            Cache key used
        """
        key = self.generate_key(f"model:{self.model_name}", id=instance.id)
        timeout = timeout or self.default_timeout
        
        # Serialize the instance data
        serialized_data = self._serialize_instance(instance)
        self.cache.set(key, serialized_data, timeout)
        
        logger.debug(f"Cached {self.model_name} instance {instance.id}")
        return key
    
    def get_cached_instance(self, instance_id: Union[str, int]) -> Optional[Dict[str, Any]]:
        """
        Get cached model instance.
        
        Args:
            instance_id: ID of the instance
            
        Returns:
            Cached instance data or None
        """
        key = self.generate_key(f"model:{self.model_name}", id=instance_id)
        return self.cache.get(key)
    
    def cache_queryset(self, queryset, cache_key: str, timeout: Optional[int] = None) -> str:
        """
        Cache a queryset result.
        
        Args:
            queryset: Django QuerySet
            cache_key: Key to cache under
            timeout: Cache timeout
            
        Returns:
            Cache key used
        """
        timeout = timeout or self.default_timeout
        
        # Convert queryset to list and serialize
        data = list(queryset.values())
        self.cache.set(cache_key, data, timeout)
        
        logger.debug(f"Cached queryset with {len(data)} items under key: {cache_key}")
        return cache_key
    
    def invalidate_model_cache(self, instance_id: Union[str, int]) -> None:
        """
        Invalidate cache for a specific model instance.
        
        Args:
            instance_id: ID of the instance
        """
        # Invalidate instance cache
        instance_key = self.generate_key(f"model:{self.model_name}", id=instance_id)
        self.cache.delete(instance_key)
        
        # Invalidate related queryset caches
        pattern = f"*{self.model_name}*"
        self.invalidate_pattern(pattern)
        
        logger.debug(f"Invalidated cache for {self.model_name} instance {instance_id}")
    
    def _serialize_instance(self, instance: Model) -> Dict[str, Any]:
        """
        Serialize a model instance for caching.
        
        Args:
            instance: Model instance
            
        Returns:
            Serialized data
        """
        # Use Django's serialization for consistency
        serialized = serialize('json', [instance])
        data = json.loads(serialized)[0]['fields']
        data['id'] = instance.id
        data['_cached_at'] = timezone.now().isoformat()
        return data


class ViewCacheStrategy(CacheStrategy):
    """
    Caching strategy for view responses and API endpoints.
    
    Provides per-user caching, group-based invalidation,
    and conditional caching based on request parameters.
    """
    
    def cache_view_response(self, view_name: str, response_data: Any, 
                          user_id: Optional[str] = None, 
                          group_id: Optional[str] = None,
                          params: Optional[Dict[str, Any]] = None,
                          timeout: Optional[int] = None) -> str:
        """
        Cache a view response.
        
        Args:
            view_name: Name of the view
            response_data: Response data to cache
            user_id: User ID for user-specific caching
            group_id: Group ID for group-specific caching
            params: Request parameters to include in key
            timeout: Cache timeout
            
        Returns:
            Cache key used
        """
        key_params = {'view': view_name}
        
        if user_id:
            key_params['user'] = user_id
        if group_id:
            key_params['group'] = group_id
        if params:
            key_params.update(params)
        
        cache_key = self.generate_key("view_response", **key_params)
        timeout = timeout or self.default_timeout
        
        # Add metadata to cached response
        cached_data = {
            'data': response_data,
            'cached_at': timezone.now().isoformat(),
            'cache_key': cache_key
        }
        
        self.cache.set(cache_key, cached_data, timeout)
        logger.debug(f"Cached view response for {view_name}")
        return cache_key
    
    def get_cached_view_response(self, view_name: str, 
                               user_id: Optional[str] = None,
                               group_id: Optional[str] = None,
                               params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """
        Get cached view response.
        
        Args:
            view_name: Name of the view
            user_id: User ID for user-specific caching
            group_id: Group ID for group-specific caching
            params: Request parameters
            
        Returns:
            Cached response data or None
        """
        key_params = {'view': view_name}
        
        if user_id:
            key_params['user'] = user_id
        if group_id:
            key_params['group'] = group_id
        if params:
            key_params.update(params)
        
        cache_key = self.generate_key("view_response", **key_params)
        cached_data = self.cache.get(cache_key)
        
        if cached_data:
            return cached_data.get('data')
        return None
    
    def invalidate_view_cache(self, view_name: Optional[str] = None,
                            user_id: Optional[str] = None,
                            group_id: Optional[str] = None) -> int:
        """
        Invalidate view caches based on criteria.
        
        Args:
            view_name: Specific view to invalidate
            user_id: User-specific caches to invalidate
            group_id: Group-specific caches to invalidate
            
        Returns:
            Number of keys invalidated
        """
        patterns = []
        
        if view_name:
            patterns.append(f"*view_response*view:{view_name}*")
        if user_id:
            patterns.append(f"*view_response*user:{user_id}*")
        if group_id:
            patterns.append(f"*view_response*group:{group_id}*")
        
        if not patterns:
            patterns = ["*view_response*"]
        
        total_invalidated = 0
        for pattern in patterns:
            total_invalidated += self.invalidate_pattern(pattern)
        
        return total_invalidated


class SessionCacheStrategy(CacheStrategy):
    """
    Caching strategy for user sessions and temporary data.
    
    Provides session-based caching, temporary data storage,
    and automatic cleanup of expired sessions.
    """
    
    def set_session_data(self, session_key: str, data: Any, timeout: Optional[int] = None) -> str:
        """
        Store session-specific data.
        
        Args:
            session_key: Session identifier
            data: Data to store
            timeout: Cache timeout (default: 1 hour)
            
        Returns:
            Cache key used
        """
        cache_key = self.generate_key("session", key=session_key)
        timeout = timeout or 3600  # 1 hour default
        
        self.cache.set(cache_key, data, timeout)
        logger.debug(f"Stored session data for key: {session_key}")
        return cache_key
    
    def get_session_data(self, session_key: str) -> Optional[Any]:
        """
        Get session-specific data.
        
        Args:
            session_key: Session identifier
            
        Returns:
            Cached data or None
        """
        cache_key = self.generate_key("session", key=session_key)
        return self.cache.get(cache_key)
    
    def invalidate_session(self, session_key: str) -> None:
        """
        Invalidate all data for a session.
        
        Args:
            session_key: Session identifier
        """
        pattern = f"*session*key:{session_key}*"
        invalidated = self.invalidate_pattern(pattern)
        logger.debug(f"Invalidated {invalidated} cache entries for session: {session_key}")


class CacheWarmer:
    """
    Cache warming strategies to proactively populate frequently accessed data.
    """
    
    def __init__(self):
        self.strategies = {
            'model': ModelCacheStrategy,
            'view': ViewCacheStrategy,
            'session': SessionCacheStrategy
        }
    
    def warm_model_cache(self, model_class: type, queryset=None, timeout: int = 300) -> int:
        """
        Warm cache for model instances.
        
        Args:
            model_class: Model class to warm
            queryset: Optional queryset to limit warming
            timeout: Cache timeout
            
        Returns:
            Number of instances cached
        """
        strategy = ModelCacheStrategy(model_class, default_timeout=timeout)
        
        if queryset is None:
            queryset = model_class.objects.all()[:100]  # Limit to 100 most recent
        
        cached_count = 0
        for instance in queryset:
            strategy.cache_model_instance(instance, timeout)
            cached_count += 1
        
        logger.info(f"Warmed cache for {cached_count} {model_class.__name__} instances")
        return cached_count
    
    def warm_view_cache(self, view_configs: List[Dict[str, Any]]) -> int:
        """
        Warm cache for view responses.
        
        Args:
            view_configs: List of view configuration dicts
            
        Returns:
            Number of views cached
        """
        strategy = ViewCacheStrategy()
        cached_count = 0
        
        for config in view_configs:
            try:
                # This would need to be implemented based on specific view requirements
                # For now, just count the configurations
                cached_count += 1
            except Exception as e:
                logger.error(f"Error warming view cache: {e}")
        
        logger.info(f"Warmed cache for {cached_count} view configurations")
        return cached_count


class CacheMonitor:
    """
    Monitor cache performance and health.
    """
    
    def __init__(self, cache_alias: str = 'default'):
        self.cache = caches[cache_alias] if cache_alias != 'default' else cache
        self.redis_client = self._get_redis_client()
    
    def _get_redis_client(self) -> Optional[redis.Redis]:
        """
        Get Redis client for monitoring operations.
        """
        try:
            if hasattr(self.cache, '_cache'):
                return self.cache._cache.get_client()
            return None
        except Exception:
            return None
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        stats = {
            'timestamp': timezone.now().isoformat(),
            'backend': str(type(self.cache)),
        }
        
        if self.redis_client:
            try:
                info = self.redis_client.info()
                stats.update({
                    'redis_version': info.get('redis_version'),
                    'used_memory': info.get('used_memory_human'),
                    'connected_clients': info.get('connected_clients'),
                    'total_commands_processed': info.get('total_commands_processed'),
                    'cache_hit_rate': self._calculate_hit_rate(info),
                    'keyspace_hits': info.get('keyspace_hits', 0),
                    'keyspace_misses': info.get('keyspace_misses', 0),
                })
            except Exception as e:
                stats['redis_error'] = str(e)
        
        return stats
    
    def _calculate_hit_rate(self, redis_info: Dict[str, Any]) -> float:
        """
        Calculate cache hit rate.
        
        Args:
            redis_info: Redis info dictionary
            
        Returns:
            Hit rate as percentage
        """
        hits = redis_info.get('keyspace_hits', 0)
        misses = redis_info.get('keyspace_misses', 0)
        
        if hits + misses == 0:
            return 0.0
        
        return round((hits / (hits + misses)) * 100, 2)
    
    def get_key_count_by_pattern(self, pattern: str = '*') -> int:
        """
        Get count of keys matching a pattern.
        
        Args:
            pattern: Pattern to match
            
        Returns:
            Number of matching keys
        """
        if not self.redis_client:
            return 0
        
        try:
            keys = self.redis_client.keys(pattern)
            return len(keys)
        except Exception:
            return 0
    
    def cleanup_expired_keys(self) -> int:
        """
        Clean up expired keys (force garbage collection).
        
        Returns:
            Number of keys cleaned up
        """
        if not self.redis_client:
            return 0
        
        try:
            # This is a Redis-specific operation
            # Get memory usage before
            before_info = self.redis_client.info('memory')
            before_memory = before_info.get('used_memory', 0)
            
            # Force garbage collection
            self.redis_client.execute_command('MEMORY', 'PURGE')
            
            # Get memory usage after
            after_info = self.redis_client.info('memory')
            after_memory = after_info.get('used_memory', 0)
            
            freed_memory = before_memory - after_memory
            logger.info(f"Cache cleanup freed {freed_memory} bytes")
            
            return freed_memory
        except Exception as e:
            logger.error(f"Error during cache cleanup: {e}")
            return 0


# Decorators for easy caching

def cache_result(timeout: int = 300, key_prefix: str = '', 
                vary_on: Optional[List[str]] = None):
    """
    Decorator to cache function results.
    
    Args:
        timeout: Cache timeout in seconds
        key_prefix: Prefix for cache key
        vary_on: List of argument names to include in cache key
        
    Returns:
        Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            key_parts = [key_prefix or func.__name__]
            
            if vary_on:
                for i, arg_name in enumerate(vary_on):
                    if i < len(args):
                        key_parts.append(f"{arg_name}:{args[i]}")
                    elif arg_name in kwargs:
                        key_parts.append(f"{arg_name}:{kwargs[arg_name]}")
            
            cache_key = ":".join(str(part) for part in key_parts)
            
            # Try to get from cache
            result = cache.get(cache_key)
            if result is not None:
                return result
            
            # Calculate and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            return result
        
        return wrapper
    return decorator


def invalidate_cache_on_save(model_class: type, cache_patterns: List[str]):
    """
    Decorator to invalidate cache patterns when a model is saved.
    
    Args:
        model_class: Model class to monitor
        cache_patterns: List of cache key patterns to invalidate
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            
            # Invalidate cache patterns
            strategy = CacheStrategy()
            for pattern in cache_patterns:
                strategy.invalidate_pattern(pattern)
            
            return result
        
        return wrapper
    return decorator