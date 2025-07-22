"""
Tests for API Key serializers.

Tests serialization, deserialization, validation, and field handling.
"""

import json
from datetime import timedelta

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from accounts.models import Group
from .models import APIKey, APIKeyUsage
from .serializers import (
    APIKeyCreateSerializer,
    APIKeySerializer,
    APIKeyListSerializer,
    APIKeyUpdateSerializer,
    APIKeyRotateSerializer,
    APIKeyUsageSerializer,
    APIKeyUsageStatsSerializer,
    APIKeyResponseSerializer
)

User = get_user_model()


class APIKeyCreateSerializerTests(TestCase):
    """Test APIKeyCreateSerializer."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_valid_serialization(self):
        """Test serialization with valid data."""
        data = {
            'name': 'Test API Key',
            'scopes': ['read', 'write'],
            'expires_in_days': 30,
            'rate_limit': 5000,
            'allowed_ips': ['192.168.1.100', '10.0.0.1'],
            'metadata': {'purpose': 'testing'}
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['name'], 'Test API Key')
        self.assertEqual(validated_data['scopes'], ['read', 'write'])
        self.assertEqual(validated_data['expires_in_days'], 30)
        self.assertEqual(validated_data['rate_limit'], 5000)
        self.assertEqual(validated_data['allowed_ips'], ['192.168.1.100', '10.0.0.1'])
        self.assertEqual(validated_data['metadata'], {'purpose': 'testing'})
        
    def test_minimal_valid_data(self):
        """Test serialization with minimal required data."""
        data = {
            'name': 'Minimal Key',
            'scopes': ['read']
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['expires_in_days'], 365)  # Default
        self.assertEqual(validated_data['rate_limit'], 1000)  # Default
        
    def test_invalid_scopes(self):
        """Test validation of invalid scopes."""
        data = {
            'name': 'Test Key',
            'scopes': ['invalid_scope']
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('scopes', serializer.errors)
        
    def test_empty_scopes(self):
        """Test validation of empty scopes."""
        data = {
            'name': 'Test Key',
            'scopes': []
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('scopes', serializer.errors)
        
    def test_invalid_expires_in_days(self):
        """Test validation of invalid expiration days."""
        data = {
            'name': 'Test Key',
            'scopes': ['read'],
            'expires_in_days': 0
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('expires_in_days', serializer.errors)
        
    def test_invalid_rate_limit(self):
        """Test validation of invalid rate limit."""
        data = {
            'name': 'Test Key',
            'scopes': ['read'],
            'rate_limit': -1
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('rate_limit', serializer.errors)
        
    def test_invalid_ip_addresses(self):
        """Test validation of invalid IP addresses."""
        data = {
            'name': 'Test Key',
            'scopes': ['read'],
            'allowed_ips': ['invalid.ip.address']
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('allowed_ips', serializer.errors)
        
    def test_valid_ipv6_addresses(self):
        """Test validation of IPv6 addresses."""
        data = {
            'name': 'Test Key',
            'scopes': ['read'],
            'allowed_ips': ['2001:db8::1', '192.168.1.100']
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
    def test_long_name_validation(self):
        """Test validation of overly long names."""
        data = {
            'name': 'x' * 300,  # Exceeds max length
            'scopes': ['read']
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('name', serializer.errors)


class APIKeySerializerTests(TestCase):
    """Test APIKeySerializer."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.group = Group.objects.create(name='Test Group')
        
    def test_serialization(self):
        """Test serializing an API key."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read', 'write'],
            group=self.group,
            metadata={'purpose': 'testing'}
        )
        
        serializer = APIKeySerializer(api_key)
        data = serializer.data
        
        self.assertEqual(data['id'], str(api_key.id))
        self.assertEqual(data['name'], 'Test Key')
        self.assertEqual(data['scopes'], ['read', 'write'])
        self.assertEqual(data['user']['email'], self.user.email)
        self.assertEqual(data['group']['name'], self.group.name)
        self.assertEqual(data['metadata'], {'purpose': 'testing'})
        self.assertTrue(data['is_active'])
        self.assertFalse(data['is_expired'])
        self.assertEqual(data['key_type'], 'user')
        
        # Should not contain sensitive data
        self.assertNotIn('key_hash', data)
        
    def test_application_key_serialization(self):
        """Test serializing an application API key."""
        api_key, _ = APIKey.objects.create_key(
            application_name='Test App',
            name='App Key',
            scopes=['admin']
        )
        
        serializer = APIKeySerializer(api_key)
        data = serializer.data
        
        self.assertIsNone(data['user'])
        self.assertEqual(data['application_name'], 'Test App')
        self.assertEqual(data['key_type'], 'application')
        
    def test_expired_key_serialization(self):
        """Test serializing an expired key."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Expired Key',
            scopes=['read'],
            expires_in_days=1
        )
        
        # Manually expire the key
        api_key.expires_at = timezone.now() - timedelta(hours=1)
        api_key.save()
        
        serializer = APIKeySerializer(api_key)
        data = serializer.data
        
        self.assertTrue(data['is_expired'])
        self.assertFalse(data['is_valid'])
        self.assertEqual(data['days_until_expiry'], 0)


class APIKeyListSerializerTests(TestCase):
    """Test APIKeyListSerializer."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_list_serialization(self):
        """Test serializing API keys for list view."""
        api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='List Test Key',
            scopes=['read']
        )
        
        # Add some usage
        APIKeyUsage.objects.create(
            api_key=api_key,
            endpoint='/api/test/',
            method='GET',
            status_code=200,
            ip_address='192.168.1.100',
            response_time_ms=100
        )
        
        serializer = APIKeyListSerializer(api_key)
        data = serializer.data
        
        # Should contain summary information
        self.assertEqual(data['name'], 'List Test Key')
        self.assertEqual(data['key_prefix'], api_key.key_prefix)
        self.assertTrue(data['is_active'])
        self.assertEqual(data['usage_count'], 1)
        self.assertIsNotNone(data['last_used_at'])
        
        # Should not contain detailed metadata
        self.assertNotIn('metadata', data)


class APIKeyUpdateSerializerTests(TestCase):
    """Test APIKeyUpdateSerializer."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Original Name',
            scopes=['read']
        )
        
    def test_valid_update(self):
        """Test valid update data."""
        data = {
            'name': 'Updated Name',
            'scopes': ['read', 'write'],
            'rate_limit_per_hour': 2000,
            'allowed_ips': ['192.168.1.100']
        }
        
        serializer = APIKeyUpdateSerializer(self.api_key, data=data)
        self.assertTrue(serializer.is_valid())
        
        updated_key = serializer.save()
        self.assertEqual(updated_key.name, 'Updated Name')
        self.assertEqual(updated_key.scopes, ['read', 'write'])
        self.assertEqual(updated_key.rate_limit_per_hour, 2000)
        
    def test_partial_update(self):
        """Test partial update."""
        data = {'name': 'New Name Only'}
        
        serializer = APIKeyUpdateSerializer(self.api_key, data=data, partial=True)
        self.assertTrue(serializer.is_valid())
        
        updated_key = serializer.save()
        self.assertEqual(updated_key.name, 'New Name Only')
        # Other fields should remain unchanged
        self.assertEqual(updated_key.scopes, ['read'])
        
    def test_read_only_fields(self):
        """Test that read-only fields cannot be updated."""
        data = {
            'name': 'Updated Name',
            'key_hash': 'new_hash',  # Should be ignored
            'created_at': timezone.now(),  # Should be ignored
            'usage_count': 999  # Should be ignored
        }
        
        serializer = APIKeyUpdateSerializer(self.api_key, data=data)
        self.assertTrue(serializer.is_valid())
        
        # Read-only fields should not be in validated data
        self.assertNotIn('key_hash', serializer.validated_data)
        self.assertNotIn('created_at', serializer.validated_data)
        self.assertNotIn('usage_count', serializer.validated_data)


class APIKeyRotateSerializerTests(TestCase):
    """Test APIKeyRotateSerializer."""
    
    def test_valid_rotation_data(self):
        """Test valid rotation parameters."""
        data = {
            'overlap_hours': 24,
            'revoke_old_key': False
        }
        
        serializer = APIKeyRotateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['overlap_hours'], 24)
        self.assertFalse(validated_data['revoke_old_key'])
        
    def test_default_values(self):
        """Test default values for rotation."""
        data = {}
        
        serializer = APIKeyRotateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['overlap_hours'], 24)  # Default
        self.assertFalse(validated_data['revoke_old_key'])  # Default
        
    def test_invalid_overlap_hours(self):
        """Test validation of invalid overlap hours."""
        data = {'overlap_hours': -1}
        
        serializer = APIKeyRotateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('overlap_hours', serializer.errors)
        
    def test_maximum_overlap_hours(self):
        """Test validation of maximum overlap hours."""
        data = {'overlap_hours': 8760}  # 1 year
        
        serializer = APIKeyRotateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Test exceeding maximum
        data = {'overlap_hours': 10000}
        
        serializer = APIKeyRotateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('overlap_hours', serializer.errors)


class APIKeyUsageSerializerTests(TestCase):
    """Test APIKeyUsageSerializer."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Usage Test Key',
            scopes=['read']
        )
        
    def test_usage_serialization(self):
        """Test serializing usage data."""
        usage = APIKeyUsage.objects.create(
            api_key=self.api_key,
            endpoint='/api/test/',
            method='GET',
            status_code=200,
            ip_address='192.168.1.100',
            user_agent='Mozilla/5.0 Test Browser',
            response_time_ms=150,
            error_message=''
        )
        
        serializer = APIKeyUsageSerializer(usage)
        data = serializer.data
        
        self.assertEqual(data['endpoint'], '/api/test/')
        self.assertEqual(data['method'], 'GET')
        self.assertEqual(data['status_code'], 200)
        self.assertEqual(data['ip_address'], '192.168.1.100')
        self.assertEqual(data['response_time_ms'], 150)
        self.assertIsNotNone(data['timestamp'])
        
    def test_usage_with_error(self):
        """Test serializing usage data with error."""
        usage = APIKeyUsage.objects.create(
            api_key=self.api_key,
            endpoint='/api/error/',
            method='POST',
            status_code=500,
            ip_address='192.168.1.100',
            response_time_ms=300,
            error_message='Internal server error'
        )
        
        serializer = APIKeyUsageSerializer(usage)
        data = serializer.data
        
        self.assertEqual(data['status_code'], 500)
        self.assertEqual(data['error_message'], 'Internal server error')


class APIKeyUsageStatsSerializerTests(TestCase):
    """Test APIKeyUsageStatsSerializer."""
    
    def test_stats_serialization(self):
        """Test serializing usage statistics."""
        stats_data = {
            'total_requests': 1000,
            'successful_requests': 950,
            'failed_requests': 50,
            'average_response_time_ms': 125.5,
            'unique_ips': 25,
            'top_endpoints': [
                {'endpoint': '/api/test/', 'method': 'GET', 'count': 500},
                {'endpoint': '/api/data/', 'method': 'POST', 'count': 300}
            ],
            'requests_by_hour': [
                {'hour': '2023-01-01 00:00', 'requests': 10},
                {'hour': '2023-01-01 01:00', 'requests': 15}
            ],
            'error_rate': 5.0
        }
        
        serializer = APIKeyUsageStatsSerializer(stats_data)
        data = serializer.data
        
        self.assertEqual(data['total_requests'], 1000)
        self.assertEqual(data['successful_requests'], 950)
        self.assertEqual(data['failed_requests'], 50)
        self.assertEqual(data['average_response_time_ms'], 125.5)
        self.assertEqual(data['error_rate'], 5.0)
        self.assertEqual(len(data['top_endpoints']), 2)
        self.assertEqual(len(data['requests_by_hour']), 2)


class APIKeyResponseSerializerTests(TestCase):
    """Test APIKeyResponseSerializer."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_response_serialization(self):
        """Test serializing API key response."""
        api_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Response Test Key',
            scopes=['read']
        )
        
        response_data = {
            'api_key': APIKeySerializer(api_key).data,
            'key': raw_key,
            'message': 'API key created successfully'
        }
        
        serializer = APIKeyResponseSerializer(response_data)
        data = serializer.data
        
        self.assertIn('api_key', data)
        self.assertEqual(data['key'], raw_key)
        self.assertEqual(data['message'], 'API key created successfully')
        
        # Check that nested API key data is properly serialized
        api_key_data = data['api_key']
        self.assertEqual(api_key_data['name'], 'Response Test Key')
        self.assertEqual(api_key_data['scopes'], ['read'])


class SerializerValidationTests(TestCase):
    """Test advanced validation scenarios."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_custom_validation_methods(self):
        """Test custom validation methods in serializers."""
        # Test name validation (if any custom logic exists)
        data = {
            'name': '',  # Empty name
            'scopes': ['read']
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('name', serializer.errors)
        
    def test_scope_combination_validation(self):
        """Test validation of scope combinations."""
        # Test that admin scope can be combined with others
        data = {
            'name': 'Admin Key',
            'scopes': ['admin', 'read']  # Should be valid
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
    def test_metadata_validation(self):
        """Test metadata field validation."""
        # Test that metadata accepts valid JSON-like structures
        data = {
            'name': 'Metadata Key',
            'scopes': ['read'],
            'metadata': {
                'string_field': 'value',
                'number_field': 123,
                'boolean_field': True,
                'array_field': ['a', 'b', 'c'],
                'nested_object': {'key': 'value'}
            }
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
    def test_rate_limit_boundaries(self):
        """Test rate limit boundary validation."""
        # Test minimum rate limit
        data = {
            'name': 'Min Rate Key',
            'scopes': ['read'],
            'rate_limit': 1
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Test very high rate limit
        data = {
            'name': 'High Rate Key',
            'scopes': ['read'],
            'rate_limit': 1000000
        }
        
        serializer = APIKeyCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())


class SerializerPerformanceTests(TestCase):
    """Test serializer performance with large datasets."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_bulk_serialization_performance(self):
        """Test performance when serializing many API keys."""
        import time
        
        # Create multiple API keys
        api_keys = []
        for i in range(100):
            api_key, _ = APIKey.objects.create_key(
                user=self.user,
                name=f'Perf Key {i}',
                scopes=['read']
            )
            api_keys.append(api_key)
        
        # Time the serialization
        start_time = time.time()
        
        serializer = APIKeyListSerializer(api_keys, many=True)
        data = serializer.data
        
        serialization_time = time.time() - start_time
        
        # Serialization should be reasonably fast
        self.assertLess(serialization_time, 1.0)  # Less than 1 second
        self.assertEqual(len(data), 100)
        
    def test_usage_stats_serialization_performance(self):
        """Test performance of usage stats serialization."""
        import time
        
        # Create large stats data
        stats_data = {
            'total_requests': 100000,
            'successful_requests': 95000,
            'failed_requests': 5000,
            'average_response_time_ms': 125.5,
            'unique_ips': 1000,
            'top_endpoints': [
                {'endpoint': f'/api/endpoint_{i}/', 'method': 'GET', 'count': 1000 - i}
                for i in range(100)
            ],
            'requests_by_hour': [
                {'hour': f'2023-01-01 {i:02d}:00', 'requests': 100 + i}
                for i in range(24)
            ],
            'error_rate': 5.0
        }
        
        start_time = time.time()
        
        serializer = APIKeyUsageStatsSerializer(stats_data)
        data = serializer.data
        
        serialization_time = time.time() - start_time
        
        # Should handle large stats efficiently
        self.assertLess(serialization_time, 0.1)  # Less than 100ms
        self.assertEqual(len(data['top_endpoints']), 100)
        self.assertEqual(len(data['requests_by_hour']), 24)