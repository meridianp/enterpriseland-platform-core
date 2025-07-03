"""
Comprehensive Caching Strategy

Advanced caching system with multiple strategies, invalidation patterns,
and performance optimization.
"""

from .strategies import (
    CacheStrategy,
    TTLCacheStrategy,
    LRUCacheStrategy,
    TagBasedCacheStrategy,
    TieredCacheStrategy,
    AdaptiveCacheStrategy
)
from .invalidation import (
    CacheInvalidator,
    TagInvalidator,
    PatternInvalidator,
    DependencyInvalidator
)
from .warmup import (
    CacheWarmer,
    QueryCacheWarmer,
    ViewCacheWarmer,
    APIEndpointCacheWarmer
)
from .monitoring import (
    CacheMonitor,
    CacheMetrics,
    cache_monitor
)
from .decorators import (
    cached_view,
    cached_method,
    cached_api,
    smart_cache
)
from .backends import (
    MultiTierCache,
    DistributedCache,
    EdgeCache
)
from .manager import CacheManager

__all__ = [
    # Strategies
    'CacheStrategy',
    'TTLCacheStrategy',
    'LRUCacheStrategy',
    'TagBasedCacheStrategy',
    'TieredCacheStrategy',
    'AdaptiveCacheStrategy',
    
    # Invalidation
    'CacheInvalidator',
    'TagInvalidator',
    'PatternInvalidator',
    'DependencyInvalidator',
    
    # Warmup
    'CacheWarmer',
    'QueryCacheWarmer',
    'ViewCacheWarmer',
    'APIEndpointCacheWarmer',
    
    # Monitoring
    'CacheMonitor',
    'CacheMetrics',
    'cache_monitor',
    
    # Decorators
    'cached_view',
    'cached_method',
    'cached_api',
    'smart_cache',
    
    # Backends
    'MultiTierCache',
    'DistributedCache',
    'EdgeCache',
    
    # Manager
    'CacheManager'
]