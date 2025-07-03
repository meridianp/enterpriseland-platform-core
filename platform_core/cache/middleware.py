"""
Cache Middleware

Provides middleware for view and page caching.
"""

import hashlib
import logging
from typing import Optional, Dict, Any, List
from django.conf import settings
from django.core.cache import caches
from django.http import HttpRequest, HttpResponse
from django.utils.cache import (
    get_cache_key, learn_cache_key, patch_response_headers,
    patch_cache_control, patch_vary_headers
)
from django.utils.deprecation import MiddlewareMixin

from .cache import cache_manager

logger = logging.getLogger(__name__)


class EnhancedCacheMiddleware(MiddlewareMixin):
    """
    Enhanced cache middleware with additional features.
    
    Features:
    - Multiple cache backend support
    - Conditional caching based on request attributes
    - Cache warming support
    - Cache statistics
    - Custom key generation
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.cache_timeout = getattr(settings, 'CACHE_MIDDLEWARE_SECONDS', 600)
        self.cache_backend = getattr(settings, 'CACHE_MIDDLEWARE_BACKEND', 'default')
        self.key_prefix = getattr(settings, 'CACHE_MIDDLEWARE_KEY_PREFIX', 'views')
        self.cache_anonymous_only = getattr(
            settings, 'CACHE_MIDDLEWARE_ANONYMOUS_ONLY', True
        )
        self.cache_get_only = getattr(settings, 'CACHE_MIDDLEWARE_GET_ONLY', True)
        self.excluded_paths = getattr(settings, 'CACHE_MIDDLEWARE_EXCLUDED_PATHS', [])
        self.cache_control_max_age = getattr(
            settings, 'CACHE_MIDDLEWARE_MAX_AGE', self.cache_timeout
        )
        
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """
        Try to fetch response from cache.
        """
        # Skip if caching should be bypassed
        if not self._should_cache_request(request):
            return None
            
        # Generate cache key
        cache_key = self._get_cache_key(request)
        if not cache_key:
            return None
            
        # Try to get cached response
        cached_response = cache_manager.get(
            cache_key,
            backend=self.cache_backend,
            prefix=self.key_prefix
        )
        
        if cached_response is not None:
            # Update statistics
            self._update_stats('hit', request)
            
            # Add cache headers
            cached_response['X-Cache'] = 'HIT'
            cached_response['X-Cache-Backend'] = self.cache_backend
            
            logger.debug(f"Cache hit for {request.path}")
            return cached_response
            
        # Update statistics
        self._update_stats('miss', request)
        
        return None
    
    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        """
        Cache the response if appropriate.
        """
        # Skip if response shouldn't be cached
        if not self._should_cache_response(request, response):
            response['X-Cache'] = 'BYPASS'
            return response
            
        # Don't cache responses with specific status codes
        if response.status_code not in (200, 301, 302, 304):
            response['X-Cache'] = 'BYPASS'
            return response
            
        # Generate cache key
        cache_key = self._get_cache_key(request)
        if not cache_key:
            response['X-Cache'] = 'BYPASS'
            return response
            
        # Prepare response for caching
        patch_response_headers(response, self.cache_timeout)
        
        # Cache the response
        timeout = self._get_cache_timeout(request, response)
        tags = self._get_cache_tags(request, response)
        
        cache_manager.set(
            cache_key,
            response,
            timeout=timeout,
            backend=self.cache_backend,
            prefix=self.key_prefix,
            tags=tags
        )
        
        # Add cache headers
        response['X-Cache'] = 'MISS'
        response['X-Cache-Backend'] = self.cache_backend
        response['X-Cache-Key'] = cache_key
        
        logger.debug(f"Cached response for {request.path}")
        
        return response
    
    def _should_cache_request(self, request: HttpRequest) -> bool:
        """
        Determine if request should be cached.
        """
        # Only cache GET/HEAD requests if configured
        if self.cache_get_only and request.method not in ('GET', 'HEAD'):
            return False
            
        # Skip authenticated users if configured
        if self.cache_anonymous_only and request.user.is_authenticated:
            return False
            
        # Skip excluded paths
        for path in self.excluded_paths:
            if request.path.startswith(path):
                return False
                
        # Skip if no-cache header present
        if request.META.get('HTTP_CACHE_CONTROL', '').lower() == 'no-cache':
            return False
            
        return True
    
    def _should_cache_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> bool:
        """
        Determine if response should be cached.
        """
        # Don't cache if request shouldn't be cached
        if not self._should_cache_request(request):
            return False
            
        # Don't cache private responses
        cache_control = response.get('Cache-Control', '')
        if 'private' in cache_control or 'no-store' in cache_control:
            return False
            
        # Don't cache responses with Set-Cookie
        if response.has_header('Set-Cookie'):
            return False
            
        return True
    
    def _get_cache_key(self, request: HttpRequest) -> Optional[str]:
        """
        Generate cache key for request.
        """
        # Use Django's cache key generation
        cache_key = get_cache_key(
            request,
            self.key_prefix,
            request.method,
            cache=caches[self.cache_backend]
        )
        
        if not cache_key:
            # Learn cache key for future requests
            cache_key = learn_cache_key(
                request,
                HttpResponse(),
                self.cache_timeout,
                self.key_prefix,
                cache=caches[self.cache_backend]
            )
            
        return cache_key
    
    def _get_cache_timeout(
        self, request: HttpRequest, response: HttpResponse
    ) -> int:
        """
        Get cache timeout for response.
        """
        # Check for custom timeout in response
        if hasattr(response, 'cache_timeout'):
            return response.cache_timeout
            
        # Check Cache-Control max-age
        cache_control = response.get('Cache-Control', '')
        if 'max-age=' in cache_control:
            try:
                max_age = int(
                    cache_control.split('max-age=')[1].split(',')[0]
                )
                return min(max_age, self.cache_timeout)
            except (ValueError, IndexError):
                pass
                
        return self.cache_timeout
    
    def _get_cache_tags(
        self, request: HttpRequest, response: HttpResponse
    ) -> Optional[List[str]]:
        """
        Get cache tags for response.
        """
        tags = []
        
        # Add view-based tag
        if hasattr(request, 'resolver_match') and request.resolver_match:
            view_name = request.resolver_match.view_name
            if view_name:
                tags.append(f"view:{view_name}")
                
        # Add custom tags from response
        if hasattr(response, 'cache_tags'):
            tags.extend(response.cache_tags)
            
        # Add content-type tag
        content_type = response.get('Content-Type', '').split(';')[0]
        if content_type:
            tags.append(f"type:{content_type}")
            
        return tags if tags else None
    
    def _update_stats(self, stat_type: str, request: HttpRequest):
        """
        Update cache statistics.
        """
        stats_key = f"cache:stats:{stat_type}:{request.method}"
        cache_manager.increment(stats_key, backend='redis')
        
        # Update path-specific stats
        path_key = f"cache:stats:path:{request.path}:{stat_type}"
        cache_manager.increment(path_key, backend='redis')


class ConditionalCacheMiddleware(MiddlewareMixin):
    """
    Conditional caching based on request/response attributes.
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.conditions = getattr(settings, 'CACHE_CONDITIONS', {})
        
    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        """
        Apply conditional caching rules.
        """
        # Check each condition
        for condition_name, condition_config in self.conditions.items():
            if self._check_condition(request, response, condition_config):
                # Apply caching configuration
                timeout = condition_config.get('timeout', 300)
                cache_control = condition_config.get('cache_control', {})
                
                # Set cache timeout
                response.cache_timeout = timeout
                
                # Apply cache control headers
                if cache_control:
                    patch_cache_control(response, **cache_control)
                    
                # Add vary headers if specified
                vary_on = condition_config.get('vary_on', [])
                if vary_on:
                    patch_vary_headers(response, vary_on)
                    
                logger.debug(
                    f"Applied cache condition '{condition_name}' to {request.path}"
                )
                break
                
        return response
    
    def _check_condition(
        self,
        request: HttpRequest,
        response: HttpResponse,
        config: Dict[str, Any]
    ) -> bool:
        """
        Check if condition matches.
        """
        # Check path patterns
        path_patterns = config.get('path_patterns', [])
        if path_patterns:
            path_match = any(
                request.path.startswith(pattern) for pattern in path_patterns
            )
            if not path_match:
                return False
                
        # Check content types
        content_types = config.get('content_types', [])
        if content_types:
            response_type = response.get('Content-Type', '').split(';')[0]
            if response_type not in content_types:
                return False
                
        # Check custom condition function
        condition_func = config.get('condition')
        if condition_func:
            if not condition_func(request, response):
                return False
                
        return True


class CacheWarmingMiddleware(MiddlewareMixin):
    """
    Middleware to support cache warming.
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.warming_enabled = getattr(settings, 'CACHE_WARMING_ENABLED', False)
        self.warming_paths = getattr(settings, 'CACHE_WARMING_PATHS', [])
        
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """
        Check if this is a cache warming request.
        """
        if not self.warming_enabled:
            return None
            
        # Check for warming header
        if request.META.get('HTTP_X_CACHE_WARM') != 'true':
            return None
            
        # Verify path is in warming list
        if request.path not in self.warming_paths:
            return HttpResponse('Path not configured for warming', status=403)
            
        # Mark request as warming
        request.is_warming = True
        
        return None
    
    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        """
        Handle cache warming response.
        """
        if getattr(request, 'is_warming', False):
            # Force cache the response
            response.cache_timeout = getattr(
                settings, 'CACHE_WARMING_TIMEOUT', 3600
            )
            response['X-Cache-Warming'] = 'true'
            
        return response


class APICacheMiddleware(MiddlewareMixin):
    """
    Specialized caching for API endpoints.
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.api_prefix = getattr(settings, 'API_URL_PREFIX', '/api/')
        self.default_timeout = getattr(settings, 'API_CACHE_TIMEOUT', 300)
        self.cache_backend = 'redis'  # Use Redis for API caching
        
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """
        Try to serve API response from cache.
        """
        # Only cache API endpoints
        if not request.path.startswith(self.api_prefix):
            return None
            
        # Only cache GET requests
        if request.method != 'GET':
            return None
            
        # Generate cache key including query params
        cache_key = self._generate_api_cache_key(request)
        
        # Try to get from cache
        cached_data = cache_manager.get(
            cache_key,
            backend=self.cache_backend,
            prefix='api'
        )
        
        if cached_data:
            # Create response from cached data
            response = HttpResponse(
                cached_data['content'],
                content_type=cached_data['content_type'],
                status=cached_data['status']
            )
            
            # Restore headers
            for header, value in cached_data.get('headers', {}).items():
                response[header] = value
                
            response['X-API-Cache'] = 'HIT'
            return response
            
        return None
    
    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        """
        Cache API response.
        """
        # Only cache successful API responses
        if (
            request.path.startswith(self.api_prefix) and
            request.method == 'GET' and
            response.status_code == 200
        ):
            cache_key = self._generate_api_cache_key(request)
            
            # Prepare data for caching
            cache_data = {
                'content': response.content.decode('utf-8'),
                'content_type': response.get('Content-Type'),
                'status': response.status_code,
                'headers': {
                    'ETag': response.get('ETag', ''),
                    'Last-Modified': response.get('Last-Modified', ''),
                }
            }
            
            # Get timeout from response or use default
            timeout = getattr(response, 'cache_timeout', self.default_timeout)
            
            # Cache with tags for invalidation
            tags = ['api', f"endpoint:{request.path}"]
            if hasattr(response, 'cache_tags'):
                tags.extend(response.cache_tags)
                
            cache_manager.set(
                cache_key,
                cache_data,
                timeout=timeout,
                backend=self.cache_backend,
                prefix='api',
                tags=tags
            )
            
            response['X-API-Cache'] = 'MISS'
            
        return response
    
    def _generate_api_cache_key(self, request: HttpRequest) -> str:
        """
        Generate cache key for API request.
        """
        # Include path and query params
        key_parts = [
            request.path,
            request.GET.urlencode() if request.GET else ''
        ]
        
        # Include authentication info if needed
        if request.user.is_authenticated:
            key_parts.append(f"user:{request.user.id}")
            
        # Include important headers
        for header in ['Accept', 'Accept-Language']:
            value = request.META.get(f'HTTP_{header.upper().replace("-", "_")}')
            if value:
                key_parts.append(f"{header}:{value}")
                
        # Generate hash of key parts
        key_string = ':'.join(filter(None, key_parts))
        return hashlib.md5(key_string.encode()).hexdigest()