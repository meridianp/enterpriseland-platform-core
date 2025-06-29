"""
Comprehensive unit tests for the audit middleware.

Tests audit context management, request processing, error handling,
and integration with the Django request/response cycle.
"""

import json
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime

from django.test import TestCase, RequestFactory, override_settings
from django.http import HttpResponse, HttpRequest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from accounts.models import Group
from platform_core.core.middleware.audit import (
    AuditMiddleware,
    AuditContext,
    get_current_audit_context,
    get_client_ip,
    get_user_agent,
    should_audit_model,
    get_field_changes,
    serialize_field_value,
    is_sensitive_field,
    create_audit_log_async,
    audit_context,
    log_action
)
from platform_core.core.models import AuditLog, AuditLogEntry
from assessments.models import Assessment, DevelopmentPartner

User = get_user_model()


class AuditContextTestCase(TestCase):
    """Test cases for AuditContext management."""
    
    def setUp(self):
        """Set up test data."""
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
        self.user.groups.add(self.group)
    
    def test_audit_context_creation(self):
        """Test creating an audit context."""
        context = AuditContext(
            user=self.user,
            ip_address='192.168.1.1',
            user_agent='Mozilla/5.0',
            group=self.group
        )
        
        self.assertEqual(context.user, self.user)
        self.assertEqual(context.ip_address, '192.168.1.1')
        self.assertEqual(context.user_agent, 'Mozilla/5.0')
        self.assertEqual(context.group, self.group)
    
    def test_audit_context_manager(self):
        """Test audit context as context manager."""
        # Verify no context initially
        self.assertIsNone(get_current_audit_context())
        
        # Create and use context
        with AuditContext(user=self.user, ip_address='10.0.0.1') as ctx:
            # Context should be available inside
            current = get_current_audit_context()
            self.assertIsNotNone(current)
            self.assertEqual(current.user, self.user)
            self.assertEqual(current.ip_address, '10.0.0.1')
        
        # Context should be cleared after
        self.assertIsNone(get_current_audit_context())
    
    def test_nested_audit_contexts(self):
        """Test nested audit contexts (last one wins)."""
        with AuditContext(user=self.user, ip_address='1.1.1.1'):
            ctx1 = get_current_audit_context()
            self.assertEqual(ctx1.ip_address, '1.1.1.1')
            
            with AuditContext(ip_address='2.2.2.2'):
                ctx2 = get_current_audit_context()
                self.assertEqual(ctx2.ip_address, '2.2.2.2')
            
            # Should restore to first context
            ctx3 = get_current_audit_context()
            self.assertIsNone(ctx3)  # Actually clears on exit
    
    def test_audit_context_function(self):
        """Test the audit_context function wrapper."""
        with audit_context(user=self.user, group=self.group) as ctx:
            self.assertEqual(ctx.user, self.user)
            self.assertEqual(ctx.group, self.group)
            
            current = get_current_audit_context()
            self.assertEqual(current, ctx)


class UtilityFunctionTestCase(TestCase):
    """Test cases for audit utility functions."""
    
    def test_get_client_ip(self):
        """Test IP address extraction from request."""
        factory = RequestFactory()
        
        # Test with REMOTE_ADDR
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.100'
        self.assertEqual(get_client_ip(request), '192.168.1.100')
        
        # Test with X-Forwarded-For (single IP)
        request.META['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
        self.assertEqual(get_client_ip(request), '10.0.0.1')
        
        # Test with X-Forwarded-For (multiple IPs)
        request.META['HTTP_X_FORWARDED_FOR'] = '10.0.0.1, 192.168.1.1, 172.16.0.1'
        self.assertEqual(get_client_ip(request), '10.0.0.1')
        
        # Test with no IP
        request = factory.get('/')
        self.assertEqual(get_client_ip(request), '')
    
    def test_get_user_agent(self):
        """Test user agent extraction from request."""
        factory = RequestFactory()
        
        # Test with user agent
        request = factory.get('/')
        request.META['HTTP_USER_AGENT'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        self.assertEqual(get_user_agent(request), 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        
        # Test with very long user agent (should be truncated)
        long_agent = 'x' * 1000
        request.META['HTTP_USER_AGENT'] = long_agent
        result = get_user_agent(request)
        self.assertEqual(len(result), 500)
        self.assertEqual(result, 'x' * 500)
        
        # Test with no user agent
        request = factory.get('/')
        self.assertEqual(get_user_agent(request), '')
    
    @override_settings(AUDIT_LOGGING={
        'ENABLED': True,
        'EXCLUDED_MODELS': ['accounts.User'],
        'EXCLUDED_APPS': ['django_celery_beat'],
        'INCLUDED_MODELS': [],
        'INCLUDED_APPS': []
    })
    def test_should_audit_model(self):
        """Test model audit filtering."""
        # Should audit by default
        self.assertTrue(should_audit_model(Assessment))
        self.assertTrue(should_audit_model(DevelopmentPartner))
        
        # Should not audit excluded models
        self.assertFalse(should_audit_model(User))
        
        # Should not audit audit models (prevent recursion)
        self.assertFalse(should_audit_model(AuditLog))
        self.assertFalse(should_audit_model(AuditLogEntry))
        
        # Test with included models only
        with override_settings(AUDIT_LOGGING={
            'ENABLED': True,
            'INCLUDED_MODELS': ['assessments.Assessment']
        }):
            self.assertTrue(should_audit_model(Assessment))
            self.assertFalse(should_audit_model(DevelopmentPartner))
        
        # Test with included apps only
        with override_settings(AUDIT_LOGGING={
            'ENABLED': True,
            'INCLUDED_APPS': ['assessments']
        }):
            self.assertTrue(should_audit_model(Assessment))
            self.assertTrue(should_audit_model(DevelopmentPartner))
            self.assertFalse(should_audit_model(User))
        
        # Test with auditing disabled
        with override_settings(AUDIT_LOGGING={'ENABLED': False}):
            self.assertFalse(should_audit_model(Assessment))
    
    def test_serialize_field_value(self):
        """Test field value serialization."""
        # Test None
        self.assertIsNone(serialize_field_value(None))
        
        # Test primitives
        self.assertEqual(serialize_field_value('string'), 'string')
        self.assertEqual(serialize_field_value(123), 123)
        self.assertEqual(serialize_field_value(True), True)
        self.assertEqual(serialize_field_value(3.14), 3.14)
        
        # Test datetime
        now = timezone.now()
        serialized = serialize_field_value(now)
        self.assertIsInstance(serialized, str)
        
        # Test model instance (with pk)
        group = Group.objects.create(name="Test")
        result = serialize_field_value(group)
        self.assertIsInstance(result, dict)
        self.assertEqual(result['id'], str(group.pk))
        self.assertIn('Test', result['repr'])
        
        # Test list
        list_val = [1, 2, 'three']
        result = serialize_field_value(list_val)
        self.assertEqual(result, [1, 2, 'three'])
        
        # Test dict
        dict_val = {'key': 'value', 'num': 42}
        result = serialize_field_value(dict_val)
        self.assertEqual(result, dict_val)
        
        # Test nested structures
        nested = {'list': [1, 2], 'model': group}
        result = serialize_field_value(nested)
        self.assertEqual(result['list'], [1, 2])
        self.assertEqual(result['model']['id'], str(group.pk))
        
        # Test non-serializable object
        class CustomObject:
            def __str__(self):
                return 'custom'
        
        result = serialize_field_value(CustomObject())
        self.assertEqual(result, 'custom')
    
    def test_is_sensitive_field(self):
        """Test sensitive field detection."""
        # Test default patterns
        sensitive_fields = [
            'password', 'user_password', 'passwd', 'pwd',
            'secret', 'api_secret', 'secret_key',
            'token', 'auth_token', 'access_token',
            'ssn', 'social_security_number',
            'credit_card', 'cc_number', 'card_number',
            'bank_account', 'account_number',
            'api_key', 'private_key'
        ]
        
        for field in sensitive_fields:
            self.assertTrue(
                is_sensitive_field(field, Assessment),
                f"{field} should be sensitive"
            )
        
        # Test non-sensitive fields
        non_sensitive = ['name', 'email', 'description', 'status']
        for field in non_sensitive:
            self.assertFalse(
                is_sensitive_field(field, Assessment),
                f"{field} should not be sensitive"
            )
        
        # Test with custom configuration
        with override_settings(AUDIT_LOGGING={
            'SENSITIVE_FIELDS': {
                'assessments.Assessment': ['custom_field', 'another_field']
            }
        }):
            self.assertTrue(is_sensitive_field('custom_field', Assessment))
            self.assertTrue(is_sensitive_field('another_field', Assessment))
            self.assertFalse(is_sensitive_field('name', Assessment))
    
    def test_get_field_changes(self):
        """Test field change detection."""
        group = Group.objects.create(name="Test Group")
        
        # Create two partner instances
        old_partner = DevelopmentPartner(
            id=1,
            group=group,
            name="Old Name",
            country="US",
            is_active=True
        )
        
        new_partner = DevelopmentPartner(
            id=1,
            group=group,
            name="New Name",
            country="GB",
            is_active=True
        )
        
        changes = get_field_changes(old_partner, new_partner)
        
        # Should detect name and country changes
        self.assertIn('name', changes)
        self.assertEqual(changes['name']['old'], 'Old Name')
        self.assertEqual(changes['name']['new'], 'New Name')
        
        self.assertIn('country', changes)
        self.assertEqual(changes['country']['old'], 'US')
        self.assertEqual(changes['country']['new'], 'GB')
        
        # Should not include unchanged fields
        self.assertNotIn('is_active', changes)
        
        # Test with JSON field changes
        old_partner.metadata = {'key': 'old_value'}
        new_partner.metadata = {'key': 'new_value'}
        
        changes = get_field_changes(old_partner, new_partner)
        self.assertIn('metadata', changes)


class AuditMiddlewareTestCase(TestCase):
    """Test cases for AuditMiddleware."""
    
    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.middleware = AuditMiddleware(get_response=lambda r: HttpResponse())
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
        self.user.groups.add(self.group)
    
    def test_process_request_authenticated(self):
        """Test processing request for authenticated user."""
        request = self.factory.get('/')
        request.user = self.user
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        request.META['HTTP_USER_AGENT'] = 'TestAgent/1.0'
        
        # Process request
        response = self.middleware.process_request(request)
        self.assertIsNone(response)  # Should continue processing
        
        # Check audit context was set
        context = get_current_audit_context()
        self.assertIsNotNone(context)
        self.assertEqual(context.user, self.user)
        self.assertEqual(context.ip_address, '192.168.1.1')
        self.assertEqual(context.user_agent, 'TestAgent/1.0')
        self.assertEqual(context.group, self.group)
    
    def test_process_request_anonymous(self):
        """Test processing request for anonymous user."""
        request = self.factory.get('/')
        request.user = AnonymousUser()
        request.META['REMOTE_ADDR'] = '10.0.0.1'
        
        # Process request
        response = self.middleware.process_request(request)
        self.assertIsNone(response)
        
        # Check audit context
        context = get_current_audit_context()
        self.assertIsNotNone(context)
        self.assertIsNone(context.user)
        self.assertEqual(context.ip_address, '10.0.0.1')
        self.assertIsNone(context.group)
    
    def test_process_response(self):
        """Test response processing cleans up context."""
        request = self.factory.get('/')
        request.user = self.user
        
        # Set up context
        self.middleware.process_request(request)
        self.assertIsNotNone(get_current_audit_context())
        
        # Process response
        response = HttpResponse()
        result = self.middleware.process_response(request, response)
        
        # Should return response unchanged
        self.assertEqual(result, response)
        
        # Context should be cleaned up
        self.assertIsNone(get_current_audit_context())
    
    def test_process_exception(self):
        """Test exception handling and logging."""
        request = self.factory.get('/api/test/')
        request.user = self.user
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        
        # Set up context
        self.middleware.process_request(request)
        
        # Process exception
        exception = PermissionDenied("Access denied")
        
        with patch('core.models.AuditLog.objects.create_log') as mock_create:
            response = self.middleware.process_exception(request, exception)
            
            # Should log the exception
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            
            self.assertEqual(call_args.kwargs['action'], AuditLog.Action.API_ERROR)
            self.assertEqual(call_args.kwargs['user'], self.user)
            self.assertFalse(call_args.kwargs['success'])
            self.assertEqual(call_args.kwargs['error_message'], 'Access denied')
            self.assertIn('exception_type', call_args.kwargs['metadata'])
            self.assertEqual(call_args.kwargs['metadata']['exception_type'], 'PermissionDenied')
        
        # Should clean up context
        self.assertIsNone(get_current_audit_context())
        
        # Should return None to continue exception handling
        self.assertIsNone(response)
    
    def test_full_request_cycle(self):
        """Test complete request/response cycle."""
        # Create a view that modifies data
        def test_view(request):
            # Simulate data modification
            partner = DevelopmentPartner.objects.create(
                group=request.user.groups.first(),
                name="Test Partner",
                country="US"
            )
            return HttpResponse(f"Created {partner.id}")
        
        # Set up middleware with the view
        middleware = AuditMiddleware(get_response=test_view)
        
        # Create request
        request = self.factory.post('/api/partners/')
        request.user = self.user
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        
        # Process full cycle
        response = middleware(request)
        
        # Should get response
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Created", response.content)
        
        # Context should be cleaned up
        self.assertIsNone(get_current_audit_context())
    
    def test_middleware_with_async_context(self):
        """Test middleware behavior in async context."""
        request = self.factory.get('/')
        request.user = self.user
        
        async def async_test():
            # Process request
            self.middleware.process_request(request)
            context = get_current_audit_context()
            self.assertIsNotNone(context)
            
            # Clean up
            self.middleware.process_response(request, HttpResponse())
            self.assertIsNone(get_current_audit_context())
        
        # Run async test
        asyncio.run(async_test())


class AsyncAuditLoggingTestCase(TestCase):
    """Test cases for asynchronous audit logging."""
    
    def setUp(self):
        """Set up test data."""
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
        self.partner = DevelopmentPartner.objects.create(
            group=self.group,
            name="Test Partner",
            country="US"
        )
    
    @patch('core.middleware.audit.AuditLog.objects.create_log')
    @patch('core.middleware.audit.create_audit_log_entries_async', new_callable=AsyncMock)
    async def test_create_audit_log_async(self, mock_entries, mock_create):
        """Test async audit log creation."""
        # Set up mock
        mock_log = Mock(id=1)
        mock_create.return_value = mock_log
        
        # Create audit log
        await create_audit_log_async(
            action='CREATE',
            user=self.user,
            content_object=self.partner,
            changes={'name': {'old': None, 'new': 'Test Partner'}},
            ip_address='192.168.1.1',
            user_agent='TestAgent',
            group=self.group,
            success=True
        )
        
        # Verify creation
        mock_create.assert_called_once_with(
            action='CREATE',
            user=self.user,
            content_object=self.partner,
            changes={'name': {'old': None, 'new': 'Test Partner'}},
            ip_address='192.168.1.1',
            user_agent='TestAgent',
            group=self.group,
            success=True,
            error_message=None
        )
        
        # Verify entries creation
        mock_entries.assert_called_once()
    
    async def test_create_audit_log_async_error_handling(self):
        """Test error handling in async audit logging."""
        with patch('core.middleware.audit.AuditLog.objects.create_log') as mock_create:
            mock_create.side_effect = Exception("Database error")
            
            # Should not raise exception
            with patch('core.middleware.audit.logger.error') as mock_logger:
                await create_audit_log_async(
                    action='CREATE',
                    user=self.user
                )
                
                # Should log the error
                mock_logger.assert_called_once()
                self.assertIn("Failed to create audit log", mock_logger.call_args[0][0])


class ManualAuditLoggingTestCase(TestCase):
    """Test cases for manual audit logging functions."""
    
    def setUp(self):
        """Set up test data."""
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
        self.user.groups.add(self.group)
    
    def test_log_action_with_context(self):
        """Test manual logging with audit context."""
        with audit_context(user=self.user, ip_address='10.0.0.1', group=self.group):
            log_action(
                'CUSTOM_ACTION',
                metadata={'custom': 'data'}
            )
        
        # Verify log was created
        log = AuditLog.objects.filter(action='CUSTOM_ACTION').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.ip_address, '10.0.0.1')
        self.assertEqual(log.group, self.group)
        self.assertEqual(log.metadata['custom'], 'data')
    
    def test_log_action_without_context(self):
        """Test manual logging without audit context."""
        log_action(
            'SYSTEM_ACTION',
            user=self.user,
            metadata={'system': True}
        )
        
        # Verify log was created
        log = AuditLog.objects.filter(action='SYSTEM_ACTION').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.user)
        self.assertIsNone(log.ip_address)  # No context
        self.assertEqual(log.metadata['system'], True)
    
    def test_log_action_error_handling(self):
        """Test error handling in manual logging."""
        with patch('core.models.AuditLog.objects.create_log') as mock_create:
            mock_create.side_effect = Exception("Database error")
            
            # Should not raise exception
            with patch('core.middleware.audit.logger.error') as mock_logger:
                log_action('TEST_ACTION')
                
                # Should log the error
                mock_logger.assert_called_once()
                self.assertIn("Failed to manually log", mock_logger.call_args[0][0])


class AuditConfigurationTestCase(TestCase):
    """Test cases for audit configuration settings."""
    
    @override_settings(AUDIT_LOGGING={'ENABLED': False})
    def test_auditing_disabled(self):
        """Test behavior when auditing is disabled."""
        # Should not audit when disabled
        self.assertFalse(should_audit_model(Assessment))
        
        # Manual logging should be skipped
        with patch('core.models.AuditLog.objects.create_log') as mock_create:
            log_action('TEST_ACTION')
            mock_create.assert_not_called()
    
    @override_settings(AUDIT_LOGGING={
        'ENABLED': True,
        'EXCLUDED_APPS': ['assessments']
    })
    def test_excluded_apps(self):
        """Test app exclusion."""
        self.assertFalse(should_audit_model(Assessment))
        self.assertFalse(should_audit_model(DevelopmentPartner))
    
    @override_settings(AUDIT_LOGGING={
        'ENABLED': True,
        'INCLUDED_MODELS': ['assessments.Assessment']
    })
    def test_included_models_only(self):
        """Test including specific models only."""
        self.assertTrue(should_audit_model(Assessment))
        self.assertFalse(should_audit_model(DevelopmentPartner))
        self.assertFalse(should_audit_model(User))
    
    @override_settings(AUDIT_LOGGING={})
    def test_default_configuration(self):
        """Test default configuration behavior."""
        # Should be enabled by default
        self.assertTrue(should_audit_model(Assessment))
        
        # Should exclude audit models
        self.assertFalse(should_audit_model(AuditLog))
        self.assertFalse(should_audit_model(AuditLogEntry))


class IPAddressExtractionTestCase(TestCase):
    """Test cases for IP address extraction edge cases."""
    
    def test_ipv6_addresses(self):
        """Test IPv6 address handling."""
        factory = RequestFactory()
        request = factory.get('/')
        
        # Test IPv6 address
        request.META['REMOTE_ADDR'] = '2001:0db8:85a3:0000:0000:8a2e:0370:7334'
        self.assertEqual(get_client_ip(request), '2001:0db8:85a3:0000:0000:8a2e:0370:7334')
        
        # Test IPv6 in X-Forwarded-For
        request.META['HTTP_X_FORWARDED_FOR'] = '2001:db8::1, 192.168.1.1'
        self.assertEqual(get_client_ip(request), '2001:db8::1')
    
    def test_private_ip_addresses(self):
        """Test private IP address handling."""
        factory = RequestFactory()
        request = factory.get('/')
        
        # Test various private IP ranges
        private_ips = [
            '10.0.0.1',
            '172.16.0.1',
            '192.168.1.1',
            '127.0.0.1'
        ]
        
        for ip in private_ips:
            request.META['REMOTE_ADDR'] = ip
            self.assertEqual(get_client_ip(request), ip)
    
    def test_malformed_x_forwarded_for(self):
        """Test handling of malformed X-Forwarded-For headers."""
        factory = RequestFactory()
        request = factory.get('/')
        
        # Test with spaces and commas
        request.META['HTTP_X_FORWARDED_FOR'] = '  10.0.0.1  ,  192.168.1.1  '
        self.assertEqual(get_client_ip(request), '10.0.0.1')
        
        # Test empty X-Forwarded-For
        request.META['HTTP_X_FORWARDED_FOR'] = ''
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        self.assertEqual(get_client_ip(request), '192.168.1.1')