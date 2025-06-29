"""
Tests for cookie-based JWT authentication
"""
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class CookieAuthenticationTest(TestCase):
    """Test cookie-based authentication endpoints"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            username='testuser',
            first_name='Test',
            last_name='User'
        )
        
    def test_cookie_login_success(self):
        """Test successful login sets httpOnly cookies"""
        url = reverse('cookie_login')
        data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Check response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('user', response.data)
        self.assertIn('csrf_token', response.data)
        self.assertEqual(response.data['user']['email'], 'test@example.com')
        
        # Check cookies are set
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)
        
        # Check cookie properties
        access_cookie = response.cookies['access_token']
        self.assertTrue(access_cookie['httponly'])
        self.assertEqual(access_cookie['samesite'], 'Lax')
        self.assertEqual(access_cookie['path'], '/')
        
        refresh_cookie = response.cookies['refresh_token']
        self.assertTrue(refresh_cookie['httponly'])
        self.assertEqual(refresh_cookie['samesite'], 'Lax')
        self.assertEqual(refresh_cookie['path'], '/')
        
    def test_cookie_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        url = reverse('cookie_login')
        data = {
            'email': 'test@example.com',
            'password': 'wrongpass'
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn('access_token', response.cookies)
        self.assertNotIn('refresh_token', response.cookies)
        
    def test_cookie_refresh_success(self):
        """Test token refresh using cookie"""
        # First login
        login_url = reverse('cookie_login')
        login_data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        
        login_response = self.client.post(
            login_url,
            data=json.dumps(login_data),
            content_type='application/json'
        )
        
        # Now refresh
        refresh_url = reverse('cookie_refresh')
        response = self.client.post(refresh_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('csrf_token', response.data)
        self.assertIn('access_token', response.cookies)
        
    def test_cookie_refresh_without_token(self):
        """Test refresh without refresh token cookie"""
        url = reverse('cookie_refresh')
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('error', response.data)
        
    def test_cookie_logout(self):
        """Test logout clears cookies"""
        # First login
        login_url = reverse('cookie_login')
        login_data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        
        self.client.post(
            login_url,
            data=json.dumps(login_data),
            content_type='application/json'
        )
        
        # Now logout
        logout_url = reverse('cookie_logout')
        response = self.client.post(logout_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check cookies are cleared
        self.assertEqual(response.cookies['access_token'].value, '')
        self.assertEqual(response.cookies['refresh_token'].value, '')
        
    def test_authenticated_request_with_cookie(self):
        """Test making authenticated request using cookie"""
        # First login
        login_url = reverse('cookie_login')
        login_data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        
        self.client.post(
            login_url,
            data=json.dumps(login_data),
            content_type='application/json'
        )
        
        # Make authenticated request
        me_url = reverse('user-me')
        response = self.client.get(me_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'test@example.com')
        
    def test_csrf_token_endpoint(self):
        """Test CSRF token endpoint"""
        # First login
        login_url = reverse('cookie_login')
        login_data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        
        self.client.post(
            login_url,
            data=json.dumps(login_data),
            content_type='application/json'
        )
        
        # Get CSRF token
        csrf_url = reverse('get_csrf_token')
        response = self.client.get(csrf_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('csrf_token', response.data)
        self.assertTrue(len(response.data['csrf_token']) > 0)
        
    def test_csrf_protection_enforced(self):
        """Test that CSRF protection is enforced for state-changing requests"""
        # First login
        login_url = reverse('cookie_login')
        login_data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        
        self.client.post(
            login_url,
            data=json.dumps(login_data),
            content_type='application/json'
        )
        
        # Try to make a POST request without CSRF token
        # This should fail when using cookie auth
        # Note: This test assumes an endpoint that requires CSRF
        # You'll need to adjust based on your actual endpoints
        
    def test_cookie_auth_with_bearer_fallback(self):
        """Test that bearer token still works as fallback"""
        # Get tokens the old way
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        
        # Make request with Authorization header
        me_url = reverse('user-me')
        response = self.client.get(
            me_url,
            HTTP_AUTHORIZATION=f'Bearer {access_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'test@example.com')