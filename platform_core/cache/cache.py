"""
Cache Manager and Helper Functions

Main cache interface and management.
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional, Callable, Union
from functools import wraps

from django.conf import settings
from django.core.cache import cache as django_cache
from django.core.cache.backends.base import DEFAULT_TIMEOUT

from .backends import RedisCache, TieredCache, TaggedCache

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Central cache manager for the platform.
    """
    
    def __init__(self):
        """Initialize cache manager."""
        self._caches = {}
        self._default_timeout = getattr(settings, 'CACHE_DEFAULT_TIMEOUT', 300)
        self._key_prefix = getattr(settings, 'CACHE_KEY_PREFIX', 'platform')
        self._init_caches()
    
    def _init_caches(self):
        """Initialize cache backends."""
        # Default cache (Django cache)
        self._caches['default'] = django_cache
        
        # Redis cache
        redis_config = getattr(settings, 'REDIS_CACHE_CONFIG', None)
        self._caches['redis'] = RedisCache(redis_config)
        
        # Tiered cache
        tiered_config = getattr(settings, 'TIERED_CACHE_CONFIG', {})
        self._caches['tiered'] = TieredCache(
            l1_size=tiered_config.get('l1_size', 1000),
            l2_cache=self._caches['redis']
        )
        
        # Tagged cache
        self._caches['tagged'] = TaggedCache(self._caches['redis'])
        
        logger.info("Cache manager initialized with backends: %s", 
                   list(self._caches.keys()))
    
    def get_cache(self, backend: str = 'default'):
        """Get specific cache backend."""
        return self._caches.get(backend, self._caches['default'])
    
    def make_key(self, key: str, prefix: Optional[str] = None) -> str:
        """Make cache key with prefix."""
        prefix = prefix or self._key_prefix
        return f"{prefix}:{key}" if prefix else key
    
    def get(self, key: str, default: Any = None, 
            backend: str = 'default', prefix: Optional[str] = None) -> Any:
        """Get value from cache."""
        cache = self.get_cache(backend)
        full_key = self.make_key(key, prefix)
        
        try:
            return cache.get(full_key, default)
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return default
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None,
            backend: str = 'default', prefix: Optional[str] = None,
            tags: List[str] = None) -> bool:
        """Set value in cache."""
        cache = self.get_cache(backend)
        full_key = self.make_key(key, prefix)
        timeout = timeout if timeout is not None else self._default_timeout
        
        try:
            if backend == 'tagged' and tags:
                return cache.set(full_key, value, tags=tags, timeout=timeout)
            return cache.set(full_key, value, timeout)
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    def delete(self, key: str, backend: str = 'default', 
               prefix: Optional[str] = None) -> bool:
        """Delete key from cache."""
        cache = self.get_cache(backend)
        full_key = self.make_key(key, prefix)
        
        try:
            return cache.delete(full_key)
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    def clear(self, backend: str = 'default') -> bool:
        """Clear all cache for backend."""
        cache = self.get_cache(backend)
        
        try:
            if hasattr(cache, 'clear'):
                return cache.clear()
            else:
                cache.clear()
                return True
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return False
    
    def get_many(self, keys: List[str], backend: str = 'default',
                 prefix: Optional[str] = None) -> Dict[str, Any]:
        """Get multiple values."""
        cache = self.get_cache(backend)
        full_keys = [self.make_key(k, prefix) for k in keys]
        
        try:
            if hasattr(cache, 'get_many'):
                results = cache.get_many(full_keys)
                # Map back to original keys
                return {
                    keys[i]: results.get(full_keys[i])
                    for i in range(len(keys))
                    if full_keys[i] in results
                }
            else:
                # Fallback for caches without get_many
                return {
                    key: cache.get(self.make_key(key, prefix))
                    for key in keys
                }
        except Exception as e:
            logger.error(f"Cache get_many error: {e}")
            return {}
    
    def set_many(self, data: Dict[str, Any], timeout: Optional[int] = None,
                 backend: str = 'default', prefix: Optional[str] = None) -> bool:
        """Set multiple values."""
        cache = self.get_cache(backend)
        timeout = timeout if timeout is not None else self._default_timeout
        
        full_data = {
            self.make_key(k, prefix): v
            for k, v in data.items()
        }
        
        try:
            if hasattr(cache, 'set_many'):
                return cache.set_many(full_data, timeout)
            else:
                # Fallback for caches without set_many
                for key, value in full_data.items():
                    cache.set(key, value, timeout)
                return True
        except Exception as e:
            logger.error(f"Cache set_many error: {e}")
            return False
    
    def delete_many(self, keys: List[str], backend: str = 'default',
                    prefix: Optional[str] = None) -> int:
        """Delete multiple keys."""
        cache = self.get_cache(backend)
        full_keys = [self.make_key(k, prefix) for k in keys]
        
        try:
            if hasattr(cache, 'delete_many'):
                return cache.delete_many(full_keys)
            else:
                # Fallback for caches without delete_many
                count = 0
                for key in full_keys:
                    if cache.delete(key):
                        count += 1
                return count
        except Exception as e:
            logger.error(f"Cache delete_many error: {e}")
            return 0
    
    def invalidate_tag(self, tag: str, backend: str = 'tagged') -> int:
        """Invalidate all cache entries with tag."""
        cache = self.get_cache(backend)
        
        if hasattr(cache, 'invalidate_tag'):
            return cache.invalidate_tag(tag)
        
        logger.warning(f"Backend {backend} does not support tags")
        return 0
    
    def invalidate_tags(self, tags: List[str], backend: str = 'tagged') -> int:
        """Invalidate all cache entries with any of the tags."""
        cache = self.get_cache(backend)
        
        if hasattr(cache, 'invalidate_tags'):
            return cache.invalidate_tags(tags)
        
        logger.warning(f"Backend {backend} does not support tags")
        return 0
    
    def increment(self, key: str, delta: int = 1, backend: str = 'redis',
                  prefix: Optional[str] = None) -> Optional[int]:
        """Increment counter."""
        cache = self.get_cache(backend)
        full_key = self.make_key(key, prefix)
        
        if hasattr(cache, 'increment'):
            return cache.increment(full_key, delta)
        
        # Fallback for caches without increment
        current = cache.get(full_key, 0)
        new_value = current + delta
        cache.set(full_key, new_value)
        return new_value
    
    def decrement(self, key: str, delta: int = 1, backend: str = 'redis',
                  prefix: Optional[str] = None) -> Optional[int]:
        """Decrement counter."""
        cache = self.get_cache(backend)
        full_key = self.make_key(key, prefix)
        
        if hasattr(cache, 'decrement'):
            return cache.decrement(full_key, delta)
        
        # Fallback for caches without decrement
        current = cache.get(full_key, 0)
        new_value = current - delta
        cache.set(full_key, new_value)
        return new_value
    
    def get_or_set(self, key: str, default: Union[Any, Callable],
                   timeout: Optional[int] = None, backend: str = 'default',
                   prefix: Optional[str] = None) -> Any:
        """Get value or set if not exists."""
        value = self.get(key, backend=backend, prefix=prefix)
        
        if value is None:
            if callable(default):
                value = default()
            else:
                value = default
            
            self.set(key, value, timeout, backend, prefix)
        
        return value
    
    def touch(self, key: str, timeout: Optional[int] = None,
              backend: str = 'default', prefix: Optional[str] = None) -> bool:
        """Update expiration time."""
        cache = self.get_cache(backend)
        full_key = self.make_key(key, prefix)
        timeout = timeout if timeout is not None else self._default_timeout
        
        if hasattr(cache, 'touch'):
            return cache.touch(full_key, timeout)
        
        # Fallback: get and set again
        value = cache.get(full_key)
        if value is not None:
            return cache.set(full_key, value, timeout)
        return False
    
    def ttl(self, key: str, backend: str = 'redis',
            prefix: Optional[str] = None) -> Optional[int]:
        """Get time to live for key."""
        cache = self.get_cache(backend)
        full_key = self.make_key(key, prefix)
        
        if hasattr(cache, 'ttl'):
            return cache.ttl(full_key)
        
        return None
    
    def lock(self, key: str, timeout: int = 10, backend: str = 'redis',
             prefix: Optional[str] = None):
        """Get distributed lock."""
        cache = self.get_cache(backend)
        full_key = self.make_key(key, prefix)
        
        if hasattr(cache, 'lock'):
            return cache.lock(full_key, timeout)
        
        raise NotImplementedError(f"Backend {backend} does not support locking")
    
    def get_stats(self, backend: str = 'tiered') -> Dict[str, Any]:
        """Get cache statistics."""
        cache = self.get_cache(backend)
        
        if hasattr(cache, 'get_stats'):
            return cache.get_stats()
        
        return {}


# Global cache manager instance
cache_manager = CacheManager()


# Convenience functions
def cache_get(key: str, default: Any = None, **kwargs) -> Any:
    """Get value from cache."""
    return cache_manager.get(key, default, **kwargs)


def cache_set(key: str, value: Any, timeout: Optional[int] = None, **kwargs) -> bool:
    """Set value in cache."""
    return cache_manager.set(key, value, timeout, **kwargs)


def cache_delete(key: str, **kwargs) -> bool:
    """Delete key from cache."""
    return cache_manager.delete(key, **kwargs)


def cache_clear(backend: str = 'default') -> bool:
    """Clear cache."""
    return cache_manager.clear(backend)


def cache_many_get(keys: List[str], **kwargs) -> Dict[str, Any]:
    """Get multiple values."""
    return cache_manager.get_many(keys, **kwargs)


def cache_many_set(data: Dict[str, Any], timeout: Optional[int] = None, **kwargs) -> bool:
    """Set multiple values."""
    return cache_manager.set_many(data, timeout, **kwargs)


def cache_many_delete(keys: List[str], **kwargs) -> int:
    """Delete multiple keys."""
    return cache_manager.delete_many(keys, **kwargs)


def make_cache_key(*args, **kwargs) -> str:
    """
    Generate cache key from arguments.
    """
    key_parts = []
    
    # Add args
    for arg in args:
        if isinstance(arg, (str, int, float, bool)):
            key_parts.append(str(arg))
        else:
            # Hash complex objects
            key_parts.append(
                hashlib.md5(str(arg).encode()).hexdigest()[:8]
            )
    
    # Add kwargs
    for k, v in sorted(kwargs.items()):
        if isinstance(v, (str, int, float, bool)):
            key_parts.append(f"{k}:{v}")
        else:
            key_parts.append(
                f"{k}:{hashlib.md5(str(v).encode()).hexdigest()[:8]}"
            )
    
    return ":".join(key_parts)