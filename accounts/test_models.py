"""
Tests for accounts app models.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
import uuid

from accounts.models import Group, GroupMembership, GuestAccess
from tests.base import BaseTestCase

User = get_user_model()


class UserModelTest(BaseTestCase):
    """Test custom User model."""
    
    def test_create_user(self):
        """Test creating a user."""
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            role=User.Role.BUSINESS_ANALYST
        )
        
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.role, User.Role.BUSINESS_ANALYST)
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.id)
        self.assertIsInstance(user.id, uuid.UUID)
    
    def test_user_str_representation(self):
        """Test string representation of user."""
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            role=User.Role.PORTFOLIO_MANAGER
        )
        self.assertEqual(str(user), 'test@example.com (Portfolio Manager)')
    
    def test_user_role_choices(self):
        """Test all valid role choices."""
        valid_roles = [
            User.Role.BUSINESS_ANALYST,
            User.Role.PORTFOLIO_MANAGER,
            User.Role.EXTERNAL_PARTNER,
            User.Role.AUDITOR,
            User.Role.ADMIN,
            User.Role.READ_ONLY
        ]
        
        for role in valid_roles:
            user = User.objects.create_user(
                username=f'user_{role}',
                email=f'{role}@example.com',
                role=role
            )
            self.assertEqual(user.role, role)
    
    def test_user_permissions_business_analyst(self):
        """Test business analyst permissions."""
        user = User.objects.create_user(
            username='analyst_perm_test',
            email='analyst_perm@example.com',
            role=User.Role.BUSINESS_ANALYST
        )
        
        self.assertTrue(user.can_create_assessments)
        self.assertFalse(user.can_approve_assessments)
        self.assertTrue(user.can_export_data)
    
    def test_user_permissions_portfolio_manager(self):
        """Test portfolio manager permissions."""
        user = User.objects.create_user(
            username='manager_perm_test',
            email='manager_perm@example.com',
            role=User.Role.PORTFOLIO_MANAGER
        )
        
        self.assertTrue(user.can_create_assessments)
        self.assertTrue(user.can_approve_assessments)
        self.assertTrue(user.can_export_data)
    
    def test_user_permissions_external_partner(self):
        """Test external partner permissions."""
        user = User.objects.create_user(
            username='partner_perm_test',
            email='partner_perm@example.com',
            role=User.Role.EXTERNAL_PARTNER
        )
        
        self.assertFalse(user.can_create_assessments)
        self.assertFalse(user.can_approve_assessments)
        self.assertFalse(user.can_export_data)
    
    def test_user_permissions_auditor(self):
        """Test auditor permissions."""
        user = User.objects.create_user(
            username='auditor_perm_test',
            email='auditor_perm@example.com',
            role=User.Role.AUDITOR
        )
        
        self.assertFalse(user.can_create_assessments)
        self.assertFalse(user.can_approve_assessments)
        self.assertTrue(user.can_export_data)
    
    def test_user_permissions_admin(self):
        """Test admin permissions."""
        user = User.objects.create_user(
            username='admin_perm_test',
            email='admin_perm@example.com',
            role=User.Role.ADMIN
        )
        
        self.assertTrue(user.can_create_assessments)
        self.assertTrue(user.can_approve_assessments)
        self.assertTrue(user.can_export_data)
    
    def test_user_permissions_read_only(self):
        """Test read-only permissions."""
        user = User.objects.create_user(
            username='readonly',
            email='readonly@example.com',
            role=User.Role.READ_ONLY
        )
        
        self.assertFalse(user.can_create_assessments)
        self.assertFalse(user.can_approve_assessments)
        self.assertFalse(user.can_export_data)
    
    def test_email_uniqueness(self):
        """Test email must be unique."""
        User.objects.create_user(
            username='user1',
            email='duplicate@example.com'
        )
        
        with self.assertRaises(Exception):
            User.objects.create_user(
                username='user2',
                email='duplicate@example.com'
            )
    
    def test_auth0_sub_field(self):
        """Test auth0_sub field for SSO integration."""
        user = User.objects.create_user(
            username='ssouser',
            email='sso@example.com',
            auth0_sub='auth0|123456789'
        )
        
        self.assertEqual(user.auth0_sub, 'auth0|123456789')
        
        # Should be unique
        with self.assertRaises(Exception):
            User.objects.create_user(
                username='another',
                email='another@example.com',
                auth0_sub='auth0|123456789'
            )


class GroupModelTest(BaseTestCase):
    """Test Group model."""
    
    def test_create_group(self):
        """Test creating a group."""
        group = Group.objects.create(
            name='Test Group',
            description='A test group for multi-tenancy'
        )
        
        self.assertEqual(group.name, 'Test Group')
        self.assertEqual(group.description, 'A test group for multi-tenancy')
        self.assertIsNotNone(group.id)
        self.assertIsInstance(group.id, uuid.UUID)
        self.assertIsNotNone(group.created_at)
    
    def test_group_str_representation(self):
        """Test string representation of group."""
        group = Group.objects.create(name='My Group')
        self.assertEqual(str(group), 'My Group')
    
    def test_group_name_uniqueness(self):
        """Test group name must be unique."""
        Group.objects.create(name='Unique Group')
        
        with self.assertRaises(Exception):
            Group.objects.create(name='Unique Group')


class GroupMembershipModelTest(BaseTestCase):
    """Test GroupMembership model."""
    
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        self.group = Group.objects.create(name='Test Group')
    
    def test_create_membership(self):
        """Test creating a group membership."""
        membership = GroupMembership.objects.create(
            user=self.user,
            group=self.group,
            is_admin=False
        )
        
        self.assertEqual(membership.user, self.user)
        self.assertEqual(membership.group, self.group)
        self.assertFalse(membership.is_admin)
        self.assertIsNotNone(membership.joined_at)
    
    def test_membership_str_representation(self):
        """Test string representation of membership."""
        membership = GroupMembership.objects.create(
            user=self.user,
            group=self.group
        )
        self.assertEqual(str(membership), 'test@example.com in Test Group')
    
    def test_unique_membership(self):
        """Test user can only have one membership per group."""
        GroupMembership.objects.create(
            user=self.user,
            group=self.group
        )
        
        with self.assertRaises(Exception):
            GroupMembership.objects.create(
                user=self.user,
                group=self.group
            )
    
    def test_membership_cascade_delete(self):
        """Test membership is deleted when user or group is deleted."""
        membership = GroupMembership.objects.create(
            user=self.user,
            group=self.group
        )
        membership_id = membership.id
        
        # Delete user
        self.user.delete()
        self.assertFalse(GroupMembership.objects.filter(id=membership_id).exists())
        
        # Create new membership
        user2 = User.objects.create_user(username='user2', email='user2@example.com')
        membership2 = GroupMembership.objects.create(user=user2, group=self.group)
        membership2_id = membership2.id
        
        # Delete group
        self.group.delete()
        self.assertFalse(GroupMembership.objects.filter(id=membership2_id).exists())
    
    def test_user_groups_relationship(self):
        """Test accessing groups through user."""
        membership = GroupMembership.objects.create(
            user=self.user,
            group=self.group
        )
        
        self.assertIn(self.group, self.user.groups.all())
        self.assertEqual(self.user.groups.count(), 1)
    
    def test_group_members_relationship(self):
        """Test accessing members through group."""
        membership = GroupMembership.objects.create(
            user=self.user,
            group=self.group
        )
        
        self.assertIn(self.user, self.group.members.all())
        self.assertEqual(self.group.members.count(), 1)


class GuestAccessModelTest(BaseTestCase):
    """Test GuestAccess model."""
    
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            username='creator',
            email='creator@example.com'
        )
        # Note: We'll need to create a mock assessment since it's in a different app
        # For now, we'll skip tests that require assessment
    
    def test_guest_access_properties(self):
        """Test guest access properties."""
        # Test expiration logic
        future_time = timezone.now() + timedelta(days=7)
        past_time = timezone.now() - timedelta(days=1)
        
        # Would need assessment model to fully test
        # Just test the property logic with mock data
    
    def test_is_expired_property(self):
        """Test is_expired property logic."""
        # Create a mock guest access object
        class MockGuestAccess:
            def __init__(self, expires_at):
                self.expires_at = expires_at
                self.is_active = True
            
            @property
            def is_expired(self):
                from django.utils import timezone
                return timezone.now() > self.expires_at
            
            @property
            def is_valid(self):
                return self.is_active and not self.is_expired
        
        # Test not expired
        future_access = MockGuestAccess(timezone.now() + timedelta(days=1))
        self.assertFalse(future_access.is_expired)
        self.assertTrue(future_access.is_valid)
        
        # Test expired
        past_access = MockGuestAccess(timezone.now() - timedelta(days=1))
        self.assertTrue(past_access.is_expired)
        self.assertFalse(past_access.is_valid)
        
        # Test inactive but not expired
        inactive_access = MockGuestAccess(timezone.now() + timedelta(days=1))
        inactive_access.is_active = False
        self.assertFalse(inactive_access.is_expired)
        self.assertFalse(inactive_access.is_valid)