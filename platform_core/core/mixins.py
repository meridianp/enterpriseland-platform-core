"""
View mixins for applying custom throttle configurations.
"""

from rest_framework.viewsets import GenericViewSet
from platform_core.core.throttling import (
    AuthenticationThrottle,
    AIAgentThrottle,
    FileUploadThrottle,
    PublicAPIThrottle,
    ScopedRateThrottle,
)


class AuthenticationThrottleMixin:
    """Apply stricter rate limiting to authentication endpoints."""
    throttle_classes = [AuthenticationThrottle]


class AIAgentThrottleMixin:
    """Apply AI/token-based rate limiting to AI agent endpoints."""
    throttle_classes = [AIAgentThrottle]
    
    def finalize_response(self, request, response, *args, **kwargs):
        """Update token usage after AI response."""
        response = super().finalize_response(request, response, *args, **kwargs)
        
        # If response contains token usage info, update it
        if hasattr(response, 'data') and isinstance(response.data, dict):
            tokens_used = response.data.get('tokens_used', 0)
            if tokens_used > 0 and hasattr(request, '_throttle'):
                for throttle in request._throttle:
                    if isinstance(throttle, AIAgentThrottle):
                        throttle.update_token_usage(request, tokens_used)
                        
        return response


class FileUploadThrottleMixin:
    """Apply file upload rate limiting."""
    throttle_classes = [FileUploadThrottle]


class PublicAPIThrottleMixin:
    """Apply public API rate limiting."""
    throttle_classes = [PublicAPIThrottle]
    
    
class ScopedThrottleMixin:
    """
    Allow views to specify their own throttle scope.
    
    Usage:
        class MyViewSet(ScopedThrottleMixin, viewsets.ModelViewSet):
            throttle_scope = 'analytics'  # Uses analytics rate limit
    """
    throttle_classes = [ScopedRateThrottle]


class NoThrottleMixin:
    """
    Disable throttling for specific views.
    Use with caution - only for internal endpoints.
    """
    throttle_classes = []


class BurstThrottleMixin:
    """
    Apply burst rate limiting for endpoints that might receive burst traffic.
    """
    from platform_core.core.throttling import BurstRateThrottle
    throttle_classes = [BurstRateThrottle]