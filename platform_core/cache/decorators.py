"""
Cache Decorators

Provides decorators for caching function and method results.
"""

import functools
import hashlib
import logging
from typing import Any, Callable, Optional, List, Union
from django.core.cache import cache as django_cache
from django.http import HttpRequest, HttpResponse
from django.utils.cache import get_cache_key, patch_response_headers
from django.views.decorators.cache import cache_page as django_cache_page

from .cache import cache_manager, make_cache_key

logger = logging.getLogger(__name__)


def cache_result(
    timeout: Optional[int] = None,
    key_prefix: Optional[str] = None,
    backend: str = 'default',
    tags: List[str] = None,
    cache_on_none: bool = False,
    make_key: Optional[Callable] = None
):
    """
    Cache function result decorator.
    
    Args:
        timeout: Cache timeout in seconds
        key_prefix: Prefix for cache key
        backend: Cache backend to use
        tags: Tags for cache invalidation
        cache_on_none: Whether to cache None results
        make_key: Custom key generation function
    
    Example:
        @cache_result(timeout=300, key_prefix='user')
        def get_user(user_id):
            return User.objects.get(id=user_id)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            if make_key:
                cache_key = make_key(*args, **kwargs)
            else:
                # Default key generation
                func_name = f"{func.__module__}.{func.__name__}"
                cache_key = make_cache_key(func_name, *args, **kwargs)
            
            # Use provided prefix or generate from function
            prefix = key_prefix or func.__module__.replace('.', ':')
            
            # Try to get from cache
            result = cache_manager.get(
                cache_key, 
                backend=backend, 
                prefix=prefix
            )
            
            if result is not None or (result is None and cache_key in cache_manager._caches[backend]):
                logger.debug(f"Cache hit for {func_name}")
                return result
            
            # Call function
            result = func(*args, **kwargs)
            
            # Cache result if not None or cache_on_none is True
            if result is not None or cache_on_none:
                cache_manager.set(
                    cache_key,
                    result,
                    timeout=timeout,
                    backend=backend,
                    prefix=prefix,
                    tags=tags
                )
                logger.debug(f"Cached result for {func_name}")
            
            return result
        
        # Add cache control methods
        wrapper.cache_key = lambda *args, **kwargs: make_cache_key(
            f"{func.__module__}.{func.__name__}", *args, **kwargs
        )
        wrapper.invalidate = lambda *args, **kwargs: cache_manager.delete(
            wrapper.cache_key(*args, **kwargs),
            backend=backend,
            prefix=key_prefix or func.__module__.replace('.', ':')
        )
        
        return wrapper
    return decorator


def cache_method(
    timeout: Optional[int] = None,
    key_prefix: Optional[str] = None,
    backend: str = 'default',
    tags: List[str] = None,
    cache_on_none: bool = False,
    include_self: bool = False
):
    """
    Cache method result decorator.
    
    Similar to cache_result but for class methods.
    By default, excludes 'self' from cache key generation.
    
    Args:
        timeout: Cache timeout in seconds
        key_prefix: Prefix for cache key
        backend: Cache backend to use
        tags: Tags for cache invalidation
        cache_on_none: Whether to cache None results
        include_self: Include self instance in cache key
    
    Example:
        class UserService:
            @cache_method(timeout=300)
            def get_user_stats(self, user_id):
                return calculate_stats(user_id)
    """
    def decorator(method):
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            # Generate cache key
            method_name = f"{self.__class__.__module__}.{self.__class__.__name__}.{method.__name__}"
            
            if include_self:
                # Include instance id or hash
                instance_key = getattr(self, 'pk', None) or getattr(self, 'id', None) or id(self)
                cache_key = make_cache_key(method_name, instance_key, *args, **kwargs)
            else:
                cache_key = make_cache_key(method_name, *args, **kwargs)
            
            # Use provided prefix or generate from class
            prefix = key_prefix or self.__class__.__module__.replace('.', ':')
            
            # Try to get from cache
            result = cache_manager.get(
                cache_key,
                backend=backend,
                prefix=prefix
            )
            
            if result is not None:
                logger.debug(f"Cache hit for {method_name}")
                return result
            
            # Call method
            result = method(self, *args, **kwargs)
            
            # Cache result
            if result is not None or cache_on_none:
                cache_manager.set(
                    cache_key,
                    result,
                    timeout=timeout,
                    backend=backend,
                    prefix=prefix,
                    tags=tags
                )
                logger.debug(f"Cached result for {method_name}")
            
            return result
        
        return wrapper
    return decorator


def cache_page_result(
    timeout: Optional[int] = None,
    key_prefix: Optional[str] = None,
    backend: str = 'default',
    cache_control_public: bool = False,
    cache_control_private: bool = False
):
    """
    Enhanced page caching decorator.
    
    Extends Django's cache_page with additional features.
    
    Args:
        timeout: Cache timeout in seconds
        key_prefix: Prefix for cache key
        backend: Cache backend to use
        cache_control_public: Set Cache-Control: public
        cache_control_private: Set Cache-Control: private
    
    Example:
        @cache_page_result(timeout=600)
        def product_list(request):
            return render(request, 'products.html', {...})
    """
    def decorator(view_func):
        # Use Django's cache_page as base
        cached_view = django_cache_page(
            timeout or 60,
            cache=backend,
            key_prefix=key_prefix
        )(view_func)
        
        @functools.wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            response = cached_view(request, *args, **kwargs)
            
            # Add cache control headers
            if cache_control_public:
                patch_response_headers(response, cache_timeout=timeout)
                response['Cache-Control'] = f'public, max-age={timeout or 60}'
            elif cache_control_private:
                response['Cache-Control'] = f'private, max-age={timeout or 60}'
            
            return response
        
        return wrapper
    return decorator


def invalidate_cache(
    pattern: Optional[str] = None,
    tags: Optional[List[str]] = None,
    backend: str = 'default'
):
    """
    Invalidate cache decorator.
    
    Automatically invalidates cache when decorated function is called.
    
    Args:
        pattern: Cache key pattern to invalidate
        tags: Tags to invalidate
        backend: Cache backend to use
    
    Example:
        @invalidate_cache(tags=['user-data'])
        def update_user(user_id, data):
            # Update user logic
            pass
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Call the function first
            result = func(*args, **kwargs)
            
            # Invalidate cache
            if tags:
                for tag in tags:
                    count = cache_manager.invalidate_tag(tag, backend=backend)
                    logger.debug(f"Invalidated {count} cache entries for tag: {tag}")
            
            if pattern:
                # Pattern-based invalidation would require additional implementation
                logger.warning("Pattern-based cache invalidation not yet implemented")
            
            return result
        
        return wrapper
    return decorator


def conditional_cache(
    condition: Callable[..., bool],
    timeout: Optional[int] = None,
    key_prefix: Optional[str] = None,
    backend: str = 'default'
):
    """
    Conditionally cache based on runtime conditions.
    
    Args:
        condition: Function that returns True if result should be cached
        timeout: Cache timeout in seconds
        key_prefix: Prefix for cache key
        backend: Cache backend to use
    
    Example:
        @conditional_cache(
            condition=lambda user, *args: user.is_premium,
            timeout=3600
        )
        def get_analytics(user, date_range):
            return expensive_calculation(date_range)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Check condition
            should_cache = condition(*args, **kwargs)
            
            if should_cache:
                # Use cache_result behavior
                func_name = f"{func.__module__}.{func.__name__}"
                cache_key = make_cache_key(func_name, *args, **kwargs)
                prefix = key_prefix or func.__module__.replace('.', ':')
                
                # Try cache
                result = cache_manager.get(
                    cache_key,
                    backend=backend,
                    prefix=prefix
                )
                
                if result is not None:
                    return result
                
                # Call function
                result = func(*args, **kwargs)
                
                # Cache result
                if result is not None:
                    cache_manager.set(
                        cache_key,
                        result,
                        timeout=timeout,
                        backend=backend,
                        prefix=prefix
                    )
                
                return result
            else:
                # Don't use cache
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def cache_aside(
    cache_loader: Callable,
    cache_writer: Callable,
    timeout: Optional[int] = None,
    backend: str = 'default'
):
    """
    Cache-aside pattern decorator.
    
    Provides custom cache loading and writing logic.
    
    Args:
        cache_loader: Function to load from cache
        cache_writer: Function to write to cache
        timeout: Cache timeout in seconds
        backend: Cache backend to use
    
    Example:
        @cache_aside(
            cache_loader=lambda key: redis_client.get(key),
            cache_writer=lambda key, value: redis_client.setex(key, 300, value)
        )
        def get_data(data_id):
            return fetch_from_database(data_id)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate key
            func_name = f"{func.__module__}.{func.__name__}"
            cache_key = make_cache_key(func_name, *args, **kwargs)
            
            # Try custom loader
            try:
                result = cache_loader(cache_key)
                if result is not None:
                    return result
            except Exception as e:
                logger.error(f"Cache loader error: {e}")
            
            # Call function
            result = func(*args, **kwargs)
            
            # Use custom writer
            if result is not None:
                try:
                    cache_writer(cache_key, result)
                except Exception as e:
                    logger.error(f"Cache writer error: {e}")
            
            return result
        
        return wrapper
    return decorator


def memoize(
    timeout: Optional[int] = None,
    max_size: int = 128,
    typed: bool = False
):
    """
    Memoization decorator with size limit and optional typing.
    
    Uses tiered cache for in-memory + Redis caching.
    
    Args:
        timeout: Cache timeout in seconds
        max_size: Maximum number of cached results
        typed: If True, arguments of different types cached separately
    
    Example:
        @memoize(timeout=3600, max_size=1000)
        def fibonacci(n):
            if n < 2:
                return n
            return fibonacci(n-1) + fibonacci(n-2)
    """
    def decorator(func):
        # Use tiered cache for memoization
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate typed key if needed
            if typed:
                key_args = []
                for arg in args:
                    key_args.append(f"{type(arg).__name__}:{arg}")
                cache_key = make_cache_key(
                    f"{func.__module__}.{func.__name__}",
                    *key_args,
                    **kwargs
                )
            else:
                cache_key = make_cache_key(
                    f"{func.__module__}.{func.__name__}",
                    *args,
                    **kwargs
                )
            
            # Use tiered cache
            result = cache_manager.get(
                cache_key,
                backend='tiered'
            )
            
            if result is not None:
                return result
            
            # Call function
            result = func(*args, **kwargs)
            
            # Cache result
            cache_manager.set(
                cache_key,
                result,
                timeout=timeout,
                backend='tiered'
            )
            
            return result
        
        # Add cache info method
        wrapper.cache_info = lambda: cache_manager.get_stats('tiered')
        
        return wrapper
    return decorator