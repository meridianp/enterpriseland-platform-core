"""
Rate Limiting Decorators

Decorators for applying rate limits to specific views or methods.
"""

import functools
from typing import Optional, Union, Callable
from django.http import JsonResponse
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from .backends import get_backend
from .models import RateLimitViolation
from ..auth.authentication import get_client_ip


def ratelimit(
    key: Optional[str] = None,
    rate: str = '100/m',
    method: Optional[Union[str, list]] = None,
    block: bool = True,
    key_func: Optional[Callable] = None
):
    """
    Rate limit decorator for views.
    
    Args:
        key: Key pattern for rate limiting (default: user or IP)
        rate: Rate limit string (e.g., '100/m', '10/s', '1000/h')
        method: HTTP method(s) to limit (default: all)
        block: Whether to block requests (True) or just annotate (False)
        key_func: Custom function to generate cache key
        
    Examples:
        @ratelimit(rate='10/m')
        def my_view(request):
            ...
            
        @ratelimit(key='user', rate='100/h', method='POST')
        def create_view(request):
            ...
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            # Check if method matches
            if method:
                methods = [method] if isinstance(method, str) else method
                if request.method not in methods:
                    return view_func(request, *args, **kwargs)
            
            # Parse rate limit
            limit, period = parse_rate(rate)
            
            # Get rate limit key
            if key_func:
                cache_key = key_func(request)
            else:
                cache_key = get_cache_key(request, key)
            
            # Check rate limit
            backend = get_backend()
            allowed, metadata = backend.check_rate_limit(
                key=f"decorator:{cache_key}",
                limit=limit,
                window=period
            )
            
            # Add rate limit info to request
            request.rate_limited = not allowed
            request.rate_limit_metadata = metadata
            
            # Add headers
            if not hasattr(request, 'rate_limit_headers'):
                request.rate_limit_headers = {}
            
            request.rate_limit_headers.update({
                'X-RateLimit-Limit': str(metadata['limit']),
                'X-RateLimit-Remaining': str(metadata['remaining']),
                'X-RateLimit-Reset': str(metadata['reset']),
            })
            
            if not allowed and block:
                # Log violation
                log_violation(request, limit, period, metadata)
                
                # Return rate limit response
                response = JsonResponse({
                    'error': 'Rate limit exceeded',
                    'retry_after': metadata.get('retry_after', 60)
                }, status=429)
                
                if metadata.get('retry_after'):
                    response['Retry-After'] = str(metadata['retry_after'])
                
                return response
            
            # Call the view
            response = view_func(request, *args, **kwargs)
            
            # Add headers to response
            for header, value in request.rate_limit_headers.items():
                response[header] = value
            
            return response
        
        return wrapped_view
    return decorator


def parse_rate(rate: str) -> tuple:
    """
    Parse rate string into limit and period.
    
    Args:
        rate: Rate string (e.g., '100/m', '10/s', '1000/h')
        
    Returns:
        Tuple of (limit, period_seconds)
    """
    periods = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
    }
    
    parts = rate.split('/')
    if len(parts) != 2:
        raise ValueError(f"Invalid rate format: {rate}")
    
    try:
        limit = int(parts[0])
    except ValueError:
        raise ValueError(f"Invalid limit in rate: {rate}")
    
    period_char = parts[1].lower()
    if period_char not in periods:
        raise ValueError(f"Invalid period in rate: {rate}")
    
    return limit, periods[period_char]


def get_cache_key(request, key: Optional[str] = None) -> str:
    """
    Get cache key for rate limiting.
    
    Args:
        request: Django request object
        key: Key type ('user', 'ip', 'user_or_ip', etc.)
        
    Returns:
        Cache key string
    """
    if key == 'user':
        if request.user.is_authenticated:
            return f"user:{request.user.id}"
        else:
            return f"anon:{get_client_ip(request)}"
    
    elif key == 'ip':
        return f"ip:{get_client_ip(request)}"
    
    elif key == 'user_or_ip':
        if request.user.is_authenticated:
            return f"user:{request.user.id}"
        else:
            return f"ip:{get_client_ip(request)}"
    
    elif key and '{' in key:
        # Format string with request attributes
        return key.format(
            user=request.user.id if request.user.is_authenticated else 'anon',
            ip=get_client_ip(request),
            path=request.path,
            method=request.method
        )
    
    else:
        # Default to user or IP
        if request.user.is_authenticated:
            return f"user:{request.user.id}"
        else:
            return f"ip:{get_client_ip(request)}"


def log_violation(request, limit: int, period: int, metadata: dict):
    """Log rate limit violation"""
    RateLimitViolation.objects.create(
        user=request.user if request.user.is_authenticated else None,
        ip_address=get_client_ip(request),
        endpoint=request.path,
        method=request.method,
        limit_exceeded=limit,
        request_count=metadata.get('current_requests', 0),
        window_seconds=period,
        action_taken='throttled',
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        request_data={
            'method': request.method,
            'path': request.path,
        }
    )


# Convenience decorators with common configurations

def ratelimit_user(rate: str = '100/m', **kwargs):
    """Rate limit by authenticated user"""
    return ratelimit(key='user', rate=rate, **kwargs)


def ratelimit_ip(rate: str = '100/m', **kwargs):
    """Rate limit by IP address"""
    return ratelimit(key='ip', rate=rate, **kwargs)


def ratelimit_post(rate: str = '10/m', **kwargs):
    """Rate limit POST requests"""
    return ratelimit(rate=rate, method='POST', **kwargs)


def ratelimit_expensive(rate: str = '10/h', **kwargs):
    """Rate limit expensive operations"""
    return ratelimit(rate=rate, **kwargs)


# Method decorator for class-based views
def method_ratelimit(rate: str = '100/m', **kwargs):
    """
    Rate limit decorator for class methods.
    
    Usage:
        class MyView(APIView):
            @method_ratelimit(rate='10/m')
            def post(self, request):
                ...
    """
    def decorator(method):
        @functools.wraps(method)
        def wrapped(self, request, *args, **kwargs):
            # Create a partial function with self bound
            view_func = functools.partial(method, self)
            
            # Apply rate limit decorator
            limited_func = ratelimit(rate=rate, **kwargs)(view_func)
            
            # Call the limited function
            return limited_func(request, *args, **kwargs)
        
        return wrapped
    return decorator


# Conditional rate limiting
def ratelimit_if(
    condition: Callable[[Any], bool],
    rate: str = '100/m',
    **kwargs
):
    """
    Apply rate limiting conditionally.
    
    Args:
        condition: Function that returns True if rate limit should apply
        rate: Rate limit string
        **kwargs: Other arguments for ratelimit decorator
        
    Usage:
        @ratelimit_if(lambda req: not req.user.is_staff, rate='10/m')
        def my_view(request):
            ...
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if condition(request):
                # Apply rate limiting
                return ratelimit(rate=rate, **kwargs)(view_func)(request, *args, **kwargs)
            else:
                # Skip rate limiting
                return view_func(request, *args, **kwargs)
        
        return wrapped_view
    return decorator