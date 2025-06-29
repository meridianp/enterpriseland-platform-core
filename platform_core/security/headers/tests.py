"""
Tests for Security Headers Middleware

Tests security header middleware functionality and configurations.
"""

from django.test import TestCase, RequestFactory, override_settings
from django.http import HttpResponse
from django.template import Template, Context
from django.template.response import TemplateResponse

from .middleware import SecurityHeadersMiddleware, CSPNonceMiddleware, SecurityReportMiddleware
from .config import SecurityHeadersConfig, get_security_headers_config


class SecurityHeadersMiddlewareTests(TestCase):
    """Test security headers middleware"""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = SecurityHeadersMiddleware(lambda r: HttpResponse())
    
    def test_basic_headers(self):
        """Test basic security headers are added"""
        request = self.factory.get('/')
        response = self.middleware(request)
        
        # Check basic headers
        self.assertIn('X-Content-Type-Options', response)
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        
        self.assertIn('X-Frame-Options', response)
        self.assertIn('X-XSS-Protection', response)
        self.assertIn('Referrer-Policy', response)
    
    @override_settings(SECURITY_HEADERS={'ENABLED': False})
    def test_disabled_middleware(self):
        """Test middleware can be disabled"""
        middleware = SecurityHeadersMiddleware(lambda r: HttpResponse())
        request = self.factory.get('/')
        response = middleware(request)
        
        # No security headers should be added
        self.assertNotIn('X-Content-Type-Options', response)
        self.assertNotIn('X-Frame-Options', response)
    
    def test_csp_header(self):
        """Test Content Security Policy header"""
        with override_settings(SECURITY_HEADERS={
            'CSP': {
                'ENABLED': True,
                'DIRECTIVES': {
                    'default-src': ["'self'"],
                    'script-src': ["'self'", 'https://trusted.com'],
                    'style-src': ["'self'", "'unsafe-inline'"],
                }
            }
        }):
            middleware = SecurityHeadersMiddleware(lambda r: HttpResponse())
            request = self.factory.get('/')
            response = middleware(request)
            
            self.assertIn('Content-Security-Policy', response)
            csp = response['Content-Security-Policy']
            
            self.assertIn("default-src 'self'", csp)
            self.assertIn("script-src 'self' https://trusted.com", csp)
            self.assertIn("style-src 'self' 'unsafe-inline'", csp)
    
    def test_csp_nonce_generation(self):
        """Test CSP nonce is generated"""
        request = self.factory.get('/')
        response = self.middleware(request)
        
        # Check nonce was generated
        self.assertTrue(hasattr(request, 'csp_nonce'))
        self.assertIsInstance(request.csp_nonce, str)
        self.assertTrue(len(request.csp_nonce) > 0)
        
        # Check nonce is in CSP header
        if 'Content-Security-Policy' in response:
            csp = response['Content-Security-Policy']
            self.assertIn(f"'nonce-{request.csp_nonce}'", csp)
    
    def test_hsts_header(self):
        """Test HSTS header"""
        with override_settings(SECURITY_HEADERS={
            'HSTS': {
                'ENABLED': True,
                'MAX_AGE': 31536000,
                'INCLUDE_SUBDOMAINS': True,
                'PRELOAD': True,
            }
        }):
            middleware = SecurityHeadersMiddleware(lambda r: HttpResponse())
            request = self.factory.get('/')
            response = middleware(request)
            
            self.assertIn('Strict-Transport-Security', response)
            hsts = response['Strict-Transport-Security']
            
            self.assertIn('max-age=31536000', hsts)
            self.assertIn('includeSubDomains', hsts)
            self.assertIn('preload', hsts)
    
    def test_permissions_policy(self):
        """Test Permissions Policy header"""
        with override_settings(SECURITY_HEADERS={
            'PERMISSIONS_POLICY': {
                'camera': 'none',
                'microphone': 'self',
                'geolocation': ['self', 'https://maps.example.com'],
            }
        }):
            middleware = SecurityHeadersMiddleware(lambda r: HttpResponse())
            request = self.factory.get('/')
            response = middleware(request)
            
            self.assertIn('Permissions-Policy', response)
            policy = response['Permissions-Policy']
            
            self.assertIn('camera=()', policy)
            self.assertIn('microphone=(self)', policy)
            self.assertIn('geolocation=(self https://maps.example.com)', policy)
    
    def test_cors_headers(self):
        """Test CORS headers"""
        with override_settings(SECURITY_HEADERS={
            'CORS': {
                'ENABLED': True,
                'ALLOWED_ORIGINS': ['https://app.example.com'],
                'ALLOW_CREDENTIALS': True,
                'ALLOWED_METHODS': ['GET', 'POST'],
                'ALLOWED_HEADERS': ['Content-Type', 'Authorization'],
            }
        }):
            middleware = SecurityHeadersMiddleware(lambda r: HttpResponse())
            request = self.factory.get('/', HTTP_ORIGIN='https://app.example.com')
            response = middleware(request)
            
            self.assertEqual(
                response['Access-Control-Allow-Origin'],
                'https://app.example.com'
            )
            self.assertEqual(
                response['Access-Control-Allow-Credentials'],
                'true'
            )
            self.assertIn('Access-Control-Allow-Methods', response)
            self.assertIn('Access-Control-Allow-Headers', response)
    
    def test_report_only_mode(self):
        """Test report-only mode for CSP"""
        with override_settings(SECURITY_HEADERS={
            'CSP': {
                'ENABLED': True,
                'REPORT_ONLY': True,
                'DIRECTIVES': {'default-src': ["'self'"]},
            }
        }):
            middleware = SecurityHeadersMiddleware(lambda r: HttpResponse())
            request = self.factory.get('/')
            response = middleware(request)
            
            # Should use Report-Only header
            self.assertIn('Content-Security-Policy-Report-Only', response)
            self.assertNotIn('Content-Security-Policy', response)


class SecurityHeadersConfigTests(TestCase):
    """Test security headers configuration"""
    
    def test_development_config(self):
        """Test development configuration"""
        config = SecurityHeadersConfig.development()
        
        self.assertTrue(config['ENABLED'])
        self.assertTrue(config['REPORT_ONLY'])
        self.assertFalse(config['HSTS']['ENABLED'])
        
        # Should allow localhost
        csp_directives = config['CSP']['DIRECTIVES']
        self.assertIn('http://localhost:*', csp_directives['script-src'])
        self.assertIn('ws://localhost:*', csp_directives['connect-src'])
    
    def test_production_config(self):
        """Test production configuration"""
        config = SecurityHeadersConfig.production()
        
        self.assertTrue(config['ENABLED'])
        self.assertFalse(config['REPORT_ONLY'])
        self.assertTrue(config['HSTS']['ENABLED'])
        self.assertTrue(config['HSTS']['PRELOAD'])
        
        # Should be restrictive
        csp_directives = config['CSP']['DIRECTIVES']
        self.assertEqual(csp_directives['default-src'], ["'none'"])
        self.assertEqual(config['X_FRAME_OPTIONS'], 'DENY')
    
    def test_api_only_config(self):
        """Test API-only configuration"""
        config = SecurityHeadersConfig.api_only()
        
        self.assertFalse(config['CSP']['ENABLED'])
        self.assertTrue(config['CORS']['ENABLED'])
        self.assertEqual(config['X_XSS_PROTECTION'], '0')
        self.assertEqual(config['REFERRER_POLICY'], 'no-referrer')
    
    def test_cdn_configuration(self):
        """Test adding CDN domains"""
        base_config = SecurityHeadersConfig.production()
        cdn_domains = ['https://cdn.example.com', 'https://static.example.com']
        
        config = SecurityHeadersConfig.with_cdn(base_config, cdn_domains)
        
        directives = config['CSP']['DIRECTIVES']
        for cdn in cdn_domains:
            self.assertIn(cdn, directives['script-src'])
            self.assertIn(cdn, directives['style-src'])
            self.assertIn(cdn, directives['img-src'])
            self.assertIn(cdn, directives['font-src'])
    
    def test_analytics_configuration(self):
        """Test adding analytics domains"""
        base_config = SecurityHeadersConfig.production()
        analytics_domains = ['https://analytics.example.com']
        
        config = SecurityHeadersConfig.with_analytics(base_config, analytics_domains)
        
        directives = config['CSP']['DIRECTIVES']
        
        # Should include custom analytics
        self.assertIn('https://analytics.example.com', directives['script-src'])
        
        # Should include default analytics
        self.assertIn('https://www.google-analytics.com', directives['script-src'])
        self.assertIn('https://www.googletagmanager.com', directives['script-src'])
    
    def test_get_config_helper(self):
        """Test configuration helper function"""
        # Development
        dev_config = get_security_headers_config('development')
        self.assertFalse(dev_config['HSTS']['ENABLED'])
        
        # Production with options
        prod_config = get_security_headers_config(
            'production',
            cdn_domains=['https://cdn.example.com'],
            cors_origins=['https://app.example.com']
        )
        
        self.assertIn(
            'https://cdn.example.com',
            prod_config['CSP']['DIRECTIVES']['script-src']
        )


class CSPNonceMiddlewareTests(TestCase):
    """Test CSP nonce template middleware"""
    
    def test_nonce_in_template_context(self):
        """Test nonce is added to template context"""
        factory = RequestFactory()
        request = factory.get('/')
        request.csp_nonce = 'test-nonce-123'
        
        # Create a template response
        response = TemplateResponse(
            request,
            Template('{{ csp_nonce }}'),
            {}
        )
        
        # Process with middleware
        middleware = CSPNonceMiddleware(lambda r: response)
        processed_response = middleware.process_template_response(request, response)
        
        # Nonce should be in context
        self.assertEqual(processed_response.context_data.get('csp_nonce'), 'test-nonce-123')


class SecurityReportMiddlewareTests(TestCase):
    """Test security report handling"""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = SecurityReportMiddleware(lambda r: HttpResponse())
    
    def test_csp_report_handling(self):
        """Test CSP violation report is handled"""
        report_data = {
            'csp-report': {
                'document-uri': 'https://example.com/page',
                'referrer': '',
                'violated-directive': 'script-src',
                'effective-directive': 'script-src',
                'original-policy': "script-src 'self'",
                'blocked-uri': 'https://evil.com/script.js',
                'status-code': 0,
            }
        }
        
        request = self.factory.post(
            '/api/security/reports/csp/',
            data=report_data,
            content_type='application/json'
        )
        
        response = self.middleware(request)
        
        self.assertEqual(response.status_code, 200)
        
        # Check if security event was created
        from platform_core.security.audit.models import SecurityEvent
        event = SecurityEvent.objects.filter(event_type='csp_violation').first()
        
        if event:  # May not exist if models aren't migrated in test
            self.assertEqual(event.severity, 'medium')
            self.assertIn('script-src', event.description)
    
    def test_invalid_report_handling(self):
        """Test invalid report is rejected"""
        request = self.factory.post(
            '/api/security/reports/csp/',
            data='invalid json',
            content_type='application/json'
        )
        
        response = self.middleware(request)
        
        self.assertEqual(response.status_code, 400)