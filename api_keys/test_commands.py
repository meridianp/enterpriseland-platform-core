"""
Tests for API Key management commands.

Tests all management commands for functionality, error handling, and edge cases.
"""

import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Group
from .models import APIKey

User = get_user_model()


class CreateAPIKeyCommandTests(TestCase):
    """Test create_api_key management command."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.group = Group.objects.create(name='Test Group')
        
    def test_create_user_api_key(self):
        """Test creating a user API key via command."""
        out = StringIO()
        
        call_command(
            'create_api_key',
            '--user', self.user.email,
            '--name', 'Test Command Key',
            '--scopes', 'read,write',
            '--expires-in-days', '30',
            stdout=out
        )
        
        # Check key was created
        api_key = APIKey.objects.get(name='Test Command Key')
        self.assertEqual(api_key.user, self.user)
        self.assertEqual(api_key.scopes, ['read', 'write'])
        self.assertEqual(api_key.days_until_expiry, 29)  # approximately
        
        # Check output contains the API key
        output = out.getvalue()
        self.assertIn('API Key created successfully', output)
        self.assertIn('sk_live_', output)
        
    def test_create_application_api_key(self):
        """Test creating an application API key via command."""
        out = StringIO()
        
        call_command(
            'create_api_key',
            '--application', 'Test App',
            '--name', 'App Command Key',
            '--scopes', 'read',
            '--rate-limit', '5000',
            stdout=out
        )
        
        # Check key was created
        api_key = APIKey.objects.get(name='App Command Key')
        self.assertIsNone(api_key.user)
        self.assertEqual(api_key.application_name, 'Test App')
        self.assertEqual(api_key.rate_limit_per_hour, 5000)
        
        # Check output
        output = out.getvalue()
        self.assertIn('ak_live_', output)
        
    def test_create_key_with_ip_restrictions(self):
        """Test creating key with IP restrictions."""
        out = StringIO()
        
        call_command(
            'create_api_key',
            '--user', self.user.email,
            '--name', 'IP Restricted Key',
            '--scopes', 'read',
            '--allowed-ips', '192.168.1.100,10.0.0.1',
            stdout=out
        )
        
        api_key = APIKey.objects.get(name='IP Restricted Key')
        self.assertEqual(api_key.allowed_ips, ['192.168.1.100', '10.0.0.1'])
        
    def test_create_key_with_metadata(self):
        """Test creating key with metadata."""
        out = StringIO()
        
        call_command(
            'create_api_key',
            '--user', self.user.email,
            '--name', 'Metadata Key',
            '--scopes', 'read',
            '--metadata', '{"purpose": "testing", "version": "1.0"}',
            stdout=out
        )
        
        api_key = APIKey.objects.get(name='Metadata Key')
        self.assertEqual(api_key.metadata['purpose'], 'testing')
        self.assertEqual(api_key.metadata['version'], '1.0')
        
    def test_invalid_user_email(self):
        """Test error handling for invalid user email."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                'create_api_key',
                '--user', 'nonexistent@example.com',
                '--name', 'Test Key',
                '--scopes', 'read'
            )
        
        self.assertIn('User not found', str(cm.exception))
        
    def test_invalid_scopes(self):
        """Test error handling for invalid scopes."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                'create_api_key',
                '--user', self.user.email,
                '--name', 'Test Key',
                '--scopes', 'invalid_scope'
            )
        
        self.assertIn('Invalid scope', str(cm.exception))
        
    def test_missing_user_and_application(self):
        """Test error when neither user nor application specified."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                'create_api_key',
                '--name', 'Test Key',
                '--scopes', 'read'
            )
        
        self.assertIn('Must specify either --user or --application', str(cm.exception))
        
    def test_both_user_and_application(self):
        """Test error when both user and application specified."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                'create_api_key',
                '--user', self.user.email,
                '--application', 'Test App',
                '--name', 'Test Key',
                '--scopes', 'read'
            )
        
        self.assertIn('Cannot specify both --user and --application', str(cm.exception))


class ListAPIKeysCommandTests(TestCase):
    """Test list_api_keys management command."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test keys
        self.active_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Active Key',
            scopes=['read']
        )
        
        self.expired_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Expired Key',
            scopes=['write'],
            expires_in_days=1
        )
        # Manually expire it
        self.expired_key.expires_at = timezone.now() - timedelta(hours=1)
        self.expired_key.save()
        
        self.app_key, _ = APIKey.objects.create_key(
            application_name='Test App',
            name='App Key',
            scopes=['admin']
        )
        
    def test_list_all_keys(self):
        """Test listing all API keys."""
        out = StringIO()
        
        call_command('list_api_keys', stdout=out)
        
        output = out.getvalue()
        self.assertIn('Active Key', output)
        self.assertIn('Expired Key', output)
        self.assertIn('App Key', output)
        self.assertIn(self.user.email, output)
        self.assertIn('Test App', output)
        
    def test_list_active_keys_only(self):
        """Test listing only active keys."""
        out = StringIO()
        
        call_command('list_api_keys', '--active-only', stdout=out)
        
        output = out.getvalue()
        self.assertIn('Active Key', output)
        self.assertNotIn('Expired Key', output)
        self.assertIn('App Key', output)
        
    def test_list_user_keys_only(self):
        """Test listing keys for specific user."""
        out = StringIO()
        
        call_command('list_api_keys', '--user', self.user.email, stdout=out)
        
        output = out.getvalue()
        self.assertIn('Active Key', output)
        self.assertIn('Expired Key', output)
        self.assertNotIn('App Key', output)
        
    def test_list_application_keys_only(self):
        """Test listing keys for specific application."""
        out = StringIO()
        
        call_command('list_api_keys', '--application', 'Test App', stdout=out)
        
        output = out.getvalue()
        self.assertNotIn('Active Key', output)
        self.assertNotIn('Expired Key', output)
        self.assertIn('App Key', output)
        
    def test_list_with_usage_stats(self):
        """Test listing keys with usage statistics."""
        # Add some usage to a key
        from .models import APIKeyUsage
        APIKeyUsage.objects.create(
            api_key=self.active_key,
            endpoint='/api/test/',
            method='GET',
            status_code=200,
            ip_address='192.168.1.100',
            response_time_ms=100
        )
        
        out = StringIO()
        
        call_command('list_api_keys', '--show-usage', stdout=out)
        
        output = out.getvalue()
        self.assertIn('Usage: 1', output)
        
    def test_list_expiring_soon(self):
        """Test listing keys expiring soon."""
        # Create a key expiring soon
        soon_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Expiring Soon',
            scopes=['read'],
            expires_in_days=3
        )
        
        out = StringIO()
        
        call_command('list_api_keys', '--expiring-in-days', '7', stdout=out)
        
        output = out.getvalue()
        self.assertIn('Expiring Soon', output)
        self.assertNotIn('Active Key', output)  # Not expiring soon
        
    def test_csv_output_format(self):
        """Test CSV output format."""
        out = StringIO()
        
        call_command('list_api_keys', '--format', 'csv', stdout=out)
        
        output = out.getvalue()
        # Should contain CSV headers
        self.assertIn('ID,Name,User,Application,Scopes,Created,Expires,Active', output)
        
    def test_json_output_format(self):
        """Test JSON output format."""
        out = StringIO()
        
        call_command('list_api_keys', '--format', 'json', stdout=out)
        
        output = out.getvalue()
        self.assertIn('[', output)  # JSON array start
        self.assertIn('"name":', output)  # JSON field


class RevokeAPIKeyCommandTests(TestCase):
    """Test revoke_api_key management command."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.api_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Key to Revoke',
            scopes=['read']
        )
        
    def test_revoke_by_id(self):
        """Test revoking key by ID."""
        out = StringIO()
        
        call_command(
            'revoke_api_key',
            '--key-id', str(self.api_key.id),
            '--reason', 'Test revocation',
            stdout=out
        )
        
        self.api_key.refresh_from_db()
        self.assertFalse(self.api_key.is_active)
        
        output = out.getvalue()
        self.assertIn('successfully revoked', output)
        
    def test_revoke_by_prefix(self):
        """Test revoking key by prefix."""
        out = StringIO()
        
        call_command(
            'revoke_api_key',
            '--key-prefix', self.api_key.key_prefix,
            '--reason', 'Test revocation',
            stdout=out
        )
        
        self.api_key.refresh_from_db()
        self.assertFalse(self.api_key.is_active)
        
    def test_revoke_user_keys(self):
        """Test revoking all keys for a user."""
        # Create another key for the same user
        key2, _ = APIKey.objects.create_key(
            user=self.user,
            name='Another Key',
            scopes=['write']
        )
        
        out = StringIO()
        
        call_command(
            'revoke_api_key',
            '--user', self.user.email,
            '--reason', 'User cleanup',
            stdout=out
        )
        
        self.api_key.refresh_from_db()
        key2.refresh_from_db()
        
        self.assertFalse(self.api_key.is_active)
        self.assertFalse(key2.is_active)
        
        output = out.getvalue()
        self.assertIn('2 key(s) revoked', output)
        
    def test_revoke_application_keys(self):
        """Test revoking all keys for an application."""
        app_key, _ = APIKey.objects.create_key(
            application_name='Test App',
            name='App Key',
            scopes=['read']
        )
        
        out = StringIO()
        
        call_command(
            'revoke_api_key',
            '--application', 'Test App',
            '--reason', 'App decommissioned',
            stdout=out
        )
        
        app_key.refresh_from_db()
        self.assertFalse(app_key.is_active)
        
        # User key should remain active
        self.api_key.refresh_from_db()
        self.assertTrue(self.api_key.is_active)
        
    def test_revoke_expired_keys(self):
        """Test revoking expired keys."""
        # Create an expired key
        expired_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Expired Key',
            scopes=['read'],
            expires_in_days=1
        )
        expired_key.expires_at = timezone.now() - timedelta(hours=1)
        expired_key.save()
        
        out = StringIO()
        
        call_command(
            'revoke_api_key',
            '--expired',
            '--reason', 'Cleanup expired keys',
            stdout=out
        )
        
        expired_key.refresh_from_db()
        self.assertFalse(expired_key.is_active)
        
        # Active key should remain active
        self.api_key.refresh_from_db()
        self.assertTrue(self.api_key.is_active)
        
    def test_dry_run(self):
        """Test dry run mode."""
        out = StringIO()
        
        call_command(
            'revoke_api_key',
            '--key-id', str(self.api_key.id),
            '--reason', 'Test revocation',
            '--dry-run',
            stdout=out
        )
        
        # Key should still be active
        self.api_key.refresh_from_db()
        self.assertTrue(self.api_key.is_active)
        
        output = out.getvalue()
        self.assertIn('DRY RUN', output)
        
    def test_invalid_key_id(self):
        """Test error handling for invalid key ID."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                'revoke_api_key',
                '--key-id', str(uuid.uuid4()),
                '--reason', 'Test'
            )
        
        self.assertIn('API key not found', str(cm.exception))
        
    def test_no_arguments(self):
        """Test error when no revocation criteria specified."""
        with self.assertRaises(CommandError) as cm:
            call_command('revoke_api_key', '--reason', 'Test')
        
        self.assertIn('Must specify', str(cm.exception))


class RotateAPIKeysCommandTests(TestCase):
    """Test rotate_api_keys management command."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create keys with different expiration dates
        self.expiring_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Expiring Key',
            scopes=['read'],
            expires_in_days=5
        )
        
        self.normal_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Normal Key',
            scopes=['write'],
            expires_in_days=365
        )
        
    def test_rotate_expiring_keys(self):
        """Test rotating keys expiring within specified days."""
        out = StringIO()
        
        # Use mock to auto-confirm
        with patch('builtins.input', return_value='y'):
            call_command(
                'rotate_api_keys',
                '--expiring-in-days', '7',
                '--overlap-hours', '24',
                stdout=out
            )
        
        self.expiring_key.refresh_from_db()
        self.assertIsNotNone(self.expiring_key.replaced_by)
        
        # Normal key should not be rotated
        self.normal_key.refresh_from_db()
        self.assertIsNone(self.normal_key.replaced_by)
        
        output = out.getvalue()
        self.assertIn('1 API key(s) to rotate', output)
        self.assertIn('Successfully rotated: 1', output)
        
    def test_rotate_specific_key(self):
        """Test rotating a specific key by ID."""
        out = StringIO()
        
        call_command(
            'rotate_api_keys',
            '--key-id', str(self.normal_key.id),
            '--overlap-hours', '48',
            stdout=out
        )
        
        self.normal_key.refresh_from_db()
        self.assertIsNotNone(self.normal_key.replaced_by)
        
        # Check that new key is displayed
        output = out.getvalue()
        self.assertIn('New API Key', output)
        self.assertIn('sk_live_', output)
        
    def test_rotate_all_keys(self):
        """Test rotating all active keys."""
        out = StringIO()
        
        # Use mock to auto-confirm
        with patch('builtins.input', return_value='y'):
            call_command(
                'rotate_api_keys',
                '--all',
                '--overlap-hours', '12',
                stdout=out
            )
        
        self.expiring_key.refresh_from_db()
        self.normal_key.refresh_from_db()
        
        self.assertIsNotNone(self.expiring_key.replaced_by)
        self.assertIsNotNone(self.normal_key.replaced_by)
        
        output = out.getvalue()
        self.assertIn('Successfully rotated: 2', output)
        
    def test_dry_run_rotation(self):
        """Test dry run mode for rotation."""
        out = StringIO()
        
        call_command(
            'rotate_api_keys',
            '--expiring-in-days', '7',
            '--dry-run',
            stdout=out
        )
        
        # Keys should not be rotated
        self.expiring_key.refresh_from_db()
        self.assertIsNone(self.expiring_key.replaced_by)
        
        output = out.getvalue()
        self.assertIn('DRY RUN', output)
        self.assertIn('No keys were actually rotated', output)
        
    def test_rotation_with_zero_overlap(self):
        """Test rotation with immediate revocation."""
        out = StringIO()
        
        call_command(
            'rotate_api_keys',
            '--key-id', str(self.normal_key.id),
            '--overlap-hours', '0',
            stdout=out
        )
        
        self.normal_key.refresh_from_db()
        
        # Key should be rotated and immediately expired
        self.assertIsNotNone(self.normal_key.replaced_by)
        self.assertTrue(self.normal_key.expires_at <= timezone.now())
        
    def test_rotation_failure_handling(self):
        """Test handling of rotation failures."""
        # Create an invalid key state that might cause rotation to fail
        invalid_key, _ = APIKey.objects.create_key(
            user=self.user,
            name='Invalid Key',
            scopes=['read']
        )
        
        # Mock the rotate method to raise an exception
        with patch.object(APIKey, 'rotate', side_effect=Exception('Test error')):
            out = StringIO()
            
            call_command(
                'rotate_api_keys',
                '--key-id', str(invalid_key.id),
                stdout=out
            )
            
            output = out.getvalue()
            self.assertIn('Failed: 1', output)
            self.assertIn('Test error', output)
            
    def test_no_keys_to_rotate(self):
        """Test behavior when no keys match rotation criteria."""
        out = StringIO()
        
        call_command(
            'rotate_api_keys',
            '--expiring-in-days', '1',  # Very short window
            stdout=out
        )
        
        output = out.getvalue()
        self.assertIn('No API keys found to rotate', output)
        
    def test_invalid_key_id(self):
        """Test error handling for invalid key ID."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                'rotate_api_keys',
                '--key-id', str(uuid.uuid4())
            )
        
        self.assertIn('does not exist', str(cm.exception))
        
    def test_missing_rotation_criteria(self):
        """Test error when no rotation criteria specified."""
        with self.assertRaises(CommandError) as cm:
            call_command('rotate_api_keys')
        
        self.assertIn('Must specify one of', str(cm.exception))


class CommandIntegrationTests(TestCase):
    """Test integration between different commands."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_create_list_revoke_workflow(self):
        """Test complete workflow: create -> list -> revoke."""
        # Create a key
        out1 = StringIO()
        call_command(
            'create_api_key',
            '--user', self.user.email,
            '--name', 'Workflow Test Key',
            '--scopes', 'read,write',
            stdout=out1
        )
        
        # Extract key ID from output (would be more robust in real implementation)
        api_key = APIKey.objects.get(name='Workflow Test Key')
        
        # List keys to verify creation
        out2 = StringIO()
        call_command('list_api_keys', '--user', self.user.email, stdout=out2)
        list_output = out2.getvalue()
        self.assertIn('Workflow Test Key', list_output)
        self.assertIn('Active: True', list_output)
        
        # Revoke the key
        out3 = StringIO()
        call_command(
            'revoke_api_key',
            '--key-id', str(api_key.id),
            '--reason', 'Workflow test complete',
            stdout=out3
        )
        
        # Verify revocation
        api_key.refresh_from_db()
        self.assertFalse(api_key.is_active)
        
        # List again to verify revocation
        out4 = StringIO()
        call_command('list_api_keys', '--user', self.user.email, stdout=out4)
        final_output = out4.getvalue()
        self.assertIn('Active: False', final_output)
        
    def test_create_rotate_workflow(self):
        """Test create -> rotate workflow."""
        # Create a key
        out1 = StringIO()
        call_command(
            'create_api_key',
            '--user', self.user.email,
            '--name', 'Rotation Test Key',
            '--scopes', 'admin',
            stdout=out1
        )
        
        api_key = APIKey.objects.get(name='Rotation Test Key')
        original_id = api_key.id
        
        # Rotate the key
        out2 = StringIO()
        call_command(
            'rotate_api_keys',
            '--key-id', str(original_id),
            '--overlap-hours', '1',
            stdout=out2
        )
        
        # Verify rotation
        api_key.refresh_from_db()
        self.assertIsNotNone(api_key.replaced_by)
        
        # List keys to see both old and new
        out3 = StringIO()
        call_command('list_api_keys', '--user', self.user.email, stdout=out3)
        list_output = out3.getvalue()
        
        # Should show both the original and rotated key
        self.assertIn('Rotation Test Key', list_output)
        self.assertIn('Rotation Test Key (Rotated)', list_output)


@override_settings(DEBUG=True)
class CommandErrorHandlingTests(TestCase):
    """Test error handling and edge cases in commands."""
    
    def test_command_with_invalid_json_metadata(self):
        """Test handling of invalid JSON in metadata."""
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        with self.assertRaises(CommandError) as cm:
            call_command(
                'create_api_key',
                '--user', user.email,
                '--name', 'Test Key',
                '--scopes', 'read',
                '--metadata', '{"invalid": json}'
            )
        
        self.assertIn('Invalid JSON', str(cm.exception))
        
    def test_command_with_database_error(self):
        """Test handling of database errors."""
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Mock database error during key creation
        with patch('api_keys.models.APIKey.objects.create_key', side_effect=Exception('DB Error')):
            with self.assertRaises(CommandError) as cm:
                call_command(
                    'create_api_key',
                    '--user', user.email,
                    '--name', 'Test Key',
                    '--scopes', 'read'
                )
            
            self.assertIn('Failed to create API key', str(cm.exception))
            
    def test_command_output_encoding(self):
        """Test that commands handle Unicode output correctly."""
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create key with Unicode name
        out = StringIO()
        call_command(
            'create_api_key',
            '--user', user.email,
            '--name', 'Test Key 测试 🔑',
            '--scopes', 'read',
            stdout=out
        )
        
        output = out.getvalue()
        self.assertIn('Test Key 测试 🔑', output)
        
        # List the key
        out2 = StringIO()
        call_command('list_api_keys', '--user', user.email, stdout=out2)
        
        list_output = out2.getvalue()
        self.assertIn('Test Key 测试 🔑', list_output)