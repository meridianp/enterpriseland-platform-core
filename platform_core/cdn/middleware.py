"""
CDN Middleware

Middleware for CDN integration and optimization.
"""

import re
import time
import hashlib
from typing import Optional, List, Dict, Any
from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_vary_headers, patch_cache_control
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
import logging

from .providers import get_cdn_provider
from .utils import should_use_cdn, get_asset_version

logger = logging.getLogger(__name__)


class CDNMiddleware(MiddlewareMixin):
    """
    Middleware to handle CDN URL rewriting and optimization.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.cdn_provider = get_cdn_provider()
        self.static_url = settings.STATIC_URL
        self.media_url = settings.MEDIA_URL
        
        # Patterns to rewrite
        self.static_pattern = re.compile(
            rf'(src|href)=["\']({re.escape(self.static_url)}[^"\']+)["\']'
        )
        self.media_pattern = re.compile(
            rf'(src|href)=["\']({re.escape(self.media_url)}[^"\']+)["\']'
        )
        
        # Exclude patterns
        self.exclude_paths = getattr(
            settings, 
            'CDN_EXCLUDE_PATHS', 
            ['/admin/', '/api/', '/__debug__/']
        )
    
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Process incoming request."""
        # Skip CDN for excluded paths
        for path in self.exclude_paths:
            if request.path.startswith(path):
                request._skip_cdn = True
                return None
        
        # Add CDN context
        request.cdn_enabled = self.cdn_provider and self.cdn_provider.is_enabled()
        
        return None
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Process response to rewrite URLs to CDN."""
        # Skip if CDN is disabled or excluded
        if getattr(request, '_skip_cdn', False) or not request.cdn_enabled:
            return response
        
        # Only process HTML responses
        if not response.get('Content-Type', '').startswith('text/html'):
            return response
        
        # Skip if response is too large (>1MB)
        if len(response.content) > 1048576:
            return response
        
        # Rewrite URLs in response
        if response.status_code == 200:
            try:
                content = response.content.decode('utf-8')
                
                # Rewrite static URLs
                content = self.static_pattern.sub(
                    lambda m: self._rewrite_url(m, 'static'),
                    content
                )
                
                # Rewrite media URLs
                content = self.media_pattern.sub(
                    lambda m: self._rewrite_url(m, 'media'),
                    content
                )
                
                response.content = content.encode('utf-8')
                response['Content-Length'] = len(response.content)
                
            except Exception as e:
                logger.error(f"Error rewriting URLs: {e}")
        
        return response
    
    def _rewrite_url(self, match, url_type):
        """Rewrite matched URL to CDN."""
        attr = match.group(1)
        url = match.group(2)
        
        # Get path relative to static/media URL
        if url_type == 'static':
            path = url[len(self.static_url):]
        else:
            path = url[len(self.media_url):]
        
        # Get CDN URL
        cdn_url = self.cdn_provider.get_url(path)
        
        # Add version parameter for cache busting
        version = get_asset_version(path)
        if version:
            cdn_url = f"{cdn_url}?v={version}"
        
        return f'{attr}="{cdn_url}"'


class CDNHeadersMiddleware(MiddlewareMixin):
    """
    Middleware to set appropriate CDN and caching headers.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Cache control settings
        self.static_cache_age = getattr(settings, 'CDN_STATIC_CACHE_AGE', 31536000)  # 1 year
        self.media_cache_age = getattr(settings, 'CDN_MEDIA_CACHE_AGE', 86400)  # 1 day
        self.html_cache_age = getattr(settings, 'CDN_HTML_CACHE_AGE', 300)  # 5 minutes
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Add CDN-related headers to response."""
        # Skip if response already has cache headers
        if response.has_header('Cache-Control'):
            return response
        
        path = request.path
        
        # Set cache headers based on content type
        if path.startswith(settings.STATIC_URL):
            # Static files - long cache
            patch_cache_control(
                response,
                max_age=self.static_cache_age,
                public=True,
                immutable=True
            )
            response['Vary'] = 'Accept-Encoding'
            
        elif path.startswith(settings.MEDIA_URL):
            # Media files - medium cache
            patch_cache_control(
                response,
                max_age=self.media_cache_age,
                public=True
            )
            response['Vary'] = 'Accept-Encoding'
            
        elif response.get('Content-Type', '').startswith('text/html'):
            # HTML - short cache
            if response.status_code == 200:
                patch_cache_control(
                    response,
                    max_age=self.html_cache_age,
                    public=True,
                    must_revalidate=True
                )
                patch_vary_headers(response, ['Accept-Encoding', 'Accept'])
        
        # Add security headers
        self._add_security_headers(response)
        
        # Add performance headers
        self._add_performance_headers(request, response)
        
        return response
    
    def _add_security_headers(self, response: HttpResponse):
        """Add security-related headers."""
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # XSS protection
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    def _add_performance_headers(self, request: HttpRequest, response: HttpResponse):
        """Add performance-related headers."""
        # Server timing
        if hasattr(request, '_start_time'):
            duration = (time.time() - request._start_time) * 1000
            response['Server-Timing'] = f'total;dur={duration:.2f}'
        
        # Early hints for resource preloading
        if hasattr(request, '_preload_resources'):
            links = []
            for resource in request._preload_resources:
                links.append(f'<{resource["url"]}>; rel=preload; as={resource["as"]}')
            
            if links:
                response['Link'] = ', '.join(links)


class CDNPurgeMiddleware(MiddlewareMixin):
    """
    Middleware to handle automatic CDN cache purging.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.cdn_provider = get_cdn_provider()
        
        # Purge settings
        self.auto_purge = getattr(settings, 'CDN_AUTO_PURGE', True)
        self.purge_patterns = getattr(settings, 'CDN_PURGE_PATTERNS', [])
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Check if CDN purge is needed based on response."""
        if not self.auto_purge or not self.cdn_provider:
            return response
        
        # Only purge on successful POST/PUT/DELETE requests
        if request.method in ['POST', 'PUT', 'DELETE'] and 200 <= response.status_code < 300:
            # Check if path matches purge patterns
            paths_to_purge = self._get_purge_paths(request)
            
            if paths_to_purge:
                # Queue purge operation (async)
                self._queue_purge(paths_to_purge)
        
        return response
    
    def _get_purge_paths(self, request: HttpRequest) -> List[str]:
        """Get paths that should be purged based on request."""
        paths = []
        
        # Check configured patterns
        for pattern in self.purge_patterns:
            if re.match(pattern['match'], request.path):
                paths.extend(pattern.get('purge_paths', []))
        
        # Add related paths based on request
        if request.path.startswith('/api/'):
            # API changes might affect cached pages
            if 'assessments' in request.path:
                paths.extend(['/assessments/', '/dashboard/'])
            elif 'users' in request.path:
                paths.extend(['/users/', '/profiles/'])
        
        return paths
    
    def _queue_purge(self, paths: List[str]):
        """Queue CDN purge operation."""
        # Use cache to deduplicate purge requests
        cache_key = f"cdn_purge:{hashlib.md5(''.join(paths).encode()).hexdigest()}"
        
        if not cache.get(cache_key):
            # Mark as queued
            cache.set(cache_key, True, 60)  # 1 minute deduplication
            
            # In production, this would queue to Celery
            try:
                from celery import current_app
                current_app.send_task(
                    'platform_core.tasks.purge_cdn_cache',
                    args=[paths]
                )
            except:
                # Fallback to synchronous purge
                try:
                    self.cdn_provider.purge(paths)
                except Exception as e:
                    logger.error(f"CDN purge failed: {e}")


class CDNDebugMiddleware(MiddlewareMixin):
    """
    Debug middleware for CDN development.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = settings.DEBUG and getattr(settings, 'CDN_DEBUG', False)
    
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Add timing information."""
        if self.enabled:
            request._start_time = time.time()
            request._cdn_debug = []
        
        return None
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Add debug information to response."""
        if not self.enabled or not hasattr(request, '_cdn_debug'):
            return response
        
        # Add debug headers
        if hasattr(request, '_start_time'):
            duration = (time.time() - request._start_time) * 1000
            response['X-CDN-Time'] = f'{duration:.2f}ms'
        
        # Add debug info about CDN usage
        cdn_info = {
            'enabled': getattr(request, 'cdn_enabled', False),
            'provider': getattr(settings, 'CDN_PROVIDER', 'none'),
            'rewritten_urls': len(getattr(request, '_cdn_urls', [])),
            'cache_headers': dict(response.items())
        }
        
        response['X-CDN-Debug'] = json.dumps(cdn_info)
        
        return response


import json