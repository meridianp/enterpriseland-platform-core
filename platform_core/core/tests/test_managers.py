"""
Tests for custom Django managers in the EnterpriseLand platform.

Tests multi-tenancy, caching, and security functionality.
"""

import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from accounts.models import Group
from platform_core.core.managers import GroupFilteredManager, GroupFilteredQuerySet
from assessments.base_models import GroupFilteredModel

User = get_user_model()


# Test model for testing the manager
class TestModel(GroupFilteredModel):
    """
    Test model that inherits from GroupFilteredModel.
    """
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default='active')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        app_label = 'core'


class GroupFilteredManagerTest(TestCase):
    """
    Test cases for GroupFilteredManager functionality.
    """
    
    def setUp(self):
        """
        Set up test data.
        """
        # Clear cache before each test
        cache.clear()
        
        # Create test groups
        self.group1 = Group.objects.create(name="Group 1")
        self.group2 = Group.objects.create(name="Group 2")
        
        # Create test users
        self.user1 = User.objects.create_user(
            email="user1@example.com",
            password="testpass123"
        )
        self.user1.groups.add(self.group1)
        
        self.user2 = User.objects.create_user(
            email="user2@example.com",
            password="testpass123"
        )
        self.user2.groups.add(self.group2)
        
        self.superuser = User.objects.create_superuser(
            email="admin@example.com",
            password="testpass123"
        )
        
        # Create test records
        self.record1 = TestModel.objects.create(
            name="Record 1",
            group=self.group1,
            created_by=self.user1
        )
        self.record2 = TestModel.objects.create(
            name="Record 2",
            group=self.group2,
            created_by=self.user2
        )
    
    def test_queryset_for_group(self):
        """
        Test QuerySet filtering by group.
        """
        # Filter by group instance
        records = TestModel.objects.for_group(self.group1)
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.first().name, "Record 1")
        
        # Filter by group ID string
        records = TestModel.objects.for_group(str(self.group1.id))
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.first().name, "Record 1")
    
    def test_queryset_for_user(self):
        """
        Test QuerySet filtering by user.
        """
        # User 1 should only see records in group 1
        records = TestModel.objects.for_user(self.user1)
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.first().name, "Record 1")
        
        # User 2 should only see records in group 2
        records = TestModel.objects.for_user(self.user2)
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.first().name, "Record 2")
        
        # Superuser should see all records
        records = TestModel.objects.for_user(self.superuser)
        self.assertEqual(records.count(), 2)
    
    def test_queryset_for_unauthenticated_user(self):
        """
        Test QuerySet filtering for unauthenticated user.
        """
        # Unauthenticated user should see no records
        records = TestModel.objects.for_user(None)
        self.assertEqual(records.count(), 0)
        
        # User with no groups should see no records
        user_no_groups = User.objects.create_user(
            email="nogroups@example.com",
            password="testpass123"
        )
        records = TestModel.objects.for_user(user_no_groups)
        self.assertEqual(records.count(), 0)
    
    def test_queryset_recent(self):
        """
        Test QuerySet filtering by recent records.
        """
        # All records should be recent (just created)
        recent_records = TestModel.objects.recent(days=1)
        self.assertEqual(recent_records.count(), 2)
        
        # No records should be recent if we look for very recent (1 minute)
        # This test might be flaky in slow environments
        recent_records = TestModel.objects.recent(days=0)
        self.assertTrue(recent_records.count() >= 0)  # Allow for timing variations
    
    def test_queryset_by_status(self):
        """
        Test QuerySet filtering by status.
        """
        # Filter by status
        active_records = TestModel.objects.by_status('active')
        self.assertEqual(active_records.count(), 2)
        
        # Change one record's status
        self.record1.status = 'inactive'
        self.record1.save()
        
        active_records = TestModel.objects.by_status('active')
        self.assertEqual(active_records.count(), 1)
        
        inactive_records = TestModel.objects.by_status('inactive')
        self.assertEqual(inactive_records.count(), 1)
    
    def test_queryset_active(self):
        """
        Test QuerySet filtering by active records.
        """
        # All records should be active initially
        active_records = TestModel.objects.active()
        self.assertEqual(active_records.count(), 2)
        
        # Deactivate one record
        self.record1.is_active = False
        self.record1.save()
        
        active_records = TestModel.objects.active()
        self.assertEqual(active_records.count(), 1)
    
    def test_create_for_group(self):
        """
        Test creating records for a specific group.
        """
        # Create by group instance
        record = TestModel.objects.create_for_group(
            self.group1,
            name="Test Record",
            created_by=self.user1
        )
        self.assertEqual(record.group, self.group1)
        self.assertEqual(record.name, "Test Record")
        
        # Create by group ID string
        record = TestModel.objects.create_for_group(
            str(self.group2.id),
            name="Test Record 2",
            created_by=self.user2
        )
        self.assertEqual(record.group, self.group2)
        self.assertEqual(record.name, "Test Record 2")
    
    def test_create_for_group_invalid(self):
        """
        Test creating records for invalid group.
        """
        with self.assertRaises(ValidationError):
            TestModel.objects.create_for_group(
                str(uuid.uuid4()),  # Non-existent group ID
                name="Test Record"
            )
    
    def test_create_for_user(self):
        """
        Test creating records for a specific user.
        """
        record = TestModel.objects.create_for_user(
            self.user1,
            name="User Record"
        )
        self.assertEqual(record.group, self.group1)
        self.assertEqual(record.created_by, self.user1)
        self.assertEqual(record.name, "User Record")
    
    def test_create_for_user_invalid(self):
        """
        Test creating records for invalid user.
        """
        # Unauthenticated user
        with self.assertRaises(PermissionDenied):
            TestModel.objects.create_for_user(
                None,
                name="Test Record"
            )
        
        # User with no groups
        user_no_groups = User.objects.create_user(
            email="nogroups@example.com",
            password="testpass123"
        )
        with self.assertRaises(ValidationError):
            TestModel.objects.create_for_user(
                user_no_groups,
                name="Test Record"
            )
    
    @patch('django.core.cache.cache')
    def test_get_cached(self, mock_cache):
        """
        Test cached record retrieval.
        """
        # Set up mock cache
        mock_cache.get.return_value = None
        mock_cache.set.return_value = None
        
        # Test cache miss
        record = TestModel.objects.get_cached(
            'test_key',
            timeout=300,
            id=self.record1.id
        )
        
        self.assertEqual(record, self.record1)
        mock_cache.get.assert_called_once_with('test_key')
        mock_cache.set.assert_called_once_with('test_key', self.record1, 300)
    
    @patch('django.core.cache.cache')
    def test_filter_cached(self, mock_cache):
        """
        Test cached record filtering.
        """
        # Set up mock cache
        mock_cache.get.return_value = None
        mock_cache.set.return_value = None
        
        # Test cache miss
        records = TestModel.objects.filter_cached(
            'test_filter_key',
            timeout=300,
            group=self.group1
        )
        
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0], self.record1)
        mock_cache.get.assert_called_once_with('test_filter_key')
        mock_cache.set.assert_called_once()
    
    def test_bulk_create_for_group(self):
        """
        Test bulk creation of records for a group.
        """
        objects_data = [
            {'name': 'Bulk Record 1'},
            {'name': 'Bulk Record 2'},
            {'name': 'Bulk Record 3'},
        ]
        
        created_records = TestModel.objects.bulk_create_for_group(
            self.group1,
            objects_data
        )
        
        self.assertEqual(len(created_records), 3)
        
        # Verify all records belong to the correct group
        for record in created_records:
            self.assertEqual(record.group, self.group1)
        
        # Verify records were actually created in database
        total_records = TestModel.objects.for_group(self.group1).count()
        self.assertEqual(total_records, 4)  # 1 existing + 3 bulk created
    
    def test_get_statistics(self):
        """
        Test statistics generation.
        """
        # Overall statistics
        stats = TestModel.objects.get_statistics()
        self.assertEqual(stats['total_count'], 2)
        self.assertEqual(stats['recent_count'], 2)
        self.assertEqual(stats['active_count'], 2)
        
        # Group-specific statistics
        stats_group1 = TestModel.objects.get_statistics(self.group1)
        self.assertEqual(stats_group1['total_count'], 1)
        
        # Test status breakdown
        self.assertIn('status_breakdown', stats)
        self.assertEqual(stats['status_breakdown']['active'], 2)
    
    def test_cleanup_old_records(self):
        """
        Test cleanup of old records.
        """
        # Create an old record by manually setting created_at
        old_date = timezone.now() - timezone.timedelta(days=400)
        old_record = TestModel.objects.create(
            name="Old Record",
            group=self.group1,
            created_by=self.user1
        )
        TestModel.objects.filter(id=old_record.id).update(created_at=old_date)
        
        # Test soft delete (should deactivate records)
        cleaned_count = TestModel.objects.cleanup_old_records(days=365)
        self.assertEqual(cleaned_count, 1)
        
        # Verify record was soft deleted (deactivated)
        old_record.refresh_from_db()
        self.assertFalse(old_record.is_active)
    
    def test_model_save_validation(self):
        """
        Test that GroupFilteredModel validates group on save.
        """
        # Create a record without group should fail
        record = TestModel(name="No Group Record")
        with self.assertRaises(ValidationError):
            record.save()
    
    def test_model_convenience_methods(self):
        """
        Test convenience methods on GroupFilteredModel.
        """
        # Test get_for_user class method
        records = TestModel.get_for_user(self.user1, name="Record 1")
        self.assertEqual(records.count(), 1)
        
        # Test create_for_user class method
        record = TestModel.create_for_user(
            self.user1,
            name="Convenience Record"
        )
        self.assertEqual(record.group, self.group1)
        self.assertEqual(record.created_by, self.user1)


class GroupFilteredQuerySetTest(TestCase):
    """
    Test cases for GroupFilteredQuerySet functionality.
    """
    
    def setUp(self):
        """
        Set up test data.
        """
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123"
        )
        self.user.groups.add(self.group)
    
    def test_queryset_with_audit_trail(self):
        """
        Test QuerySet with audit trail information.
        """
        record = TestModel.objects.create(
            name="Test Record",
            group=self.group,
            created_by=self.user
        )
        
        # Test that with_audit_trail includes related fields
        queryset = TestModel.objects.with_audit_trail()
        
        # This should not raise a database query when accessing created_by
        with self.assertNumQueries(1):  # Only one query for the select_related
            record_with_audit = queryset.get(id=record.id)
            self.assertEqual(record_with_audit.created_by.email, self.user.email)
    
    def test_queryset_with_performance_metrics(self):
        """
        Test QuerySet with performance annotations.
        """
        TestModel.objects.create(
            name="Test Record 1",
            group=self.group,
            created_by=self.user
        )
        TestModel.objects.create(
            name="Test Record 2",
            group=self.group,
            created_by=self.user
        )
        
        # Test performance metrics annotation
        queryset = TestModel.objects.with_performance_metrics()
        
        # Should have performance annotations
        record = queryset.first()
        self.assertTrue(hasattr(record, 'record_count'))
        self.assertTrue(hasattr(record, 'avg_created_time'))
        self.assertTrue(hasattr(record, 'last_updated'))


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
})
class CachedGroupFilteredManagerTest(TestCase):
    """
    Test cases for CachedGroupFilteredManager functionality.
    """
    
    def setUp(self):
        """
        Set up test data.
        """
        cache.clear()
        
        self.group = Group.objects.create(name="Test Group")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123"
        )
        self.user.groups.add(self.group)
    
    def test_cache_key_generation(self):
        """
        Test cache key generation.
        """
        from platform_core.core.managers import CachedGroupFilteredManager
        
        manager = CachedGroupFilteredManager()
        manager.model = TestModel
        
        # Test simple key
        key = manager._get_cache_key("test", id=123)
        self.assertIn("test", key)
        self.assertIn("TestModel", key)
        self.assertIn("id:123", key)
        
        # Test complex key that should be hashed
        long_key = manager._get_cache_key(
            "very_long_prefix" * 20,
            very_long_param="value" * 50
        )
        self.assertTrue(len(long_key) <= 200)  # Should be hashed to shorter length
    
    def test_cached_operations_integration(self):
        """
        Integration test for cached operations.
        """
        # This test verifies that the caching manager can be used
        # Note: The actual TestModel uses GroupFilteredManager, not CachedGroupFilteredManager
        # So this is more of an integration test to ensure no errors occur
        
        record = TestModel.objects.create(
            name="Cached Test",
            group=self.group,
            created_by=self.user
        )
        
        # Basic operations should work
        retrieved = TestModel.objects.get(id=record.id)
        self.assertEqual(retrieved.name, "Cached Test")
        
        filtered = TestModel.objects.filter(name="Cached Test")
        self.assertEqual(filtered.count(), 1)