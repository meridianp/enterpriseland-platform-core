"""
Caching Layer with Redis

Provides a comprehensive caching solution with:
- Multi-level caching strategy
- Cache invalidation patterns
- Distributed caching
- Session storage
- Rate limiting backend
- Real-time data structures
- Cache warming
- Cache tagging
"""

from .cache import (
    cache_get,
    cache_set,
    cache_delete,
    cache_clear,
    cache_many_get,
    cache_many_set,
    cache_many_delete,
    CacheManager,
    cache_manager,
    make_cache_key
)
from .decorators import (
    cache_result,
    cache_page_result,
    invalidate_cache,
    cache_method,
    conditional_cache,
    cache_aside,
    memoize
)
from .backends import (
    RedisCache,
    TieredCache,
    TaggedCache,
    RedisLock
)
from .middleware import (
    EnhancedCacheMiddleware,
    ConditionalCacheMiddleware,
    CacheWarmingMiddleware,
    APICacheMiddleware
)
from .sessions import (
    RedisSessionStore,
    EnhancedSessionStore,
    SessionManager,
    session_manager
)
from .warming import (
    CacheWarmer,
    cache_warmer,
    warm_cache,
    scheduled_cache_warming,
    warm_queryset
)
from .realtime import (
    Counter,
    Leaderboard,
    RateLimiter,
    RealtimeAnalytics,
    Presence
)

__all__ = [
    # Cache functions
    'cache_get',
    'cache_set',
    'cache_delete',
    'cache_clear',
    'cache_many_get',
    'cache_many_set',
    'cache_many_delete',
    'CacheManager',
    'cache_manager',
    'make_cache_key',
    
    # Decorators
    'cache_result',
    'cache_page_result',
    'invalidate_cache',
    'cache_method',
    'conditional_cache',
    'cache_aside',
    'memoize',
    
    # Backends
    'RedisCache',
    'TieredCache',
    'TaggedCache',
    'RedisLock',
    
    # Middleware
    'EnhancedCacheMiddleware',
    'ConditionalCacheMiddleware',
    'CacheWarmingMiddleware',
    'APICacheMiddleware',
    
    # Sessions
    'RedisSessionStore',
    'EnhancedSessionStore',
    'SessionManager',
    'session_manager',
    
    # Warming
    'CacheWarmer',
    'cache_warmer',
    'warm_cache',
    'scheduled_cache_warming',
    'warm_queryset',
    
    # Real-time
    'Counter',
    'Leaderboard',
    'RateLimiter',
    'RealtimeAnalytics',
    'Presence',
]

default_app_config = 'platform_core.cache.apps.CacheConfig'