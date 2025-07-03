"""
Cache Strategies

Different caching strategies for various use cases.
"""

import time
import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any, Optional, Dict, List, Callable, Tuple
from datetime import datetime, timedelta
from collections import OrderedDict, defaultdict
from django.core.cache import cache, caches
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class CacheStrategy(ABC):
    """Base cache strategy interface."""
    
    @abstractmethod
    def get(self, key: str) -> Any:
        """Get value from cache."""
        pass
    
    @abstractmethod
    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """Set value in cache."""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete value from cache."""
        pass
    
    @abstractmethod
    def clear(self) -> bool:
        """Clear all cache entries."""
        pass
    
    def get_or_set(self, key: str, callable: Callable, timeout: Optional[int] = None) -> Any:
        """Get from cache or compute and set."""
        value = self.get(key)
        if value is None:
            value = callable()
            self.set(key, value, timeout)
        return value


class TTLCacheStrategy(CacheStrategy):
    """Time-to-live based caching strategy."""
    
    def __init__(self, default_timeout: int = 300):
        self.default_timeout = default_timeout
        self.cache = cache
    
    def get(self, key: str) -> Any:
        """Get value with TTL check."""
        return self.cache.get(key)
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """Set value with TTL."""
        timeout = timeout or self.default_timeout
        return self.cache.set(key, value, timeout)
    
    def delete(self, key: str) -> bool:
        """Delete value."""
        return self.cache.delete(key)
    
    def clear(self) -> bool:
        """Clear all entries."""
        self.cache.clear()
        return True
    
    def touch(self, key: str, timeout: Optional[int] = None) -> bool:
        """Update TTL without changing value."""
        value = self.get(key)
        if value is not None:
            return self.set(key, value, timeout or self.default_timeout)
        return False


class LRUCacheStrategy(CacheStrategy):
    """Least Recently Used caching strategy."""
    
    def __init__(self, max_entries: int = 1000):
        self.max_entries = max_entries
        self.cache = cache
        self.access_order = OrderedDict()
        self._lock = threading.Lock()
    
    def get(self, key: str) -> Any:
        """Get value and update access order."""
        value = self.cache.get(key)
        if value is not None:
            with self._lock:
                # Move to end (most recently used)
                if key in self.access_order:
                    self.access_order.move_to_end(key)
                else:
                    self.access_order[key] = time.time()
        return value
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """Set value and manage LRU eviction."""
        with self._lock:
            # Add to access order
            self.access_order[key] = time.time()
            
            # Evict least recently used if at capacity
            while len(self.access_order) > self.max_entries:
                lru_key = next(iter(self.access_order))
                self.access_order.pop(lru_key)
                self.cache.delete(lru_key)
        
        return self.cache.set(key, value, timeout)
    
    def delete(self, key: str) -> bool:
        """Delete value and remove from access order."""
        with self._lock:
            self.access_order.pop(key, None)
        return self.cache.delete(key)
    
    def clear(self) -> bool:
        """Clear all entries."""
        with self._lock:
            self.access_order.clear()
        self.cache.clear()
        return True


class TagBasedCacheStrategy(CacheStrategy):
    """Tag-based cache invalidation strategy."""
    
    def __init__(self):
        self.cache = cache
        self.tag_index = defaultdict(set)
        self._lock = threading.Lock()
    
    def get(self, key: str) -> Any:
        """Get value from cache."""
        return self.cache.get(key)
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None, 
            tags: Optional[List[str]] = None) -> bool:
        """Set value with tags."""
        # Store value
        result = self.cache.set(key, value, timeout)
        
        # Update tag index
        if tags:
            with self._lock:
                for tag in tags:
                    self.tag_index[tag].add(key)
                
                # Store tag associations in cache
                self.cache.set(f"_tags:{key}", tags, timeout)
        
        return result
    
    def delete(self, key: str) -> bool:
        """Delete value and clean up tags."""
        # Get tags for this key
        tags = self.cache.get(f"_tags:{key}")
        
        # Remove from tag index
        if tags:
            with self._lock:
                for tag in tags:
                    self.tag_index[tag].discard(key)
        
        # Delete tag association
        self.cache.delete(f"_tags:{key}")
        
        # Delete value
        return self.cache.delete(key)
    
    def delete_by_tag(self, tag: str) -> int:
        """Delete all entries with a specific tag."""
        count = 0
        with self._lock:
            keys = list(self.tag_index.get(tag, set()))
            
        for key in keys:
            if self.delete(key):
                count += 1
        
        return count
    
    def clear(self) -> bool:
        """Clear all entries."""
        with self._lock:
            self.tag_index.clear()
        self.cache.clear()
        return True


class TieredCacheStrategy(CacheStrategy):
    """Multi-tier caching strategy (L1, L2, L3)."""
    
    def __init__(self, tiers: Optional[List[Dict[str, Any]]] = None):
        self.tiers = tiers or self._default_tiers()
        self.tier_caches = []
        
        for tier_config in self.tiers:
            cache_name = tier_config.get('cache', 'default')
            self.tier_caches.append({
                'cache': caches[cache_name],
                'timeout': tier_config.get('timeout', 300),
                'size': tier_config.get('size', 1000)
            })
    
    def _default_tiers(self) -> List[Dict[str, Any]]:
        """Default tier configuration."""
        return [
            {'cache': 'default', 'timeout': 60, 'size': 100},     # L1: Hot cache
            {'cache': 'default', 'timeout': 300, 'size': 1000},   # L2: Warm cache
            {'cache': 'default', 'timeout': 3600, 'size': 10000}  # L3: Cold cache
        ]
    
    def get(self, key: str) -> Any:
        """Get from tiers, promoting on hit."""
        for i, tier in enumerate(self.tier_caches):
            value = tier['cache'].get(key)
            if value is not None:
                # Promote to higher tiers
                for j in range(i):
                    self.tier_caches[j]['cache'].set(
                        key, value, self.tier_caches[j]['timeout']
                    )
                return value
        return None
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """Set in appropriate tier based on timeout."""
        # Determine tier based on timeout
        if timeout is None:
            tier_index = 1  # Default to L2
        elif timeout <= 60:
            tier_index = 0  # L1: Hot
        elif timeout <= 300:
            tier_index = 1  # L2: Warm
        else:
            tier_index = 2  # L3: Cold
        
        # Set in determined tier and all lower tiers
        result = True
        for i in range(tier_index + 1):
            if i < len(self.tier_caches):
                tier = self.tier_caches[i]
                tier_result = tier['cache'].set(
                    key, value, 
                    min(timeout or tier['timeout'], tier['timeout'])
                )
                result = result and tier_result
        
        return result
    
    def delete(self, key: str) -> bool:
        """Delete from all tiers."""
        result = True
        for tier in self.tier_caches:
            tier_result = tier['cache'].delete(key)
            result = result and tier_result
        return result
    
    def clear(self) -> bool:
        """Clear all tiers."""
        for tier in self.tier_caches:
            tier['cache'].clear()
        return True


class AdaptiveCacheStrategy(CacheStrategy):
    """Adaptive caching strategy that adjusts based on access patterns."""
    
    def __init__(self, base_timeout: int = 300, 
                 min_timeout: int = 60,
                 max_timeout: int = 3600):
        self.base_timeout = base_timeout
        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
        self.cache = cache
        self.access_stats = defaultdict(lambda: {
            'count': 0,
            'last_access': None,
            'frequency': 0.0
        })
        self._lock = threading.Lock()
    
    def get(self, key: str) -> Any:
        """Get value and update access statistics."""
        value = self.cache.get(key)
        
        if value is not None:
            with self._lock:
                stats = self.access_stats[key]
                now = time.time()
                
                # Update access count
                stats['count'] += 1
                
                # Calculate frequency (accesses per hour)
                if stats['last_access']:
                    time_diff = now - stats['last_access']
                    if time_diff > 0:
                        stats['frequency'] = stats['count'] / (time_diff / 3600)
                
                stats['last_access'] = now
        
        return value
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """Set value with adaptive timeout."""
        # Calculate adaptive timeout based on access patterns
        adaptive_timeout = self._calculate_timeout(key)
        timeout = timeout or adaptive_timeout
        
        return self.cache.set(key, value, timeout)
    
    def _calculate_timeout(self, key: str) -> int:
        """Calculate timeout based on access patterns."""
        with self._lock:
            stats = self.access_stats.get(key, {})
            frequency = stats.get('frequency', 0.0)
        
        if frequency == 0:
            return self.base_timeout
        
        # Higher frequency = longer timeout
        if frequency > 10:  # More than 10 accesses per hour
            timeout = self.max_timeout
        elif frequency > 1:  # 1-10 accesses per hour
            # Linear interpolation
            ratio = (frequency - 1) / 9
            timeout = int(self.base_timeout + (self.max_timeout - self.base_timeout) * ratio)
        else:  # Less than 1 access per hour
            timeout = self.min_timeout
        
        return timeout
    
    def delete(self, key: str) -> bool:
        """Delete value and stats."""
        with self._lock:
            self.access_stats.pop(key, None)
        return self.cache.delete(key)
    
    def clear(self) -> bool:
        """Clear cache and stats."""
        with self._lock:
            self.access_stats.clear()
        self.cache.clear()
        return True
    
    def get_stats(self, key: str) -> Dict[str, Any]:
        """Get access statistics for a key."""
        with self._lock:
            return dict(self.access_stats.get(key, {}))


import threading