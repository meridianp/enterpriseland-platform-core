"""
Comprehensive tests for rate limiting functionality.
"""

import time
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase, APIClient
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.throttling import SimpleRateThrottle

from platform_core.core.throttling import (
    BaseEnhancedThrottle,
    TenantRateThrottle,
    AuthenticationThrottle,
    AIAgentThrottle,
    FileUploadThrottle,
    BurstRateThrottle,
    ScopedRateThrottle,
)
from platform_core.core.middleware.rate_limiting import (
    RateLimitHeadersMiddleware,
    RateLimitMonitoringMiddleware,
)
from accounts.models import User, Group


class BaseRateLimitingTestCase(APITestCase):
    """Base test case with common setup for rate limiting tests."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        # Clear cache before each test
        cache.clear()
        
        # Create test group and users
        self.group = Group.objects.create(
            name="Test Group",
            description="Test group for rate limiting"
        )
        
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
            role=User.Role.ANALYST
        )
        self.user.groups.add(self.group)
        
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="adminpass123",
            first_name="Admin",
            last_name="User",
            role=User.Role.ADMIN
        )
        self.admin.groups.add(self.group)
        
        self.client = APIClient()
        self.factory = RequestFactory()
    
    def tearDown(self):
        """Clean up after each test."""
        cache.clear()
        super().tearDown()


class TestBaseEnhancedThrottle(BaseRateLimitingTestCase):
    """Test the base enhanced throttle functionality."""
    
    def test_cache_key_generation_authenticated(self):
        """Test cache key generation for authenticated users."""
        throttle = BaseEnhancedThrottle()
        throttle.scope = 'test'
        
        request = self.factory.get('/')
        request.user = self.user
        request.user.group_id = self.group.id
        
        key = throttle.get_cache_key(request, None)
        self.assertIsNotNone(key)
        self.assertIn(str(self.user.pk), key)
    
    def test_cache_key_generation_anonymous(self):
        """Test cache key generation for anonymous users."""
        throttle = BaseEnhancedThrottle()
        throttle.scope = 'test'
        
        request = self.factory.get('/')
        request.user = None
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        
        key = throttle.get_cache_key(request, None)
        self.assertIsNotNone(key)
    
    def test_rate_limit_headers_added(self):
        """Test that rate limit info is added to request."""
        throttle = BaseEnhancedThrottle()
        throttle.rate = '5/hour'
        throttle.scope = 'test'
        
        request = self.factory.get('/')
        request.user = self.user
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        
        # First request should pass
        allowed = throttle.allow_request(request, None)
        self.assertTrue(allowed)
        self.assertEqual(request.rate_limit_limit, 5)
        self.assertEqual(request.rate_limit_remaining, 4)
        self.assertIsInstance(request.rate_limit_reset, int)
    
    def test_throttle_failure(self):
        """Test throttle failure when rate limit exceeded."""
        throttle = BaseEnhancedThrottle()
        throttle.rate = '2/hour'
        throttle.scope = 'test'
        
        request = self.factory.get('/')
        request.user = self.user
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        
        # Make requests up to limit
        self.assertTrue(throttle.allow_request(request, None))
        self.assertTrue(throttle.allow_request(request, None))
        
        # Next request should fail
        with self.assertRaises(Exception) as context:
            throttle.allow_request(request, None)
        
        self.assertIn('throttled', str(context.exception).lower())


class TestTenantRateThrottle(BaseRateLimitingTestCase):
    """Test tenant-level rate limiting."""
    
    def test_tenant_rate_limiting(self):
        """Test that rate limiting is applied per tenant."""
        throttle = TenantRateThrottle()
        
        # Create request for first tenant
        request1 = self.factory.get('/')
        request1.user = self.user
        request1.user.group_id = self.group.id
        
        # Create second group and user
        group2 = Group.objects.create(name="Test Group 2")
        user2 = User.objects.create_user(
            email="user2@example.com",
            password="pass123"
        )
        user2.groups.add(group2)
        
        request2 = self.factory.get('/')
        request2.user = user2
        request2.user.group_id = group2.id
        
        # Both tenants should have independent limits
        key1 = throttle.get_cache_key(request1, None)
        key2 = throttle.get_cache_key(request2, None)
        
        self.assertNotEqual(key1, key2)


class TestAuthenticationThrottle(BaseRateLimitingTestCase):
    """Test authentication endpoint throttling."""
    
    def test_strict_auth_rate_limit(self):
        """Test that auth endpoints have strict rate limits."""
        throttle = AuthenticationThrottle()
        self.assertEqual(throttle.rate, '10/hour')
        
        request = self.factory.post('/api/auth/login/')
        request.META = {'REMOTE_ADDR': '192.168.1.1'}
        
        # Should use IP-based limiting
        key = throttle.get_cache_key(request, None)
        self.assertIn('authentication', key)


class TestAIAgentThrottle(BaseRateLimitingTestCase):
    """Test AI agent throttling with token limits."""
    
    @override_settings(AI_TOKEN_LIMIT_PER_HOUR=1000)
    def test_token_usage_tracking(self):
        """Test that token usage is tracked correctly."""
        throttle = AIAgentThrottle()
        
        request = self.factory.post('/api/ai/generate/')
        request.user = self.user
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        
        # First request should pass
        self.assertTrue(throttle.allow_request(request, None))
        
        # Update token usage
        throttle.update_token_usage(request, 500)
        
        # Check token usage is tracked
        token_key = f'ai_tokens:{self.user.pk}'
        usage = cache.get(token_key)
        self.assertEqual(usage, 500)
        
        # Update again
        throttle.update_token_usage(request, 600)
        usage = cache.get(token_key)
        self.assertEqual(usage, 1100)
    
    @override_settings(AI_TOKEN_LIMIT_PER_HOUR=1000)
    def test_token_limit_exceeded(self):
        """Test that requests fail when token limit is exceeded."""
        throttle = AIAgentThrottle()
        
        request = self.factory.post('/api/ai/generate/')
        request.user = self.user
        request.user.ai_token_usage = True  # Enable token tracking
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        
        # Set high token usage
        token_key = f'ai_tokens:{self.user.pk}'
        cache.set(token_key, 1100, 3600)
        
        # Request should fail
        with self.assertRaises(Exception) as context:
            throttle.allow_request(request, None)
        
        self.assertIn('token limit exceeded', str(context.exception).lower())


class TestFileUploadThrottle(BaseRateLimitingTestCase):
    """Test file upload throttling."""
    
    @override_settings(FILE_UPLOAD_SIZE_LIMIT_PER_HOUR=1024*1024)  # 1MB for testing
    def test_upload_size_limit(self):
        """Test that upload size limits are enforced."""
        throttle = FileUploadThrottle()
        
        # Create mock file
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        request = self.factory.post('/api/files/upload/')
        request.user = self.user
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        request.method = 'POST'
        
        # Add a file that's within limit
        small_file = SimpleUploadedFile(
            "test.txt",
            b"x" * (512 * 1024),  # 512KB
            content_type="text/plain"
        )
        request.FILES = {'file': small_file}
        
        # Should pass
        self.assertTrue(throttle.allow_request(request, None))
        
        # Add another file that exceeds limit
        large_file = SimpleUploadedFile(
            "test2.txt",
            b"x" * (600 * 1024),  # 600KB
            content_type="text/plain"
        )
        request.FILES = {'file': large_file}
        
        # Should fail
        with self.assertRaises(Exception) as context:
            throttle.allow_request(request, None)
        
        self.assertIn('upload size limit exceeded', str(context.exception).lower())


class TestBurstRateThrottle(BaseRateLimitingTestCase):
    """Test burst rate throttling."""
    
    def test_burst_allowance(self):
        """Test that burst traffic is allowed up to limit."""
        throttle = BurstRateThrottle()
        throttle.burst_rate = '5/second'
        throttle.sustained_rate = '100/hour'
        
        request = self.factory.get('/')
        request.user = self.user
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        
        # Should allow burst of requests
        for i in range(5):
            self.assertTrue(throttle.allow_request(request, None))
        
        # Next immediate request should fail
        with self.assertRaises(Exception):
            throttle.allow_request(request, None)
    
    def test_token_refill(self):
        """Test that tokens refill over time."""
        throttle = BurstRateThrottle()
        throttle.burst_rate = '2/second'
        throttle.sustained_rate = '100/hour'
        
        request = self.factory.get('/')
        request.user = self.user
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        
        # Use up tokens
        self.assertTrue(throttle.allow_request(request, None))
        self.assertTrue(throttle.allow_request(request, None))
        
        # Should fail immediately
        with self.assertRaises(Exception):
            throttle.allow_request(request, None)
        
        # Wait for refill
        time.sleep(1)
        
        # Should allow again
        self.assertTrue(throttle.allow_request(request, None))


class TestScopedRateThrottle(BaseRateLimitingTestCase):
    """Test scoped rate throttling."""
    
    def test_different_scopes_different_limits(self):
        """Test that different scopes have different rate limits."""
        throttle = ScopedRateThrottle()
        
        # Create mock views with different scopes
        class AnalyticsView:
            throttle_scope = 'analytics'
        
        class SearchView:
            throttle_scope = 'search'
        
        request = self.factory.get('/')
        request.user = self.user
        request.META = {'REMOTE_ADDR': '127.0.0.1'}
        
        # Check different scopes
        analytics_scope = throttle.get_scope(request, AnalyticsView())
        search_scope = throttle.get_scope(request, SearchView())
        
        self.assertEqual(analytics_scope, 'analytics')
        self.assertEqual(search_scope, 'search')
        
        # Check rates are different
        self.assertNotEqual(
            throttle.THROTTLE_RATES['analytics'],
            throttle.THROTTLE_RATES['search']
        )


class TestRateLimitMiddleware(TestCase):
    """Test rate limit middleware."""
    
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.middleware = RateLimitHeadersMiddleware()
        self.monitoring_middleware = RateLimitMonitoringMiddleware()
    
    def test_headers_added_to_response(self):
        """Test that rate limit headers are added to API responses."""
        request = self.factory.get('/api/test/')
        request.rate_limit_limit = 100
        request.rate_limit_remaining = 75
        request.rate_limit_reset = 1234567890
        
        response = Response()
        processed_response = self.middleware.process_response(request, response)
        
        self.assertEqual(processed_response['X-RateLimit-Limit'], '100')
        self.assertEqual(processed_response['X-RateLimit-Remaining'], '75')
        self.assertEqual(processed_response['X-RateLimit-Reset'], '1234567890')
    
    def test_no_headers_for_non_api_endpoints(self):
        """Test that headers are not added to non-API endpoints."""
        request = self.factory.get('/admin/')
        response = Response()
        
        processed_response = self.middleware.process_response(request, response)
        
        self.assertNotIn('X-RateLimit-Limit', processed_response)
    
    def test_429_response_handling(self):
        """Test special handling for 429 responses."""
        request = self.factory.get('/api/test/')
        request.user = MagicMock(is_authenticated=True, id=123)
        
        response = Response(
            data={'detail': {'throttle_scope': 'user'}},
            status=429
        )
        
        with self.assertLogs('core.middleware.rate_limiting', level='WARNING') as logs:
            processed_response = self.middleware.process_response(request, response)
        
        self.assertIn('Rate limit exceeded', logs.output[0])
    
    @patch('core.middleware.rate_limiting.logger')
    def test_monitoring_alerts(self, mock_logger):
        """Test that monitoring alerts are triggered."""
        request = self.factory.get('/api/test/')
        request.rate_limit_limit = 100
        request.rate_limit_remaining = 15  # 85% usage
        request.user = MagicMock(is_authenticated=True, id=123)
        
        response = Response()
        self.monitoring_middleware.process_response(request, response)
        
        # Should trigger warning
        mock_logger.warning.assert_called_once()
        
        # Test critical alert
        request.rate_limit_remaining = 2  # 98% usage
        self.monitoring_middleware.process_response(request, response)
        
        # Should trigger error
        mock_logger.error.assert_called_once()


class TestIntegrationRateLimiting(BaseRateLimitingTestCase):
    """Integration tests for rate limiting with actual API calls."""
    
    @override_settings(
        REST_FRAMEWORK={
            'DEFAULT_THROTTLE_CLASSES': ['core.throttling.EnhancedUserRateThrottle'],
            'DEFAULT_THROTTLE_RATES': {'user': '5/minute'}
        }
    )
    def test_api_rate_limiting_integration(self):
        """Test rate limiting on actual API endpoints."""
        # Login first
        self.client.force_authenticate(user=self.user)
        
        # Make requests up to limit
        for i in range(5):
            response = self.client.get('/api/assessments/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('X-RateLimit-Remaining', response)
        
        # Next request should be throttled
        response = self.client.get('/api/assessments/')
        self.assertEqual(response.status_code, 429)
        self.assertIn('throttled', response.data.get('detail', '').lower())
    
    def test_different_users_different_limits(self):
        """Test that different users have independent rate limits."""
        # Clear any existing limits
        cache.clear()
        
        # First user makes request
        self.client.force_authenticate(user=self.user)
        response1 = self.client.get('/api/assessments/')
        self.assertEqual(response1.status_code, 200)
        
        # Second user should also be able to make request
        self.client.force_authenticate(user=self.admin)
        response2 = self.client.get('/api/assessments/')
        self.assertEqual(response2.status_code, 200)
        
        # Both should have independent limits
        self.assertIn('X-RateLimit-Remaining', response1)
        self.assertIn('X-RateLimit-Remaining', response2)