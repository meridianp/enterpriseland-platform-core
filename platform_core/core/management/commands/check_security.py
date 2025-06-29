"""
Management command to check security settings and headers.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.test import Client
from django.urls import reverse
import sys


class Command(BaseCommand):
    help = 'Check security settings and headers configuration'
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Checking security configuration...\n'))
        
        errors = []
        warnings = []
        success = []
        
        # Check middleware configuration
        self.stdout.write(self.style.NOTICE('Checking middleware...'))
        required_middleware = [
            'django.middleware.security.SecurityMiddleware',
            'core.middleware.security.SecurityHeadersMiddleware',
            'csp.middleware.CSPMiddleware',
            'core.middleware.security.RequestValidationMiddleware',
            'core.middleware.security.ContentTypeValidationMiddleware',
        ]
        
        for mw in required_middleware:
            if mw in settings.MIDDLEWARE:
                success.append(f"✓ {mw} is installed")
            else:
                errors.append(f"✗ {mw} is missing from MIDDLEWARE")
        
        # Check security settings
        self.stdout.write(self.style.NOTICE('\nChecking security settings...'))
        
        security_checks = {
            'SECURE_BROWSER_XSS_FILTER': (True, 'XSS filter should be enabled'),
            'SECURE_CONTENT_TYPE_NOSNIFF': (True, 'Content type sniffing should be disabled'),
            'X_FRAME_OPTIONS': ('DENY', 'X-Frame-Options should be set to DENY'),
            'SECURE_REFERRER_POLICY': ('strict-origin-when-cross-origin', 'Referrer policy should be set'),
        }
        
        if not settings.DEBUG:
            # Production-only checks
            security_checks.update({
                'SECURE_SSL_REDIRECT': (True, 'HTTPS redirect should be enabled in production'),
                'SECURE_HSTS_SECONDS': (31536000, 'HSTS should be enabled with at least 1 year'),
                'SECURE_HSTS_INCLUDE_SUBDOMAINS': (True, 'HSTS should include subdomains'),
                'SESSION_COOKIE_SECURE': (True, 'Session cookies should be secure in production'),
                'CSRF_COOKIE_SECURE': (True, 'CSRF cookies should be secure in production'),
            })
        
        for setting, (expected, message) in security_checks.items():
            value = getattr(settings, setting, None)
            if value == expected:
                success.append(f"✓ {setting} = {value}")
            else:
                if settings.DEBUG and setting in ['SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE']:
                    warnings.append(f"⚠ {setting} = {value} ({message})")
                else:
                    errors.append(f"✗ {setting} = {value} (expected {expected}, {message})")
        
        # Check CSP settings
        self.stdout.write(self.style.NOTICE('\nChecking CSP configuration...'))
        
        csp_settings = [
            'CSP_DEFAULT_SRC',
            'CSP_SCRIPT_SRC',
            'CSP_STYLE_SRC',
            'CSP_IMG_SRC',
            'CSP_CONNECT_SRC',
            'CSP_FONT_SRC',
            'CSP_OBJECT_SRC',
            'CSP_FRAME_ANCESTORS',
        ]
        
        for setting in csp_settings:
            value = getattr(settings, setting, None)
            if value:
                success.append(f"✓ {setting} is configured")
            else:
                warnings.append(f"⚠ {setting} is not configured")
        
        # Check file upload settings
        self.stdout.write(self.style.NOTICE('\nChecking file upload security...'))
        
        if hasattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE'):
            max_size = settings.FILE_UPLOAD_MAX_MEMORY_SIZE
            if max_size <= 10 * 1024 * 1024:  # 10MB
                success.append(f"✓ FILE_UPLOAD_MAX_MEMORY_SIZE = {max_size} bytes")
            else:
                warnings.append(f"⚠ FILE_UPLOAD_MAX_MEMORY_SIZE = {max_size} bytes (consider reducing)")
        
        # Test actual headers by making a request
        self.stdout.write(self.style.NOTICE('\nTesting actual response headers...'))
        
        client = Client()
        try:
            response = client.get('/api/')
            
            header_checks = {
                'X-Content-Type-Options': 'nosniff',
                'X-Frame-Options': ['DENY', 'SAMEORIGIN'],
                'Permissions-Policy': True,  # Just check it exists
                'X-DNS-Prefetch-Control': 'off',
            }
            
            for header, expected in header_checks.items():
                value = response.get(header)
                if value:
                    if isinstance(expected, list):
                        if value in expected:
                            success.append(f"✓ {header}: {value}")
                        else:
                            warnings.append(f"⚠ {header}: {value} (expected one of {expected})")
                    elif isinstance(expected, bool):
                        success.append(f"✓ {header} is present")
                    elif value == expected:
                        success.append(f"✓ {header}: {value}")
                    else:
                        warnings.append(f"⚠ {header}: {value} (expected {expected})")
                else:
                    errors.append(f"✗ {header} header is missing")
            
            # Check for CSP header
            csp = response.get('Content-Security-Policy') or response.get('Content-Security-Policy-Report-Only')
            if csp:
                success.append("✓ Content-Security-Policy header is present")
            else:
                errors.append("✗ Content-Security-Policy header is missing")
            
        except Exception as e:
            errors.append(f"✗ Failed to test headers: {str(e)}")
        
        # Print results
        self.stdout.write(self.style.SUCCESS(f'\n\nSecurity Check Results:'))
        self.stdout.write(self.style.SUCCESS(f'Success: {len(success)}'))
        self.stdout.write(self.style.WARNING(f'Warnings: {len(warnings)}'))
        self.stdout.write(self.style.ERROR(f'Errors: {len(errors)}'))
        
        if success:
            self.stdout.write(self.style.SUCCESS('\n✓ Successes:'))
            for s in success:
                self.stdout.write(self.style.SUCCESS(f'  {s}'))
        
        if warnings:
            self.stdout.write(self.style.WARNING('\n⚠ Warnings:'))
            for w in warnings:
                self.stdout.write(self.style.WARNING(f'  {w}'))
        
        if errors:
            self.stdout.write(self.style.ERROR('\n✗ Errors:'))
            for e in errors:
                self.stdout.write(self.style.ERROR(f'  {e}'))
        
        # Exit with error code if there are errors
        if errors:
            self.stdout.write(self.style.ERROR('\n\nSecurity check failed! Please fix the errors above.'))
            sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS('\n\nSecurity check passed!'))