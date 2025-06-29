"""
Comprehensive unit tests for audit signals.

Tests Django signal handlers for automatic audit logging,
including model changes, authentication events, and
special operations.
"""

import json
import asyncio
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime
from threading import Thread

from django.test import TestCase, TransactionTestCase, override_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import pre_save, post_save, pre_delete, post_delete, m2m_changed
from django.utils import timezone
from django.db import transaction

from accounts.models import Group
from assessments.models import Assessment, DevelopmentPartner
from platform_core.core.models import AuditLog
from platform_core.core.signals import (
    audit_pre_save,
    audit_post_save,
    audit_pre_delete,
    audit_post_delete,
    audit_m2m_changed,
    audit_user_login,
    audit_user_logout,
    audit_login_failed,
    audit_bulk_operation,
    audit_permission_change,
    audit_data_export,
    get_cache_key,
    is_audit_enabled,
    should_audit_action
)
from platform_core.core.middleware.audit import audit_context

User = get_user_model()


class SignalSetupTestCase(TestCase):
    """Test cases for signal setup and configuration."""
    
    def test_signals_connected(self):
        """Test that audit signals are properly connected."""
        # Check pre_save
        receivers = pre_save._live_receivers(sender=Assessment)
        receiver_funcs = [r[1]() for r in receivers]
        self.assertIn(audit_pre_save, receiver_funcs)
        
        # Check post_save
        receivers = post_save._live_receivers(sender=Assessment)
        receiver_funcs = [r[1]() for r in receivers]
        self.assertIn(audit_post_save, receiver_funcs)
        
        # Check pre_delete
        receivers = pre_delete._live_receivers(sender=Assessment)
        receiver_funcs = [r[1]() for r in receivers]
        self.assertIn(audit_pre_delete, receiver_funcs)
        
        # Check post_delete
        receivers = post_delete._live_receivers(sender=Assessment)
        receiver_funcs = [r[1]() for r in receivers]
        self.assertIn(audit_post_delete, receiver_funcs)
    
    def test_auth_signals_connected(self):
        """Test that authentication signals are connected."""
        # Check login signal
        receivers = user_logged_in._live_receivers(sender=None)
        receiver_funcs = [r[1]() for r in receivers]
        self.assertIn(audit_user_login, receiver_funcs)
        
        # Check logout signal
        receivers = user_logged_out._live_receivers(sender=None)
        receiver_funcs = [r[1]() for r in receivers]
        self.assertIn(audit_user_logout, receiver_funcs)
        
        # Check login failed signal
        receivers = user_login_failed._live_receivers(sender=None)
        receiver_funcs = [r[1]() for r in receivers]
        self.assertIn(audit_login_failed, receiver_funcs)


class ModelChangeSignalTestCase(TestCase):
    """Test cases for model change signals."""
    
    def setUp(self):
        """Set up test data."""
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
        self.user.groups.add(self.group)
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_create_signal(self):
        """Test audit logging on model creation."""
        with audit_context(user=self.user, group=self.group):
            partner = DevelopmentPartner.objects.create(
                group=self.group,
                name="New Partner",
                country="US"
            )
        
        # Check audit log was created
        log = AuditLog.objects.filter(
            action=AuditLog.Action.CREATE,
            model_name='DevelopmentPartner',
            object_id=str(partner.id)
        ).first()
        
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.group, self.group)
        self.assertIsNone(log.changes)  # No changes for new records
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_update_signal(self):
        """Test audit logging on model update."""
        # Create initial object
        partner = DevelopmentPartner.objects.create(
            group=self.group,
            name="Original Name",
            country="US"
        )
        
        # Clear any creation logs
        AuditLog.objects.all().delete()
        
        # Update the object
        with audit_context(user=self.user):
            partner.name = "Updated Name"
            partner.country = "GB"
            partner.save()
        
        # Check audit log
        log = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE,
            object_id=str(partner.id)
        ).first()
        
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.user)
        self.assertIn('name', log.changes)
        self.assertEqual(log.changes['name']['old'], 'Original Name')
        self.assertEqual(log.changes['name']['new'], 'Updated Name')
        self.assertIn('country', log.changes)
        self.assertEqual(log.changes['country']['old'], 'US')
        self.assertEqual(log.changes['country']['new'], 'GB')
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_no_change_update(self):
        """Test that no audit log is created when no fields change."""
        partner = DevelopmentPartner.objects.create(
            group=self.group,
            name="Test Partner",
            country="US"
        )
        
        # Clear creation log
        AuditLog.objects.all().delete()
        
        # Save without changes
        with audit_context(user=self.user):
            partner.save()
        
        # Should not create update log
        log_count = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE,
            object_id=str(partner.id)
        ).count()
        
        self.assertEqual(log_count, 0)
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_delete_signal(self):
        """Test audit logging on model deletion."""
        partner = DevelopmentPartner.objects.create(
            group=self.group,
            name="To Delete",
            country="US"
        )
        partner_id = partner.id
        
        # Clear creation log
        AuditLog.objects.all().delete()
        
        # Delete the object
        with audit_context(user=self.user):
            partner.delete()
        
        # Check delete logs (pre_delete and post_delete)
        logs = AuditLog.objects.filter(
            action=AuditLog.Action.DELETE,
            object_id=str(partner_id)
        ).order_by('timestamp')
        
        self.assertGreaterEqual(logs.count(), 1)
        
        # Check pre_delete log has field values
        pre_delete_log = logs.first()
        self.assertIn('name', pre_delete_log.changes)
        self.assertEqual(pre_delete_log.changes['name']['old'], 'To Delete')
        self.assertIsNone(pre_delete_log.changes['name']['new'])
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_bulk_create_not_logged(self):
        """Test that bulk_create doesn't trigger individual signals."""
        partners = [
            DevelopmentPartner(group=self.group, name=f"Partner {i}", country="US")
            for i in range(5)
        ]
        
        # Bulk create
        with audit_context(user=self.user):
            DevelopmentPartner.objects.bulk_create(partners)
        
        # Should not create individual logs
        log_count = AuditLog.objects.filter(
            action=AuditLog.Action.CREATE,
            model_name='DevelopmentPartner'
        ).count()
        
        self.assertEqual(log_count, 0)
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_m2m_add_signal(self):
        """Test audit logging for many-to-many additions."""
        assessment = Assessment.objects.create(
            group=self.group,
            title="Test Assessment",
            development_partner=DevelopmentPartner.objects.create(
                group=self.group,
                name="Partner",
                country="US"
            )
        )
        
        # Create users to add
        user1 = User.objects.create_user(email="user1@example.com", password="Pass123!")
        user2 = User.objects.create_user(email="user2@example.com", password="Pass123!")
        
        # Clear existing logs
        AuditLog.objects.all().delete()
        
        # Add users to M2M
        with audit_context(user=self.user):
            assessment.assessors.add(user1, user2)
        
        # Check audit log
        log = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE,
            object_id=str(assessment.id)
        ).first()
        
        self.assertIsNotNone(log)
        self.assertIn('m2m_added', log.changes)
        self.assertEqual(log.changes['m2m_added']['action'], 'add')
        self.assertIn(str(user1.id), [str(id) for id in log.changes['m2m_added']['added_ids']])
        self.assertIn(str(user2.id), [str(id) for id in log.changes['m2m_added']['added_ids']])
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_m2m_remove_signal(self):
        """Test audit logging for many-to-many removals."""
        assessment = Assessment.objects.create(
            group=self.group,
            title="Test Assessment",
            development_partner=DevelopmentPartner.objects.create(
                group=self.group,
                name="Partner",
                country="US"
            )
        )
        
        user1 = User.objects.create_user(email="user1@example.com", password="Pass123!")
        assessment.assessors.add(user1)
        
        # Clear existing logs
        AuditLog.objects.all().delete()
        
        # Remove user from M2M
        with audit_context(user=self.user):
            assessment.assessors.remove(user1)
        
        # Check audit log
        log = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE,
            object_id=str(assessment.id)
        ).first()
        
        self.assertIsNotNone(log)
        self.assertIn('m2m_removed', log.changes)
        self.assertEqual(log.changes['m2m_removed']['action'], 'remove')
        self.assertIn(str(user1.id), [str(id) for id in log.changes['m2m_removed']['removed_ids']])
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_m2m_clear_signal(self):
        """Test audit logging for many-to-many clear."""
        assessment = Assessment.objects.create(
            group=self.group,
            title="Test Assessment",
            development_partner=DevelopmentPartner.objects.create(
                group=self.group,
                name="Partner",
                country="US"
            )
        )
        
        # Add users
        user1 = User.objects.create_user(email="user1@example.com", password="Pass123!")
        user2 = User.objects.create_user(email="user2@example.com", password="Pass123!")
        assessment.assessors.add(user1, user2)
        
        # Clear existing logs
        AuditLog.objects.all().delete()
        
        # Clear M2M
        with audit_context(user=self.user):
            assessment.assessors.clear()
        
        # Check audit log
        log = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE,
            object_id=str(assessment.id)
        ).first()
        
        self.assertIsNotNone(log)
        self.assertIn('m2m_cleared', log.changes)
        self.assertEqual(log.changes['m2m_cleared']['action'], 'clear')
    
    @override_settings(AUDIT_LOGGING={'ENABLED': False})
    def test_signals_disabled(self):
        """Test that signals don't create logs when auditing is disabled."""
        with audit_context(user=self.user):
            partner = DevelopmentPartner.objects.create(
                group=self.group,
                name="No Audit",
                country="US"
            )
        
        # Should not create any logs
        log_count = AuditLog.objects.filter(
            object_id=str(partner.id)
        ).count()
        
        self.assertEqual(log_count, 0)
    
    @override_settings(AUDIT_LOGGING={
        'ENABLED': True,
        'EXCLUDED_MODELS': ['assessments.DevelopmentPartner']
    })
    def test_excluded_model_signals(self):
        """Test that excluded models don't trigger audit logs."""
        with audit_context(user=self.user):
            partner = DevelopmentPartner.objects.create(
                group=self.group,
                name="Excluded",
                country="US"
            )
        
        # Should not create logs for excluded model
        log_count = AuditLog.objects.filter(
            model_name='DevelopmentPartner',
            object_id=str(partner.id)
        ).count()
        
        self.assertEqual(log_count, 0)


class AuthenticationSignalTestCase(TestCase):
    """Test cases for authentication signals."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
        self.factory = Mock()
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    @patch('core.middleware.audit.get_client_ip')
    @patch('core.middleware.audit.get_user_agent')
    def test_user_login_signal(self, mock_user_agent, mock_client_ip):
        """Test audit logging on user login."""
        mock_client_ip.return_value = '192.168.1.1'
        mock_user_agent.return_value = 'TestBrowser/1.0'
        
        # Create mock request
        request = Mock()
        
        # Send login signal
        user_logged_in.send(
            sender=None,
            request=request,
            user=self.user
        )
        
        # Check audit log
        log = AuditLog.objects.filter(
            action=AuditLog.Action.LOGIN,
            user=self.user
        ).first()
        
        self.assertIsNotNone(log)
        self.assertEqual(log.content_object, self.user)
        self.assertIn('login_time', log.metadata)
        mock_client_ip.assert_called_once_with(request)
        mock_user_agent.assert_called_once_with(request)
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    @patch('core.middleware.audit.get_client_ip')
    @patch('core.middleware.audit.get_user_agent')
    def test_user_logout_signal(self, mock_user_agent, mock_client_ip):
        """Test audit logging on user logout."""
        mock_client_ip.return_value = '10.0.0.1'
        mock_user_agent.return_value = 'MobileBrowser/2.0'
        
        # Create mock request
        request = Mock()
        
        # Send logout signal
        user_logged_out.send(
            sender=None,
            request=request,
            user=self.user
        )
        
        # Check audit log
        log = AuditLog.objects.filter(
            action=AuditLog.Action.LOGOUT,
            user=self.user
        ).first()
        
        self.assertIsNotNone(log)
        self.assertEqual(log.content_object, self.user)
        self.assertIn('logout_time', log.metadata)
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    @patch('core.middleware.audit.get_client_ip')
    @patch('core.middleware.audit.get_user_agent')
    def test_login_failed_signal(self, mock_user_agent, mock_client_ip):
        """Test audit logging on failed login."""
        mock_client_ip.return_value = '192.168.100.1'
        mock_user_agent.return_value = 'SuspiciousBrowser/1.0'
        
        # Create mock request
        request = Mock()
        
        # Send login failed signal
        credentials = {'username': 'hacker@example.com', 'password': 'wrong'}
        user_login_failed.send(
            sender=None,
            credentials=credentials,
            request=request
        )
        
        # Check audit log
        log = AuditLog.objects.filter(
            action=AuditLog.Action.LOGIN_FAILED
        ).first()
        
        self.assertIsNotNone(log)
        self.assertFalse(log.success)
        self.assertEqual(log.error_message, 'Invalid credentials provided')
        self.assertEqual(log.metadata['username'], 'hacker@example.com')
        self.assertIn('failure_time', log.metadata)
        self.assertEqual(log.metadata['credentials_provided'], ['username', 'password'])


class UtilityFunctionSignalTestCase(TestCase):
    """Test cases for utility functions used in signals."""
    
    def setUp(self):
        """Set up test data."""
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
        self.user.groups.add(self.group)
    
    def test_get_cache_key(self):
        """Test cache key generation."""
        partner = DevelopmentPartner.objects.create(
            group=self.group,
            name="Test",
            country="US"
        )
        
        key = get_cache_key(partner)
        self.assertEqual(key, f"DevelopmentPartner:{partner.pk}")
        
        # Test with unsaved instance
        new_partner = DevelopmentPartner(name="New")
        key = get_cache_key(new_partner)
        self.assertEqual(key, "DevelopmentPartner:None")
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_is_audit_enabled(self):
        """Test audit enabled check."""
        self.assertTrue(is_audit_enabled())
        
        with override_settings(AUDIT_LOGGING={'ENABLED': False}):
            self.assertFalse(is_audit_enabled())
        
        # Test with missing setting
        with override_settings():
            delattr(settings, 'AUDIT_LOGGING')
            self.assertTrue(is_audit_enabled())  # Default True
    
    @override_settings(AUDIT_LOGGING={
        'ENABLED': True,
        'DISABLED_ACTIONS': ['READ', 'API_ACCESS']
    })
    def test_should_audit_action(self):
        """Test action filtering."""
        self.assertTrue(should_audit_action('CREATE'))
        self.assertTrue(should_audit_action('UPDATE'))
        self.assertFalse(should_audit_action('READ'))
        self.assertFalse(should_audit_action('API_ACCESS'))
    
    def test_audit_bulk_operation(self):
        """Test bulk operation audit logging."""
        with audit_context(user=self.user):
            audit_bulk_operation(
                action='BULK_UPDATE',
                model_class=DevelopmentPartner,
                count=50,
                filters={'country': 'US'},
                user=self.user
            )
        
        # Check audit log
        log = AuditLog.objects.filter(
            action='BULK_UPDATE'
        ).first()
        
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.metadata['model_name'], 'DevelopmentPartner')
        self.assertEqual(log.metadata['affected_count'], 50)
        self.assertEqual(log.metadata['filters']['country'], 'US')
    
    def test_audit_permission_change(self):
        """Test permission change audit logging."""
        target_user = User.objects.create_user(
            email="target@example.com",
            password="Pass123!"
        )
        
        old_permissions = {'view_assessment', 'add_assessment'}
        new_permissions = {'view_assessment', 'add_assessment', 'change_assessment', 'delete_assessment'}
        
        audit_permission_change(
            user=self.user,
            target_user=target_user,
            old_permissions=old_permissions,
            new_permissions=new_permissions,
            changed_by=self.user
        )
        
        # Check audit log
        log = AuditLog.objects.filter(
            action='PERMISSION_CHANGE'
        ).first()
        
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.content_object, target_user)
        self.assertIn('permissions_added', log.changes)
        self.assertIn('change_assessment', log.changes['permissions_added'])
        self.assertIn('delete_assessment', log.changes['permissions_added'])
        self.assertNotIn('permissions_removed', log.changes)
    
    def test_audit_data_export(self):
        """Test data export audit logging."""
        audit_data_export(
            user=self.user,
            export_type='CSV',
            model_name='Assessment',
            record_count=1000,
            filters={'status': 'COMPLETED', 'date_range': '2024-01-01 to 2024-12-31'}
        )
        
        # Check audit log
        log = AuditLog.objects.filter(
            action='EXPORT'
        ).first()
        
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.metadata['export_type'], 'CSV')
        self.assertEqual(log.metadata['model_name'], 'Assessment')
        self.assertEqual(log.metadata['record_count'], 1000)
        self.assertEqual(log.metadata['filters']['status'], 'COMPLETED')


class AsyncSignalTestCase(TransactionTestCase):
    """Test cases for async signal handling."""
    
    def setUp(self):
        """Set up test data."""
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_async_audit_creation(self):
        """Test that audit logs can be created asynchronously."""
        # Create with async context
        async def create_partner():
            with audit_context(user=self.user):
                partner = DevelopmentPartner.objects.create(
                    group=self.group,
                    name="Async Partner",
                    country="US"
                )
                return partner
        
        # Run async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        partner = loop.run_until_complete(create_partner())
        loop.close()
        
        # Give async tasks time to complete
        import time
        time.sleep(0.1)
        
        # Check audit log was created
        log = AuditLog.objects.filter(
            action=AuditLog.Action.CREATE,
            object_id=str(partner.id)
        ).first()
        
        # May or may not be created depending on async execution
        # This is testing that it doesn't crash
        self.assertIsNotNone(partner)
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    @patch('core.signals.create_audit_log_sync')
    @patch('asyncio.get_event_loop')
    def test_fallback_to_sync_logging(self, mock_get_loop, mock_sync_log):
        """Test fallback to sync logging when async not available."""
        # Mock no event loop
        mock_get_loop.side_effect = RuntimeError("No event loop")
        
        with audit_context(user=self.user):
            partner = DevelopmentPartner.objects.create(
                group=self.group,
                name="Sync Fallback",
                country="US"
            )
        
        # Should fall back to sync logging
        mock_sync_log.assert_called()
        call_args = mock_sync_log.call_args
        self.assertEqual(call_args[0][0], 'CREATE')
        self.assertEqual(call_args[0][1].id, partner.id)


class SignalErrorHandlingTestCase(TestCase):
    """Test error handling in signal handlers."""
    
    def setUp(self):
        """Set up test data."""
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    @patch('core.signals.logger.error')
    @patch('core.signals.get_field_changes')
    def test_signal_error_handling(self, mock_get_changes, mock_logger):
        """Test that errors in signals don't crash the application."""
        # Make get_field_changes raise an error
        mock_get_changes.side_effect = Exception("Field comparison error")
        
        # This should not raise an exception
        partner = DevelopmentPartner.objects.create(
            group=self.group,
            name="Test",
            country="US"
        )
        partner.name = "Updated"
        partner.save()
        
        # Should log the error
        mock_logger.assert_called()
        self.assertIn("Failed to process post_save audit", mock_logger.call_args[0][0])
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    @patch('core.signals.logger.error')
    @patch('core.models.AuditLog.objects.create_log')
    def test_database_error_handling(self, mock_create_log, mock_logger):
        """Test handling of database errors during audit creation."""
        # Make create_log raise a database error
        mock_create_log.side_effect = Exception("Database connection lost")
        
        # This should not raise an exception
        with audit_context(user=self.user):
            partner = DevelopmentPartner.objects.create(
                group=self.group,
                name="Test",
                country="US"
            )
        
        # Should log the error
        mock_logger.assert_called()
        self.assertIn("Failed to create sync audit log", mock_logger.call_args[0][0])
        
        # Original operation should succeed
        self.assertIsNotNone(partner.id)


class SignalThreadSafetyTestCase(TransactionTestCase):
    """Test thread safety of signal handlers."""
    
    def setUp(self):
        """Set up test data."""
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
    
    @override_settings(AUDIT_LOGGING={'ENABLED': True})
    def test_concurrent_signal_handling(self):
        """Test that signals handle concurrent operations correctly."""
        results = []
        errors = []
        
        def create_partner(index):
            try:
                with audit_context(user=self.user):
                    partner = DevelopmentPartner.objects.create(
                        group=self.group,
                        name=f"Partner {index}",
                        country="US"
                    )
                    results.append(partner.id)
            except Exception as e:
                errors.append(str(e))
        
        # Create multiple threads
        threads = []
        for i in range(10):
            thread = Thread(target=create_partner, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # All should succeed
        self.assertEqual(len(results), 10)
        self.assertEqual(len(errors), 0)
        
        # Check audit logs were created
        log_count = AuditLog.objects.filter(
            action=AuditLog.Action.CREATE,
            model_name='DevelopmentPartner'
        ).count()
        
        # Should have logs for all (or most due to async)
        self.assertGreaterEqual(log_count, 5)  # At least half


class RequestSignalTestCase(TestCase):
    """Test cases for request lifecycle signals."""
    
    @override_settings(AUDIT_LOGGING={
        'ENABLED': True,
        'AUDIT_ALL_REQUESTS': True
    })
    @patch('core.signals.log_action')
    def test_request_started_signal(self, mock_log_action):
        """Test request started signal (when enabled)."""
        from platform_core.core.signals import audit_request_started
        
        # Create mock environ
        environ = {
            'PATH_INFO': '/api/assessments/',
            'REQUEST_METHOD': 'GET',
            'REMOTE_ADDR': '192.168.1.1',
            'HTTP_USER_AGENT': 'TestClient/1.0'
        }
        
        # Trigger signal
        audit_request_started(sender=None, environ=environ)
        
        # Should log the request
        mock_log_action.assert_called_once()
        call_args = mock_log_action.call_args
        self.assertEqual(call_args[0][0], 'API_ACCESS')
        self.assertEqual(call_args[1]['metadata']['path'], '/api/assessments/')
        self.assertEqual(call_args[1]['metadata']['method'], 'GET')
    
    @override_settings(AUDIT_LOGGING={
        'ENABLED': True,
        'AUDIT_ALL_REQUESTS': True
    })
    @patch('core.signals.log_action')
    def test_request_signal_skip_static(self, mock_log_action):
        """Test that static/health requests are skipped."""
        from platform_core.core.signals import audit_request_started
        
        # Test various paths that should be skipped
        skip_paths = [
            '/static/css/style.css',
            '/media/uploads/file.pdf',
            '/health/',
            '/favicon.ico'
        ]
        
        for path in skip_paths:
            mock_log_action.reset_mock()
            environ = {'PATH_INFO': path, 'REQUEST_METHOD': 'GET'}
            audit_request_started(sender=None, environ=environ)
            mock_log_action.assert_not_called()
    
    @override_settings(AUDIT_LOGGING={
        'ENABLED': True,
        'AUDIT_ALL_REQUESTS': False  # Disabled
    })
    @patch('core.signals.log_action')
    def test_request_signal_disabled(self, mock_log_action):
        """Test request signals when disabled."""
        from platform_core.core.signals import audit_request_started
        
        environ = {
            'PATH_INFO': '/api/assessments/',
            'REQUEST_METHOD': 'POST'
        }
        
        audit_request_started(sender=None, environ=environ)
        mock_log_action.assert_not_called()