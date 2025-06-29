"""
Gateway Utilities

Helper functions for the API Gateway.
"""

import re
from typing import Optional, Tuple
from django.http import HttpRequest


def get_client_ip(request: HttpRequest) -> str:
    """
    Get client IP address from request.
    
    Handles X-Forwarded-For and other proxy headers.
    
    Args:
        request: HTTP request
        
    Returns:
        Client IP address
    """
    # Check X-Forwarded-For header
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Get first IP in the chain
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        # Check other headers
        ip = request.META.get('HTTP_X_REAL_IP')
        if not ip:
            # Fall back to REMOTE_ADDR
            ip = request.META.get('REMOTE_ADDR', '')
    
    return ip


def parse_rate_limit(rate_limit_str: str) -> Tuple[int, int]:
    """
    Parse rate limit string.
    
    Args:
        rate_limit_str: Rate limit like "100/hour" or "10/minute"
        
    Returns:
        Tuple of (limit, seconds)
    """
    if not rate_limit_str:
        return (0, 0)
    
    match = re.match(r'^(\d+)/(\w+)$', rate_limit_str)
    if not match:
        raise ValueError(f"Invalid rate limit format: {rate_limit_str}")
    
    limit = int(match.group(1))
    period = match.group(2).lower()
    
    # Convert period to seconds
    periods = {
        'second': 1,
        'minute': 60,
        'hour': 3600,
        'day': 86400,
        'week': 604800,
    }
    
    # Handle plural forms
    period = period.rstrip('s')
    
    if period not in periods:
        raise ValueError(f"Unknown period: {period}")
    
    return (limit, periods[period])


def match_path_pattern(pattern: str, path: str) -> Optional[dict]:
    """
    Match URL path against pattern with placeholders.
    
    Args:
        pattern: Pattern like "/users/{id}/posts/{post_id}"
        path: Actual path like "/users/123/posts/456"
        
    Returns:
        Dict of placeholder values or None if no match
    """
    # Convert pattern to regex
    regex_pattern = pattern
    param_names = []
    
    # Find all placeholders
    for match in re.finditer(r'\{(\w+)\}', pattern):
        param_name = match.group(1)
        param_names.append(param_name)
        # Replace with named group
        regex_pattern = regex_pattern.replace(
            match.group(0),
            f'(?P<{param_name}>[^/]+)'
        )
    
    # Add anchors
    regex_pattern = f'^{regex_pattern}$'
    
    # Try to match
    match = re.match(regex_pattern, path)
    if match:
        return match.groupdict()
    
    return None


def build_cache_key(route_path: str, method: str, 
                   query_params: dict, key_params: list) -> str:
    """
    Build cache key for response caching.
    
    Args:
        route_path: Route path
        method: HTTP method
        query_params: Query parameters
        key_params: List of params to include in key
        
    Returns:
        Cache key string
    """
    # Start with method and path
    parts = [f"gateway:{method}:{route_path}"]
    
    # Add specified query params
    if key_params and query_params:
        param_parts = []
        for param in sorted(key_params):
            if param in query_params:
                value = query_params[param]
                param_parts.append(f"{param}={value}")
        
        if param_parts:
            parts.append(':'.join(param_parts))
    
    return ':'.join(parts)


def sanitize_headers(headers: dict) -> dict:
    """
    Remove sensitive headers.
    
    Args:
        headers: Request/response headers
        
    Returns:
        Sanitized headers
    """
    sensitive_headers = {
        'authorization',
        'cookie',
        'x-api-key',
        'x-auth-token',
        'x-csrf-token',
    }
    
    sanitized = {}
    for key, value in headers.items():
        if key.lower() not in sensitive_headers:
            sanitized[key] = value
        else:
            # Mask sensitive values
            sanitized[key] = '***'
    
    return sanitized


def format_size(bytes_size: int) -> str:
    """
    Format byte size in human-readable format.
    
    Args:
        bytes_size: Size in bytes
        
    Returns:
        Formatted string like "1.5 MB"
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    
    return f"{bytes_size:.1f} PB"


def is_json_response(content_type: str) -> bool:
    """
    Check if response is JSON based on content type.
    
    Args:
        content_type: Content-Type header value
        
    Returns:
        True if JSON response
    """
    if not content_type:
        return False
    
    # Extract main type
    main_type = content_type.split(';')[0].strip().lower()
    
    json_types = {
        'application/json',
        'application/hal+json',
        'application/ld+json',
        'application/vnd.api+json',
    }
    
    return main_type in json_types or main_type.endswith('+json')