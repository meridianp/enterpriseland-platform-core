"""
Security Headers Middleware

Adds security headers to HTTP responses to protect against common attacks.
"""

from typing import Dict, Optional, List, Callable
from django.conf import settings
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin
import hashlib
import base64
import secrets


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Middleware to add security headers to responses.
    
    Implements:
    - Content Security Policy (CSP)
    - HTTP Strict Transport Security (HSTS)
    - X-Frame-Options
    - X-Content-Type-Options
    - X-XSS-Protection
    - Referrer-Policy
    - Permissions-Policy
    - Cross-Origin headers
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Load configuration
        self.config = getattr(settings, 'SECURITY_HEADERS', {})
        self.csp_config = self.config.get('CSP', {})
        self.enabled = self.config.get('ENABLED', True)
        self.report_only = self.config.get('REPORT_ONLY', False)
        
        # Nonce for CSP
        self.nonce_length = self.config.get('NONCE_LENGTH', 16)
    
    def __call__(self, request):
        # Generate CSP nonce for this request
        if self.csp_config.get('USE_NONCE', True):
            request.csp_nonce = self._generate_nonce()
        
        response = self.get_response(request)
        
        if self.enabled and hasattr(response, 'status_code'):
            self._add_security_headers(request, response)
        
        return response
    
    def _generate_nonce(self) -> str:
        """Generate a CSP nonce"""
        nonce_bytes = secrets.token_bytes(self.nonce_length)
        return base64.b64encode(nonce_bytes).decode('ascii')
    
    def _add_security_headers(self, request, response: HttpResponse):
        """Add security headers to response"""
        # Content Security Policy
        self._add_csp_header(request, response)
        
        # HSTS
        self._add_hsts_header(response)
        
        # Frame Options
        self._add_frame_options(response)
        
        # Content Type Options
        self._add_content_type_options(response)
        
        # XSS Protection (legacy)
        self._add_xss_protection(response)
        
        # Referrer Policy
        self._add_referrer_policy(response)
        
        # Permissions Policy
        self._add_permissions_policy(response)
        
        # CORS headers (if needed)
        self._add_cors_headers(request, response)
        
        # Custom headers
        self._add_custom_headers(response)
    
    def _add_csp_header(self, request, response: HttpResponse):
        """Add Content Security Policy header"""
        if not self.csp_config.get('ENABLED', True):
            return
        
        directives = []
        
        # Default CSP directives
        default_directives = {
            'default-src': ["'self'"],
            'script-src': ["'self'"],
            'style-src': ["'self'"],
            'img-src': ["'self'", 'data:', 'https:'],
            'font-src': ["'self'"],
            'connect-src': ["'self'"],
            'media-src': ["'self'"],
            'object-src': ["'none'"],
            'frame-ancestors': ["'none'"],
            'base-uri': ["'self'"],
            'form-action': ["'self'"],
        }
        
        # Merge with custom directives
        csp_directives = {**default_directives, **self.csp_config.get('DIRECTIVES', {})}
        
        # Add nonce if available
        if hasattr(request, 'csp_nonce'):
            nonce = f"'nonce-{request.csp_nonce}'"
            if 'script-src' in csp_directives:
                csp_directives['script-src'].append(nonce)
            if 'style-src' in csp_directives:
                csp_directives['style-src'].append(nonce)
        
        # Build CSP string
        for directive, sources in csp_directives.items():
            if sources:
                directive_str = f"{directive} {' '.join(sources)}"
                directives.append(directive_str)
        
        # Add report-uri if configured
        report_uri = self.csp_config.get('REPORT_URI')
        if report_uri:
            directives.append(f"report-uri {report_uri}")
        
        # Add report-to if configured
        report_to = self.csp_config.get('REPORT_TO')
        if report_to:
            directives.append(f"report-to {report_to}")
        
        csp_header = '; '.join(directives)
        
        # Use Report-Only mode if configured
        if self.report_only or self.csp_config.get('REPORT_ONLY', False):
            response['Content-Security-Policy-Report-Only'] = csp_header
        else:
            response['Content-Security-Policy'] = csp_header
    
    def _add_hsts_header(self, response: HttpResponse):
        """Add HTTP Strict Transport Security header"""
        hsts_config = self.config.get('HSTS', {})
        
        if not hsts_config.get('ENABLED', True):
            return
        
        max_age = hsts_config.get('MAX_AGE', 31536000)  # 1 year default
        include_subdomains = hsts_config.get('INCLUDE_SUBDOMAINS', True)
        preload = hsts_config.get('PRELOAD', False)
        
        hsts_value = f"max-age={max_age}"
        
        if include_subdomains:
            hsts_value += "; includeSubDomains"
        
        if preload:
            hsts_value += "; preload"
        
        response['Strict-Transport-Security'] = hsts_value
    
    def _add_frame_options(self, response: HttpResponse):
        """Add X-Frame-Options header"""
        frame_options = self.config.get('X_FRAME_OPTIONS', 'DENY')
        
        if frame_options:
            response['X-Frame-Options'] = frame_options
    
    def _add_content_type_options(self, response: HttpResponse):
        """Add X-Content-Type-Options header"""
        if self.config.get('X_CONTENT_TYPE_OPTIONS', True):
            response['X-Content-Type-Options'] = 'nosniff'
    
    def _add_xss_protection(self, response: HttpResponse):
        """Add X-XSS-Protection header (legacy)"""
        xss_protection = self.config.get('X_XSS_PROTECTION', '1; mode=block')
        
        if xss_protection:
            response['X-XSS-Protection'] = xss_protection
    
    def _add_referrer_policy(self, response: HttpResponse):
        """Add Referrer-Policy header"""
        referrer_policy = self.config.get('REFERRER_POLICY', 'strict-origin-when-cross-origin')
        
        if referrer_policy:
            response['Referrer-Policy'] = referrer_policy
    
    def _add_permissions_policy(self, response: HttpResponse):
        """Add Permissions-Policy header"""
        permissions_config = self.config.get('PERMISSIONS_POLICY', {})
        
        if not permissions_config:
            # Default restrictive policy
            permissions_config = {
                'camera': 'none',
                'microphone': 'none',
                'geolocation': 'none',
                'payment': 'none',
                'usb': 'none',
                'magnetometer': 'none',
                'accelerometer': 'none',
                'gyroscope': 'none',
            }
        
        policies = []
        for feature, allowlist in permissions_config.items():
            if isinstance(allowlist, str):
                if allowlist == 'none':
                    policies.append(f'{feature}=()')
                else:
                    policies.append(f'{feature}=({allowlist})')
            elif isinstance(allowlist, list):
                policies.append(f'{feature}=({" ".join(allowlist)})')
        
        if policies:
            response['Permissions-Policy'] = ', '.join(policies)
    
    def _add_cors_headers(self, request, response: HttpResponse):
        """Add CORS headers if configured"""
        cors_config = self.config.get('CORS', {})
        
        if not cors_config.get('ENABLED', False):
            return
        
        # Get origin from request
        origin = request.headers.get('Origin')
        
        # Check allowed origins
        allowed_origins = cors_config.get('ALLOWED_ORIGINS', [])
        allow_all = cors_config.get('ALLOW_ALL_ORIGINS', False)
        
        if allow_all or (origin and origin in allowed_origins):
            response['Access-Control-Allow-Origin'] = origin if not allow_all else '*'
            
            # Add other CORS headers
            if cors_config.get('ALLOW_CREDENTIALS', False):
                response['Access-Control-Allow-Credentials'] = 'true'
            
            allowed_methods = cors_config.get('ALLOWED_METHODS', ['GET', 'POST'])
            response['Access-Control-Allow-Methods'] = ', '.join(allowed_methods)
            
            allowed_headers = cors_config.get('ALLOWED_HEADERS', ['Content-Type'])
            response['Access-Control-Allow-Headers'] = ', '.join(allowed_headers)
            
            exposed_headers = cors_config.get('EXPOSED_HEADERS', [])
            if exposed_headers:
                response['Access-Control-Expose-Headers'] = ', '.join(exposed_headers)
            
            max_age = cors_config.get('MAX_AGE', 86400)
            response['Access-Control-Max-Age'] = str(max_age)
    
    def _add_custom_headers(self, response: HttpResponse):
        """Add any custom headers"""
        custom_headers = self.config.get('CUSTOM_HEADERS', {})
        
        for header, value in custom_headers.items():
            response[header] = value


class CSPNonceMiddleware(MiddlewareMixin):
    """
    Middleware to inject CSP nonce into templates.
    
    Allows using {{ csp_nonce }} in templates.
    """
    
    def process_template_response(self, request, response):
        """Add CSP nonce to template context"""
        if hasattr(request, 'csp_nonce') and hasattr(response, 'context_data'):
            response.context_data['csp_nonce'] = request.csp_nonce
        
        return response


class SecurityReportMiddleware(MiddlewareMixin):
    """
    Middleware to handle security violation reports.
    
    Processes CSP, Expect-CT, and other security reports.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.report_handlers = {
            'csp': self._handle_csp_report,
            'expect-ct': self._handle_expect_ct_report,
            'nel': self._handle_nel_report,
        }
    
    def __call__(self, request):
        # Check if this is a report submission
        if request.path in ['/api/security/reports/csp/',
                           '/api/security/reports/expect-ct/',
                           '/api/security/reports/nel/']:
            return self._handle_report(request)
        
        return self.get_response(request)
    
    def _handle_report(self, request):
        """Handle security report submission"""
        import json
        from django.http import JsonResponse
        
        if request.method != 'POST':
            return JsonResponse({'error': 'Method not allowed'}, status=405)
        
        try:
            report_data = json.loads(request.body)
            report_type = request.path.split('/')[-2]
            
            handler = self.report_handlers.get(report_type)
            if handler:
                handler(request, report_data)
            
            return JsonResponse({'status': 'received'})
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to process security report: {e}")
            return JsonResponse({'error': 'Invalid report'}, status=400)
    
    def _handle_csp_report(self, request, report_data):
        """Handle CSP violation report"""
        from platform_core.security.audit.models import SecurityEvent
        
        csp_report = report_data.get('csp-report', {})
        
        SecurityEvent.objects.create(
            event_type='csp_violation',
            severity='medium',
            title='Content Security Policy Violation',
            description=f"CSP violation: {csp_report.get('violated-directive', 'Unknown')}",
            ip_address=self._get_client_ip(request),
            user_agent=request.headers.get('User-Agent', ''),
            details={
                'document_uri': csp_report.get('document-uri'),
                'violated_directive': csp_report.get('violated-directive'),
                'blocked_uri': csp_report.get('blocked-uri'),
                'line_number': csp_report.get('line-number'),
                'column_number': csp_report.get('column-number'),
                'source_file': csp_report.get('source-file'),
            }
        )
    
    def _handle_expect_ct_report(self, request, report_data):
        """Handle Expect-CT report"""
        from platform_core.security.audit.models import SecurityEvent
        
        SecurityEvent.objects.create(
            event_type='expect_ct_failure',
            severity='high',
            title='Certificate Transparency Failure',
            description='Expect-CT policy violation detected',
            ip_address=self._get_client_ip(request),
            details=report_data
        )
    
    def _handle_nel_report(self, request, report_data):
        """Handle Network Error Logging report"""
        from platform_core.security.audit.models import SecurityEvent
        
        SecurityEvent.objects.create(
            event_type='network_error',
            severity='info',
            title='Network Error',
            description=f"Network error: {report_data.get('type', 'Unknown')}",
            ip_address=self._get_client_ip(request),
            details=report_data
        )
    
    def _get_client_ip(self, request) -> str:
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip or ''