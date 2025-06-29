"""
Tests for the manage_encryption management command.

Tests all subcommands and their functionality.
"""

import base64
import json
from io import StringIO
from unittest.mock import patch, MagicMock, call
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.core.management.base import CommandError

from platform_core.core.encryption.backends import get_encryption_backend, reset_encryption_backend
from platform_core.core.encryption.keys import KeyManager, EncryptionKey
from platform_core.core.management.commands.manage_encryption import Command
from datetime import datetime, timedelta


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
    ENCRYPTION_BACKEND='aes',
    ENCRYPTION_KEY_STORE='local'
)
class ManageEncryptionCommandTests(TestCase):
    """Test the manage_encryption management command."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.stdout = StringIO()
        self.stderr = StringIO()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_command_without_subcommand(self):
        """Test running command without subcommand shows help."""
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption')
        
        output = self.stdout.getvalue()
        self.assertIn('subcommand', output.lower())
        self.assertIn('help', output.lower())
    
    def test_test_subcommand(self):
        """Test the 'test' subcommand."""
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'test', '--value', 'Hello, World!')
        
        output = self.stdout.getvalue()
        
        # Check expected output
        self.assertIn('Testing encryption with value: Hello, World!', output)
        self.assertIn('Encrypted:', output)
        self.assertIn('Decrypted: Hello, World!', output)
        self.assertIn('✓ Encryption/decryption successful!', output)
        self.assertIn('Search hash:', output)
        self.assertIn('✓ Search hash verification successful!', output)
    
    def test_test_subcommand_with_special_characters(self):
        """Test encryption with special characters."""
        test_value = "Special: !@#$%^&*() Unicode: 你好 🌍"
        
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'test', '--value', test_value)
        
        output = self.stdout.getvalue()
        self.assertIn(f'Decrypted: {test_value}', output)
        self.assertIn('✓ Encryption/decryption successful!', output)
    
    def test_generate_key_subcommand(self):
        """Test the 'generate-key' subcommand."""
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'generate-key')
        
        output = self.stdout.getvalue()
        
        # Check expected output
        self.assertIn('Generating new encryption key...', output)
        self.assertIn('Generated key (base64):', output)
        self.assertIn('ENCRYPTION_MASTER_KEY =', output)
        self.assertIn('⚠️  Store this key securely!', output)
        self.assertIn('environment variables', output)
        self.assertIn('Never commit keys', output)
        
        # Extract and validate the generated key
        lines = output.split('\n')
        key_line = next(line for line in lines if 'ENCRYPTION_MASTER_KEY =' in line)
        key_value = key_line.split("'")[1]
        
        # Validate it's a valid base64 key
        try:
            decoded = base64.b64decode(key_value)
            self.assertEqual(len(decoded), 32)  # 256-bit key
        except Exception:
            self.fail("Generated key is not valid base64")
    
    def test_list_keys_subcommand(self):
        """Test the 'list-keys' subcommand."""
        # Create some test keys
        with patch('core.encryption.keys.KeyManager.list_keys') as mock_list:
            mock_list.return_value = [
                EncryptionKey(
                    key_material=b'0' * 32,
                    version=1,
                    created_at=datetime.utcnow() - timedelta(days=30),
                    expires_at=datetime.utcnow() + timedelta(days=335),
                    is_primary=False
                ),
                EncryptionKey(
                    key_material=b'1' * 32,
                    version=2,
                    created_at=datetime.utcnow(),
                    expires_at=None,
                    is_primary=True
                ),
            ]
            
            with patch('core.encryption.keys.KeyManager.get_current_key') as mock_current:
                mock_current.return_value = mock_list.return_value[1]
                
                with patch('sys.stdout', self.stdout):
                    call_command('manage_encryption', 'list-keys')
        
        output = self.stdout.getvalue()
        
        # Check expected output
        self.assertIn('Listing encryption keys...', output)
        self.assertIn('Found 2 key(s):', output)
        self.assertIn('Version 1: ACTIVE', output)
        self.assertIn('Version 2: PRIMARY', output)
        self.assertIn('Current key: Version 2', output)
    
    def test_list_keys_no_keys(self):
        """Test list-keys when no keys exist."""
        with patch('core.encryption.keys.KeyManager.list_keys') as mock_list:
            mock_list.return_value = []
            
            with patch('sys.stdout', self.stdout):
                call_command('manage_encryption', 'list-keys')
        
        output = self.stdout.getvalue()
        self.assertIn('No encryption keys found.', output)
    
    def test_rotate_keys_dry_run(self):
        """Test key rotation in dry-run mode."""
        with patch('core.encryption.utils.rotate_encryption_keys') as mock_rotate:
            mock_rotate.return_value = {
                'status': 'dry_run',
                'current_version': 1,
                'new_version': 2,
                'message': 'Dry run completed'
            }
            
            with patch('sys.stdout', self.stdout):
                call_command('manage_encryption', 'rotate-keys', '--dry-run')
        
        output = self.stdout.getvalue()
        
        # Check expected output
        self.assertIn('DRY RUN: Simulating key rotation...', output)
        self.assertIn('Dry run completed: would rotate v1 → v2', output)
        
        # Verify dry_run was passed
        mock_rotate.assert_called_once_with(dry_run=True)
    
    def test_rotate_keys_actual(self):
        """Test actual key rotation."""
        with patch('core.encryption.utils.rotate_encryption_keys') as mock_rotate:
            mock_rotate.return_value = {
                'status': 'success',
                'old_version': 1,
                'new_version': 2,
                'message': 'Key rotation completed'
            }
            
            with patch('sys.stdout', self.stdout):
                call_command('manage_encryption', 'rotate-keys')
        
        output = self.stdout.getvalue()
        
        # Check expected output
        self.assertIn('Rotating encryption keys...', output)
        self.assertIn('✓ Key rotation completed: v1 → v2', output)
        self.assertIn('⚠️  Important: Update your key configuration', output)
        
        # Verify dry_run=False was passed
        mock_rotate.assert_called_once_with(dry_run=False)
    
    def test_rotate_keys_error(self):
        """Test key rotation error handling."""
        with patch('core.encryption.utils.rotate_encryption_keys') as mock_rotate:
            mock_rotate.side_effect = Exception("Rotation failed!")
            
            with self.assertRaises(CommandError) as cm:
                call_command('manage_encryption', 'rotate-keys')
            
            self.assertIn("Key rotation failed", str(cm.exception))
    
    def test_validate_subcommand_valid(self):
        """Test the 'validate' subcommand with valid configuration."""
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'validate')
        
        output = self.stdout.getvalue()
        
        # Check expected output
        self.assertIn('Validating encryption configuration...', output)
        self.assertIn('✓ Configuration is valid!', output)
        self.assertIn('Current configuration:', output)
        self.assertIn('Environment:', output)
        self.assertIn('Key store: local', output)
        self.assertIn('Backend: aes', output)
        self.assertIn('Master key: Configured ✓', output)
    
    @override_settings(ENCRYPTION_MASTER_KEY=None)
    def test_validate_subcommand_invalid(self):
        """Test validate with invalid configuration."""
        with patch('core.encryption.utils.validate_encryption_config') as mock_validate:
            mock_validate.side_effect = Exception("ENCRYPTION_MASTER_KEY not configured")
            
            with self.assertRaises(CommandError) as cm:
                call_command('manage_encryption', 'validate')
            
            self.assertIn("Please fix the configuration errors", str(cm.exception))
    
    def test_audit_subcommand(self):
        """Test the 'audit' subcommand."""
        with patch('core.encryption.utils.audit_encryption_usage') as mock_audit:
            mock_audit.return_value = {
                'total_models': 50,
                'encrypted_models': 10,
                'total_fields': 500,
                'encrypted_fields': 25,
                'fields_by_type': {
                    'EncryptedCharField': 15,
                    'EncryptedTextField': 5,
                    'EncryptedEmailField': 3,
                    'EncryptedDecimalField': 2,
                },
                'models': [
                    {
                        'app_label': 'accounts',
                        'model_name': 'User',
                        'encrypted_fields': [
                            {'name': 'email', 'type': 'EncryptedEmailField', 'searchable': True},
                            {'name': 'ssn', 'type': 'EncryptedCharField', 'searchable': True},
                        ]
                    },
                    {
                        'app_label': 'core',
                        'model_name': 'SecretData',
                        'encrypted_fields': [
                            {'name': 'data', 'type': 'EncryptedTextField', 'searchable': False},
                        ]
                    }
                ]
            }
            
            with patch('sys.stdout', self.stdout):
                call_command('manage_encryption', 'audit')
        
        output = self.stdout.getvalue()
        
        # Check expected output
        self.assertIn('Auditing encryption usage...', output)
        self.assertIn('Encryption Usage Summary:', output)
        self.assertIn('Total models: 50', output)
        self.assertIn('Models with encryption: 10', output)
        self.assertIn('Total fields: 500', output)
        self.assertIn('Encrypted fields: 25', output)
        
        # Field types
        self.assertIn('Encrypted field types:', output)
        self.assertIn('EncryptedCharField: 15', output)
        self.assertIn('EncryptedTextField: 5', output)
        
        # Model details
        self.assertIn('Models with encrypted fields:', output)
        self.assertIn('accounts.User:', output)
        self.assertIn('- email (EncryptedEmailField, searchable)', output)
        self.assertIn('- ssn (EncryptedCharField, searchable)', output)
        self.assertIn('core.SecretData:', output)
        self.assertIn('- data (EncryptedTextField, not searchable)', output)
        
        # Coverage
        self.assertIn('Encryption coverage: 20.0%', output)
    
    def test_audit_subcommand_error(self):
        """Test audit error handling."""
        with patch('core.encryption.utils.audit_encryption_usage') as mock_audit:
            mock_audit.side_effect = Exception("Audit failed!")
            
            with self.assertRaises(CommandError) as cm:
                call_command('manage_encryption', 'audit')
            
            self.assertIn("Audit failed", str(cm.exception))
    
    def test_command_error_handling(self):
        """Test general error handling in the command."""
        # Test with invalid backend
        with patch('core.encryption.backends.get_encryption_backend') as mock_get:
            mock_get.side_effect = Exception("Backend not available")
            
            with self.assertRaises(CommandError):
                call_command('manage_encryption', 'test')


class CommandIntegrationTests(TestCase):
    """Integration tests for the management command."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.stdout = StringIO()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    @override_settings(
        ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
        ENCRYPTION_BACKEND='aes',
        ENCRYPTION_KEY_STORE='local',
        ENCRYPTION_KEYS={
            '1': {
                'key': base64.b64encode(b'0' * 32).decode('utf-8'),
                'created_at': '2024-01-01T00:00:00',
                'is_primary': False
            },
            '2': {
                'key': base64.b64encode(b'1' * 32).decode('utf-8'),
                'created_at': '2024-06-01T00:00:00',
                'is_primary': True
            }
        }
    )
    def test_full_command_workflow(self):
        """Test a full workflow using multiple subcommands."""
        # 1. Validate configuration
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'validate')
        
        self.assertIn('✓ Configuration is valid!', self.stdout.getvalue())
        
        # 2. List current keys
        self.stdout = StringIO()
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'list-keys')
        
        output = self.stdout.getvalue()
        self.assertIn('Found 2 key(s):', output)
        self.assertIn('Current key: Version 2', output)
        
        # 3. Test encryption
        self.stdout = StringIO()
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'test', '--value', 'Integration test')
        
        self.assertIn('✓ Encryption/decryption successful!', self.stdout.getvalue())
        
        # 4. Generate a new key
        self.stdout = StringIO()
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'generate-key')
        
        self.assertIn('Generated key (base64):', self.stdout.getvalue())
        
        # 5. Dry-run rotation
        self.stdout = StringIO()
        with patch('sys.stdout', self.stdout):
            call_command('manage_encryption', 'rotate-keys', '--dry-run')
        
        self.assertIn('DRY RUN: Simulating key rotation', self.stdout.getvalue())