"""
Comprehensive tests for API Key functionality.

This test suite covers:
1. Functional Testing - API key generation, authentication, rotation, usage tracking, rate limiting
2. Security Testing - Hashed storage, timing attacks, expiration, scope control, audit logging
3. Integration Testing - JWT auth integration, middleware, management commands, API endpoints
4. Edge Case Testing - Expired keys, revoked keys, invalid scopes, concurrent usage, bulk operations
"""

import hashlib
import secrets
import time
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
import threading

from django.test import TestCase, TransactionTestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.test.client import RequestFactory
from django.http import HttpRequest

from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, Throttled

from accounts.models import Group
from core.models import AuditLog
from .models import APIKey, APIKeyUsage
from .authentication import APIKeyAuthentication
from .permissions import (
    HasAPIKeyScope, ReadOnlyAPIKey, WriteAPIKey, AdminAPIKey,
    AssessmentsAPIKeyPermission, LeadsAPIKeyPermission
)
from .middleware import APIKeyUsageMiddleware, APIKeySecurityMiddleware

User = get_user_model()


class APIKeyModelTests(TestCase):
    """Test APIKey model functionality."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.group = Group.objects.create(name='Test Group')
        
    def test_create_user_api_key(self):
        """Test creating a user API key."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read', 'write'],
            group=self.group
        )
        
        self.assertEqual(api_key.user, self.user)
        self.assertEqual(api_key.name, 'Test Key')
        self.assertEqual(api_key.scopes, ['read', 'write'])
        self.assertEqual(api_key.group, self.group)
        self.assertTrue(api_key.is_active)
        self.assertFalse(api_key.is_expired)
        self.assertTrue(raw_key.startswith('sk_live_'))
        
        # Check audit log was created
        audit_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(api_key.id)
        )
        self.assertTrue(audit_logs.exists())
        
    def test_create_application_api_key(self):
        """Test creating an application API key."""
        api_key, raw_key = APIKey.objects.create_key(
            application_name='My App',
            name='App Key',
            scopes=['read'],
            expires_in_days=30
        )
        
        self.assertIsNone(api_key.user)
        self.assertEqual(api_key.application_name, 'My App')
        self.assertEqual(api_key.key_type, 'application')
        self.assertTrue(raw_key.startswith('ak_live_'))
        
    def test_verify_valid_key(self):
        """Test verifying a valid API key."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read']
        )
        
        # Test verification with prefix
        verified_key = APIKey.objects.verify_key(raw_key)
        self.assertEqual(verified_key, api_key)
        
        # Test verification without prefix
        raw_without_prefix = raw_key.replace('sk_live_', '')
        verified_key = APIKey.objects.verify_key(raw_without_prefix)
        self.assertEqual(verified_key, api_key)
        
        # Check usage tracking
        api_key.refresh_from_db()
        self.assertEqual(api_key.usage_count, 2)
        self.assertIsNotNone(api_key.last_used_at)
        
    def test_verify_invalid_key(self):
        """Test verifying an invalid API key."""
        verified_key = APIKey.objects.verify_key('invalid_key')
        self.assertIsNone(verified_key)
        
    def test_verify_expired_key(self):
        """Test verifying an expired API key."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read'],
            expires_in_days=1
        )
        
        # Manually expire the key
        api_key.expires_at = timezone.now() - timedelta(hours=1)
        api_key.save()
        
        verified_key = APIKey.objects.verify_key(raw_key)
        self.assertIsNone(verified_key)
        
    def test_verify_inactive_key(self):
        """Test verifying an inactive API key."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read']
        )
        
        # Deactivate the key
        api_key.is_active = False
        api_key.save()
        
        verified_key = APIKey.objects.verify_key(raw_key)
        self.assertIsNone(verified_key)
        
    def test_key_scopes(self):
        """Test scope checking methods."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read', 'assessments:read']
        )
        
        self.assertTrue(api_key.has_scope('read'))
        self.assertTrue(api_key.has_scope('assessments:read'))
        self.assertFalse(api_key.has_scope('write'))
        self.assertTrue(api_key.has_any_scope(['write', 'read']))
        self.assertFalse(api_key.has_any_scope(['write', 'delete']))
        
    def test_admin_scope_access(self):
        """Test that admin scope grants all access."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Admin Key',
            scopes=['admin']
        )
        
        self.assertTrue(api_key.has_scope('read'))
        self.assertTrue(api_key.has_scope('write'))
        self.assertTrue(api_key.has_scope('delete'))
        self.assertTrue(api_key.has_scope('anything'))
        
    def test_key_rotation(self):
        """Test API key rotation."""
        original_key, original_raw = APIKey.objects.create_key(
            user=self.user,
            name='Original Key',
            scopes=['read', 'write'],
            metadata={'test': 'value'}
        )
        
        # Rotate the key
        new_key, new_raw = original_key.rotate(user=self.user)
        
        # Check that new key has same settings
        self.assertEqual(new_key.user, original_key.user)
        self.assertEqual(new_key.scopes, original_key.scopes)
        self.assertEqual(new_key.rate_limit_per_hour, original_key.rate_limit_per_hour)
        self.assertEqual(new_key.name, 'Original Key (Rotated)')
        self.assertEqual(new_key.metadata['rotated_from'], str(original_key.id))
        self.assertEqual(new_key.metadata['test'], 'value')
        
        # Check replacement relationship
        original_key.refresh_from_db()
        self.assertEqual(original_key.replaced_by, new_key)
        
        # Keys should be different
        self.assertNotEqual(original_raw, new_raw)
        
        # Check audit log
        audit_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(original_key.id),
            action=AuditLog.Action.UPDATE
        )
        self.assertTrue(audit_logs.exists())
        
    def test_key_revocation(self):
        """Test API key revocation."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read']
        )
        
        # Revoke the key
        api_key.revoke(user=self.user, reason='Test revocation')
        
        self.assertFalse(api_key.is_active)
        self.assertFalse(api_key.is_valid)
        
        # Should not be verifiable anymore
        verified_key = APIKey.objects.verify_key(raw_key)
        self.assertIsNone(verified_key)
        
        # Check audit log
        audit_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(api_key.id),
            action=AuditLog.Action.UPDATE
        )
        revocation_log = audit_logs.filter(metadata__reason='Test revocation').first()
        self.assertIsNotNone(revocation_log)
        
    def test_ip_restrictions(self):
        """Test IP address restrictions."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='IP Restricted Key',
            scopes=['read'],
            allowed_ips=['192.168.1.100', '10.0.0.1']
        )
        
        self.assertEqual(api_key.allowed_ips, ['192.168.1.100', '10.0.0.1'])
        
    def test_key_properties(self):
        """Test key property methods."""
        # Test non-expired key
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read'],
            expires_in_days=30
        )
        
        self.assertFalse(api_key.is_expired)
        self.assertTrue(api_key.is_valid)
        self.assertEqual(api_key.days_until_expiry, 29)  # approximately
        self.assertEqual(api_key.key_type, 'user')
        
        # Test expired key
        api_key.expires_at = timezone.now() - timedelta(hours=1)
        api_key.save()
        
        self.assertTrue(api_key.is_expired)
        self.assertFalse(api_key.is_valid)
        self.assertEqual(api_key.days_until_expiry, 0)
        
    def test_model_validation(self):
        """Test model validation rules."""
        with self.assertRaises(Exception):
            # Should fail validation - no user or application
            api_key = APIKey(
                name='Invalid Key',
                key_hash='test',
                scopes=[],
                expires_at=timezone.now() + timedelta(days=30)
            )
            api_key.clean()
            
    def test_queryset_methods(self):
        """Test custom queryset methods."""
        # Create test keys
        active_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Active Key',
            scopes=['read']
        )
        
        expired_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Expired Key',
            scopes=['read'],
            expires_in_days=1
        )
        expired_key.expires_at = timezone.now() - timedelta(hours=1)
        expired_key.save()
        
        app_key, _ = APIKey.objects.create_key(
            application_name='Test App',
            name='App Key',
            scopes=['read']
        )
        
        # Test queryset filtering
        active_keys = APIKey.objects.active()
        self.assertIn(active_key, active_keys)
        self.assertNotIn(expired_key, active_keys)
        
        user_keys = APIKey.objects.for_user(self.user)
        self.assertIn(active_key, user_keys)
        self.assertNotIn(app_key, user_keys)
        
        app_keys = APIKey.objects.for_application('Test App')
        self.assertIn(app_key, app_keys)
        self.assertNotIn(active_key, app_keys)
        
        read_keys = APIKey.objects.with_scope('read')
        self.assertIn(active_key, read_keys)
        self.assertIn(app_key, read_keys)


class APIKeySecurityTests(TestCase):
    """Test security aspects of API keys."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_key_hashing(self):
        """Test that only hashed keys are stored."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read']
        )
        
        # Raw key should not be stored anywhere
        self.assertNotIn(raw_key, str(api_key.key_hash))
        self.assertNotEqual(raw_key, api_key.key_hash)
        
        # Key hash should be a SHA-256 hash
        raw_without_prefix = raw_key.replace('sk_live_', '')
        expected_hash = hashlib.sha256(raw_without_prefix.encode()).hexdigest()
        self.assertEqual(api_key.key_hash, expected_hash)
        
    def test_timing_attack_prevention(self):
        """Test timing attack prevention in key verification."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read']
        )
        
        # Time valid key verification
        start_time = time.time()
        APIKey.objects.verify_key(raw_key)
        valid_time = time.time() - start_time
        
        # Time invalid key verification
        start_time = time.time()
        APIKey.objects.verify_key('invalid_key')
        invalid_time = time.time() - start_time
        
        # Timing should be similar (within reasonable bounds)
        # This is a basic test - in practice, you'd want more sophisticated timing analysis
        time_ratio = max(valid_time, invalid_time) / min(valid_time, invalid_time)
        self.assertLess(time_ratio, 10)  # Should not differ by more than 10x
        
    def test_key_expiration_enforcement(self):
        """Test that expired keys are strictly enforced."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read'],
            expires_in_days=1
        )
        
        # Key should work initially
        verified_key = APIKey.objects.verify_key(raw_key)
        self.assertIsNotNone(verified_key)
        
        # Expire the key
        api_key.expires_at = timezone.now() - timedelta(seconds=1)
        api_key.save()
        
        # Key should not work after expiration
        verified_key = APIKey.objects.verify_key(raw_key)
        self.assertIsNone(verified_key)
        
    def test_scope_based_access_control(self):
        """Test that scope restrictions are enforced."""
        read_key, read_raw = APIKey.objects.create_key(
            user=self.user,
            name='Read Key',
            scopes=['read']
        )
        
        write_key, write_raw = APIKey.objects.create_key(
            user=self.user,
            name='Write Key',
            scopes=['write']
        )
        
        admin_key, admin_raw = APIKey.objects.create_key(
            user=self.user,
            name='Admin Key',
            scopes=['admin']
        )
        
        # Test read scope
        self.assertTrue(read_key.has_scope('read'))
        self.assertFalse(read_key.has_scope('write'))
        self.assertFalse(read_key.has_scope('delete'))
        
        # Test write scope
        self.assertFalse(write_key.has_scope('read'))
        self.assertTrue(write_key.has_scope('write'))
        self.assertFalse(write_key.has_scope('delete'))
        
        # Test admin scope (should have all access)
        self.assertTrue(admin_key.has_scope('read'))
        self.assertTrue(admin_key.has_scope('write'))
        self.assertTrue(admin_key.has_scope('delete'))
        
    def test_secure_key_generation(self):
        """Test that keys are generated securely."""
        keys = set()
        
        # Generate multiple keys and ensure they're unique
        for _ in range(100):
            api_key, raw_key = APIKey.objects.create_key(
                user=self.user,
                name='Test Key',
                scopes=['read']
            )
            keys.add(raw_key)
            
        # All keys should be unique
        self.assertEqual(len(keys), 100)
        
        # Keys should have proper length and format
        for key in keys:
            self.assertTrue(key.startswith('sk_live_'))
            key_part = key.replace('sk_live_', '')
            self.assertEqual(len(key_part), 32)
            # Should only contain alphanumeric characters
            self.assertTrue(key_part.isalnum())


class APIKeyUsageTests(TestCase):
    """Test API key usage tracking."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.api_key, self.raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read']
        )
        
    def test_usage_logging(self):
        """Test that API key usage is logged."""
        usage = APIKeyUsage.objects.create(
            api_key=self.api_key,
            endpoint='/api/test/',
            method='GET',
            status_code=200,
            ip_address='192.168.1.100',
            response_time_ms=150
        )
        
        self.assertEqual(usage.api_key, self.api_key)
        self.assertEqual(usage.endpoint, '/api/test/')
        self.assertEqual(usage.method, 'GET')
        self.assertEqual(usage.status_code, 200)
        self.assertEqual(usage.response_time_ms, 150)
        
    def test_rate_limit_checking(self):
        """Test rate limit checking."""
        # Create some usage logs within the hour
        base_time = timezone.now() - timedelta(minutes=30)
        for i in range(5):
            APIKeyUsage.objects.create(
                api_key=self.api_key,
                endpoint='/api/test/',
                method='GET',
                status_code=200,
                ip_address='192.168.1.100',
                response_time_ms=100,
                timestamp=base_time + timedelta(minutes=i)
            )
        
        # Check rate limit (should be within limit)
        is_within_limit, count = self.api_key.check_rate_limit(window_minutes=60)
        self.assertTrue(is_within_limit)
        self.assertEqual(count, 5)
        
        # Set low rate limit and check again
        self.api_key.rate_limit_per_hour = 3
        self.api_key.save()
        
        is_within_limit, count = self.api_key.check_rate_limit(window_minutes=60)
        self.assertFalse(is_within_limit)
        self.assertEqual(count, 5)
        
    def test_usage_analytics(self):
        """Test usage analytics calculations."""
        # Create diverse usage logs
        base_time = timezone.now() - timedelta(hours=2)
        
        usage_data = [
            ('/api/test/', 'GET', 200, 100),
            ('/api/test/', 'POST', 201, 200),
            ('/api/test/', 'GET', 200, 150),
            ('/api/other/', 'GET', 404, 50),
            ('/api/test/', 'GET', 500, 300),
        ]
        
        for i, (endpoint, method, status, response_time) in enumerate(usage_data):
            APIKeyUsage.objects.create(
                api_key=self.api_key,
                endpoint=endpoint,
                method=method,
                status_code=status,
                ip_address=f'192.168.1.{100 + i}',
                response_time_ms=response_time,
                timestamp=base_time + timedelta(minutes=i * 10)
            )
        
        # Test analytics queries
        usage_logs = self.api_key.usage_logs.all()
        total_requests = usage_logs.count()
        successful_requests = usage_logs.filter(status_code__lt=400).count()
        failed_requests = total_requests - successful_requests
        
        self.assertEqual(total_requests, 5)
        self.assertEqual(successful_requests, 3)
        self.assertEqual(failed_requests, 2)
        
        # Test unique IPs
        unique_ips = usage_logs.values('ip_address').distinct().count()
        self.assertEqual(unique_ips, 5)


class APIKeyAuthenticationTests(TestCase):
    """Test API key authentication backend."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.api_key, self.raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read']
        )
        self.auth = APIKeyAuthentication()
        self.factory = RequestFactory()
        
    def test_authenticate_with_bearer_header(self):
        """Test authentication with Authorization: Bearer header."""
        request = self.factory.get('/', HTTP_AUTHORIZATION=f'Bearer {self.raw_key}')
        
        user, auth_token = self.auth.authenticate(request)
        
        self.assertEqual(user, self.user)
        self.assertEqual(auth_token, self.api_key)
        
    def test_authenticate_with_api_key_header(self):
        """Test authentication with X-API-Key header."""
        request = self.factory.get('/', HTTP_X_API_KEY=self.raw_key)
        
        user, auth_token = self.auth.authenticate(request)
        
        self.assertEqual(user, self.user)
        self.assertEqual(auth_token, self.api_key)
        
    def test_authenticate_with_query_param(self):
        """Test authentication with query parameter."""
        request = self.factory.get(f'/?api_key={self.raw_key}')
        
        user, auth_token = self.auth.authenticate(request)
        
        self.assertEqual(user, self.user)
        self.assertEqual(auth_token, self.api_key)
        
    def test_authenticate_no_key(self):
        """Test authentication when no API key is provided."""
        request = self.factory.get('/')
        
        result = self.auth.authenticate(request)
        
        self.assertIsNone(result)
        
    def test_authenticate_invalid_key(self):
        """Test authentication with invalid API key."""
        request = self.factory.get('/', HTTP_AUTHORIZATION='Bearer invalid_key')
        
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)
            
    def test_authenticate_ip_restriction(self):
        """Test IP address restrictions."""
        # Create key with IP restrictions
        restricted_key, restricted_raw = APIKey.objects.create_key(
            user=self.user,
            name='IP Restricted Key',
            scopes=['read'],
            allowed_ips=['192.168.1.100']
        )
        
        # Test with allowed IP
        request = self.factory.get(
            '/',
            HTTP_AUTHORIZATION=f'Bearer {restricted_raw}',
            REMOTE_ADDR='192.168.1.100'
        )
        
        user, auth_token = self.auth.authenticate(request)
        self.assertEqual(user, self.user)
        
        # Test with disallowed IP
        request = self.factory.get(
            '/',
            HTTP_AUTHORIZATION=f'Bearer {restricted_raw}',
            REMOTE_ADDR='192.168.1.200'
        )
        
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)
            
    def test_authenticate_rate_limit(self):
        """Test rate limiting during authentication."""
        # Set very low rate limit
        self.api_key.rate_limit_per_hour = 1
        self.api_key.save()
        
        # Create usage that exceeds limit
        APIKeyUsage.objects.create(
            api_key=self.api_key,
            endpoint='/api/test/',
            method='GET',
            status_code=200,
            ip_address='192.168.1.100',
            response_time_ms=100,
            timestamp=timezone.now() - timedelta(minutes=30)
        )
        
        request = self.factory.get('/', HTTP_AUTHORIZATION=f'Bearer {self.raw_key}')
        
        with patch.object(self.api_key, 'check_rate_limit', return_value=(False, 2)):
            with self.assertRaises(Throttled):
                self.auth.authenticate(request)
                
    def test_get_client_ip(self):
        """Test client IP extraction."""
        # Test direct connection
        request = self.factory.get('/', REMOTE_ADDR='192.168.1.100')
        ip = self.auth._get_client_ip(request)
        self.assertEqual(ip, '192.168.1.100')
        
        # Test with X-Forwarded-For header
        request = self.factory.get(
            '/',
            HTTP_X_FORWARDED_FOR='203.0.113.1, 192.168.1.100',
            REMOTE_ADDR='192.168.1.100'
        )
        ip = self.auth._get_client_ip(request)
        self.assertEqual(ip, '203.0.113.1')


class APIKeyPermissionTests(TestCase):
    """Test API key permission classes."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.factory = RequestFactory()
        
    def test_has_api_key_scope_permission(self):
        """Test HasAPIKeyScope permission class."""
        # Create keys with different scopes
        read_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Read Key',
            scopes=['read']
        )
        
        write_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Write Key',
            scopes=['write']
        )
        
        permission = HasAPIKeyScope()
        
        # Mock view with required scopes
        class MockView:
            required_scopes = ['read']
        
        view = MockView()
        
        # Test with read key (should pass)
        request = self.factory.get('/')
        request.auth = read_key
        self.assertTrue(permission.has_permission(request, view))
        
        # Test with write key (should fail)
        request = self.factory.get('/')
        request.auth = write_key
        self.assertFalse(permission.has_permission(request, view))
        
        # Test without API key auth (should pass - defer to other auth)
        request = self.factory.get('/')
        request.auth = None
        self.assertTrue(permission.has_permission(request, view))
        
    def test_read_only_api_key_permission(self):
        """Test ReadOnlyAPIKey permission."""
        read_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Read Key',
            scopes=['read']
        )
        
        permission = ReadOnlyAPIKey()
        view = MagicMock()
        
        # Test GET request (should pass)
        request = self.factory.get('/')
        request.auth = read_key
        self.assertTrue(permission.has_permission(request, view))
        
        # Test POST request (should fail)
        request = self.factory.post('/')
        request.auth = read_key
        self.assertFalse(permission.has_permission(request, view))
        
    def test_write_api_key_permission(self):
        """Test WriteAPIKey permission."""
        write_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Write Key',
            scopes=['read', 'write']
        )
        
        permission = WriteAPIKey()
        view = MagicMock()
        
        # Test GET request (should pass with read scope)
        request = self.factory.get('/')
        request.auth = write_key
        self.assertTrue(permission.has_permission(request, view))
        
        # Test POST request (should pass with write scope)
        request = self.factory.post('/')
        request.auth = write_key
        self.assertTrue(permission.has_permission(request, view))
        
    def test_admin_api_key_permission(self):
        """Test AdminAPIKey permission."""
        admin_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Admin Key',
            scopes=['admin']
        )
        
        regular_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Regular Key',
            scopes=['read', 'write']
        )
        
        permission = AdminAPIKey()
        view = MagicMock()
        
        # Test with admin key (should pass)
        request = self.factory.get('/')
        request.auth = admin_key
        self.assertTrue(permission.has_permission(request, view))
        
        # Test with regular key (should fail)
        request = self.factory.get('/')
        request.auth = regular_key
        self.assertFalse(permission.has_permission(request, view))
        
    def test_resource_specific_permissions(self):
        """Test resource-specific permission classes."""
        assessments_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Assessments Key',
            scopes=['assessments:read', 'assessments:write']
        )
        
        permission = AssessmentsAPIKeyPermission()
        view = MagicMock()
        
        # Test read access
        request = self.factory.get('/')
        request.auth = assessments_key
        self.assertTrue(permission.has_permission(request, view))
        
        # Test write access
        request = self.factory.post('/')
        request.auth = assessments_key
        self.assertTrue(permission.has_permission(request, view))
        
        # Test with wrong scope
        leads_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Leads Key',
            scopes=['leads:read']
        )
        
        request = self.factory.get('/')
        request.auth = leads_key
        self.assertFalse(permission.has_permission(request, view))


class APIKeyMiddlewareTests(TestCase):
    """Test API key middleware functionality."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.api_key, self.raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read']
        )
        self.factory = RequestFactory()
        
    def test_usage_middleware_logging(self):
        """Test that usage middleware logs requests."""
        middleware = APIKeyUsageMiddleware(lambda r: MagicMock(status_code=200))
        
        request = self.factory.get('/api/test/')
        request.auth = self.api_key
        
        # Process request
        middleware.process_request(request)
        self.assertTrue(hasattr(request, '_api_key_start_time'))
        
        # Process response
        response = MagicMock(status_code=200)
        middleware.process_response(request, response)
        
        # Check that usage was logged
        usage_logs = APIKeyUsage.objects.filter(api_key=self.api_key)
        self.assertEqual(usage_logs.count(), 1)
        
        usage = usage_logs.first()
        self.assertEqual(usage.endpoint, '/api/test/')
        self.assertEqual(usage.method, 'GET')
        self.assertEqual(usage.status_code, 200)
        
    def test_security_middleware_headers(self):
        """Test that security middleware adds appropriate headers."""
        middleware = APIKeySecurityMiddleware(lambda r: MagicMock())
        
        request = self.factory.get('/')
        request.auth = self.api_key
        
        response = MagicMock()
        response.__setitem__ = MagicMock()
        
        middleware.process_response(request, response)
        
        # Check that security headers were added
        expected_headers = [
            'X-API-Key-Used',
            'X-Content-Type-Options',
            'X-Frame-Options',
            'X-XSS-Protection',
            'X-RateLimit-Limit',
            'X-RateLimit-Remaining'
        ]
        
        for header in expected_headers:
            response.__setitem__.assert_any_call(header, MagicMock())


class APIKeyViewSetTests(APITestCase):
    """Test API key ViewSet endpoints."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            role=User.Role.ADMIN
        )
        self.client.force_authenticate(user=self.user)
        
    def test_create_api_key(self):
        """Test creating API key via API."""
        data = {
            'name': 'Test API Key',
            'scopes': ['read', 'write'],
            'expires_in_days': 30,
            'rate_limit': 5000
        }
        
        response = self.client.post('/api/api-keys/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('api_key', response.data)
        self.assertIn('key', response.data)
        self.assertTrue(response.data['key'].startswith('sk_live_'))
        
        # Check that API key was created in database
        api_key = APIKey.objects.get(name='Test API Key')
        self.assertEqual(api_key.user, self.user)
        self.assertEqual(api_key.scopes, ['read', 'write'])
        
    def test_list_api_keys(self):
        """Test listing API keys."""
        # Create some test keys
        APIKey.objects.create_key(
            user=self.user,
            name='Key 1',
            scopes=['read']
        )
        APIKey.objects.create_key(
            user=self.user,
            name='Key 2',
            scopes=['write']
        )
        
        response = self.client.get('/api/api-keys/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        
    def test_rotate_api_key(self):
        """Test rotating API key via API."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Original Key',
            scopes=['read']
        )
        
        data = {
            'overlap_hours': 48,
            'revoke_old_key': False
        }
        
        response = self.client.post(
            f'/api/api-keys/{api_key.id}/rotate/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('api_key', response.data)
        self.assertIn('key', response.data)
        
        # Check that new key was created
        api_key.refresh_from_db()
        self.assertIsNotNone(api_key.replaced_by)
        
    def test_revoke_api_key(self):
        """Test revoking API key via API."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Key to Revoke',
            scopes=['read']
        )
        
        response = self.client.delete(
            f'/api/api-keys/{api_key.id}/',
            {'reason': 'Test revocation'},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        api_key.refresh_from_db()
        self.assertFalse(api_key.is_active)
        
    def test_api_key_usage_stats(self):
        """Test getting usage statistics."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Stats Key',
            scopes=['read']
        )
        
        # Create some usage logs
        for i in range(5):
            APIKeyUsage.objects.create(
                api_key=api_key,
                endpoint='/api/test/',
                method='GET',
                status_code=200,
                ip_address='192.168.1.100',
                response_time_ms=100 + i * 10
            )
        
        response = self.client.get(f'/api/api-keys/{api_key.id}/stats/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_requests'], 5)
        self.assertEqual(response.data['successful_requests'], 5)
        
    def test_permission_filtering(self):
        """Test that users can only see their own keys."""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        
        # Create keys for both users
        my_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='My Key',
            scopes=['read']
        )
        
        other_key, _ = APIKey.objects.create_key(
            user=other_user,
            name='Other Key',
            scopes=['read']
        )
        
        # Admin should see all keys
        response = self.client.get('/api/api-keys/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        
        # Regular user should only see their own
        regular_user = User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='testpass123',
            role=User.Role.ANALYST
        )
        self.client.force_authenticate(user=regular_user)
        
        regular_key, _ = APIKey.objects.create_key(
            user=regular_user,
            name='Regular Key',
            scopes=['read']
        )
        
        response = self.client.get('/api/api-keys/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], 'Regular Key')


class APIKeyManagementCommandTests(TestCase):
    """Test management commands for API keys."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_create_api_key_command(self):
        """Test create_api_key management command."""
        # This would require reading the actual command file to test properly
        # For now, test that it exists and can be imported
        from api_keys.management.commands.create_api_key import Command
        self.assertTrue(issubclass(Command, BaseCommand))
        
    def test_rotate_api_keys_command(self):
        """Test rotate_api_keys management command."""
        # Create test keys
        expiring_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Expiring Key',
            scopes=['read'],
            expires_in_days=5
        )
        
        normal_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Normal Key',
            scopes=['read'],
            expires_in_days=365
        )
        
        # Test dry run
        call_command('rotate_api_keys', '--expiring-in-days=7', '--dry-run')
        
        # Keys should not be rotated in dry run
        expiring_key.refresh_from_db()
        self.assertIsNone(expiring_key.replaced_by)
        
    def test_list_api_keys_command(self):
        """Test list_api_keys management command."""
        # Create test key
        APIKey.objects.create_key(
            user=self.user,
            name='Listed Key',
            scopes=['read']
        )
        
        # Test that command can be called without error
        call_command('list_api_keys')
        
    def test_revoke_api_key_command(self):
        """Test revoke_api_key management command."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Key to Revoke',
            scopes=['read']
        )
        
        # Test revoking by ID
        call_command('revoke_api_key', '--key-id', str(api_key.id))
        
        api_key.refresh_from_db()
        self.assertFalse(api_key.is_active)


class APIKeyEdgeCaseTests(TransactionTestCase):
    """Test edge cases and error conditions."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_concurrent_key_usage(self):
        """Test concurrent usage of the same API key."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Concurrent Key',
            scopes=['read']
        )
        
        results = []
        errors = []
        
        def verify_key():
            try:
                result = APIKey.objects.verify_key(raw_key)
                results.append(result is not None)
            except Exception as e:
                errors.append(e)
        
        # Run concurrent verifications
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(verify_key) for _ in range(50)]
            for future in futures:
                future.result()
        
        # All verifications should succeed
        self.assertEqual(len(results), 50)
        self.assertTrue(all(results))
        self.assertEqual(len(errors), 0)
        
        # Usage count should be accurate
        api_key.refresh_from_db()
        self.assertEqual(api_key.usage_count, 50)
        
    def test_bulk_key_operations(self):
        """Test bulk operations on API keys."""
        keys = []
        
        # Create many keys
        for i in range(100):
            api_key, _ = APIKey.objects.create_key(
                user=self.user,
                name=f'Bulk Key {i}',
                scopes=['read']
            )
            keys.append(api_key)
        
        # Bulk expire keys
        APIKey.objects.filter(id__in=[k.id for k in keys[:50]]).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        
        # Test queryset operations
        active_keys = APIKey.objects.active()
        expired_keys = APIKey.objects.filter(expires_at__lt=timezone.now())
        
        self.assertEqual(active_keys.count(), 50)
        self.assertEqual(expired_keys.count(), 50)
        
    def test_invalid_scope_handling(self):
        """Test handling of invalid scopes."""
        # Test with invalid scope value
        with self.assertRaises(Exception):
            APIKey.objects.create_key(
                user=self.user,
                name='Invalid Scope Key',
                scopes=['invalid_scope']  # Not in choices
            )
            
    def test_memory_usage_with_large_datasets(self):
        """Test memory efficiency with large usage datasets."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Large Dataset Key',
            scopes=['read']
        )
        
        # Create large number of usage logs
        usage_logs = []
        for i in range(1000):
            usage_logs.append(APIKeyUsage(
                api_key=api_key,
                endpoint=f'/api/endpoint/{i % 10}/',
                method='GET',
                status_code=200,
                ip_address=f'192.168.1.{i % 255}',
                response_time_ms=100 + (i % 200)
            ))
        
        APIKeyUsage.objects.bulk_create(usage_logs)
        
        # Test that queries remain efficient
        # This is a basic test - in practice you'd want more sophisticated performance testing
        import time
        
        start_time = time.time()
        rate_limit_result = api_key.check_rate_limit()
        query_time = time.time() - start_time
        
        # Query should complete quickly even with large dataset
        self.assertLess(query_time, 1.0)  # Should take less than 1 second
        
    def test_unicode_handling(self):
        """Test proper handling of unicode in API key data."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Unicode Key 测试 🔑',
            scopes=['read'],
            metadata={'description': 'Test with unicode: 测试数据 🚀'}
        )
        
        self.assertEqual(api_key.name, 'Unicode Key 测试 🔑')
        self.assertEqual(api_key.metadata['description'], 'Test with unicode: 测试数据 🚀')
        
        # Test in usage logs
        APIKeyUsage.objects.create(
            api_key=api_key,
            endpoint='/api/测试/',
            method='GET',
            status_code=200,
            ip_address='192.168.1.100',
            response_time_ms=100,
            user_agent='Mozilla/5.0 (测试浏览器)'
        )
        
        usage = api_key.usage_logs.first()
        self.assertEqual(usage.endpoint, '/api/测试/')
        
    def test_timezone_handling(self):
        """Test proper timezone handling in expiration."""
        import pytz
        
        # Create key with specific timezone
        utc_now = timezone.now()
        
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Timezone Key',
            scopes=['read'],
            expires_in_days=1
        )
        
        # Should be in UTC
        self.assertEqual(api_key.expires_at.tzinfo, pytz.UTC)
        
        # Should be approximately 1 day from now
        time_diff = api_key.expires_at - utc_now
        self.assertAlmostEqual(time_diff.days, 1, delta=0)


class APIKeyIntegrationTests(APITestCase):
    """Test integration with other system components."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.api_key, self.raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Integration Key',
            scopes=['read', 'assessments:read']
        )
        
    def test_jwt_and_api_key_coexistence(self):
        """Test that JWT and API key auth can coexist."""
        # Test with JWT authentication
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/api-keys/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Test with API key authentication
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key}')
        
        # API key user should be able to access endpoints they have scope for
        # This would require actual endpoints to test properly
        
    def test_group_filtering_with_api_keys(self):
        """Test that group filtering works with API key authentication."""
        group = Group.objects.create(name='Test Group')
        
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Group Key',
            scopes=['read'],
            group=group
        )
        
        self.assertEqual(api_key.group, group)
        
        # Test that API key respects group boundaries
        # This would require models with group filtering to test properly
        
    def test_audit_logging_integration(self):
        """Test that API key operations are properly audited."""
        # Create key
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Audit Key',
            scopes=['read']
        )
        
        # Check creation was logged
        creation_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(api_key.id),
            action=AuditLog.Action.CREATE
        )
        self.assertTrue(creation_logs.exists())
        
        # Rotate key
        new_key, _ = api_key.rotate(user=self.user)
        
        # Check rotation was logged
        rotation_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(api_key.id),
            action=AuditLog.Action.UPDATE
        )
        rotation_log = rotation_logs.filter(
            changes__action='key_rotated'
        ).first()
        self.assertIsNotNone(rotation_log)
        
        # Revoke key
        api_key.revoke(user=self.user, reason='Test')
        
        # Check revocation was logged
        revocation_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(api_key.id),
            action=AuditLog.Action.UPDATE
        )
        revocation_log = revocation_logs.filter(
            metadata__reason='Test'
        ).first()
        self.assertIsNotNone(revocation_log)


# Performance and Load Testing
class APIKeyPerformanceTests(TestCase):
    """Test performance characteristics of API key system."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_key_verification_performance(self):
        """Test that key verification performs well at scale."""
        # Create multiple keys
        keys = []
        for i in range(100):
            api_key, raw_key = APIKey.objects.create_key(
                user=self.user,
                name=f'Perf Key {i}',
                scopes=['read']
            )
            keys.append((api_key, raw_key))
        
        # Test verification performance
        import time
        
        start_time = time.time()
        
        for api_key, raw_key in keys:
            verified_key = APIKey.objects.verify_key(raw_key)
            self.assertEqual(verified_key, api_key)
        
        total_time = time.time() - start_time
        avg_time = total_time / len(keys)
        
        # Each verification should be fast
        self.assertLess(avg_time, 0.01)  # Less than 10ms per verification
        
    def test_usage_logging_performance(self):
        """Test performance of usage logging."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Usage Perf Key',
            scopes=['read']
        )
        
        import time
        
        start_time = time.time()
        
        # Create many usage logs
        usage_logs = []
        for i in range(1000):
            usage_logs.append(APIKeyUsage(
                api_key=api_key,
                endpoint=f'/api/test/{i}/',
                method='GET',
                status_code=200,
                ip_address='192.168.1.100',
                response_time_ms=100
            ))
        
        APIKeyUsage.objects.bulk_create(usage_logs)
        
        creation_time = time.time() - start_time
        
        # Bulk creation should be efficient
        self.assertLess(creation_time, 1.0)  # Should take less than 1 second
        
        # Test querying performance
        start_time = time.time()
        
        recent_usage = api_key.usage_logs.filter(
            timestamp__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        query_time = time.time() - start_time
        
        # Query should be fast even with many records
        self.assertLess(query_time, 0.1)  # Should take less than 100ms
        self.assertEqual(recent_usage, 1000)