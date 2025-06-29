"""
Custom security middleware for additional security headers and request/response validation.
"""
import re
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Custom middleware to add security headers not covered by django-csp
    and remove sensitive information from responses.
    """
    
    def process_response(self, request, response):
        """Add security headers to all responses."""
        
        # Remove server identification headers
        response.headers.pop('Server', None)
        response.headers.pop('X-Powered-By', None)
        
        # Add Permissions-Policy header (formerly Feature-Policy)
        # Restrict access to sensitive browser features
        permissions_policy = [
            "accelerometer=()",
            "ambient-light-sensor=()",
            "autoplay=()",
            "battery=()",
            "camera=()",
            "display-capture=()",
            "document-domain=()",
            "encrypted-media=()",
            "execution-while-not-rendered=()",
            "execution-while-out-of-viewport=()",
            "fullscreen=(self)",
            "geolocation=()",
            "gyroscope=()",
            "layout-animations=(self)",
            "legacy-image-formats=(self)",
            "magnetometer=()",
            "microphone=()",
            "midi=()",
            "navigation-override=()",
            "oversized-images=(self)",
            "payment=()",
            "picture-in-picture=()",
            "publickey-credentials-get=()",
            "screen-wake-lock=()",
            "sync-xhr=()",
            "usb=()",
            "wake-lock=()",
            "web-share=()",
            "xr-spatial-tracking=()"
        ]
        response['Permissions-Policy'] = ", ".join(permissions_policy)
        
        # Add X-Permitted-Cross-Domain-Policies
        response['X-Permitted-Cross-Domain-Policies'] = 'none'
        
        # Add Clear-Site-Data for logout responses
        if request.path == '/api/auth/logout/' and response.status_code == 200:
            response['Clear-Site-Data'] = '"cache", "cookies", "storage"'
        
        # Add Cache-Control for security-sensitive endpoints
        if self._is_sensitive_endpoint(request.path):
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        
        # Add X-DNS-Prefetch-Control
        response['X-DNS-Prefetch-Control'] = 'off'
        
        # Add Expect-CT header for Certificate Transparency
        if not settings.DEBUG:
            response['Expect-CT'] = 'max-age=86400, enforce'
        
        return response
    
    def _is_sensitive_endpoint(self, path):
        """Check if the endpoint handles sensitive data."""
        sensitive_patterns = [
            r'^/api/auth/',
            r'^/api/users/',
            r'^/api/assessments/',
            r'^/admin/',
        ]
        return any(re.match(pattern, path) for pattern in sensitive_patterns)


class RequestValidationMiddleware(MiddlewareMixin):
    """
    Middleware to validate incoming requests for security purposes.
    """
    
    # Maximum allowed request size (10MB)
    MAX_REQUEST_SIZE = 10 * 1024 * 1024
    
    # Allowed HTTP methods
    ALLOWED_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
    
    def process_request(self, request):
        """Validate incoming requests."""
        
        # Check request method
        if request.method not in self.ALLOWED_METHODS:
            from django.http import HttpResponseNotAllowed
            return HttpResponseNotAllowed(self.ALLOWED_METHODS)
        
        # Check Content-Length for POST/PUT/PATCH requests
        if request.method in ['POST', 'PUT', 'PATCH']:
            content_length = request.headers.get('Content-Length')
            if content_length:
                try:
                    size = int(content_length)
                    if size > self.MAX_REQUEST_SIZE:
                        from django.http import HttpResponse
                        return HttpResponse(
                            'Request body too large',
                            status=413
                        )
                except (ValueError, TypeError):
                    from django.http import HttpResponseBadRequest
                    return HttpResponseBadRequest('Invalid Content-Length header')
        
        # Validate Host header against ALLOWED_HOSTS
        host = request.get_host()
        if not self._validate_host(host):
            from django.http import HttpResponseBadRequest
            return HttpResponseBadRequest('Invalid Host header')
        
        return None
    
    def _validate_host(self, host):
        """Validate host against ALLOWED_HOSTS."""
        # Remove port if present
        if ':' in host:
            host = host.split(':')[0]
        
        # Check against ALLOWED_HOSTS
        allowed_hosts = settings.ALLOWED_HOSTS
        if not allowed_hosts:
            return True
        
        for allowed_host in allowed_hosts:
            if allowed_host == '*':
                return True
            if allowed_host.startswith('.') and host.endswith(allowed_host[1:]):
                return True
            if host == allowed_host:
                return True
        
        return False


class ContentTypeValidationMiddleware(MiddlewareMixin):
    """
    Middleware to validate Content-Type headers for API endpoints.
    """
    
    # Allowed content types for different methods
    ALLOWED_CONTENT_TYPES = {
        'POST': ['application/json', 'multipart/form-data'],
        'PUT': ['application/json', 'multipart/form-data'],
        'PATCH': ['application/json'],
    }
    
    def process_request(self, request):
        """Validate Content-Type for API requests."""
        
        # Only validate API endpoints
        if not request.path.startswith('/api/'):
            return None
        
        # Skip validation for GET, DELETE, HEAD, OPTIONS
        if request.method not in self.ALLOWED_CONTENT_TYPES:
            return None
        
        # Get content type without parameters
        content_type = request.content_type.split(';')[0].strip().lower()
        
        # Check if content type is allowed
        allowed_types = self.ALLOWED_CONTENT_TYPES.get(request.method, [])
        if content_type not in allowed_types:
            from django.http import HttpResponse
            return HttpResponse(
                f'Unsupported content type: {content_type}',
                status=415
            )
        
        return None