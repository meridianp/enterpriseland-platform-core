"""
Tests for accounts app serializers.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory
from rest_framework.request import Request

from accounts.serializers import (
    UserSerializer, UserCreateSerializer, GroupSerializer,
    GroupMembershipSerializer, LoginSerializer, GuestAccessSerializer
)
from accounts.models import Group, GroupMembership
from tests.base import BaseTestCase

User = get_user_model()


class UserSerializerTest(BaseTestCase):
    """Test UserSerializer."""
    
    def test_serialize_user(self):
        """Test serializing user data."""
        user = User.objects.create_user(
            username='testser',
            email='test@serialize.com',
            first_name='Test',
            last_name='User',
            role=User.Role.BUSINESS_ANALYST
        )
        GroupMembership.objects.create(user=user, group=self.group)
        
        serializer = UserSerializer(user)
        data = serializer.data
        
        self.assertEqual(data['username'], 'testser')
        self.assertEqual(data['email'], 'test@serialize.com')
        self.assertEqual(data['first_name'], 'Test')
        self.assertEqual(data['last_name'], 'User')
        self.assertEqual(data['role'], User.Role.BUSINESS_ANALYST)
        self.assertIn('groups', data)
        self.assertIn('created_at', data)
    
    def test_read_only_fields(self):
        """Test that certain fields are read-only."""
        serializer = UserSerializer()
        read_only_fields = serializer.Meta.read_only_fields
        
        self.assertIn('id', read_only_fields)
        self.assertIn('created_at', read_only_fields)
        self.assertIn('last_login_at', read_only_fields)


class UserCreateSerializerTest(BaseTestCase):
    """Test UserCreateSerializer."""
    
    def test_create_user_valid_data(self):
        """Test creating user with valid data."""
        data = {
            'username': 'newuser',
            'email': 'new@user.com',
            'first_name': 'New',
            'last_name': 'User',
            'role': User.Role.READ_ONLY,
            'password': 'securepass123',
            'password_confirm': 'securepass123'
        }
        
        serializer = UserCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        user = serializer.save()
        self.assertEqual(user.username, 'newuser')
        self.assertEqual(user.email, 'new@user.com')
        self.assertTrue(user.check_password('securepass123'))
    
    def test_password_mismatch(self):
        """Test validation error when passwords don't match."""
        data = {
            'username': 'newuser2',
            'email': 'new2@user.com',
            'password': 'securepass123',
            'password_confirm': 'differentpass'
        }
        
        serializer = UserCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("Passwords don't match", str(serializer.errors))
    
    def test_password_not_in_response(self):
        """Test that password fields are write-only."""
        data = {
            'username': 'newuser3',
            'email': 'new3@user.com',
            'first_name': 'New',
            'last_name': 'User',
            'role': User.Role.READ_ONLY,
            'password': 'securepass123',
            'password_confirm': 'securepass123'
        }
        
        serializer = UserCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        user = serializer.save()
        
        # Serialize the created user
        serialized_data = UserCreateSerializer(user).data
        self.assertNotIn('password', serialized_data)
        self.assertNotIn('password_confirm', serialized_data)


class GroupSerializerTest(BaseTestCase):
    """Test GroupSerializer."""
    
    def test_serialize_group(self):
        """Test serializing group data."""
        group = Group.objects.create(
            name='Test Group',
            description='A test group'
        )
        
        # Add some members
        user1 = User.objects.create_user(username='member1', email='member1@test.com')
        user2 = User.objects.create_user(username='member2', email='member2@test.com')
        GroupMembership.objects.create(user=user1, group=group)
        GroupMembership.objects.create(user=user2, group=group)
        
        serializer = GroupSerializer(group)
        data = serializer.data
        
        self.assertEqual(data['name'], 'Test Group')
        self.assertEqual(data['description'], 'A test group')
        self.assertEqual(data['member_count'], 2)
        self.assertIn('created_at', data)


class GroupMembershipSerializerTest(BaseTestCase):
    """Test GroupMembershipSerializer."""
    
    def test_serialize_membership(self):
        """Test serializing group membership."""
        user = User.objects.create_user(
            username='membertest',
            email='member@test.com',
            first_name='Member',
            last_name='Test'
        )
        group = Group.objects.create(name='Member Group')
        membership = GroupMembership.objects.create(
            user=user,
            group=group,
            is_admin=True
        )
        
        serializer = GroupMembershipSerializer(membership)
        data = serializer.data
        
        self.assertEqual(data['user'], user.id)
        self.assertEqual(data['group'], group.id)
        self.assertEqual(data['user_email'], 'member@test.com')
        self.assertEqual(data['user_name'], 'Member Test')
        self.assertEqual(data['group_name'], 'Member Group')
        self.assertTrue(data['is_admin'])
        self.assertIn('joined_at', data)


class LoginSerializerTest(BaseTestCase):
    """Test LoginSerializer."""
    
    def test_valid_login(self):
        """Test validation with valid credentials."""
        user = User.objects.create_user(
            username='logintest',
            email='login@test.com',
            password='testpass123'
        )
        
        data = {
            'email': 'login@test.com',
            'password': 'testpass123'
        }
        
        serializer = LoginSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['user'], user)
    
    def test_invalid_credentials(self):
        """Test validation with invalid credentials."""
        User.objects.create_user(
            username='logintest2',
            email='login2@test.com',
            password='testpass123'
        )
        
        data = {
            'email': 'login2@test.com',
            'password': 'wrongpassword'
        }
        
        serializer = LoginSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('Invalid credentials', str(serializer.errors))
    
    def test_inactive_user(self):
        """Test validation with inactive user."""
        user = User.objects.create_user(
            username='inactive',
            email='inactive@test.com',
            password='testpass123'
        )
        user.is_active = False
        user.save()
        
        data = {
            'email': 'inactive@test.com',
            'password': 'testpass123'
        }
        
        serializer = LoginSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        # The actual error message might be different
        errors_str = str(serializer.errors)
        self.assertTrue('Invalid credentials' in errors_str or 'User account is disabled' in errors_str)
    
    def test_missing_fields(self):
        """Test validation with missing fields."""
        # Missing password
        data = {'email': 'test@test.com'}
        serializer = LoginSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        # Missing email
        data = {'password': 'testpass123'}
        serializer = LoginSerializer(data=data)
        self.assertFalse(serializer.is_valid())