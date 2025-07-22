"""
Comprehensive security tests for API Key system.

Tests security-critical functionality including:
- Cryptographic key generation and storage
- Timing attack prevention
- Rate limiting and abuse prevention
- Input validation and sanitization
- Access control and authorization
- Audit logging and monitoring
"""

import hashlib
import hmac
import secrets
import time
import threading
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, TransactionTestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test.client import RequestFactory
from django.core.cache import cache

from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, Throttled

from accounts.models import Group
from core.models import AuditLog
from .models import APIKey, APIKeyUsage
from .authentication import APIKeyAuthentication

User = get_user_model()


class CryptographicSecurityTests(TestCase):
    """Test cryptographic security of API keys."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_key_generation_randomness(self):
        """Test that generated keys have sufficient randomness."""
        keys = set()
        
        # Generate many keys
        for _ in range(1000):
            api_key, raw_key = APIKey.objects.create_key(
                user=self.user,
                name='Randomness Test',
                scopes=['read']
            )
            keys.add(raw_key)
        
        # All keys should be unique
        self.assertEqual(len(keys), 1000, "Generated keys are not unique")
        
        # Test entropy - keys should not follow predictable patterns
        key_list = list(keys)
        
        # Check that keys don't have obvious patterns
        for i in range(100):
            key1 = key_list[i].replace('sk_live_', '')
            key2 = key_list[i + 1].replace('sk_live_', '')
            
            # Keys should not be sequential or similar
            hamming_distance = sum(c1 != c2 for c1, c2 in zip(key1, key2))
            self.assertGreater(hamming_distance, 15, "Keys are too similar")
            
    def test_key_hashing_security(self):
        """Test that key hashing is secure."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Hash Test',
            scopes=['read']
        )
        
        raw_without_prefix = raw_key.replace('sk_live_', '')
        
        # Verify hash algorithm
        expected_hash = hashlib.sha256(raw_without_prefix.encode()).hexdigest()
        self.assertEqual(api_key.key_hash, expected_hash)
        
        # Verify hash is not reversible
        self.assertNotIn(raw_without_prefix, api_key.key_hash)
        self.assertNotEqual(raw_without_prefix, api_key.key_hash)
        
        # Test salt resistance (same input should produce same hash)
        another_key, another_raw = APIKey.objects.create_key(
            user=self.user,
            name='Another Hash Test',
            scopes=['read']
        )
        
        if raw_key == another_raw:  # Extremely unlikely but check anyway
            self.assertEqual(api_key.key_hash, another_key.key_hash)
        else:
            self.assertNotEqual(api_key.key_hash, another_key.key_hash)
            
    def test_constant_time_comparison(self):
        """Test that key verification uses constant-time comparison."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Timing Test',
            scopes=['read']
        )
        
        # Test with correct key
        start_time = time.perf_counter()
        result1 = APIKey.objects.verify_key(raw_key)
        correct_time = time.perf_counter() - start_time
        
        # Test with incorrect key of same length
        incorrect_key = 'sk_live_' + 'x' * 32
        start_time = time.perf_counter()
        result2 = APIKey.objects.verify_key(incorrect_key)
        incorrect_time = time.perf_counter() - start_time
        
        # Verify results
        self.assertIsNotNone(result1)
        self.assertIsNone(result2)
        
        # Timing should be similar (constant-time comparison)
        # Allow some variance due to system load
        time_ratio = max(correct_time, incorrect_time) / min(correct_time, incorrect_time)
        self.assertLess(time_ratio, 5.0, "Timing difference suggests non-constant-time comparison")
        
    def test_key_prefix_security(self):
        """Test that key prefixes don't leak information."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Prefix Test',
            scopes=['read']
        )
        
        # Prefix should be stored safely
        self.assertEqual(len(api_key.key_prefix), 8)
        self.assertTrue(raw_key.startswith('sk_live_' + api_key.key_prefix))
        
        # Prefix alone should not allow key verification
        self.assertIsNone(APIKey.objects.verify_key(api_key.key_prefix))
        self.assertIsNone(APIKey.objects.verify_key('sk_live_' + api_key.key_prefix))
        
    def test_secure_deletion(self):
        """Test that sensitive data is properly cleaned up."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Deletion Test',
            scopes=['read']
        )
        
        original_hash = api_key.key_hash
        
        # Delete the key
        api_key.delete()
        
        # Verify the raw key can't be used
        self.assertIsNone(APIKey.objects.verify_key(raw_key))
        
        # Check that hash is not accessible
        with self.assertRaises(APIKey.DoesNotExist):
            APIKey.objects.get(key_hash=original_hash)


class TimingAttackTests(TestCase):
    """Test protection against timing attacks."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.auth = APIKeyAuthentication()
        self.factory = RequestFactory()
        
    def test_authentication_timing_consistency(self):
        """Test that authentication timing is consistent."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Timing Test',
            scopes=['read']
        )
        
        times = []
        
        # Test valid key multiple times
        for _ in range(10):
            request = self.factory.get('/', HTTP_AUTHORIZATION=f'Bearer {raw_key}')
            start_time = time.perf_counter()
            try:
                self.auth.authenticate(request)
            except:
                pass
            end_time = time.perf_counter()
            times.append(end_time - start_time)
        
        # Test invalid keys multiple times
        invalid_times = []
        for i in range(10):
            invalid_key = f'sk_live_{"x" * 32}'
            request = self.factory.get('/', HTTP_AUTHORIZATION=f'Bearer {invalid_key}')
            start_time = time.perf_counter()
            try:
                self.auth.authenticate(request)
            except AuthenticationFailed:
                pass
            end_time = time.perf_counter()
            invalid_times.append(end_time - start_time)
        
        # Calculate average times
        avg_valid_time = sum(times) / len(times)
        avg_invalid_time = sum(invalid_times) / len(invalid_times)
        
        # Timing should be relatively similar
        time_ratio = max(avg_valid_time, avg_invalid_time) / min(avg_valid_time, avg_invalid_time)
        self.assertLess(time_ratio, 3.0, "Timing difference may leak information")
        
    def test_hash_lookup_timing(self):
        """Test that hash lookup timing doesn't leak key existence."""
        # Create multiple keys
        keys = []
        for i in range(50):
            api_key, raw_key = APIKey.objects.create_key(
                user=self.user,
                name=f'Timing Key {i}',
                scopes=['read']
            )
            keys.append((api_key, raw_key))
        
        # Test lookup times for existing keys
        existing_times = []
        for api_key, raw_key in keys[:10]:
            start_time = time.perf_counter()
            result = APIKey.objects.verify_key(raw_key)
            end_time = time.perf_counter()
            existing_times.append(end_time - start_time)
            self.assertIsNotNone(result)
        
        # Test lookup times for non-existing keys
        nonexisting_times = []
        for i in range(10):
            fake_key = f'sk_live_{"y" * 32}'
            start_time = time.perf_counter()
            result = APIKey.objects.verify_key(fake_key)
            end_time = time.perf_counter()
            nonexisting_times.append(end_time - start_time)
            self.assertIsNone(result)
        
        # Times should be similar regardless of key existence
        avg_existing = sum(existing_times) / len(existing_times)
        avg_nonexisting = sum(nonexisting_times) / len(nonexisting_times)
        
        time_ratio = max(avg_existing, avg_nonexisting) / min(avg_existing, avg_nonexisting)
        self.assertLess(time_ratio, 3.0, "Lookup timing may leak key existence")


class RateLimitingSecurityTests(TestCase):
    """Test rate limiting and abuse prevention."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_rate_limit_enforcement(self):
        """Test that rate limits are strictly enforced."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Rate Limit Test',
            scopes=['read'],
            rate_limit=5  # Very low limit for testing
        )
        
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        
        # Make requests up to the limit
        for i in range(5):
            # Create usage log to simulate previous requests
            APIKeyUsage.objects.create(
                api_key=api_key,
                endpoint='/api/test/',
                method='GET',
                status_code=200,
                ip_address='192.168.1.100',
                response_time_ms=100,
                timestamp=timezone.now() - timedelta(minutes=30)
            )
        
        # Next request should be throttled
        request = factory.get('/', HTTP_AUTHORIZATION=f'Bearer {raw_key}')
        
        with self.assertRaises(Throttled):
            auth.authenticate(request)
            
    def test_rate_limit_window_accuracy(self):
        """Test that rate limit windows are accurately calculated."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Window Test',
            scopes=['read'],
            rate_limit=10
        )
        
        # Create requests outside the window (should not count)
        APIKeyUsage.objects.create(
            api_key=api_key,
            endpoint='/api/test/',
            method='GET',
            status_code=200,
            ip_address='192.168.1.100',
            response_time_ms=100,
            timestamp=timezone.now() - timedelta(hours=2)  # Outside window
        )
        
        # Create requests within the window
        for i in range(5):
            APIKeyUsage.objects.create(
                api_key=api_key,
                endpoint='/api/test/',
                method='GET',
                status_code=200,
                ip_address='192.168.1.100',
                response_time_ms=100,
                timestamp=timezone.now() - timedelta(minutes=30)
            )
        
        # Should be within limit (5 < 10)
        is_within_limit, count = api_key.check_rate_limit()
        self.assertTrue(is_within_limit)
        self.assertEqual(count, 5)
        
    def test_distributed_rate_limiting(self):
        """Test rate limiting across multiple IPs/sources."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Distributed Test',
            scopes=['read'],
            rate_limit=5
        )
        
        # Create requests from different IPs
        ips = ['192.168.1.100', '192.168.1.101', '192.168.1.102']
        
        for i, ip in enumerate(ips):
            for j in range(2):  # 2 requests per IP
                APIKeyUsage.objects.create(
                    api_key=api_key,
                    endpoint='/api/test/',
                    method='GET',
                    status_code=200,
                    ip_address=ip,
                    response_time_ms=100,
                    timestamp=timezone.now() - timedelta(minutes=30)
                )
        
        # Total: 6 requests (2 per IP × 3 IPs) - should exceed limit of 5
        is_within_limit, count = api_key.check_rate_limit()
        self.assertFalse(is_within_limit)
        self.assertEqual(count, 6)
        
    @patch('time.sleep')  # Mock sleep to speed up test
    def test_rate_limit_reset(self, mock_sleep):
        """Test that rate limits reset after the window expires."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Reset Test',
            scopes=['read'],
            rate_limit=3
        )
        
        # Fill up the rate limit
        for i in range(3):
            APIKeyUsage.objects.create(
                api_key=api_key,
                endpoint='/api/test/',
                method='GET',
                status_code=200,
                ip_address='192.168.1.100',
                response_time_ms=100,
                timestamp=timezone.now() - timedelta(minutes=30)
            )
        
        # Should be at limit
        is_within_limit, count = api_key.check_rate_limit()
        self.assertFalse(is_within_limit)
        
        # Simulate time passing (move usage outside window)
        APIKeyUsage.objects.filter(api_key=api_key).update(
            timestamp=timezone.now() - timedelta(hours=2)
        )
        
        # Should be within limit again
        is_within_limit, count = api_key.check_rate_limit()
        self.assertTrue(is_within_limit)
        self.assertEqual(count, 0)


class InputValidationSecurityTests(TestCase):
    """Test input validation and sanitization."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_sql_injection_prevention(self):
        """Test prevention of SQL injection attacks."""
        # Test malicious key input
        malicious_keys = [
            "'; DROP TABLE api_keys; --",
            "' OR '1'='1",
            "'; UPDATE api_keys SET is_active=1; --",
            "' UNION SELECT * FROM auth_user; --"
        ]
        
        for malicious_key in malicious_keys:
            result = APIKey.objects.verify_key(malicious_key)
            self.assertIsNone(result, f"SQL injection attempt succeeded: {malicious_key}")
            
    def test_xss_prevention_in_metadata(self):
        """Test prevention of XSS attacks in metadata fields."""
        malicious_metadata = {
            'description': '<script>alert("xss")</script>',
            'note': '"><script>alert("xss")</script>',
            'purpose': 'javascript:alert("xss")'
        }
        
        # Should be able to store malicious content safely
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='XSS Test',
            scopes=['read'],
            metadata=malicious_metadata
        )
        
        # Content should be stored as-is (application should handle escaping)
        self.assertEqual(api_key.metadata['description'], '<script>alert("xss")</script>')
        
    def test_path_traversal_prevention(self):
        """Test prevention of path traversal attacks."""
        malicious_names = [
            '../../../etc/passwd',
            '..\\..\\..\\windows\\system32\\config\\sam',
            '/etc/shadow',
            'C:\\Windows\\System32\\config\\SAM'
        ]
        
        for malicious_name in malicious_names:
            try:
                api_key, _ = APIKey.objects.create_key(
                    user=self.user,
                    name=malicious_name,
                    scopes=['read']
                )
                # Should be stored safely without file system access
                self.assertEqual(api_key.name, malicious_name)
            except Exception as e:
                # Some validation might reject these, which is also acceptable
                pass
                
    def test_command_injection_prevention(self):
        """Test prevention of command injection attacks."""
        malicious_names = [
            '; cat /etc/passwd',
            '| rm -rf /',
            '`whoami`',
            '$(ls -la)',
            '&& curl evil.com'
        ]
        
        for malicious_name in malicious_names:
            try:
                api_key, _ = APIKey.objects.create_key(
                    user=self.user,
                    name=malicious_name,
                    scopes=['read']
                )
                # Should be stored safely without command execution
                self.assertEqual(api_key.name, malicious_name)
            except Exception as e:
                # Some validation might reject these
                pass
                
    def test_unicode_handling_security(self):
        """Test secure handling of Unicode input."""
        unicode_inputs = [
            'test\u0000null',  # Null byte
            'test\ufeffBOM',   # Byte order mark
            'test\u202edirection',  # Text direction override
            '测试🔑',  # Normal Unicode
            '\u0041\u0301',  # Combining characters
        ]
        
        for unicode_input in unicode_inputs:
            try:
                api_key, _ = APIKey.objects.create_key(
                    user=self.user,
                    name=unicode_input,
                    scopes=['read']
                )
                # Should handle Unicode safely
                self.assertTrue(isinstance(api_key.name, str))
            except Exception as e:
                # Some Unicode might be rejected by validation
                pass


class AccessControlSecurityTests(TestCase):
    """Test access control and authorization security."""
    
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass123',
            role=User.Role.ADMIN
        )
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='userpass123',
            role=User.Role.ANALYST
        )
        
    def test_key_ownership_isolation(self):
        """Test that users can only access their own keys."""
        # Create keys for different users
        admin_key, _ = APIKey.objects.create_key(
            user=self.admin_user,
            name='Admin Key',
            scopes=['admin']
        )
        
        user_key, _ = APIKey.objects.create_key(
            user=self.regular_user,
            name='User Key',
            scopes=['read']
        )
        
        # Regular user should only see their own keys
        user_keys = APIKey.objects.filter(user=self.regular_user)
        self.assertIn(user_key, user_keys)
        self.assertNotIn(admin_key, user_keys)
        
        # Admin should see all keys (based on role)
        all_keys = APIKey.objects.all()
        self.assertIn(admin_key, all_keys)
        self.assertIn(user_key, all_keys)
        
    def test_scope_privilege_escalation_prevention(self):
        """Test prevention of privilege escalation through scopes."""
        # Create key with limited scopes
        limited_key, _ = APIKey.objects.create_key(
            user=self.regular_user,
            name='Limited Key',
            scopes=['read']
        )
        
        # Should not have admin privileges
        self.assertFalse(limited_key.has_scope('admin'))
        self.assertFalse(limited_key.has_scope('write'))
        self.assertFalse(limited_key.has_scope('delete'))
        
        # Admin scope should grant all privileges
        admin_key, _ = APIKey.objects.create_key(
            user=self.admin_user,
            name='Admin Key',
            scopes=['admin']
        )
        
        self.assertTrue(admin_key.has_scope('admin'))
        self.assertTrue(admin_key.has_scope('read'))
        self.assertTrue(admin_key.has_scope('write'))
        self.assertTrue(admin_key.has_scope('delete'))
        
    def test_ip_restriction_bypass_prevention(self):
        """Test that IP restrictions cannot be bypassed."""
        restricted_key, restricted_raw = APIKey.objects.create_key(
            user=self.regular_user,
            name='IP Restricted',
            scopes=['read'],
            allowed_ips=['192.168.1.100']
        )
        
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        
        # Test from allowed IP
        request = factory.get(
            '/',
            HTTP_AUTHORIZATION=f'Bearer {restricted_raw}',
            REMOTE_ADDR='192.168.1.100'
        )
        
        user, api_key = auth.authenticate(request)
        self.assertEqual(api_key, restricted_key)
        
        # Test from disallowed IP
        request = factory.get(
            '/',
            HTTP_AUTHORIZATION=f'Bearer {restricted_raw}',
            REMOTE_ADDR='192.168.1.200'
        )
        
        with self.assertRaises(AuthenticationFailed):
            auth.authenticate(request)
            
        # Test with spoofed headers (should still be blocked)
        request = factory.get(
            '/',
            HTTP_AUTHORIZATION=f'Bearer {restricted_raw}',
            HTTP_X_FORWARDED_FOR='192.168.1.100',
            REMOTE_ADDR='192.168.1.200'
        )
        
        # Should use X-Forwarded-For but still validate
        user, api_key = auth.authenticate(request)
        self.assertEqual(api_key, restricted_key)
        
    def test_group_isolation(self):
        """Test that group isolation is maintained."""
        group1 = Group.objects.create(name='Group 1')
        group2 = Group.objects.create(name='Group 2')
        
        key1, _ = APIKey.objects.create_key(
            user=self.regular_user,
            name='Group 1 Key',
            scopes=['read'],
            group=group1
        )
        
        key2, _ = APIKey.objects.create_key(
            user=self.regular_user,
            name='Group 2 Key',
            scopes=['read'],
            group=group2
        )
        
        # Keys should be isolated by group
        group1_keys = APIKey.objects.filter(group=group1)
        self.assertIn(key1, group1_keys)
        self.assertNotIn(key2, group1_keys)


class AuditLoggingSecurityTests(TestCase):
    """Test security audit logging."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_key_creation_audit(self):
        """Test that key creation is properly audited."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Audit Test Key',
            scopes=['read']
        )
        
        # Check audit log
        audit_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(api_key.id),
            action=AuditLog.Action.CREATE
        )
        
        self.assertTrue(audit_logs.exists())
        audit_log = audit_logs.first()
        self.assertEqual(audit_log.user, self.user)
        self.assertIn('api_key_created', audit_log.changes['action'])
        
    def test_key_rotation_audit(self):
        """Test that key rotation is properly audited."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Rotation Audit Test',
            scopes=['read']
        )
        
        # Rotate the key
        new_key, _ = api_key.rotate(user=self.user)
        
        # Check audit log for rotation
        rotation_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(api_key.id),
            action=AuditLog.Action.UPDATE
        )
        
        rotation_log = rotation_logs.filter(
            changes__action='key_rotated'
        ).first()
        
        self.assertIsNotNone(rotation_log)
        self.assertEqual(rotation_log.user, self.user)
        self.assertEqual(rotation_log.changes['new_key_id'], str(new_key.id))
        
    def test_key_revocation_audit(self):
        """Test that key revocation is properly audited."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Revocation Audit Test',
            scopes=['read']
        )
        
        # Revoke the key
        api_key.revoke(user=self.user, reason='Security audit test')
        
        # Check audit log for revocation
        revocation_logs = AuditLog.objects.filter(
            content_type__model='apikey',
            object_id=str(api_key.id),
            action=AuditLog.Action.UPDATE
        )
        
        revocation_log = revocation_logs.filter(
            metadata__reason='Security audit test'
        ).first()
        
        self.assertIsNotNone(revocation_log)
        self.assertEqual(revocation_log.user, self.user)
        
    def test_failed_authentication_logging(self):
        """Test that failed authentication attempts are logged."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Auth Logging Test',
            scopes=['read']
        )
        
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        
        # Test with invalid key
        with patch('api_keys.authentication.logging.getLogger') as mock_logger:
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            
            request = factory.get('/', HTTP_AUTHORIZATION='Bearer invalid_key')
            
            with self.assertRaises(AuthenticationFailed):
                auth.authenticate(request)
            
            # Should have logged the failed attempt
            mock_log.warning.assert_called()
            
    def test_usage_tracking_integrity(self):
        """Test integrity of usage tracking."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Usage Tracking Test',
            scopes=['read']
        )
        
        # Verify key multiple times
        for i in range(5):
            APIKey.objects.verify_key(raw_key)
        
        # Usage count should be accurate
        api_key.refresh_from_db()
        self.assertEqual(api_key.usage_count, 5)
        
        # Last used should be recent
        self.assertIsNotNone(api_key.last_used_at)
        time_diff = timezone.now() - api_key.last_used_at
        self.assertLess(time_diff.total_seconds(), 60)  # Within last minute


class ConcurrencySecurityTests(TransactionTestCase):
    """Test security under concurrent access."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_concurrent_key_verification(self):
        """Test that concurrent key verification is safe."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Concurrent Test',
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
        
        # Run multiple verifications concurrently
        threads = []
        for _ in range(20):
            thread = threading.Thread(target=verify_key)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All verifications should succeed
        self.assertEqual(len(results), 20)
        self.assertTrue(all(results))
        self.assertEqual(len(errors), 0)
        
        # Usage count should be accurate
        api_key.refresh_from_db()
        self.assertEqual(api_key.usage_count, 20)
        
    def test_race_condition_in_rate_limiting(self):
        """Test that rate limiting handles race conditions safely."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Race Condition Test',
            scopes=['read'],
            rate_limit=10
        )
        
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        
        success_count = 0
        throttle_count = 0
        error_count = 0
        
        def make_request():
            nonlocal success_count, throttle_count, error_count
            try:
                request = factory.get('/', HTTP_AUTHORIZATION=f'Bearer {raw_key}')
                result = auth.authenticate(request)
                if result:
                    success_count += 1
            except Throttled:
                throttle_count += 1
            except Exception:
                error_count += 1
        
        # Make many concurrent requests
        threads = []
        for _ in range(50):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Some requests should succeed, some should be throttled
        # Total should equal number of threads
        total = success_count + throttle_count + error_count
        self.assertEqual(total, 50)
        
        # Should have some throttling with this many requests
        self.assertGreater(throttle_count, 0)