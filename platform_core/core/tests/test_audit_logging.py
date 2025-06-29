"""
Comprehensive unit tests for the audit logging system.

Tests audit log models, managers, and core functionality with
full coverage of multi-tenancy, sensitive data handling, and
performance considerations.
"""

import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import Group
from assessments.models import Assessment, DevelopmentPartner
from platform_core.core.models import AuditLog, AuditLogEntry, SystemMetrics

User = get_user_model()


class AuditLogModelTestCase(TestCase):
    """Test cases for AuditLog model functionality."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.group = Group.objects.create(name="Test Group")
        cls.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!",
            first_name="Test",
            last_name="User"
        )
        cls.user.groups.add(cls.group)
        
        cls.partner = DevelopmentPartner.objects.create(
            group=cls.group,
            name="Test Partner",
            country="US"
        )
    
    def test_audit_log_creation(self):
        """Test basic audit log creation."""
        audit_log = AuditLog.objects.create_log(
            action=AuditLog.Action.CREATE,
            user=self.user,
            content_object=self.partner,
            changes={'name': {'old': None, 'new': 'Test Partner'}},
            ip_address='192.168.1.1',
            user_agent='Mozilla/5.0',
            group=self.group
        )
        
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.action, AuditLog.Action.CREATE)
        self.assertEqual(audit_log.user, self.user)
        self.assertEqual(audit_log.content_object, self.partner)
        self.assertEqual(audit_log.group, self.group)
        self.assertEqual(audit_log.model_name, 'DevelopmentPartner')
        self.assertEqual(audit_log.object_id, str(self.partner.pk))
        self.assertTrue(audit_log.success)
    
    def test_audit_log_without_user(self):
        """Test audit log creation for system actions."""
        audit_log = AuditLog.objects.create_log(
            action=AuditLog.Action.BACKUP,
            metadata={'backup_type': 'full', 'size_mb': 1024}
        )
        
        self.assertIsNone(audit_log.user)
        self.assertIsNone(audit_log.content_object)
        self.assertEqual(audit_log.action, AuditLog.Action.BACKUP)
    
    def test_audit_log_with_error(self):
        """Test audit log creation for failed actions."""
        audit_log = AuditLog.objects.create_log(
            action=AuditLog.Action.LOGIN_FAILED,
            ip_address='10.0.0.1',
            success=False,
            error_message='Invalid credentials',
            metadata={'username': 'unknown@example.com'}
        )
        
        self.assertFalse(audit_log.success)
        self.assertEqual(audit_log.error_message, 'Invalid credentials')
        self.assertEqual(audit_log.metadata['username'], 'unknown@example.com')
    
    def test_formatted_changes(self):
        """Test the formatted_changes property."""
        audit_log = AuditLog.objects.create_log(
            action=AuditLog.Action.UPDATE,
            user=self.user,
            content_object=self.partner,
            changes={
                'name': {'old': 'Old Name', 'new': 'New Name'},
                'country': {'old': 'US', 'new': 'GB'},
                'active': True
            }
        )
        
        formatted = audit_log.formatted_changes
        self.assertIn("name: 'Old Name' → 'New Name'", formatted)
        self.assertIn("country: 'US' → 'GB'", formatted)
        self.assertIn("active: True", formatted)
    
    def test_is_critical_property(self):
        """Test identification of critical actions."""
        critical_actions = [
            AuditLog.Action.DELETE,
            AuditLog.Action.BULK_DELETE,
            AuditLog.Action.PERMISSION_CHANGE,
            AuditLog.Action.PASSWORD_CHANGE,
            AuditLog.Action.LOGIN_FAILED,
            AuditLog.Action.ADMIN_ACCESS,
            AuditLog.Action.USER_DEACTIVATION
        ]
        
        for action in critical_actions:
            audit_log = AuditLog.objects.create_log(action=action)
            self.assertTrue(audit_log.is_critical, f"{action} should be critical")
        
        # Test non-critical action
        non_critical = AuditLog.objects.create_log(action=AuditLog.Action.READ)
        self.assertFalse(non_critical.is_critical)
    
    def test_duration_since_property(self):
        """Test human-readable duration calculation."""
        # Create log with specific timestamp
        now = timezone.now()
        
        # Test "Just now"
        recent_log = AuditLog.objects.create_log(action=AuditLog.Action.CREATE)
        self.assertEqual(recent_log.duration_since, "Just now")
        
        # Test minutes ago
        minutes_ago = now - timedelta(minutes=30)
        with patch('django.utils.timezone.now', return_value=now):
            old_log = AuditLog.objects.create_log(action=AuditLog.Action.CREATE)
            old_log.timestamp = minutes_ago
            old_log.save()
            self.assertEqual(old_log.duration_since, "30 minutes ago")
        
        # Test hours ago
        hours_ago = now - timedelta(hours=5)
        with patch('django.utils.timezone.now', return_value=now):
            older_log = AuditLog.objects.create_log(action=AuditLog.Action.CREATE)
            older_log.timestamp = hours_ago
            older_log.save()
            self.assertEqual(older_log.duration_since, "5 hours ago")
        
        # Test days ago
        days_ago = now - timedelta(days=3)
        with patch('django.utils.timezone.now', return_value=now):
            oldest_log = AuditLog.objects.create_log(action=AuditLog.Action.CREATE)
            oldest_log.timestamp = days_ago
            oldest_log.save()
            self.assertEqual(oldest_log.duration_since, "3 days ago")
    
    def test_get_related_logs(self):
        """Test retrieval of related audit logs."""
        # Create multiple logs for the same object
        for i in range(5):
            AuditLog.objects.create_log(
                action=AuditLog.Action.UPDATE,
                user=self.user,
                content_object=self.partner,
                changes={'counter': {'old': i, 'new': i + 1}}
            )
        
        # Get one log and check related
        log = AuditLog.objects.filter(content_object=self.partner).first()
        related = log.get_related_logs(limit=3)
        
        self.assertEqual(related.count(), 3)
        self.assertTrue(all(r.object_id == str(self.partner.pk) for r in related))
        self.assertNotIn(log.id, [r.id for r in related])
    
    def test_mask_sensitive_data(self):
        """Test sensitive data masking."""
        sensitive_changes = {
            'password': 'secret123',
            'api_token': 'token-xyz',
            'credit_card': '4111111111111111',
            'ssn': '123-45-6789',
            'safe_field': 'visible_value'
        }
        
        audit_log = AuditLog.objects.create_log(
            action=AuditLog.Action.UPDATE,
            changes=sensitive_changes
        )
        
        masked = audit_log.mask_sensitive_data()
        self.assertEqual(masked['password'], '***MASKED***')
        self.assertEqual(masked['api_token'], '***MASKED***')
        self.assertEqual(masked['credit_card'], '***MASKED***')
        self.assertEqual(masked['ssn'], '***MASKED***')
        self.assertEqual(masked['safe_field'], 'visible_value')
    
    def test_group_filtering(self):
        """Test audit logs are filtered by group."""
        # Create another group
        other_group = Group.objects.create(name="Other Group")
        
        # Create logs for different groups
        log1 = AuditLog.objects.create_log(
            action=AuditLog.Action.CREATE,
            group=self.group
        )
        log2 = AuditLog.objects.create_log(
            action=AuditLog.Action.CREATE,
            group=other_group
        )
        
        # Filter by group
        group_logs = AuditLog.objects.filter(group=self.group)
        self.assertIn(log1, group_logs)
        self.assertNotIn(log2, group_logs)
    
    def test_json_field_handling(self):
        """Test JSON field serialization in changes."""
        complex_changes = {
            'simple': 'value',
            'list': [1, 2, 3],
            'dict': {'key': 'value', 'nested': {'deep': True}},
            'date': timezone.now(),
            'decimal': Decimal('123.45')
        }
        
        audit_log = AuditLog.objects.create_log(
            action=AuditLog.Action.UPDATE,
            changes=complex_changes,
            metadata={'extra': 'data'}
        )
        
        # Retrieve and verify
        saved_log = AuditLog.objects.get(id=audit_log.id)
        self.assertEqual(saved_log.changes['simple'], 'value')
        self.assertEqual(saved_log.changes['list'], [1, 2, 3])
        self.assertEqual(saved_log.changes['dict']['nested']['deep'], True)
        self.assertIsInstance(saved_log.changes['date'], str)  # Serialized to string
        self.assertEqual(saved_log.metadata['extra'], 'data')


class AuditLogQuerySetTestCase(TestCase):
    """Test cases for AuditLogQuerySet methods."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data for queryset tests."""
        cls.group = Group.objects.create(name="Test Group")
        cls.user1 = User.objects.create_user(
            email="user1@example.com",
            password="TestPass123!"
        )
        cls.user2 = User.objects.create_user(
            email="user2@example.com",
            password="TestPass123!"
        )
        
        cls.partner = DevelopmentPartner.objects.create(
            group=cls.group,
            name="Test Partner",
            country="US"
        )
        
        # Create various audit logs
        cls.logs = []
        
        # Different actions
        for action in [AuditLog.Action.CREATE, AuditLog.Action.UPDATE, 
                      AuditLog.Action.DELETE, AuditLog.Action.LOGIN_FAILED]:
            log = AuditLog.objects.create_log(
                action=action,
                user=cls.user1 if action != AuditLog.Action.LOGIN_FAILED else None,
                content_object=cls.partner if action != AuditLog.Action.LOGIN_FAILED else None,
                changes={'test': 'data'} if action == AuditLog.Action.UPDATE else None,
                success=action != AuditLog.Action.LOGIN_FAILED,
                ip_address='192.168.1.100'
            )
            cls.logs.append(log)
        
        # Old log
        old_log = AuditLog.objects.create_log(
            action=AuditLog.Action.CREATE,
            user=cls.user2
        )
        old_log.timestamp = timezone.now() - timedelta(days=30)
        old_log.save()
        cls.logs.append(old_log)
    
    def test_for_model_filter(self):
        """Test filtering by model name."""
        logs = AuditLog.objects.for_model('DevelopmentPartner')
        self.assertEqual(logs.count(), 3)  # CREATE, UPDATE, DELETE
        self.assertTrue(all(log.model_name == 'DevelopmentPartner' for log in logs))
    
    def test_for_object_filter(self):
        """Test filtering by specific object."""
        logs = AuditLog.objects.for_object(self.partner)
        self.assertEqual(logs.count(), 3)  # CREATE, UPDATE, DELETE
        self.assertTrue(all(log.object_id == str(self.partner.pk) for log in logs))
    
    def test_for_user_filter(self):
        """Test filtering by user."""
        logs = AuditLog.objects.for_user(self.user1)
        self.assertEqual(logs.count(), 3)  # CREATE, UPDATE, DELETE
        self.assertTrue(all(log.user == self.user1 for log in logs))
    
    def test_for_action_filter(self):
        """Test filtering by action type."""
        logs = AuditLog.objects.for_action(AuditLog.Action.UPDATE)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().action, AuditLog.Action.UPDATE)
    
    def test_in_date_range_filter(self):
        """Test filtering by date range."""
        start = timezone.now() - timedelta(days=7)
        end = timezone.now()
        
        logs = AuditLog.objects.in_date_range(start, end)
        self.assertEqual(logs.count(), 4)  # All except the old log
    
    def test_recent_filter(self):
        """Test filtering recent logs."""
        # Default 7 days
        recent_logs = AuditLog.objects.recent()
        self.assertEqual(recent_logs.count(), 4)  # All except the old log
        
        # Custom days
        all_logs = AuditLog.objects.recent(days=45)
        self.assertEqual(all_logs.count(), 5)  # All logs
    
    def test_by_ip_address_filter(self):
        """Test filtering by IP address."""
        logs = AuditLog.objects.by_ip_address('192.168.1.100')
        self.assertEqual(logs.count(), 4)
        self.assertTrue(all(log.ip_address == '192.168.1.100' for log in logs))
    
    def test_critical_actions_filter(self):
        """Test filtering critical security actions."""
        critical_logs = AuditLog.objects.critical_actions()
        self.assertEqual(critical_logs.count(), 2)  # DELETE and LOGIN_FAILED
        
        actions = set(log.action for log in critical_logs)
        self.assertIn(AuditLog.Action.DELETE, actions)
        self.assertIn(AuditLog.Action.LOGIN_FAILED, actions)
    
    def test_with_changes_filter(self):
        """Test filtering logs with changes."""
        logs_with_changes = AuditLog.objects.with_changes()
        self.assertEqual(logs_with_changes.count(), 1)  # Only UPDATE has changes
        self.assertEqual(logs_with_changes.first().action, AuditLog.Action.UPDATE)
    
    def test_chained_filters(self):
        """Test chaining multiple filters."""
        # Recent critical actions by user1
        logs = (AuditLog.objects
                .for_user(self.user1)
                .critical_actions()
                .recent(days=7))
        
        self.assertEqual(logs.count(), 1)  # Only DELETE
        self.assertEqual(logs.first().action, AuditLog.Action.DELETE)
    
    def test_manager_methods(self):
        """Test manager convenience methods."""
        # Test for_model via manager
        logs = AuditLog.objects.for_model('DevelopmentPartner')
        self.assertEqual(logs.count(), 3)
        
        # Test recent_activity
        recent = AuditLog.objects.recent_activity(days=7)
        self.assertEqual(recent.count(), 4)
        
        # Test security_events
        security = AuditLog.objects.security_events(days=30)
        self.assertEqual(security.count(), 2)  # DELETE and LOGIN_FAILED


class AuditLogEntryTestCase(TestCase):
    """Test cases for AuditLogEntry model."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data for entry tests."""
        cls.group = Group.objects.create(name="Test Group")
        cls.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!"
        )
        
        cls.audit_log = AuditLog.objects.create_log(
            action=AuditLog.Action.UPDATE,
            user=cls.user,
            changes={'field1': {'old': 'old_value', 'new': 'new_value'}}
        )
    
    def test_audit_log_entry_creation(self):
        """Test creating audit log entries."""
        entry = AuditLogEntry.objects.create(
            audit_log=self.audit_log,
            field_name='test_field',
            field_type='CharField',
            old_value=json.dumps('old_value'),
            new_value=json.dumps('new_value'),
            is_sensitive=False
        )
        
        self.assertEqual(entry.audit_log, self.audit_log)
        self.assertEqual(entry.field_name, 'test_field')
        self.assertEqual(entry.field_type, 'CharField')
        self.assertFalse(entry.is_sensitive)
    
    def test_sensitive_field_handling(self):
        """Test handling of sensitive fields."""
        entry = AuditLogEntry.objects.create(
            audit_log=self.audit_log,
            field_name='password',
            field_type='CharField',
            old_value='***MASKED***',
            new_value='***MASKED***',
            is_sensitive=True
        )
        
        self.assertTrue(entry.is_sensitive)
        self.assertEqual(entry.formatted_change, 'password: ***SENSITIVE DATA CHANGED***')
    
    def test_formatted_change_property(self):
        """Test formatted change display."""
        # Normal field
        entry1 = AuditLogEntry.objects.create(
            audit_log=self.audit_log,
            field_name='name',
            field_type='CharField',
            old_value='Old Name',
            new_value='New Name'
        )
        self.assertEqual(entry1.formatted_change, "name: 'Old Name' → 'New Name'")
        
        # Long values (should be truncated)
        long_text = 'x' * 100
        entry2 = AuditLogEntry.objects.create(
            audit_log=self.audit_log,
            field_name='description',
            field_type='TextField',
            old_value=long_text,
            new_value=long_text + 'y'
        )
        formatted = entry2.formatted_change
        self.assertIn('...', formatted)
        self.assertTrue(len(formatted) < 150)  # Reasonable length
    
    def test_parse_value_methods(self):
        """Test parsing JSON values."""
        # JSON parseable values
        entry1 = AuditLogEntry.objects.create(
            audit_log=self.audit_log,
            field_name='data',
            field_type='JSONField',
            old_value=json.dumps({'key': 'value'}),
            new_value=json.dumps([1, 2, 3])
        )
        
        self.assertEqual(entry1.get_parsed_old_value(), {'key': 'value'})
        self.assertEqual(entry1.get_parsed_new_value(), [1, 2, 3])
        
        # Non-JSON values
        entry2 = AuditLogEntry.objects.create(
            audit_log=self.audit_log,
            field_name='plain',
            field_type='CharField',
            old_value='plain text',
            new_value='new text'
        )
        
        self.assertEqual(entry2.get_parsed_old_value(), 'plain text')
        self.assertEqual(entry2.get_parsed_new_value(), 'new text')
        
        # Null values
        entry3 = AuditLogEntry.objects.create(
            audit_log=self.audit_log,
            field_name='nullable',
            field_type='CharField',
            old_value=None,
            new_value='value'
        )
        
        self.assertIsNone(entry3.get_parsed_old_value())
        self.assertEqual(entry3.get_parsed_new_value(), 'value')
    
    def test_unique_constraint(self):
        """Test unique constraint on audit_log and field_name."""
        # Create first entry
        AuditLogEntry.objects.create(
            audit_log=self.audit_log,
            field_name='unique_field',
            field_type='CharField',
            old_value='old',
            new_value='new'
        )
        
        # Try to create duplicate
        with self.assertRaises(Exception):  # IntegrityError
            AuditLogEntry.objects.create(
                audit_log=self.audit_log,
                field_name='unique_field',  # Same field name
                field_type='CharField',
                old_value='old2',
                new_value='new2'
            )
    
    def test_bulk_creation(self):
        """Test bulk creation of entries."""
        entries = []
        for i in range(5):
            entries.append(AuditLogEntry(
                audit_log=self.audit_log,
                field_name=f'field_{i}',
                field_type='CharField',
                old_value=f'old_{i}',
                new_value=f'new_{i}'
            ))
        
        created_entries = AuditLogEntry.objects.bulk_create(entries)
        self.assertEqual(len(created_entries), 5)
        
        # Verify they were created
        count = AuditLogEntry.objects.filter(audit_log=self.audit_log).count()
        self.assertEqual(count, 5)


class SystemMetricsTestCase(TestCase):
    """Test cases for SystemMetrics model."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data for metrics tests."""
        cls.group = Group.objects.create(name="Test Group")
    
    def test_metric_creation(self):
        """Test creating system metrics."""
        metric = SystemMetrics.objects.create(
            metric_type=SystemMetrics.MetricType.PERFORMANCE,
            metric_name='api_response_time',
            value=Decimal('123.456'),
            unit='ms',
            group=self.group,
            metadata={'endpoint': '/api/assessments/', 'method': 'GET'}
        )
        
        self.assertEqual(metric.metric_type, SystemMetrics.MetricType.PERFORMANCE)
        self.assertEqual(metric.metric_name, 'api_response_time')
        self.assertEqual(metric.value, Decimal('123.456'))
        self.assertEqual(metric.unit, 'ms')
        self.assertEqual(metric.group, self.group)
        self.assertEqual(metric.metadata['endpoint'], '/api/assessments/')
    
    def test_record_metric_classmethod(self):
        """Test the record_metric class method."""
        metric = SystemMetrics.record_metric(
            metric_type=SystemMetrics.MetricType.USAGE,
            metric_name='daily_active_users',
            value=150,
            unit='count',
            group=self.group,
            peak_hour='14:00',
            date=timezone.now().date().isoformat()
        )
        
        self.assertIsNotNone(metric)
        self.assertEqual(metric.value, Decimal('150'))
        self.assertEqual(metric.metadata['peak_hour'], '14:00')
    
    def test_metric_types(self):
        """Test different metric types."""
        metric_types = [
            (SystemMetrics.MetricType.PERFORMANCE, 'cpu_usage', 75.5, 'percent'),
            (SystemMetrics.MetricType.SECURITY, 'failed_logins', 5, 'count'),
            (SystemMetrics.MetricType.USAGE, 'api_calls', 10000, 'count'),
            (SystemMetrics.MetricType.ERROR, 'error_rate', 0.05, 'ratio'),
            (SystemMetrics.MetricType.BUSINESS, 'conversion_rate', 0.15, 'ratio')
        ]
        
        for metric_type, name, value, unit in metric_types:
            metric = SystemMetrics.record_metric(
                metric_type=metric_type,
                metric_name=name,
                value=value,
                unit=unit
            )
            self.assertEqual(metric.metric_type, metric_type)
            self.assertEqual(metric.metric_name, name)
    
    def test_metric_aggregation(self):
        """Test querying and aggregating metrics."""
        # Create multiple metrics
        for i in range(10):
            SystemMetrics.record_metric(
                metric_type=SystemMetrics.MetricType.PERFORMANCE,
                metric_name='response_time',
                value=100 + i * 10,
                unit='ms',
                group=self.group
            )
        
        # Query metrics
        metrics = SystemMetrics.objects.filter(
            metric_type=SystemMetrics.MetricType.PERFORMANCE,
            metric_name='response_time',
            group=self.group
        )
        
        self.assertEqual(metrics.count(), 10)
        
        # Aggregate
        from django.db.models import Avg, Max, Min
        aggregates = metrics.aggregate(
            avg_time=Avg('value'),
            max_time=Max('value'),
            min_time=Min('value')
        )
        
        self.assertEqual(aggregates['avg_time'], Decimal('145'))
        self.assertEqual(aggregates['max_time'], Decimal('190'))
        self.assertEqual(aggregates['min_time'], Decimal('100'))
    
    def test_metric_time_filtering(self):
        """Test filtering metrics by time."""
        # Create metrics at different times
        now = timezone.now()
        
        # Recent metric
        recent = SystemMetrics.record_metric(
            metric_type=SystemMetrics.MetricType.USAGE,
            metric_name='recent_metric',
            value=1,
            unit='count'
        )
        
        # Old metric
        old = SystemMetrics.record_metric(
            metric_type=SystemMetrics.MetricType.USAGE,
            metric_name='old_metric',
            value=2,
            unit='count'
        )
        old.timestamp = now - timedelta(days=30)
        old.save()
        
        # Filter recent
        recent_metrics = SystemMetrics.objects.filter(
            timestamp__gte=now - timedelta(days=7)
        )
        self.assertIn(recent, recent_metrics)
        self.assertNotIn(old, recent_metrics)
    
    def test_metric_string_representation(self):
        """Test string representation of metrics."""
        metric = SystemMetrics.record_metric(
            metric_type=SystemMetrics.MetricType.PERFORMANCE,
            metric_name='test_metric',
            value=42.5,
            unit='ms'
        )
        
        str_rep = str(metric)
        self.assertIn('test_metric', str_rep)
        self.assertIn('42.5ms', str_rep)
    
    def test_metric_with_complex_metadata(self):
        """Test metrics with complex metadata."""
        complex_metadata = {
            'server': {
                'hostname': 'app-server-01',
                'region': 'us-west-2',
                'instance_type': 't2.medium'
            },
            'request': {
                'method': 'POST',
                'path': '/api/assessments/',
                'user_id': str(uuid.uuid4())
            },
            'tags': ['high-priority', 'customer-facing']
        }
        
        metric = SystemMetrics.record_metric(
            metric_type=SystemMetrics.MetricType.PERFORMANCE,
            metric_name='api_latency',
            value=250.75,
            unit='ms',
            **complex_metadata
        )
        
        # Verify nested metadata
        self.assertEqual(metric.metadata['server']['region'], 'us-west-2')
        self.assertEqual(metric.metadata['request']['method'], 'POST')
        self.assertIn('high-priority', metric.metadata['tags'])


class AuditLogPerformanceTestCase(TransactionTestCase):
    """Test performance aspects of audit logging."""
    
    def setUp(self):
        """Set up performance tests."""
        self.group = Group.objects.create(name="Performance Test Group")
        self.user = User.objects.create_user(
            email="perf@example.com",
            password="TestPass123!"
        )
    
    def test_bulk_audit_log_creation(self):
        """Test performance of creating many audit logs."""
        import time
        
        start_time = time.time()
        
        # Create 1000 audit logs
        logs = []
        for i in range(1000):
            log = AuditLog(
                action=AuditLog.Action.CREATE,
                user=self.user,
                group=self.group,
                metadata={'index': i}
            )
            logs.append(log)
        
        AuditLog.objects.bulk_create(logs)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(duration, 5.0)
        
        # Verify creation
        count = AuditLog.objects.filter(group=self.group).count()
        self.assertEqual(count, 1000)
    
    def test_query_performance_with_indexes(self):
        """Test query performance with database indexes."""
        # Create logs with different attributes
        for i in range(100):
            AuditLog.objects.create_log(
                action=AuditLog.Action.CREATE if i % 2 == 0 else AuditLog.Action.UPDATE,
                user=self.user if i % 3 == 0 else None,
                ip_address=f'192.168.1.{i % 256}',
                group=self.group
            )
        
        import time
        
        # Test indexed queries
        queries = [
            lambda: AuditLog.objects.filter(action=AuditLog.Action.CREATE).count(),
            lambda: AuditLog.objects.filter(user=self.user).count(),
            lambda: AuditLog.objects.filter(timestamp__gte=timezone.now() - timedelta(days=1)).count(),
            lambda: AuditLog.objects.filter(group=self.group).count(),
        ]
        
        for query_func in queries:
            start_time = time.time()
            result = query_func()
            duration = time.time() - start_time
            
            # Each query should be fast (< 0.1 seconds)
            self.assertLess(duration, 0.1)
            self.assertGreaterEqual(result, 0)
    
    def test_json_field_performance(self):
        """Test performance of JSON field operations."""
        # Create logs with large JSON data
        large_changes = {f'field_{i}': {'old': f'old_{i}', 'new': f'new_{i}'} 
                        for i in range(100)}
        
        log = AuditLog.objects.create_log(
            action=AuditLog.Action.UPDATE,
            changes=large_changes,
            metadata={'size': 'large'}
        )
        
        # Test retrieval and access
        import time
        start_time = time.time()
        
        retrieved_log = AuditLog.objects.get(id=log.id)
        changes = retrieved_log.changes
        
        # Access nested data
        self.assertEqual(changes['field_50']['old'], 'old_50')
        
        duration = time.time() - start_time
        # Should be fast even with large JSON
        self.assertLess(duration, 0.1)


class AuditLogEdgeCaseTestCase(TestCase):
    """Test edge cases and error handling."""
    
    def setUp(self):
        """Set up edge case tests."""
        self.group = Group.objects.create(name="Edge Case Group")
        self.user = User.objects.create_user(
            email="edge@example.com",
            password="TestPass123!"
        )
    
    def test_null_values_handling(self):
        """Test handling of null values."""
        log = AuditLog.objects.create_log(
            action=AuditLog.Action.CREATE,
            user=None,
            content_object=None,
            changes=None,
            ip_address=None,
            user_agent=None,
            group=None
        )
        
        self.assertIsNotNone(log)
        self.assertEqual(log.changes, {})  # Default empty dict
        self.assertIsNone(log.user)
        self.assertIsNone(log.content_object)
    
    def test_extremely_long_values(self):
        """Test handling of extremely long values."""
        # Very long user agent
        long_user_agent = 'x' * 1000
        
        log = AuditLog.objects.create_log(
            action=AuditLog.Action.API_ACCESS,
            user_agent=long_user_agent
        )
        
        # Should store without truncation in TextField
        self.assertEqual(len(log.user_agent), 1000)
    
    def test_unicode_handling(self):
        """Test handling of Unicode characters."""
        unicode_changes = {
            'name': {'old': 'Test', 'new': '测试'},
            'emoji': {'old': '😀', 'new': '🎉'},
            'special': {'old': 'café', 'new': 'naïve'}
        }
        
        log = AuditLog.objects.create_log(
            action=AuditLog.Action.UPDATE,
            changes=unicode_changes
        )
        
        # Verify Unicode is preserved
        self.assertEqual(log.changes['name']['new'], '测试')
        self.assertEqual(log.changes['emoji']['new'], '🎉')
        self.assertEqual(log.changes['special']['new'], 'naïve')
    
    def test_circular_reference_handling(self):
        """Test handling of objects with circular references."""
        # Create an object that references itself
        partner = DevelopmentPartner.objects.create(
            group=self.group,
            name="Self Referencing Partner",
            country="US"
        )
        
        # Create audit log
        log = AuditLog.objects.create_log(
            action=AuditLog.Action.CREATE,
            content_object=partner,
            metadata={'partner_id': str(partner.id)}
        )
        
        # Should handle without infinite recursion
        self.assertEqual(log.object_id, str(partner.id))
        self.assertEqual(log.metadata['partner_id'], str(partner.id))
    
    def test_deleted_object_reference(self):
        """Test audit logs referencing deleted objects."""
        # Create and delete an object
        partner = DevelopmentPartner.objects.create(
            group=self.group,
            name="To Be Deleted",
            country="US"
        )
        partner_id = partner.id
        
        # Create audit log
        log = AuditLog.objects.create_log(
            action=AuditLog.Action.DELETE,
            content_object=partner
        )
        
        # Delete the partner
        partner.delete()
        
        # Audit log should still exist
        retrieved_log = AuditLog.objects.get(id=log.id)
        self.assertEqual(retrieved_log.object_id, str(partner_id))
        self.assertIsNone(retrieved_log.content_object)  # GenericFK returns None
    
    def test_concurrent_access(self):
        """Test handling of concurrent audit log creation."""
        from threading import Thread
        import threading
        
        results = []
        lock = threading.Lock()
        
        def create_log(index):
            try:
                log = AuditLog.objects.create_log(
                    action=AuditLog.Action.CREATE,
                    metadata={'thread': index}
                )
                with lock:
                    results.append(log.id)
            except Exception as e:
                with lock:
                    results.append(f"Error: {e}")
        
        # Create logs concurrently
        threads = []
        for i in range(10):
            thread = Thread(target=create_log, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # All should succeed
        self.assertEqual(len(results), 10)
        self.assertTrue(all(isinstance(r, uuid.UUID) for r in results))
    
    def test_invalid_action_handling(self):
        """Test handling of invalid action values."""
        # Valid action should work
        valid_log = AuditLog.objects.create_log(
            action=AuditLog.Action.CREATE
        )
        self.assertIsNotNone(valid_log)
        
        # Invalid action should raise error
        with self.assertRaises(ValidationError):
            log = AuditLog(action='INVALID_ACTION')
            log.full_clean()  # Trigger validation
    
    def test_metadata_size_limits(self):
        """Test handling of large metadata."""
        # Create very large metadata
        large_metadata = {
            f'key_{i}': f'value_{i}' * 100 for i in range(100)
        }
        
        # Should handle large metadata
        log = AuditLog.objects.create_log(
            action=AuditLog.Action.EXPORT,
            metadata=large_metadata
        )
        
        self.assertIsNotNone(log)
        self.assertEqual(len(log.metadata), 100)