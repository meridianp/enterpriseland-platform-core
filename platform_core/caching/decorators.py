"""
Cache Decorators

Decorators for intelligent caching with automatic invalidation and monitoring.
"""

import functools
import hashlib
import json
from typing import Any, Optional, List, Callable, Union
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
import logging

from .strategies import CacheStrategy, AdaptiveCacheStrategy, TagBasedCacheStrategy
from .monitoring import cache_monitor

logger = logging.getLogger(__name__)


def make_cache_key(*args, **kwargs) -> str:
    """Generate a cache key from arguments."""
    # Create a unique key from args and kwargs
    key_data = {
        'args': args,
        'kwargs': sorted(kwargs.items())
    }
    
    # Use JSON serialization for consistency
    key_string = json.dumps(key_data, sort_keys=True, default=str)
    
    # Create hash for shorter keys
    key_hash = hashlib.md5(key_string.encode()).hexdigest()
    
    return key_hash


def cached_view(timeout: Optional[int] = 300,
                key_prefix: Optional[str] = None,
                vary_on: Optional[List[str]] = None,
                tags: Optional[List[str]] = None,
                cache_strategy: Optional[CacheStrategy] = None):
    """
    Cache view responses with intelligent invalidation.
    
    Args:
        timeout: Cache timeout in seconds
        key_prefix: Prefix for cache keys
        vary_on: List of headers to vary on
        tags: Tags for cache invalidation
        cache_strategy: Custom cache strategy
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            # Build cache key
            cache_key_parts = [
                key_prefix or view_func.__name__,
                request.method,
                request.get_full_path()
            ]
            
            # Add vary headers to key
            if vary_on:
                for header in vary_on:
                    cache_key_parts.append(request.META.get(header, ''))
            
            # Add user info if authenticated
            if request.user.is_authenticated:
                cache_key_parts.append(f"user:{request.user.id}")
            
            cache_key = ":".join(str(part) for part in cache_key_parts)
            
            # Try to get from cache
            strategy = cache_strategy or TagBasedCacheStrategy()
            cached_response = strategy.get(cache_key)
            
            if cached_response is not None:
                # Add cache hit header
                cached_response['X-Cache'] = 'HIT'
                return cached_response
            
            # Generate response
            response = view_func(request, *args, **kwargs)
            
            # Cache successful responses
            if response.status_code == 200:
                response['X-Cache'] = 'MISS'
                
                # Set cache with tags if using tag strategy
                if isinstance(strategy, TagBasedCacheStrategy) and tags:
                    strategy.set(cache_key, response, timeout, tags)
                else:
                    strategy.set(cache_key, response, timeout)
            
            return response
        
        # Apply vary_on_headers if specified
        if vary_on:
            wrapper = vary_on_headers(*vary_on)(wrapper)
        
        return wrapper
    return decorator


def cached_method(timeout: Optional[int] = 300,
                  key_func: Optional[Callable] = None,
                  tags_func: Optional[Callable] = None,
                  cache_none: bool = False):
    """
    Cache method results with custom key generation.
    
    Args:
        timeout: Cache timeout in seconds
        key_func: Function to generate cache key
        tags_func: Function to generate tags
        cache_none: Whether to cache None results
    """
    def decorator(method):
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func(self, *args, **kwargs)
            else:
                # Default key generation
                cache_key = f"{self.__class__.__name__}:{method.__name__}:{make_cache_key(*args, **kwargs)}"
            
            # Try to get from cache
            result = cache.get(cache_key)
            
            if result is not None or (result is None and cache.get(f"{cache_key}:none")):
                return result
            
            # Execute method
            result = method(self, *args, **kwargs)
            
            # Cache result
            if result is not None or cache_none:
                cache.set(cache_key, result, timeout)
                
                # Mark None values
                if result is None:
                    cache.set(f"{cache_key}:none", True, timeout)
                
                # Set tags if provided
                if tags_func:
                    tags = tags_func(self, *args, **kwargs)
                    if tags:
                        tag_strategy = TagBasedCacheStrategy()
                        for tag in tags:
                            tag_strategy.register_dependency(cache_key, [tag])
            
            return result
        
        return wrapper
    return decorator


def cached_api(timeout: Optional[int] = 300,
               key_prefix: Optional[str] = None,
               vary_on_auth: bool = True,
               vary_on_params: bool = True,
               cache_errors: bool = False):
    """
    Cache API responses with parameter awareness.
    
    Args:
        timeout: Cache timeout in seconds
        key_prefix: Prefix for cache keys
        vary_on_auth: Vary cache on authentication
        vary_on_params: Vary cache on query parameters
        cache_errors: Whether to cache error responses
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            # Build cache key
            cache_key_parts = [
                key_prefix or f"api:{view_func.__name__}",
                request.method
            ]
            
            # Add path
            cache_key_parts.append(request.path)
            
            # Add query params
            if vary_on_params and request.GET:
                params = sorted(request.GET.items())
                param_str = "&".join(f"{k}={v}" for k, v in params)
                cache_key_parts.append(param_str)
            
            # Add auth info
            if vary_on_auth and request.user.is_authenticated:
                cache_key_parts.append(f"user:{request.user.id}")
            
            cache_key = ":".join(cache_key_parts)
            
            # Try to get from cache
            cached_data = cache.get(cache_key)
            
            if cached_data is not None:
                # Return cached response
                response = HttpResponse(
                    cached_data['content'],
                    content_type=cached_data['content_type'],
                    status=cached_data['status']
                )
                response['X-Cache'] = 'HIT'
                
                # Restore headers
                for header, value in cached_data.get('headers', {}).items():
                    response[header] = value
                
                return response
            
            # Generate response
            response = view_func(request, *args, **kwargs)
            
            # Cache successful responses (or errors if specified)
            if response.status_code == 200 or (cache_errors and response.status_code >= 400):
                # Prepare cache data
                cache_data = {
                    'content': response.content.decode('utf-8') if isinstance(response.content, bytes) else response.content,
                    'content_type': response.get('Content-Type', 'application/json'),
                    'status': response.status_code,
                    'headers': {
                        k: v for k, v in response.items()
                        if k not in ['Content-Type', 'X-Cache']
                    }
                }
                
                # Use shorter timeout for errors
                actual_timeout = timeout if response.status_code == 200 else min(timeout, 60)
                
                cache.set(cache_key, cache_data, actual_timeout)
                response['X-Cache'] = 'MISS'
            
            return response
        
        return wrapper
    return decorator


def smart_cache(base_timeout: int = 300,
                min_timeout: int = 60,
                max_timeout: int = 3600,
                monitor: bool = True):
    """
    Smart caching with adaptive timeout based on access patterns.
    
    Args:
        base_timeout: Base cache timeout
        min_timeout: Minimum adaptive timeout
        max_timeout: Maximum adaptive timeout
        monitor: Whether to monitor cache performance
    """
    # Use adaptive strategy
    strategy = AdaptiveCacheStrategy(base_timeout, min_timeout, max_timeout)
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"smart:{func.__module__}:{func.__name__}:{make_cache_key(*args, **kwargs)}"
            
            # Get from cache
            start_time = time.time()
            result = strategy.get(cache_key)
            
            if result is not None:
                if monitor:
                    response_time = (time.time() - start_time) * 1000
                    cache_monitor.metrics.record_hit(cache_key, response_time)
                return result
            
            # Cache miss - execute function
            if monitor:
                response_time = (time.time() - start_time) * 1000
                cache_monitor.metrics.record_miss(cache_key, response_time)
            
            result = func(*args, **kwargs)
            
            # Set in cache with adaptive timeout
            start_time = time.time()
            strategy.set(cache_key, result)
            
            if monitor:
                response_time = (time.time() - start_time) * 1000
                try:
                    value_size = len(json.dumps(result, default=str))
                except:
                    value_size = len(str(result))
                cache_monitor.metrics.record_set(cache_key, value_size, response_time)
            
            return result
        
        # Add cache management methods
        wrapper.invalidate = lambda: strategy.delete(
            f"smart:{func.__module__}:{func.__name__}:*"
        )
        wrapper.get_stats = lambda: strategy.get_stats(
            f"smart:{func.__module__}:{func.__name__}:*"
        )
        
        return wrapper
    return decorator


def conditional_cache(condition_func: Callable[..., bool],
                      timeout: int = 300):
    """
    Cache only when condition is met.
    
    Args:
        condition_func: Function that returns True to cache
        timeout: Cache timeout
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Check condition
            should_cache = condition_func(*args, **kwargs)
            
            if should_cache:
                # Use caching
                cache_key = f"conditional:{func.__name__}:{make_cache_key(*args, **kwargs)}"
                
                result = cache.get(cache_key)
                if result is not None:
                    return result
                
                result = func(*args, **kwargs)
                cache.set(cache_key, result, timeout)
                
                return result
            else:
                # Skip caching
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def cache_on_success(timeout: int = 300,
                     success_func: Optional[Callable[..., bool]] = None):
    """
    Cache only successful results.
    
    Args:
        timeout: Cache timeout
        success_func: Function to determine success
    """
    def is_success(result):
        if success_func:
            return success_func(result)
        
        # Default success checks
        if hasattr(result, 'status_code'):
            return 200 <= result.status_code < 300
        
        return result is not None
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"success:{func.__name__}:{make_cache_key(*args, **kwargs)}"
            
            # Try cache first
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            
            # Execute function
            result = func(*args, **kwargs)
            
            # Cache if successful
            if is_success(result):
                cache.set(cache_key, result, timeout)
            
            return result
        
        return wrapper
    return decorator


import time