"""
Rate limiting middleware for adding rate limit headers to responses.
"""

from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from django.conf import settings
import json
import logging

logger = logging.getLogger(__name__)


class RateLimitHeadersMiddleware(MiddlewareMixin):
    """
    Middleware to add rate limit headers to API responses.
    
    Headers added:
    - X-RateLimit-Limit: Maximum number of requests allowed
    - X-RateLimit-Remaining: Number of requests remaining
    - X-RateLimit-Reset: Unix timestamp when the rate limit resets
    - X-RateLimit-Scope: The scope that was rate limited (on 429 responses)
    """
    
    def process_response(self, request, response):
        """Add rate limit headers to response if available."""
        # Only add headers for API endpoints
        if not request.path.startswith('/api/'):
            return response
            
        # Check if rate limit info was added by throttle classes
        if hasattr(request, 'rate_limit_limit'):
            response['X-RateLimit-Limit'] = str(request.rate_limit_limit)
            
        if hasattr(request, 'rate_limit_remaining'):
            response['X-RateLimit-Remaining'] = str(request.rate_limit_remaining)
            
        if hasattr(request, 'rate_limit_reset'):
            response['X-RateLimit-Reset'] = str(request.rate_limit_reset)
            
        # For 429 responses, add additional info
        if response.status_code == 429:
            try:
                # Try to get throttle scope from response data
                if hasattr(response, 'data') and isinstance(response.data, dict):
                    detail = response.data.get('detail', {})
                    if isinstance(detail, dict):
                        scope = detail.get('throttle_scope', 'unknown')
                        response['X-RateLimit-Scope'] = scope
                        
                        # Log rate limit violation for monitoring
                        user_id = request.user.id if hasattr(request, 'user') and request.user.is_authenticated else 'anonymous'
                        logger.warning(
                            f"Rate limit exceeded",
                            extra={
                                'user_id': user_id,
                                'path': request.path,
                                'method': request.method,
                                'scope': scope,
                                'ip': self.get_client_ip(request),
                            }
                        )
            except Exception as e:
                logger.error(f"Error processing rate limit response: {e}")
                
        return response
    
    def get_client_ip(self, request):
        """Get the client IP address from the request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class RateLimitMonitoringMiddleware(MiddlewareMixin):
    """
    Middleware for monitoring rate limit usage and sending alerts.
    """
    
    # Thresholds for alerts (percentage of limit)
    WARNING_THRESHOLD = 80
    CRITICAL_THRESHOLD = 95
    
    def process_response(self, request, response):
        """Monitor rate limit usage and send alerts if needed."""
        if not request.path.startswith('/api/'):
            return response
            
        # Check rate limit usage
        if hasattr(request, 'rate_limit_limit') and hasattr(request, 'rate_limit_remaining'):
            limit = request.rate_limit_limit
            remaining = request.rate_limit_remaining
            
            if limit > 0:
                usage_percent = ((limit - remaining) / limit) * 100
                
                # Check thresholds
                if usage_percent >= self.CRITICAL_THRESHOLD:
                    self.send_critical_alert(request, usage_percent)
                elif usage_percent >= self.WARNING_THRESHOLD:
                    self.send_warning_alert(request, usage_percent)
                    
        return response
    
    def send_warning_alert(self, request, usage_percent):
        """Send warning alert for high rate limit usage."""
        user_id = request.user.id if hasattr(request, 'user') and request.user.is_authenticated else 'anonymous'
        logger.warning(
            f"High rate limit usage: {usage_percent:.1f}%",
            extra={
                'user_id': user_id,
                'path': request.path,
                'usage_percent': usage_percent,
                'alert_type': 'rate_limit_warning'
            }
        )
        
        # In production, this could send to monitoring service
        # Example: send_to_sentry, send_to_datadog, etc.
        
    def send_critical_alert(self, request, usage_percent):
        """Send critical alert for very high rate limit usage."""
        user_id = request.user.id if hasattr(request, 'user') and request.user.is_authenticated else 'anonymous'
        logger.error(
            f"Critical rate limit usage: {usage_percent:.1f}%",
            extra={
                'user_id': user_id,
                'path': request.path,
                'usage_percent': usage_percent,
                'alert_type': 'rate_limit_critical'
            }
        )
        
        # In production, this could trigger immediate notifications
        # Example: send SMS, PagerDuty alert, etc.