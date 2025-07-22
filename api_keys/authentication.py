"""
API Key authentication backend.

Provides DRF authentication class that works alongside JWT authentication,
supporting both header and query parameter authentication.
"""

import time
from typing import Optional, Tuple

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework import authentication, exceptions
from rest_framework.request import Request

from .models import APIKey, APIKeyUsage

User = get_user_model()


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    API Key authentication for DRF.
    
    Supports authentication via:
    - Authorization header: "Bearer <api_key>"
    - X-API-Key header: "<api_key>"
    - Query parameter: ?api_key=<api_key>
    """
    
    def authenticate(self, request: Request) -> Optional[Tuple[User, APIKey]]:
        """
        Authenticate the request and return a tuple of (user, api_key).
        
        Returns None if authentication is not attempted.
        Raises AuthenticationFailed if authentication fails.
        """
        # Track request start time for performance metrics
        start_time = time.time()
        
        # Try to get API key from various sources
        api_key = self._get_api_key(request)
        if not api_key:
            return None
        
        # Verify the API key
        api_key_obj = APIKey.objects.verify_key(api_key)
        if not api_key_obj:
            self._log_failed_attempt(request, api_key, "Invalid API key")
            raise exceptions.AuthenticationFailed("Invalid API key")
        
        # Check IP restrictions
        client_ip = self._get_client_ip(request)
        if api_key_obj.allowed_ips and client_ip not in api_key_obj.allowed_ips:
            self._log_failed_attempt(
                request, api_key, 
                f"IP {client_ip} not in allowed list"
            )
            raise exceptions.AuthenticationFailed("IP address not allowed")
        
        # Check rate limit
        is_within_limit, request_count = api_key_obj.check_rate_limit()
        if not is_within_limit:
            self._log_usage(
                request, api_key_obj, 
                start_time, 429,
                f"Rate limit exceeded: {request_count} requests"
            )
            raise exceptions.Throttled(
                detail=f"Rate limit exceeded. Limit: {api_key_obj.rate_limit_per_hour}/hour"
            )
        
        # Log successful authentication (usage is already tracked in verify_key)
        # We'll log full usage details after the request completes
        request._api_key = api_key_obj
        request._api_key_start_time = start_time
        
        # Return user or anonymous user with API key
        user = api_key_obj.user if api_key_obj.user else AnonymousUser()
        return (user, api_key_obj)
    
    def authenticate_header(self, request: Request) -> str:
        """Return the authentication header required."""
        return 'Bearer'
    
    def _get_api_key(self, request: Request) -> Optional[str]:
        """Extract API key from request."""
        # Try Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        
        # Try X-API-Key header
        api_key_header = request.META.get('HTTP_X_API_KEY', '')
        if api_key_header:
            return api_key_header
        
        # Try query parameter (less secure, but sometimes necessary)
        api_key_param = request.query_params.get('api_key', '')
        if api_key_param:
            return api_key_param
        
        return None
    
    def _get_client_ip(self, request: Request) -> str:
        """Get the client's IP address from the request."""
        # Check for proxy headers
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # Take the first IP in the chain
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            # Use direct connection IP
            ip = request.META.get('REMOTE_ADDR', '')
        
        return ip
    
    def _log_failed_attempt(
        self, 
        request: Request, 
        api_key: str,
        reason: str
    ) -> None:
        """Log a failed authentication attempt."""
        # In production, you might want to track these for security monitoring
        # For now, we'll just use Django's logging
        import logging
        logger = logging.getLogger(__name__)
        
        logger.warning(
            f"API Key authentication failed: {reason}",
            extra={
                'api_key_prefix': api_key[:8] if len(api_key) >= 8 else api_key,
                'ip_address': self._get_client_ip(request),
                'endpoint': request.path,
                'method': request.method,
            }
        )
    
    def _log_usage(
        self,
        request: Request,
        api_key: APIKey,
        start_time: float,
        status_code: int,
        error_message: str = ""
    ) -> None:
        """Log API key usage."""
        response_time_ms = int((time.time() - start_time) * 1000)
        
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


class APIKeyPermission:
    """
    Base class for API Key permission checking.
    
    Can be used as a mixin for DRF permission classes.
    """
    
    def has_api_key_permission(
        self, 
        request: Request, 
        required_scopes: list[str]
    ) -> bool:
        """Check if the request has the required API key scopes."""
        # Check if authenticated via API key
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return False
        
        api_key = request.auth
        
        # Check if key has any of the required scopes
        return api_key.has_any_scope(required_scopes)
    
    def get_api_key_group(self, request: Request) -> Optional['Group']:
        """Get the group associated with the API key."""
        if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
            return request.auth.group
        return None