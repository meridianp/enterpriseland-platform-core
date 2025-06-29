import pytest
from django.test import TestCase
from django.contrib.auth import get_user_model

User = get_user_model()

class PlatformCoreTestCase(TestCase):
    """Base test case for platform core"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_user_creation(self):
        """Test user can be created"""
        self.assertTrue(self.user.id)
        self.assertEqual(self.user.email, 'test@example.com')
