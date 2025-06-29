"""
Comprehensive tests for the unified authentication system
"""
import json
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.cache import cache
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User, MFAMethod, MFABackupCode, SecurityEvent, LoginAttempt, UserDevice
from accounts.services import auth_service


class UnifiedAuthenticationTestCase(TestCase):
    """Test unified authentication system"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            password='testpass123',
            role=User.Role.BUSINESS_ANALYST
        )
        cache.clear()
    
    def tearDown(self):
        cache.clear()
    
    def test_jwt_login_success(self):
        """Test successful JWT login without MFA"""
        response = self.client.post(
            reverse('auth_login'),
            data=json.dumps({
                'email': 'test@example.com',
                'password': 'testpass123',
                'use_cookies': False
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('access', data)
        self.assertIn('refresh', data)
        self.assertIn('user', data)
        self.assertEqual(data['user']['email'], 'test@example.com')
        
        # Check that login attempt was logged
        self.assertTrue(LoginAttempt.objects.filter(
            email='test@example.com',
            success=True
        ).exists())
        
        # Check security event
        self.assertTrue(SecurityEvent.objects.filter(
            user=self.user,
            event_type=SecurityEvent.EventType.LOGIN_SUCCESS
        ).exists())
    
    def test_cookie_login_success(self):
        """Test successful cookie-based login"""
        response = self.client.post(
            reverse('auth_login'),
            data=json.dumps({
                'email': 'test@example.com',
                'password': 'testpass123',
                'use_cookies': True
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Tokens should not be in response body for cookie mode
        self.assertNotIn('access', data)
        self.assertNotIn('refresh', data)
        self.assertIn('user', data)
        
        # Check cookies
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)
        self.assertIn('csrftoken', response.cookies)
        
        # Verify cookie settings
        access_cookie = response.cookies['access_token']
        self.assertTrue(access_cookie['httponly'])
        self.assertEqual(access_cookie['samesite'], 'Lax')
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = self.client.post(
            reverse('auth_login'),
            data=json.dumps({
                'email': 'test@example.com',
                'password': 'wrongpass'
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 401)
        
        # Check failed login attempt was logged
        self.assertTrue(LoginAttempt.objects.filter(
            email='test@example.com',
            success=False,
            failure_reason='Invalid credentials'
        ).exists())
    
    def test_login_with_mfa_required(self):
        """Test login when MFA is enabled"""
        # Enable MFA for user
        MFAMethod.objects.create(
            user=self.user,
            method=MFAMethod.Method.TOTP,
            secret='TESTSECRET123',
            verified_at=timezone.now(),
            is_primary=True
        )
        
        response = self.client.post(
            reverse('auth_login'),
            data=json.dumps({
                'email': 'test@example.com',
                'password': 'testpass123'
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Should indicate MFA is required
        self.assertTrue(data['mfa_required'])
        self.assertEqual(data['user_id'], str(self.user.id))
        self.assertIn('totp', data['methods'])
        
        # Should not have tokens yet
        self.assertNotIn('access', data)
        self.assertNotIn('refresh', data)
    
    def test_token_refresh_jwt(self):
        """Test JWT token refresh"""
        # Get initial tokens
        refresh = RefreshToken.for_user(self.user)
        
        response = self.client.post(
            reverse('auth_refresh'),
            data=json.dumps({
                'refresh': str(refresh)
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('access', data)
        self.assertIn('access_expires_at', data)
    
    def test_token_refresh_cookie(self):
        """Test cookie-based token refresh"""
        # Set refresh token in cookie
        refresh = RefreshToken.for_user(self.user)
        self.client.cookies['refresh_token'] = str(refresh)
        
        response = self.client.post(
            reverse('auth_refresh'),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_token', response.cookies)
    
    def test_logout(self):
        """Test logout functionality"""
        # Get tokens
        refresh = RefreshToken.for_user(self.user)
        
        # Login first
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {refresh.access_token}'
        
        response = self.client.post(
            reverse('auth_logout'),
            data=json.dumps({
                'refresh': str(refresh)
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Check security event
        self.assertTrue(SecurityEvent.objects.filter(
            user=self.user,
            event_type=SecurityEvent.EventType.LOGOUT
        ).exists())
    
    def test_verify_token(self):
        """Test token verification"""
        # Get token
        refresh = RefreshToken.for_user(self.user)
        
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {refresh.access_token}'
        
        response = self.client.get(reverse('auth_verify'))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['user']['email'], 'test@example.com')
    
    def test_device_tracking(self):
        """Test device tracking functionality"""
        # Mock request
        request = MagicMock()
        request.META = {
            'HTTP_USER_AGENT': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)',
            'REMOTE_ADDR': '192.168.1.100',
            'HTTP_CF_IPCOUNTRY': 'US',
            'HTTP_CF_IPCITY': 'New York'
        }
        
        device_id = auth_service.device_tracker.get_device_id(request)
        device = auth_service.device_tracker.track_device(str(self.user.id), device_id, request)
        
        self.assertIsNotNone(device)
        self.assertEqual(device.user, self.user)
        self.assertEqual(device.device_type, 'mobile')
        self.assertEqual(device.ip_address, '192.168.1.100')
        self.assertEqual(device.country, 'US')
    
    def test_suspicious_activity_detection(self):
        """Test detection of suspicious login activity"""
        # Create multiple failed login attempts
        for i in range(6):
            LoginAttempt.objects.create(
                email=self.user.email,
                ip_address='192.168.1.100',
                user_agent='Test Agent',
                success=False,
                failure_reason='Invalid credentials'
            )
        
        request = MagicMock()
        request.META = {'REMOTE_ADDR': '192.168.1.100', 'HTTP_USER_AGENT': 'Test Agent'}
        
        is_suspicious = auth_service.check_suspicious_activity(self.user, request)
        
        self.assertTrue(is_suspicious)
        
        # Check security event was created
        self.assertTrue(SecurityEvent.objects.filter(
            user=self.user,
            event_type=SecurityEvent.EventType.SUSPICIOUS_ACTIVITY
        ).exists())
    
    def test_rate_limiting(self):
        """Test authentication rate limiting"""
        # Make multiple login attempts
        for i in range(11):  # AuthenticationThrottle allows 10/hour
            response = self.client.post(
                reverse('auth_login'),
                data=json.dumps({
                    'email': f'test{i}@example.com',
                    'password': 'wrongpass'
                }),
                content_type='application/json'
            )
            
            if i < 10:
                self.assertIn(response.status_code, [401, 400])
            else:
                # 11th request should be throttled
                self.assertEqual(response.status_code, 429)


class MFATestCase(TestCase):
    """Test Multi-Factor Authentication functionality"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='mfa@example.com',
            username='mfauser',
            password='mfapass123'
        )
        # Get auth token
        self.refresh = RefreshToken.for_user(self.user)
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {self.refresh.access_token}'
        cache.clear()
    
    def tearDown(self):
        cache.clear()
    
    def test_mfa_status_not_enabled(self):
        """Test MFA status when not enabled"""
        response = self.client.get(reverse('mfa_status'))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['mfa_enabled'])
        self.assertEqual(data['methods'], [])
    
    @patch('accounts.mfa_views.pyotp.random_base32')
    def test_setup_totp(self, mock_random):
        """Test TOTP setup"""
        mock_random.return_value = 'TESTSECRET123456'
        
        response = self.client.post(reverse('setup_totp'))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['secret'], 'TESTSECRET123456')
        self.assertIn('qr_code', data)
        self.assertIn('manual_entry_uri', data)
        
        # Check secret is cached
        cache_key = f"mfa_setup:{self.user.id}:totp"
        self.assertEqual(cache.get(cache_key), 'TESTSECRET123456')
    
    @patch('accounts.mfa_views.pyotp.TOTP')
    def test_verify_totp_setup(self, mock_totp_class):
        """Test TOTP verification during setup"""
        # Setup
        cache_key = f"mfa_setup:{self.user.id}:totp"
        cache.set(cache_key, 'TESTSECRET123456', timeout=600)
        
        # Mock TOTP verification
        mock_totp = MagicMock()
        mock_totp.verify.return_value = True
        mock_totp_class.return_value = mock_totp
        
        response = self.client.post(
            reverse('verify_totp_setup'),
            data=json.dumps({'code': '123456'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('backup_codes', data)
        self.assertEqual(len(data['backup_codes']), 10)
        
        # Check MFA method was created
        self.assertTrue(MFAMethod.objects.filter(
            user=self.user,
            method=MFAMethod.Method.TOTP
        ).exists())
        
        # Check backup codes were created
        self.assertEqual(MFABackupCode.objects.filter(user=self.user).count(), 10)
        
        # Check security event
        self.assertTrue(SecurityEvent.objects.filter(
            user=self.user,
            event_type=SecurityEvent.EventType.MFA_ENABLED
        ).exists())
    
    @patch('accounts.mfa_views.pyotp.TOTP')
    def test_verify_mfa_during_login(self, mock_totp_class):
        """Test MFA verification during login"""
        # Create MFA method
        mfa_method = MFAMethod.objects.create(
            user=self.user,
            method=MFAMethod.Method.TOTP,
            secret='TESTSECRET123456',
            verified_at=timezone.now()
        )
        
        # Mock TOTP verification
        mock_totp = MagicMock()
        mock_totp.verify.return_value = True
        mock_totp_class.return_value = mock_totp
        
        response = self.client.post(
            reverse('verify_mfa'),
            data=json.dumps({
                'user_id': str(self.user.id),
                'code': '123456',
                'method': 'totp'
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['verified'])
        self.assertIn('session_token', data)
        
        # Check MFA method was updated
        mfa_method.refresh_from_db()
        self.assertIsNotNone(mfa_method.last_used_at)
        self.assertEqual(mfa_method.use_count, 1)
    
    def test_verify_mfa_with_backup_code(self):
        """Test MFA verification using backup code"""
        # Create backup code
        backup_code = MFABackupCode.objects.create(
            user=self.user,
            code='BACKUP123'
        )
        
        response = self.client.post(
            reverse('verify_mfa'),
            data=json.dumps({
                'user_id': str(self.user.id),
                'code': 'BACKUP123',
                'method': 'backup_code'
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['verified'])
        
        # Check backup code was used
        backup_code.refresh_from_db()
        self.assertIsNotNone(backup_code.used_at)
    
    def test_complete_mfa_login(self):
        """Test completing login after MFA verification"""
        # Set up MFA verification session
        session_token = 'test_session_token'
        cache_key = f"mfa_verified:{self.user.id}"
        cache.set(cache_key, session_token, timeout=300)
        
        response = self.client.post(
            reverse('complete_mfa_login'),
            data=json.dumps({
                'user_id': str(self.user.id),
                'session_token': session_token,
                'use_cookies': False
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('access', data)
        self.assertIn('refresh', data)
        self.assertIn('user', data)
        
        # Check security event
        self.assertTrue(SecurityEvent.objects.filter(
            user=self.user,
            event_type=SecurityEvent.EventType.LOGIN_SUCCESS,
            metadata__mfa_verified=True
        ).exists())
    
    def test_disable_mfa(self):
        """Test disabling MFA"""
        # Create MFA method
        mfa_method = MFAMethod.objects.create(
            user=self.user,
            method=MFAMethod.Method.TOTP,
            secret='TESTSECRET123456',
            verified_at=timezone.now()
        )
        
        response = self.client.post(
            reverse('disable_mfa'),
            data=json.dumps({
                'method_id': str(mfa_method.id),
                'password': 'mfapass123'
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Check MFA method was disabled
        mfa_method.refresh_from_db()
        self.assertFalse(mfa_method.is_active)
        
        # Check security event
        self.assertTrue(SecurityEvent.objects.filter(
            user=self.user,
            event_type=SecurityEvent.EventType.MFA_DISABLED
        ).exists())
    
    def test_regenerate_backup_codes(self):
        """Test regenerating backup codes"""
        # Enable MFA first
        MFAMethod.objects.create(
            user=self.user,
            method=MFAMethod.Method.TOTP,
            secret='TESTSECRET123456',
            verified_at=timezone.now()
        )
        
        # Create old backup codes
        for i in range(5):
            MFABackupCode.objects.create(user=self.user, code=f'OLD{i}')
        
        response = self.client.post(
            reverse('regenerate_backup_codes'),
            data=json.dumps({'password': 'mfapass123'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['backup_codes']), 10)
        
        # Check old codes were deleted
        self.assertFalse(MFABackupCode.objects.filter(
            user=self.user,
            code__startswith='OLD'
        ).exists())
        
        # Check new codes were created
        self.assertEqual(MFABackupCode.objects.filter(user=self.user).count(), 10)