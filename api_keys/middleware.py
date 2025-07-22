"""
Middleware for API Key usage tracking and security.
"""

import time
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse

from .models import APIKey, APIKeyUsage


class APIKeyUsageMiddleware(MiddlewareMixin):
    """
    Middleware to track API key usage and log requests.
    
    Must be placed after authentication middleware to access request.auth.
    """
    
    def process_request(self, request):
        """Process the incoming request."""
        # Store start time for performance tracking
        request._api_key_start_time = time.time()
        return None
    
    def process_response(self, request, response):
        """Process the response and log usage if API key was used."""
        # Check if this was an API key authenticated request
        if (hasattr(request, 'auth') and 
            isinstance(request.auth, APIKey) and
            hasattr(request, '_api_key_start_time')):
            
            # Calculate response time
            response_time_ms = int(
                (time.time() - request._api_key_start_time) * 1000
            )
            
            # Log the usage
            self._log_usage(
                request, 
                request.auth, 
                response.status_code, 
                response_time_ms
            )
        
        return response
    
    def process_exception(self, request, exception):
        """Process exceptions and log them for API key requests."""
        if (hasattr(request, 'auth') and 
            isinstance(request.auth, APIKey) and
            hasattr(request, '_api_key_start_time')):
            
            # Calculate response time
            response_time_ms = int(
                (time.time() - request._api_key_start_time) * 1000
            )
            
            # Log the error
            self._log_usage(
                request,
                request.auth,
                500,  # Internal server error
                response_time_ms,
                str(exception)
            )
        
        return None  # Let Django handle the exception normally
    
    def _log_usage(
        self,
        request,
        api_key,
        status_code,
        response_time_ms,
        error_message=""
    ):
        """Log API key usage."""
        try:
            APIKeyUsage.objects.create(
                api_key=api_key,
                endpoint=request.path,
                method=request.method,
                status_code=status_code,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
                response_time_ms=response_time_ms,
                error_message=error_message
            )
        except Exception:
            # Don't let logging failures break the request
            pass
    
    def _get_client_ip(self, request):
        """Get the client's IP address."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip


class APIKeySecurityMiddleware(MiddlewareMixin):
    """
    Security middleware for API key requests.
    
    Adds security headers and validates request patterns.
    """
    
    def process_response(self, request, response):
        """Add security headers for API key requests."""
        if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
            # Add security headers
            response['X-API-Key-Used'] = 'true'
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-Frame-Options'] = 'DENY'
            response['X-XSS-Protection'] = '1; mode=block'
            
            # Rate limiting header
            api_key = request.auth
            is_within_limit, request_count = api_key.check_rate_limit()
            response['X-RateLimit-Limit'] = str(api_key.rate_limit_per_hour)
            response['X-RateLimit-Remaining'] = str(
                max(0, api_key.rate_limit_per_hour - request_count)
            )
        
        return response