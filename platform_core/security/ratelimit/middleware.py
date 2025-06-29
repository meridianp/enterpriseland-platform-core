"""
Rate Limiting Middleware

Django middleware for applying rate limits to requests.
"""

import re
import json
from typing import Optional, List, Tuple
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone

from .models import RateLimitRule, RateLimitViolation, IPWhitelist, UserRateLimit
from .backends import get_backend
from ..auth.authentication import get_client_ip


class RateLimitMiddleware(MiddlewareMixin):
    """
    Middleware to enforce rate limits on API requests.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.backend = get_backend()
        self.whitelist_cache_time = 300  # 5 minutes
        
        # Compile regex patterns for excluded paths
        excluded_paths = getattr(settings, 'RATELIMIT_EXCLUDE_PATHS', [])
        self.excluded_patterns = [re.compile(pattern) for pattern in excluded_paths]
    
    def process_request(self, request):
        """Process incoming request for rate limiting"""
        # Skip if path is excluded
        if self._is_path_excluded(request.path):
            return None
        
        # Get client IP
        ip_address = get_client_ip(request)
        
        # Check IP whitelist
        if self._is_ip_whitelisted(ip_address):
            return None
        
        # Get applicable rate limit rules
        rules = self._get_applicable_rules(request)
        
        # Check each rule
        for rule in rules:
            identifier = self._get_identifier(request, rule, ip_address)
            
            # Check custom user limits first
            custom_limit = self._get_custom_user_limit(request.user)
            if custom_limit:
                limit = custom_limit.rate_limit
                window = 60  # Custom limits are per minute
                burst = custom_limit.burst_limit
            else:
                limit = rule.rate_limit
                window = rule.per_seconds
                burst = rule.burst_limit
            
            # Check rate limit
            allowed, metadata = self.backend.check_rate_limit(
                key=rule.get_cache_key(identifier),
                limit=limit,
                window=window,
                burst=burst
            )
            
            if not allowed:
                # Log violation
                self._log_violation(
                    request=request,
                    rule=rule,
                    ip_address=ip_address,
                    metadata=metadata
                )
                
                # Take action based on rule
                return self._handle_rate_limit_exceeded(
                    request=request,
                    rule=rule,
                    metadata=metadata
                )
            
            # Add rate limit headers to request for later use
            if not hasattr(request, 'rate_limit_headers'):
                request.rate_limit_headers = {}
            
            request.rate_limit_headers.update({
                'X-RateLimit-Limit': str(metadata['limit']),
                'X-RateLimit-Remaining': str(metadata['remaining']),
                'X-RateLimit-Reset': str(metadata['reset']),
            })
        
        return None
    
    def process_response(self, request, response):
        """Add rate limit headers to response"""
        if hasattr(request, 'rate_limit_headers'):
            for header, value in request.rate_limit_headers.items():
                response[header] = value
        
        return response
    
    def _is_path_excluded(self, path: str) -> bool:
        """Check if path is excluded from rate limiting"""
        for pattern in self.excluded_patterns:
            if pattern.match(path):
                return True
        return False
    
    def _is_ip_whitelisted(self, ip_address: str) -> bool:
        """Check if IP is whitelisted"""
        # Check cache first
        cache_key = f"ip_whitelist:{ip_address}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        # Check database
        whitelisted = IPWhitelist.objects.filter(
            ip_address=ip_address,
            is_active=True
        ).exclude(
            expires_at__lt=timezone.now()
        ).exists()
        
        # Cache result
        cache.set(cache_key, whitelisted, self.whitelist_cache_time)
        
        return whitelisted
    
    def _get_applicable_rules(self, request) -> List[RateLimitRule]:
        """Get rate limit rules applicable to this request"""
        # Get all active rules
        rules = RateLimitRule.objects.filter(
            is_active=True
        ).order_by('-priority')
        
        applicable = []
        
        for rule in rules:
            # Check endpoint pattern
            if rule.endpoint_pattern:
                if not re.match(rule.endpoint_pattern, request.path):
                    continue
            
            # Check user group
            if rule.user_group and request.user.is_authenticated:
                if not request.user.groups.filter(name=rule.user_group).exists():
                    continue
            
            applicable.append(rule)
        
        return applicable
    
    def _get_identifier(self, request, rule: RateLimitRule, ip_address: str) -> str:
        """Get identifier for rate limiting based on strategy"""
        if rule.strategy == 'user':
            if request.user.is_authenticated:
                return f"user:{request.user.id}"
            else:
                return f"anon:{ip_address}"
        
        elif rule.strategy == 'ip':
            return f"ip:{ip_address}"
        
        elif rule.strategy == 'user_ip':
            if request.user.is_authenticated:
                return f"user_ip:{request.user.id}:{ip_address}"
            else:
                return f"anon_ip:{ip_address}"
        
        elif rule.strategy == 'global':
            return "global"
        
        return ip_address
    
    def _get_custom_user_limit(self, user) -> Optional[UserRateLimit]:
        """Get custom rate limit for user if exists"""
        if not user.is_authenticated:
            return None
        
        try:
            limit = user.custom_rate_limit
            if limit.is_valid():
                return limit
        except UserRateLimit.DoesNotExist:
            pass
        
        return None
    
    def _log_violation(self, request, rule: RateLimitRule, ip_address: str, metadata: dict):
        """Log rate limit violation"""
        # Extract sanitized request data
        request_data = {
            'method': request.method,
            'path': request.path,
            'query_params': dict(request.GET),
        }
        
        RateLimitViolation.objects.create(
            user=request.user if request.user.is_authenticated else None,
            ip_address=ip_address,
            endpoint=request.path,
            method=request.method,
            rule=rule,
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            request_data=request_data,
            limit_exceeded=metadata['limit'],
            request_count=metadata.get('current_requests', 0),
            window_seconds=rule.per_seconds,
            action_taken=rule.action
        )
    
    def _handle_rate_limit_exceeded(self, request, rule: RateLimitRule, metadata: dict):
        """Handle rate limit exceeded based on rule action"""
        if rule.action == 'throttle':
            response = JsonResponse({
                'error': 'Rate limit exceeded',
                'retry_after': metadata.get('retry_after', 60)
            }, status=429)
            
            # Add retry-after header
            if metadata.get('retry_after'):
                response['Retry-After'] = str(metadata['retry_after'])
            
            return response
        
        elif rule.action == 'block':
            return JsonResponse({
                'error': 'Access denied due to rate limit'
            }, status=403)
        
        elif rule.action == 'captcha':
            return JsonResponse({
                'error': 'Rate limit exceeded',
                'captcha_required': True,
                'captcha_url': '/api/security/captcha/'
            }, status=429)
        
        elif rule.action == 'log_only':
            # Just log, don't block
            return None
        
        # Default to throttle
        return JsonResponse({
            'error': 'Rate limit exceeded'
        }, status=429)


class APIRateLimitMiddleware(RateLimitMiddleware):
    """
    Specialized rate limit middleware for API endpoints.
    
    Provides more granular control for API-specific rate limiting.
    """
    
    def __init__(self, get_response):
        super().__init__(get_response)
        
        # API-specific configuration
        self.api_prefix = getattr(settings, 'API_PREFIX', '/api/')
        self.default_limits = {
            'GET': (100, 60),      # 100 requests per minute
            'POST': (50, 60),      # 50 requests per minute
            'PUT': (50, 60),       # 50 requests per minute
            'DELETE': (20, 60),    # 20 requests per minute
        }
    
    def process_request(self, request):
        """Process API requests with method-specific limits"""
        # Only apply to API endpoints
        if not request.path.startswith(self.api_prefix):
            return None
        
        # Check for API key authentication
        api_key = request.META.get('HTTP_X_API_KEY')
        if api_key and self._validate_api_key(api_key):
            # Apply different limits for API key users
            return self._process_api_key_request(request, api_key)
        
        # Use parent implementation for regular requests
        return super().process_request(request)
    
    def _validate_api_key(self, api_key: str) -> bool:
        """Validate API key"""
        # Check cache first
        cache_key = f"api_key_valid:{api_key}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        # In production, validate against database
        # For now, just check format
        valid = len(api_key) == 32 and api_key.isalnum()
        
        # Cache result
        cache.set(cache_key, valid, 300)
        
        return valid
    
    def _process_api_key_request(self, request, api_key: str):
        """Process request with API key authentication"""
        # API key users get higher limits
        method_limits = {
            'GET': (1000, 60),     # 1000 requests per minute
            'POST': (500, 60),     # 500 requests per minute
            'PUT': (500, 60),      # 500 requests per minute
            'DELETE': (200, 60),   # 200 requests per minute
        }
        
        limit, window = method_limits.get(request.method, (100, 60))
        
        # Check rate limit
        identifier = f"api_key:{api_key}"
        allowed, metadata = self.backend.check_rate_limit(
            key=f"api:{identifier}:{request.method}",
            limit=limit,
            window=window
        )
        
        if not allowed:
            return JsonResponse({
                'error': 'API rate limit exceeded',
                'retry_after': metadata.get('retry_after', 60)
            }, status=429)
        
        # Add headers
        request.rate_limit_headers = {
            'X-RateLimit-Limit': str(metadata['limit']),
            'X-RateLimit-Remaining': str(metadata['remaining']),
            'X-RateLimit-Reset': str(metadata['reset']),
        }
        
        return None