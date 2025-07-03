"""
Cache Backends

Different cache backend implementations.
"""

import json
import time
import logging
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import OrderedDict
from threading import RLock

import redis
from django.conf import settings
from django.core.cache import cache as django_cache
from django.core.cache.backends.base import BaseCache
from django.utils.encoding import force_bytes

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Enhanced Redis cache backend with advanced features.
    """
    
    def __init__(self, connection_config: Optional[Dict[str, Any]] = None):
        """Initialize Redis cache."""
        if connection_config is None:
            connection_config = getattr(settings, 'REDIS_CACHE_CONFIG', {
                'host': 'localhost',
                'port': 6379,
                'db': 1,
                'password': None,
                'socket_timeout': 5,
                'connection_pool_kwargs': {
                    'max_connections': 50,
                    'retry_on_timeout': True
                }
            })
        
        self.connection_config = connection_config
        self._client = None
        self._connect()
    
    def _connect(self):
        """Connect to Redis."""
        try:
            pool = redis.ConnectionPool(**self.connection_config)
            self._client = redis.Redis(connection_pool=pool)
            self._client.ping()
            logger.info("Connected to Redis cache")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        if self._client is None:
            self._connect()
        return self._client
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache."""
        try:
            value = self.client.get(key)
            if value is None:
                return default
            return self._deserialize(value)
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return default
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """Set value in cache."""
        try:
            serialized = self._serialize(value)
            if timeout is None:
                return self.client.set(key, serialized)
            return self.client.setex(key, timeout, serialized)
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        try:
            return bool(self.client.delete(key))
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            return bool(self.client.exists(key))
        except Exception as e:
            logger.error(f"Cache exists error for key {key}: {e}")
            return False
    
    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Get multiple values."""
        try:
            values = self.client.mget(keys)
            result = {}
            for key, value in zip(keys, values):
                if value is not None:
                    result[key] = self._deserialize(value)
            return result
        except Exception as e:
            logger.error(f"Cache get_many error: {e}")
            return {}
    
    def set_many(self, data: Dict[str, Any], timeout: Optional[int] = None) -> bool:
        """Set multiple values."""
        try:
            pipeline = self.client.pipeline()
            for key, value in data.items():
                serialized = self._serialize(value)
                if timeout is None:
                    pipeline.set(key, serialized)
                else:
                    pipeline.setex(key, timeout, serialized)
            pipeline.execute()
            return True
        except Exception as e:
            logger.error(f"Cache set_many error: {e}")
            return False
    
    def delete_many(self, keys: List[str]) -> int:
        """Delete multiple keys."""
        try:
            if keys:
                return self.client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Cache delete_many error: {e}")
            return 0
    
    def clear(self) -> bool:
        """Clear all cache."""
        try:
            self.client.flushdb()
            return True
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return False
    
    def increment(self, key: str, delta: int = 1) -> Optional[int]:
        """Increment counter."""
        try:
            return self.client.incr(key, delta)
        except Exception as e:
            logger.error(f"Cache increment error for key {key}: {e}")
            return None
    
    def decrement(self, key: str, delta: int = 1) -> Optional[int]:
        """Decrement counter."""
        try:
            return self.client.decr(key, delta)
        except Exception as e:
            logger.error(f"Cache decrement error for key {key}: {e}")
            return None
    
    def expire(self, key: str, timeout: int) -> bool:
        """Set expiration on key."""
        try:
            return bool(self.client.expire(key, timeout))
        except Exception as e:
            logger.error(f"Cache expire error for key {key}: {e}")
            return False
    
    def ttl(self, key: str) -> Optional[int]:
        """Get time to live for key."""
        try:
            ttl = self.client.ttl(key)
            return ttl if ttl >= 0 else None
        except Exception as e:
            logger.error(f"Cache ttl error for key {key}: {e}")
            return None
    
    # Advanced features
    
    def sadd(self, key: str, *values) -> int:
        """Add values to set."""
        try:
            return self.client.sadd(key, *values)
        except Exception as e:
            logger.error(f"Cache sadd error for key {key}: {e}")
            return 0
    
    def srem(self, key: str, *values) -> int:
        """Remove values from set."""
        try:
            return self.client.srem(key, *values)
        except Exception as e:
            logger.error(f"Cache srem error for key {key}: {e}")
            return 0
    
    def smembers(self, key: str) -> Set[str]:
        """Get all members of set."""
        try:
            return set(self.client.smembers(key))
        except Exception as e:
            logger.error(f"Cache smembers error for key {key}: {e}")
            return set()
    
    def hset(self, key: str, field: str, value: Any) -> int:
        """Set hash field."""
        try:
            return self.client.hset(key, field, self._serialize(value))
        except Exception as e:
            logger.error(f"Cache hset error for key {key}: {e}")
            return 0
    
    def hget(self, key: str, field: str) -> Any:
        """Get hash field."""
        try:
            value = self.client.hget(key, field)
            return self._deserialize(value) if value else None
        except Exception as e:
            logger.error(f"Cache hget error for key {key}: {e}")
            return None
    
    def hgetall(self, key: str) -> Dict[str, Any]:
        """Get all hash fields."""
        try:
            data = self.client.hgetall(key)
            return {
                k.decode() if isinstance(k, bytes) else k: self._deserialize(v)
                for k, v in data.items()
            }
        except Exception as e:
            logger.error(f"Cache hgetall error for key {key}: {e}")
            return {}
    
    def lpush(self, key: str, *values) -> int:
        """Push values to list."""
        try:
            serialized = [self._serialize(v) for v in values]
            return self.client.lpush(key, *serialized)
        except Exception as e:
            logger.error(f"Cache lpush error for key {key}: {e}")
            return 0
    
    def lrange(self, key: str, start: int, stop: int) -> List[Any]:
        """Get range from list."""
        try:
            values = self.client.lrange(key, start, stop)
            return [self._deserialize(v) for v in values]
        except Exception as e:
            logger.error(f"Cache lrange error for key {key}: {e}")
            return []
    
    def lock(self, key: str, timeout: int = 10) -> 'RedisLock':
        """Get distributed lock."""
        return RedisLock(self.client, key, timeout)
    
    def _serialize(self, value: Any) -> bytes:
        """Serialize value for storage."""
        return json.dumps(value).encode('utf-8')
    
    def _deserialize(self, value: bytes) -> Any:
        """Deserialize value from storage."""
        return json.loads(value.decode('utf-8'))


class RedisLock:
    """Distributed lock using Redis."""
    
    def __init__(self, redis_client: redis.Redis, key: str, timeout: int = 10):
        self.redis = redis_client
        self.key = f"lock:{key}"
        self.timeout = timeout
        self.identifier = None
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
    
    def acquire(self, blocking: bool = True) -> bool:
        """Acquire lock."""
        identifier = str(time.time())
        end = time.time() + self.timeout
        
        while time.time() < end:
            if self.redis.set(self.key, identifier, nx=True, ex=self.timeout):
                self.identifier = identifier
                return True
            
            if not blocking:
                return False
            
            time.sleep(0.001)
        
        return False
    
    def release(self) -> bool:
        """Release lock."""
        if self.identifier is None:
            return False
        
        pipe = self.redis.pipeline(True)
        while True:
            try:
                pipe.watch(self.key)
                if pipe.get(self.key) == self.identifier:
                    pipe.multi()
                    pipe.delete(self.key)
                    pipe.execute()
                    return True
                pipe.unwatch()
                break
            except redis.WatchError:
                pass
        
        return False


class TieredCache:
    """
    Multi-level cache with L1 (memory) and L2 (Redis) tiers.
    """
    
    def __init__(self, l1_size: int = 1000, l2_cache: Optional[RedisCache] = None):
        """Initialize tiered cache."""
        self.l1_size = l1_size
        self.l1_cache = OrderedDict()
        self.l1_lock = RLock()
        self.l2_cache = l2_cache or RedisCache()
        self.stats = {
            'l1_hits': 0,
            'l1_misses': 0,
            'l2_hits': 0,
            'l2_misses': 0
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache."""
        # Check L1
        with self.l1_lock:
            if key in self.l1_cache:
                self.stats['l1_hits'] += 1
                # Move to end (LRU)
                self.l1_cache.move_to_end(key)
                return self.l1_cache[key]
            self.stats['l1_misses'] += 1
        
        # Check L2
        value = self.l2_cache.get(key)
        if value is not None:
            self.stats['l2_hits'] += 1
            # Promote to L1
            self._set_l1(key, value)
            return value
        
        self.stats['l2_misses'] += 1
        return default
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """Set value in cache."""
        # Set in both levels
        self._set_l1(key, value)
        return self.l2_cache.set(key, value, timeout)
    
    def delete(self, key: str) -> bool:
        """Delete from cache."""
        # Delete from L1
        with self.l1_lock:
            self.l1_cache.pop(key, None)
        
        # Delete from L2
        return self.l2_cache.delete(key)
    
    def clear(self) -> bool:
        """Clear all cache."""
        with self.l1_lock:
            self.l1_cache.clear()
        return self.l2_cache.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        total_requests = (
            self.stats['l1_hits'] + self.stats['l1_misses']
        )
        
        if total_requests > 0:
            l1_hit_rate = (self.stats['l1_hits'] / total_requests) * 100
            l2_requests = self.stats['l2_hits'] + self.stats['l2_misses']
            l2_hit_rate = (
                (self.stats['l2_hits'] / l2_requests * 100)
                if l2_requests > 0 else 0
            )
        else:
            l1_hit_rate = 0
            l2_hit_rate = 0
        
        return {
            **self.stats,
            'l1_size': len(self.l1_cache),
            'l1_hit_rate': l1_hit_rate,
            'l2_hit_rate': l2_hit_rate
        }
    
    def _set_l1(self, key: str, value: Any):
        """Set value in L1 cache with LRU eviction."""
        with self.l1_lock:
            if key in self.l1_cache:
                self.l1_cache.move_to_end(key)
            else:
                self.l1_cache[key] = value
                if len(self.l1_cache) > self.l1_size:
                    self.l1_cache.popitem(last=False)


class TaggedCache:
    """
    Cache with tagging support for invalidation groups.
    """
    
    def __init__(self, cache_backend: Optional[RedisCache] = None):
        """Initialize tagged cache."""
        self.cache = cache_backend or RedisCache()
        self.tag_prefix = "tag:"
        self.key_tag_prefix = "keytag:"
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache."""
        return self.cache.get(key, default)
    
    def set(self, key: str, value: Any, tags: List[str] = None, 
            timeout: Optional[int] = None) -> bool:
        """Set value with tags."""
        # Set the value
        if not self.cache.set(key, value, timeout):
            return False
        
        # Associate tags
        if tags:
            for tag in tags:
                # Add key to tag set
                self.cache.sadd(f"{self.tag_prefix}{tag}", key)
                # Add tag to key's tag set
                self.cache.sadd(f"{self.key_tag_prefix}{key}", tag)
                
                # Set expiration on tag sets if key has timeout
                if timeout:
                    self.cache.expire(f"{self.tag_prefix}{tag}", timeout)
                    self.cache.expire(f"{self.key_tag_prefix}{key}", timeout)
        
        return True
    
    def delete(self, key: str) -> bool:
        """Delete key and clean up tags."""
        # Get key's tags
        tags = self.cache.smembers(f"{self.key_tag_prefix}{key}")
        
        # Remove key from all tag sets
        for tag in tags:
            self.cache.srem(f"{self.tag_prefix}{tag}", key)
        
        # Delete key's tag set
        self.cache.delete(f"{self.key_tag_prefix}{key}")
        
        # Delete the key
        return self.cache.delete(key)
    
    def invalidate_tag(self, tag: str) -> int:
        """Invalidate all keys with a tag."""
        # Get all keys with this tag
        keys = list(self.cache.smembers(f"{self.tag_prefix}{tag}"))
        
        if not keys:
            return 0
        
        # Delete all keys
        count = 0
        for key in keys:
            if self.delete(key):
                count += 1
        
        # Clean up tag set
        self.cache.delete(f"{self.tag_prefix}{tag}")
        
        return count
    
    def invalidate_tags(self, tags: List[str]) -> int:
        """Invalidate all keys with any of the tags."""
        count = 0
        for tag in tags:
            count += self.invalidate_tag(tag)
        return count
    
    def get_keys_by_tag(self, tag: str) -> Set[str]:
        """Get all keys with a tag."""
        return self.cache.smembers(f"{self.tag_prefix}{tag}")
    
    def get_tags_by_key(self, key: str) -> Set[str]:
        """Get all tags for a key."""
        return self.cache.smembers(f"{self.key_tag_prefix}{key}")