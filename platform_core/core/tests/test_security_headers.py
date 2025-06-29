"""
Comprehensive tests for security headers and middleware.
"""
import json
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test.client import Client

from platform_core.core.middleware.security import (
    SecurityHeadersMiddleware,
    RequestValidationMiddleware,
    ContentTypeValidationMiddleware
)

User = get_user_model()


class SecurityHeadersTestCase(TestCase):
    """Test security headers are properly set."""
    
    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
    
    def test_security_headers_middleware(self):
        """Test that SecurityHeadersMiddleware adds required headers."""
        middleware = SecurityHeadersMiddleware(lambda req: HttpResponse())
        request = self.factory.get('/')
        response = middleware(request)
        
        # Check that sensitive headers are removed
        self.assertNotIn('Server', response)
        self.assertNotIn('X-Powered-By', response)
        
        # Check security headers are added
        self.assertIn('Permissions-Policy', response)
        self.assertIn('X-Permitted-Cross-Domain-Policies', response)
        self.assertEqual(response['X-Permitted-Cross-Domain-Policies'], 'none')
        self.assertIn('X-DNS-Prefetch-Control', response)
        self.assertEqual(response['X-DNS-Prefetch-Control'], 'off')
    
    def test_permissions_policy_header(self):
        """Test that Permissions-Policy header restricts features."""
        middleware = SecurityHeadersMiddleware(lambda req: HttpResponse())
        request = self.factory.get('/')
        response = middleware(request)
        
        policy = response['Permissions-Policy']
        
        # Check that dangerous features are disabled
        self.assertIn('camera=()', policy)
        self.assertIn('microphone=()', policy)
        self.assertIn('geolocation=()', policy)
        self.assertIn('payment=()', policy)
        self.assertIn('usb=()', policy)
        
        # Check that some features are self-only
        self.assertIn('fullscreen=(self)', policy)
        self.assertIn('layout-animations=(self)', policy)
    
    def test_logout_clear_site_data(self):
        """Test Clear-Site-Data header on logout."""
        middleware = SecurityHeadersMiddleware(lambda req: HttpResponse())
        request = self.factory.post('/api/auth/logout/')
        response = HttpResponse()
        response.status_code = 200
        
        processed_response = middleware.process_response(request, response)
        
        self.assertIn('Clear-Site-Data', processed_response)
        self.assertEqual(
            processed_response['Clear-Site-Data'],
            '"cache", "cookies", "storage"'
        )
    
    def test_sensitive_endpoint_cache_control(self):
        """Test cache control headers for sensitive endpoints."""
        middleware = SecurityHeadersMiddleware(lambda req: HttpResponse())
        
        sensitive_paths = [
            '/api/auth/login/',
            '/api/users/me/',
            '/api/assessments/123/',
            '/admin/login/',
        ]
        
        for path in sensitive_paths:
            request = self.factory.get(path)
            response = middleware(request)
            
            self.assertEqual(
                response['Cache-Control'],
                'no-store, no-cache, must-revalidate, private'
            )
            self.assertEqual(response['Pragma'], 'no-cache')
            self.assertEqual(response['Expires'], '0')
    
    @override_settings(DEBUG=False)
    def test_expect_ct_header_production(self):
        """Test Expect-CT header in production."""
        middleware = SecurityHeadersMiddleware(lambda req: HttpResponse())
        request = self.factory.get('/')
        response = middleware(request)
        
        self.assertIn('Expect-CT', response)
        self.assertEqual(response['Expect-CT'], 'max-age=86400, enforce')
    
    @override_settings(DEBUG=True)
    def test_expect_ct_header_development(self):
        """Test Expect-CT header is not set in development."""
        middleware = SecurityHeadersMiddleware(lambda req: HttpResponse())
        request = self.factory.get('/')
        response = middleware(request)
        
        self.assertNotIn('Expect-CT', response)


class RequestValidationMiddlewareTestCase(TestCase):
    """Test request validation middleware."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RequestValidationMiddleware(lambda req: HttpResponse())
    
    def test_allowed_methods(self):
        """Test that only allowed HTTP methods are accepted."""
        allowed_methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
        
        for method in allowed_methods:
            request = self.factory.generic(method, '/')
            response = self.middleware(request)
            self.assertIsNone(response)  # Should pass through
    
    def test_disallowed_methods(self):
        """Test that disallowed HTTP methods are rejected."""
        disallowed_methods = ['TRACE', 'CONNECT', 'PROPFIND']
        
        for method in disallowed_methods:
            request = self.factory.generic(method, '/')
            response = self.middleware(request)
            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 405)
    
    def test_content_length_validation(self):
        """Test request size validation."""
        # Test normal size request
        request = self.factory.post(
            '/',
            data='x' * 1000,
            content_type='application/json',
            HTTP_CONTENT_LENGTH='1000'
        )
        response = self.middleware(request)
        self.assertIsNone(response)
        
        # Test oversized request
        request = self.factory.post(
            '/',
            data='x' * 1000,
            content_type='application/json',
            HTTP_CONTENT_LENGTH=str(11 * 1024 * 1024)  # 11MB
        )
        response = self.middleware(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 413)
    
    def test_invalid_content_length(self):
        """Test handling of invalid Content-Length header."""
        request = self.factory.post(
            '/',
            data='test',
            content_type='application/json',
            HTTP_CONTENT_LENGTH='invalid'
        )
        response = self.middleware(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 400)
    
    @override_settings(ALLOWED_HOSTS=['testserver', '.example.com'])
    def test_host_validation(self):
        """Test Host header validation."""
        # Valid hosts
        valid_hosts = ['testserver', 'api.example.com', 'www.example.com']
        
        for host in valid_hosts:
            request = self.factory.get('/', HTTP_HOST=host)
            response = self.middleware(request)
            self.assertIsNone(response)
        
        # Invalid host
        request = self.factory.get('/', HTTP_HOST='evil.com')
        response = self.middleware(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 400)


class ContentTypeValidationMiddlewareTestCase(TestCase):
    """Test content type validation middleware."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ContentTypeValidationMiddleware(lambda req: HttpResponse())
    
    def test_json_content_type(self):
        """Test that JSON content type is accepted for API endpoints."""
        methods = ['POST', 'PUT', 'PATCH']
        
        for method in methods:
            request = self.factory.generic(
                method,
                '/api/test/',
                data='{"test": true}',
                content_type='application/json'
            )
            response = self.middleware(request)
            self.assertIsNone(response)
    
    def test_multipart_content_type(self):
        """Test that multipart content type is accepted for file uploads."""
        methods = ['POST', 'PUT']
        
        for method in methods:
            request = self.factory.generic(
                method,
                '/api/files/',
                content_type='multipart/form-data'
            )
            response = self.middleware(request)
            self.assertIsNone(response)
    
    def test_invalid_content_type(self):
        """Test that invalid content types are rejected."""
        request = self.factory.post(
            '/api/test/',
            data='<xml>test</xml>',
            content_type='application/xml'
        )
        response = self.middleware(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 415)
    
    def test_non_api_endpoints_bypass(self):
        """Test that non-API endpoints bypass content type validation."""
        request = self.factory.post(
            '/admin/login/',
            data='test',
            content_type='application/x-www-form-urlencoded'
        )
        response = self.middleware(request)
        self.assertIsNone(response)
    
    def test_get_requests_bypass(self):
        """Test that GET requests bypass content type validation."""
        request = self.factory.get('/api/test/')
        response = self.middleware(request)
        self.assertIsNone(response)


class CSPHeaderTestCase(TestCase):
    """Test Content Security Policy headers."""
    
    def setUp(self):
        self.client = Client()
    
    def test_csp_header_present(self):
        """Test that CSP header is present in responses."""
        response = self.client.get('/api/')
        
        # Check for CSP header (can be either Content-Security-Policy or Content-Security-Policy-Report-Only)
        has_csp = (
            'Content-Security-Policy' in response or
            'Content-Security-Policy-Report-Only' in response
        )
        self.assertTrue(has_csp, "CSP header not found in response")
    
    @override_settings(DEBUG=True)
    def test_development_csp_policy(self):
        """Test CSP policy in development mode."""
        response = self.client.get('/api/')
        
        csp = response.get('Content-Security-Policy', '') or response.get('Content-Security-Policy-Report-Only', '')
        
        # Development should allow unsafe-inline for easier debugging
        self.assertIn("'unsafe-inline'", csp)
        self.assertIn("localhost", csp)
    
    @override_settings(DEBUG=False)
    def test_production_csp_policy(self):
        """Test CSP policy in production mode."""
        response = self.client.get('/api/')
        
        csp = response.get('Content-Security-Policy', '') or response.get('Content-Security-Policy-Report-Only', '')
        
        # Production should use nonces or strict-dynamic
        self.assertIn("'strict-dynamic'", csp)
        self.assertIn("upgrade-insecure-requests", csp.lower())


class DjangoSecuritySettingsTestCase(TestCase):
    """Test Django's built-in security settings."""
    
    def setUp(self):
        self.client = Client()
    
    def test_x_frame_options(self):
        """Test X-Frame-Options header."""
        response = self.client.get('/api/')
        self.assertIn('X-Frame-Options', response)
    
    def test_x_content_type_options(self):
        """Test X-Content-Type-Options header."""
        response = self.client.get('/api/')
        self.assertEqual(response.get('X-Content-Type-Options', '').lower(), 'nosniff')
    
    @override_settings(
        SECURE_SSL_REDIRECT=True,
        SECURE_HSTS_SECONDS=31536000,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
        SECURE_HSTS_PRELOAD=True
    )
    def test_hsts_header(self):
        """Test HSTS header in production settings."""
        response = self.client.get('/api/', secure=True)
        
        hsts = response.get('Strict-Transport-Security', '')
        self.assertIn('max-age=31536000', hsts)
        self.assertIn('includeSubDomains', hsts)
        self.assertIn('preload', hsts)
    
    def test_referrer_policy(self):
        """Test Referrer-Policy header."""
        response = self.client.get('/api/')
        
        # The header might be set by middleware or Django settings
        referrer_policy = response.get('Referrer-Policy', '')
        if referrer_policy:
            self.assertIn(referrer_policy, [
                'strict-origin-when-cross-origin',
                'same-origin',
                'strict-origin'
            ])


class FileUploadSecurityTestCase(TestCase):
    """Test file upload security settings."""
    
    def test_file_upload_size_limit(self):
        """Test that file upload size is limited."""
        from django.conf import settings
        
        # Check settings are applied
        self.assertEqual(
            settings.FILE_UPLOAD_MAX_MEMORY_SIZE,
            10 * 1024 * 1024  # 10MB
        )
        self.assertEqual(
            settings.DATA_UPLOAD_MAX_MEMORY_SIZE,
            10 * 1024 * 1024  # 10MB
        )
    
    def test_file_permissions(self):
        """Test file upload permissions."""
        from django.conf import settings
        
        self.assertEqual(settings.FILE_UPLOAD_PERMISSIONS, 0o644)
        self.assertEqual(settings.FILE_UPLOAD_DIRECTORY_PERMISSIONS, 0o755)