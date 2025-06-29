"""
Comprehensive test suite for JWT authentication and role-based access control.

Tests JWT token generation, refresh, validation, the 6 role types
(ADMIN, MANAGER, ANALYST, VIEWER, ASSESSOR, PARTNER), group-based 
row-level security, and custom Group model with UUID.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework_simplejwt.exceptions import TokenError

from accounts.models import Group, GroupMembership, GuestAccess
from accounts.serializers import UserSerializer, GroupSerializer
from assessments.models import Assessment, AssessmentStatus
from partners.models import DevelopmentPartner

User = get_user_model()


class UserModelTestCase(TestCase):
    """Test User model and role-based permissions"""
    
    def setUp(self):
        """Set up test users with different roles"""
        self.group = Group.objects.create(name="Test Organization")
        
        # Create users with each role type
        self.roles = {
            'admin': User.Role.ADMIN,
            'portfolio_manager': User.Role.PORTFOLIO_MANAGER,
            'business_analyst': User.Role.BUSINESS_ANALYST,
            'external_partner': User.Role.EXTERNAL_PARTNER,
            'auditor': User.Role.AUDITOR,
            'read_only': User.Role.READ_ONLY
        }
        
        self.users = {}
        for key, role in self.roles.items():
            user = User.objects.create_user(
                username=f"{key}@test.com",
                email=f"{key}@test.com",
                password="testpass123",
                role=role
            )
            GroupMembership.objects.create(user=user, group=self.group)
            self.users[key] = user
    
    def test_user_creation(self):
        """Test user creation with custom fields"""
        user = User.objects.create_user(
            username="newuser@test.com",
            email="newuser@test.com",
            password="securepass123",
            role=User.Role.BUSINESS_ANALYST
        )
        
        self.assertIsInstance(user.id, uuid.UUID)
        self.assertEqual(user.email, "newuser@test.com")
        self.assertEqual(user.role, User.Role.BUSINESS_ANALYST)
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)
    
    def test_role_permissions(self):
        """Test role-based permission properties"""
        # Test can_create_assessments
        self.assertTrue(self.users['admin'].can_create_assessments)
        self.assertTrue(self.users['portfolio_manager'].can_create_assessments)
        self.assertTrue(self.users['business_analyst'].can_create_assessments)
        self.assertFalse(self.users['external_partner'].can_create_assessments)
        self.assertFalse(self.users['auditor'].can_create_assessments)
        self.assertFalse(self.users['read_only'].can_create_assessments)
        
        # Test can_approve_assessments
        self.assertTrue(self.users['admin'].can_approve_assessments)
        self.assertTrue(self.users['portfolio_manager'].can_approve_assessments)
        self.assertFalse(self.users['business_analyst'].can_approve_assessments)
        self.assertFalse(self.users['external_partner'].can_approve_assessments)
        self.assertFalse(self.users['auditor'].can_approve_assessments)
        self.assertFalse(self.users['read_only'].can_approve_assessments)
        
        # Test can_export_data
        self.assertTrue(self.users['admin'].can_export_data)
        self.assertTrue(self.users['portfolio_manager'].can_export_data)
        self.assertTrue(self.users['business_analyst'].can_export_data)
        self.assertFalse(self.users['external_partner'].can_export_data)
        self.assertTrue(self.users['auditor'].can_export_data)
        self.assertFalse(self.users['read_only'].can_export_data)
    
    def test_auth0_integration(self):
        """Test Auth0 sub field for SSO integration"""
        user = User.objects.create_user(
            username="sso@test.com",
            email="sso@test.com",
            password="testpass123",
            auth0_sub="auth0|123456789"
        )
        
        self.assertEqual(user.auth0_sub, "auth0|123456789")
        
        # Test uniqueness constraint
        with self.assertRaises(Exception):
            User.objects.create_user(
                username="duplicate@test.com",
                email="duplicate@test.com",
                password="testpass123",
                auth0_sub="auth0|123456789"  # Same Auth0 ID
            )


class GroupModelTestCase(TestCase):
    """Test Group model with UUID primary key"""
    
    def test_group_creation(self):
        """Test creating groups with UUID"""
        group = Group.objects.create(
            name="Test Company",
            description="A test company for unit tests"
        )
        
        self.assertIsInstance(group.id, uuid.UUID)
        self.assertEqual(group.name, "Test Company")
        self.assertEqual(str(group), "Test Company")
        self.assertIsNotNone(group.created_at)
        self.assertIsNotNone(group.updated_at)
    
    def test_group_membership(self):
        """Test group membership relationships"""
        group = Group.objects.create(name="Member Test Group")
        user = User.objects.create_user(
            username="member@test.com",
            email="member@test.com",
            password="testpass123"
        )
        
        membership = GroupMembership.objects.create(
            user=user,
            group=group,
            is_admin=True
        )
        
        self.assertIsInstance(membership.id, uuid.UUID)
        self.assertTrue(membership.is_admin)
        self.assertEqual(membership.user, user)
        self.assertEqual(membership.group, group)
        self.assertIn(user, group.members.all())
        self.assertIn(group, user.groups.all())
    
    def test_unique_group_membership(self):
        """Test that users can only be in a group once"""
        group = Group.objects.create(name="Unique Test Group")
        user = User.objects.create_user(
            username="unique@test.com",
            email="unique@test.com",
            password="testpass123"
        )
        
        GroupMembership.objects.create(user=user, group=group)
        
        # Try to create duplicate membership
        with self.assertRaises(Exception):
            GroupMembership.objects.create(user=user, group=group)


class JWTAuthenticationTestCase(APITestCase):
    """Test JWT authentication flow"""
    
    def setUp(self):
        """Set up test data"""
        self.group = Group.objects.create(name="JWT Test Company")
        self.user = User.objects.create_user(
            username="jwt@test.com",
            email="jwt@test.com",
            password="testpass123",
            role=User.Role.BUSINESS_ANALYST
        )
        GroupMembership.objects.create(user=self.user, group=self.group)
    
    def test_jwt_token_generation(self):
        """Test JWT token generation for user"""
        refresh = RefreshToken.for_user(self.user)
        access = refresh.access_token
        
        # Verify token claims
        self.assertEqual(access['user_id'], str(self.user.id))
        self.assertEqual(access['email'], self.user.email)
        self.assertEqual(access['role'], self.user.role)
        
        # Verify token types
        self.assertEqual(refresh['token_type'], 'refresh')
        self.assertEqual(access['token_type'], 'access')
    
    def test_login_endpoint(self):
        """Test login endpoint returns JWT tokens"""
        data = {
            "email": "jwt@test.com",
            "password": "testpass123"
        }
        
        response = self.client.post('/api/auth/login/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertIn('user', response.data)
        
        # Verify user data
        self.assertEqual(response.data['user']['email'], self.user.email)
        self.assertEqual(response.data['user']['role'], self.user.role)
    
    def test_invalid_login(self):
        """Test login with invalid credentials"""
        data = {
            "email": "jwt@test.com",
            "password": "wrongpassword"
        }
        
        response = self.client.post('/api/auth/login/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_token_refresh(self):
        """Test JWT token refresh"""
        refresh = RefreshToken.for_user(self.user)
        
        data = {
            "refresh": str(refresh)
        }
        
        response = self.client.post('/api/auth/refresh/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        
        # Verify new access token is different
        self.assertNotEqual(str(refresh.access_token), response.data['access'])
    
    def test_authenticated_request(self):
        """Test making authenticated API request"""
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        
        response = self.client.get('/api/users/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.user.email)
    
    def test_expired_token(self):
        """Test handling of expired tokens"""
        # Create a token that's already expired
        refresh = RefreshToken.for_user(self.user)
        access = refresh.access_token
        
        # Manually set expiration to past
        access.set_exp(lifetime=timedelta(seconds=-1))
        
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(access)}')
        
        response = self.client.get('/api/users/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_invalid_token(self):
        """Test handling of invalid tokens"""
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid-token-here')
        
        response = self.client.get('/api/users/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_missing_token(self):
        """Test protected endpoints without token"""
        response = self.client.get('/api/users/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class MultiTenancyTestCase(TransactionTestCase):
    """Test group-based multi-tenancy and row-level security"""
    
    def setUp(self):
        """Set up test data for multi-tenancy testing"""
        # Create two separate groups
        self.group1 = Group.objects.create(name="Company Alpha")
        self.group2 = Group.objects.create(name="Company Beta")
        
        # Create users in each group
        self.user1 = User.objects.create_user(
            username="alpha@test.com",
            email="alpha@test.com",
            password="testpass123",
            role=User.Role.ADMIN
        )
        self.user2 = User.objects.create_user(
            username="beta@test.com",
            email="beta@test.com",
            password="testpass123",
            role=User.Role.ADMIN
        )
        
        GroupMembership.objects.create(user=self.user1, group=self.group1)
        GroupMembership.objects.create(user=self.user2, group=self.group2)
        
        # Create partners in each group
        self.partner1 = DevelopmentPartner.objects.create(
            name="Alpha Partner",
            email="partner@alpha.com",
            group=self.group1,
            created_by=self.user1
        )
        self.partner2 = DevelopmentPartner.objects.create(
            name="Beta Partner",
            email="partner@beta.com",
            group=self.group2,
            created_by=self.user2
        )
        
        # Create assessments in each group
        self.assessment1 = Assessment.objects.create(
            partner=self.partner1,
            assessment_date=timezone.now(),
            group=self.group1,
            created_by=self.user1
        )
        self.assessment2 = Assessment.objects.create(
            partner=self.partner2,
            assessment_date=timezone.now(),
            group=self.group2,
            created_by=self.user2
        )
    
    def test_group_filtered_queryset(self):
        """Test that querysets are automatically filtered by group"""
        # Set current user context for group filtering
        from assessments.middleware import set_current_user
        
        # User 1 should only see their group's data
        set_current_user(self.user1)
        
        partners = DevelopmentPartner.objects.all()
        self.assertEqual(partners.count(), 1)
        self.assertEqual(partners.first(), self.partner1)
        
        assessments = Assessment.objects.all()
        self.assertEqual(assessments.count(), 1)
        self.assertEqual(assessments.first(), self.assessment1)
        
        # User 2 should only see their group's data
        set_current_user(self.user2)
        
        partners = DevelopmentPartner.objects.all()
        self.assertEqual(partners.count(), 1)
        self.assertEqual(partners.first(), self.partner2)
        
        assessments = Assessment.objects.all()
        self.assertEqual(assessments.count(), 1)
        self.assertEqual(assessments.first(), self.assessment2)
    
    def test_api_multi_tenancy(self):
        """Test API-level multi-tenancy enforcement"""
        # Get tokens for both users
        token1 = str(RefreshToken.for_user(self.user1).access_token)
        token2 = str(RefreshToken.for_user(self.user2).access_token)
        
        # User 1 accessing partners
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token1}')
        response = self.client.get('/api/partners/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], "Alpha Partner")
        
        # User 2 accessing partners
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token2}')
        response = self.client.get('/api/partners/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], "Beta Partner")
    
    def test_cross_tenant_access_prevention(self):
        """Test that users cannot access other tenant's data"""
        token1 = str(RefreshToken.for_user(self.user1).access_token)
        
        # User 1 trying to access User 2's assessment
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token1}')
        response = self.client.get(f'/api/assessments/{self.assessment2.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        # User 1 trying to update User 2's partner
        response = self.client.patch(
            f'/api/partners/{self.partner2.id}/',
            {"name": "Hacked Partner"},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_multi_group_membership(self):
        """Test users with membership in multiple groups"""
        # Create a shared group
        shared_group = Group.objects.create(name="Shared Group")
        
        # Add both users to shared group
        GroupMembership.objects.create(user=self.user1, group=shared_group)
        GroupMembership.objects.create(user=self.user2, group=shared_group)
        
        # Create data in shared group
        shared_partner = DevelopmentPartner.objects.create(
            name="Shared Partner",
            email="partner@shared.com",
            group=shared_group,
            created_by=self.user1
        )
        
        # Both users should be able to see shared data
        token1 = str(RefreshToken.for_user(self.user1).access_token)
        token2 = str(RefreshToken.for_user(self.user2).access_token)
        
        # User 1 can see data from both groups
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token1}')
        response = self.client.get('/api/partners/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        partner_names = [p['name'] for p in response.data['results']]
        self.assertIn("Alpha Partner", partner_names)
        self.assertIn("Shared Partner", partner_names)
        
        # User 2 can see data from both groups
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token2}')
        response = self.client.get('/api/partners/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        partner_names = [p['name'] for p in response.data['results']]
        self.assertIn("Beta Partner", partner_names)
        self.assertIn("Shared Partner", partner_names)


class GuestAccessTestCase(APITestCase):
    """Test guest access functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.group = Group.objects.create(name="Guest Test Company")
        self.user = User.objects.create_user(
            username="guest@test.com",
            email="guest@test.com",
            password="testpass123",
            role=User.Role.PORTFOLIO_MANAGER
        )
        GroupMembership.objects.create(user=self.user, group=self.group)
        
        # Create test data
        self.partner = DevelopmentPartner.objects.create(
            name="Guest Test Partner",
            email="partner@guest.com",
            group=self.group,
            created_by=self.user
        )
        self.assessment = Assessment.objects.create(
            partner=self.partner,
            assessment_date=timezone.now(),
            group=self.group,
            created_by=self.user
        )
    
    def test_create_guest_access(self):
        """Test creating guest access tokens"""
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        data = {
            "assessment": str(self.assessment.id),
            "expires_in_days": 7
        }
        
        response = self.client.post('/api/guest-access/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertIn('expires_at', response.data)
        
        # Verify guest access was created
        guest_access = GuestAccess.objects.get(token=response.data['token'])
        self.assertEqual(guest_access.assessment, self.assessment)
        self.assertEqual(guest_access.created_by, self.user)
        self.assertTrue(guest_access.is_active)
    
    def test_access_with_guest_token(self):
        """Test accessing assessment with guest token"""
        # Create guest access
        expires_at = timezone.now() + timedelta(days=7)
        guest_access = GuestAccess.objects.create(
            token="test-guest-token",
            assessment=self.assessment,
            created_by=self.user,
            expires_at=expires_at
        )
        
        # Access assessment with guest token
        response = self.client.get(
            f'/api/assessments/{self.assessment.id}/guest/',
            HTTP_AUTHORIZATION=f'Bearer {guest_access.token}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.assessment.id))
        
        # Verify access count was incremented
        guest_access.refresh_from_db()
        self.assertEqual(guest_access.accessed_count, 1)
        self.assertIsNotNone(guest_access.last_accessed_at)
    
    def test_expired_guest_token(self):
        """Test that expired guest tokens are rejected"""
        # Create expired guest access
        expires_at = timezone.now() - timedelta(days=1)
        guest_access = GuestAccess.objects.create(
            token="expired-guest-token",
            assessment=self.assessment,
            created_by=self.user,
            expires_at=expires_at
        )
        
        # Try to access with expired token
        response = self.client.get(
            f'/api/assessments/{self.assessment.id}/guest/',
            HTTP_AUTHORIZATION=f'Bearer {guest_access.token}'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_deactivated_guest_token(self):
        """Test that deactivated guest tokens are rejected"""
        # Create deactivated guest access
        expires_at = timezone.now() + timedelta(days=7)
        guest_access = GuestAccess.objects.create(
            token="deactivated-guest-token",
            assessment=self.assessment,
            created_by=self.user,
            expires_at=expires_at,
            is_active=False
        )
        
        # Try to access with deactivated token
        response = self.client.get(
            f'/api/assessments/{self.assessment.id}/guest/',
            HTTP_AUTHORIZATION=f'Bearer {guest_access.token}'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class RoleBasedAPIAccessTestCase(APITestCase):
    """Test role-based API access control"""
    
    def setUp(self):
        """Set up users with different roles"""
        self.group = Group.objects.create(name="Role Test Company")
        
        # Create users with each role
        self.users = {}
        self.tokens = {}
        
        roles = [
            ('admin', User.Role.ADMIN),
            ('portfolio_manager', User.Role.PORTFOLIO_MANAGER),
            ('business_analyst', User.Role.BUSINESS_ANALYST),
            ('external_partner', User.Role.EXTERNAL_PARTNER),
            ('auditor', User.Role.AUDITOR),
            ('read_only', User.Role.READ_ONLY)
        ]
        
        for key, role in roles:
            user = User.objects.create_user(
                username=f"{key}@roletest.com",
                email=f"{key}@roletest.com",
                password="testpass123",
                role=role
            )
            GroupMembership.objects.create(user=user, group=self.group)
            self.users[key] = user
            self.tokens[key] = str(RefreshToken.for_user(user).access_token)
        
        # Create test data
        self.partner = DevelopmentPartner.objects.create(
            name="Role Test Partner",
            email="partner@roletest.com",
            group=self.group,
            created_by=self.users['admin']
        )
    
    def test_assessment_creation_permissions(self):
        """Test who can create assessments"""
        assessment_data = {
            "partner": str(self.partner.id),
            "assessment_date": timezone.now().isoformat()
        }
        
        # Roles that can create assessments
        allowed_roles = ['admin', 'portfolio_manager', 'business_analyst']
        
        for role, token in self.tokens.items():
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
            response = self.client.post('/api/assessments/', assessment_data, format='json')
            
            if role in allowed_roles:
                self.assertEqual(
                    response.status_code, 
                    status.HTTP_201_CREATED,
                    f"{role} should be able to create assessments"
                )
            else:
                self.assertEqual(
                    response.status_code, 
                    status.HTTP_403_FORBIDDEN,
                    f"{role} should not be able to create assessments"
                )
    
    def test_assessment_approval_permissions(self):
        """Test who can approve assessments"""
        # Create an assessment
        assessment = Assessment.objects.create(
            partner=self.partner,
            assessment_date=timezone.now(),
            status=AssessmentStatus.SUBMITTED,
            group=self.group,
            created_by=self.users['business_analyst']
        )
        
        # Roles that can approve assessments
        allowed_roles = ['admin', 'portfolio_manager']
        
        for role, token in self.tokens.items():
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
            response = self.client.post(f'/api/assessments/{assessment.id}/approve/')
            
            if role in allowed_roles:
                self.assertIn(
                    response.status_code,
                    [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST],  # 400 if already approved
                    f"{role} should be able to approve assessments"
                )
            else:
                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"{role} should not be able to approve assessments"
                )
    
    def test_data_export_permissions(self):
        """Test who can export data"""
        # Create an assessment for export
        assessment = Assessment.objects.create(
            partner=self.partner,
            assessment_date=timezone.now(),
            group=self.group,
            created_by=self.users['admin']
        )
        
        # Roles that can export data
        allowed_roles = ['admin', 'portfolio_manager', 'business_analyst', 'auditor']
        
        for role, token in self.tokens.items():
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
            response = self.client.get(f'/api/assessments/{assessment.id}/export/')
            
            if role in allowed_roles:
                self.assertEqual(
                    response.status_code,
                    status.HTTP_200_OK,
                    f"{role} should be able to export data"
                )
            else:
                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"{role} should not be able to export data"
                )
    
    def test_read_only_access(self):
        """Test read-only users can only read data"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.tokens["read_only"]}')
        
        # Should be able to read
        response = self.client.get('/api/partners/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Should not be able to create
        response = self.client.post('/api/partners/', {"name": "New Partner", "email": "new@test.com"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Should not be able to update
        response = self.client.patch(f'/api/partners/{self.partner.id}/', {"name": "Updated"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Should not be able to delete
        response = self.client.delete(f'/api/partners/{self.partner.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)