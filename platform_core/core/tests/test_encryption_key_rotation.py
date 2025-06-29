"""
Tests for encryption key rotation functionality.

Tests key rotation, re-encryption of data, and handling of multiple key versions.
"""

import base64
from datetime import datetime, timedelta
from django.test import TestCase, override_settings
from django.db import models, transaction
from unittest.mock import patch, MagicMock

from platform_core.core.encryption.keys import (
    EncryptionKey,
    KeyManager,
    LocalKeyStore,
    DatabaseKeyStore,
)
from platform_core.core.encryption.backends import get_encryption_backend, reset_encryption_backend
from platform_core.core.encryption.fields import EncryptedCharField, EncryptedTextField
from platform_core.core.encryption.utils import rotate_encryption_keys
from platform_core.core.encryption.exceptions import (
    KeyNotFoundError,
    KeyRotationError,
    InvalidKeyVersionError,
)


# Test model for rotation testing
class KeyRotationTestModel(models.Model):
    """Model for testing key rotation."""
    
    encrypted_name = EncryptedCharField(max_length=100, searchable=True)
    encrypted_data = EncryptedTextField()
    normal_field = models.CharField(max_length=100)
    
    class Meta:
        app_label = 'core'
        db_table = 'test_key_rotation'


class EncryptionKeyTests(TestCase):
    """Test EncryptionKey class functionality."""
    
    def test_encryption_key_creation(self):
        """Test creating an encryption key."""
        key_material = b'0' * 32  # 32 bytes for AES-256
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(days=365)
        
        key = EncryptionKey(
            key_material=key_material,
            version=1,
            created_at=created_at,
            expires_at=expires_at,
            is_primary=True
        )
        
        self.assertEqual(key.version, 1)
        self.assertEqual(key.key_material, key_material)
        self.assertTrue(key.is_primary)
        self.assertTrue(key.is_active)
        self.assertFalse(key.is_expired)
    
    def test_expired_key(self):
        """Test expired key detection."""
        key = EncryptionKey(
            key_material=b'0' * 32,
            version=1,
            created_at=datetime.utcnow() - timedelta(days=400),
            expires_at=datetime.utcnow() - timedelta(days=1),  # Expired yesterday
            is_primary=False
        )
        
        self.assertTrue(key.is_expired)
        self.assertFalse(key.is_active)
    
    def test_key_without_expiration(self):
        """Test key without expiration date."""
        key = EncryptionKey(
            key_material=b'0' * 32,
            version=1,
            created_at=datetime.utcnow(),
            expires_at=None,  # No expiration
            is_primary=True
        )
        
        self.assertFalse(key.is_expired)
        self.assertTrue(key.is_active)


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
    ENCRYPTION_KEY_STORE='local'
)
class LocalKeyStoreTests(TestCase):
    """Test LocalKeyStore functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.key_store = LocalKeyStore()
    
    def test_load_master_key(self):
        """Test loading master key from settings."""
        master_key = self.key_store.get_master_key()
        
        self.assertIsInstance(master_key, bytes)
        self.assertEqual(len(master_key), 32)  # 256 bits
    
    def test_get_current_key(self):
        """Test getting current active key."""
        current_key = self.key_store.get_current_key()
        
        self.assertIsInstance(current_key, EncryptionKey)
        self.assertTrue(current_key.is_active)
        self.assertEqual(current_key.version, 1)
    
    def test_get_key_by_version(self):
        """Test retrieving specific key version."""
        key = self.key_store.get_key_by_version(1)
        
        self.assertIsInstance(key, EncryptionKey)
        self.assertEqual(key.version, 1)
    
    def test_invalid_key_version(self):
        """Test retrieving non-existent key version."""
        with self.assertRaises(InvalidKeyVersionError):
            self.key_store.get_key_by_version(999)
    
    def test_generate_new_key(self):
        """Test generating a new key version."""
        initial_keys = len(self.key_store.list_keys())
        
        new_key = self.key_store.generate_new_key()
        
        self.assertIsInstance(new_key, EncryptionKey)
        self.assertEqual(new_key.version, 2)
        self.assertTrue(new_key.is_primary)
        self.assertEqual(len(new_key.key_material), 32)
        
        # Check old key is no longer primary
        old_key = self.key_store.get_key_by_version(1)
        self.assertFalse(old_key.is_primary)
        
        # Check we have one more key
        self.assertEqual(len(self.key_store.list_keys()), initial_keys + 1)
    
    @override_settings(
        ENCRYPTION_KEYS={
            '1': {
                'key': base64.b64encode(b'0' * 32).decode('utf-8'),
                'created_at': '2024-01-01T00:00:00',
                'expires_at': '2025-01-01T00:00:00',
                'is_primary': False
            },
            '2': {
                'key': base64.b64encode(b'1' * 32).decode('utf-8'),
                'created_at': '2024-06-01T00:00:00',
                'is_primary': True
            }
        }
    )
    def test_multiple_key_versions(self):
        """Test handling multiple key versions."""
        key_store = LocalKeyStore()
        
        keys = key_store.list_keys()
        self.assertEqual(len(keys), 2)
        
        # Version 2 should be current (primary)
        current = key_store.get_current_key()
        self.assertEqual(current.version, 2)
        self.assertTrue(current.is_primary)
        
        # We should still be able to get version 1
        old_key = key_store.get_key_by_version(1)
        self.assertEqual(old_key.version, 1)
        self.assertFalse(old_key.is_primary)


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
    ENCRYPTION_KEY_STORE='local'
)
class KeyManagerTests(TestCase):
    """Test KeyManager functionality."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.key_manager = KeyManager()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_get_current_key_with_caching(self):
        """Test that current key is cached."""
        # First call should hit the key store
        key1 = self.key_manager.get_current_key()
        
        # Mock the key store to verify caching
        with patch.object(self.key_manager.key_store, 'get_current_key') as mock_get:
            # Second call should use cache
            key2 = self.key_manager.get_current_key()
            
            # Key store shouldn't be called due to caching
            mock_get.assert_not_called()
        
        self.assertEqual(key1.version, key2.version)
    
    def test_get_search_key(self):
        """Test getting search key."""
        search_key = self.key_manager.get_search_key()
        
        self.assertIsInstance(search_key, bytes)
        self.assertEqual(len(search_key), 32)
        
        # Should be deterministic
        search_key2 = self.key_manager.get_search_key()
        self.assertEqual(search_key, search_key2)
    
    def test_key_rotation(self):
        """Test key rotation process."""
        initial_key = self.key_manager.get_current_key()
        initial_version = initial_key.version
        
        # Rotate key
        new_key = self.key_manager.rotate_key()
        
        self.assertIsInstance(new_key, EncryptionKey)
        self.assertEqual(new_key.version, initial_version + 1)
        self.assertTrue(new_key.is_primary)
        
        # Verify new key is now current
        current = self.key_manager.get_current_key()
        self.assertEqual(current.version, new_key.version)
    
    def test_key_rotation_clears_cache(self):
        """Test that key rotation clears caches."""
        # Populate cache
        self.key_manager.get_current_key()
        
        # Mock cache to verify clearing
        with patch('core.encryption.keys.cache') as mock_cache:
            self.key_manager.rotate_key()
            
            # Verify cache was cleared
            mock_cache.delete_pattern.assert_any_call('encryption_key:*')
            mock_cache.delete_pattern.assert_any_call('decrypted:*')


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
    ENCRYPTION_BACKEND='aes',
    ENCRYPTION_KEY_STORE='local'
)
class KeyRotationIntegrationTests(TestCase):
    """Integration tests for key rotation with encrypted data."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        
        # Create test data with version 1 key
        self.test_objects = []
        for i in range(5):
            obj = KeyRotationTestModel.objects.create(
                encrypted_name=f"Test User {i}",
                encrypted_data=f"Secret data for user {i}",
                normal_field=f"Normal {i}"
            )
            self.test_objects.append(obj)
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_data_remains_readable_after_rotation(self):
        """Test that data encrypted with old key remains readable after rotation."""
        # Verify initial data
        for i, obj in enumerate(self.test_objects):
            self.assertEqual(obj.encrypted_name, f"Test User {i}")
            self.assertEqual(obj.encrypted_data, f"Secret data for user {i}")
        
        # Rotate key
        key_manager = KeyManager()
        old_version = key_manager.get_current_key().version
        key_manager.rotate_key()
        new_version = key_manager.get_current_key().version
        
        self.assertEqual(new_version, old_version + 1)
        
        # Data should still be readable (using old key version)
        for i, obj in enumerate(self.test_objects):
            obj_from_db = KeyRotationTestModel.objects.get(pk=obj.pk)
            self.assertEqual(obj_from_db.encrypted_name, f"Test User {i}")
            self.assertEqual(obj_from_db.encrypted_data, f"Secret data for user {i}")
    
    def test_new_data_uses_new_key(self):
        """Test that new data uses the new key after rotation."""
        # Rotate key
        key_manager = KeyManager()
        key_manager.rotate_key()
        new_version = key_manager.get_current_key().version
        
        # Create new object
        new_obj = KeyRotationTestModel.objects.create(
            encrypted_name="New User",
            encrypted_data="New secret data",
            normal_field="New normal"
        )
        
        # Check raw encrypted data to verify it uses new key version
        backend = get_encryption_backend()
        
        # Get raw value from database
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT encrypted_name FROM test_key_rotation WHERE id = %s",
                [new_obj.pk]
            )
            raw_value = cursor.fetchone()[0]
        
        # Decode the encrypted data structure
        import json
        encrypted_data = json.loads(base64.b64decode(raw_value))
        
        # Verify it uses the new key version
        self.assertEqual(encrypted_data['v'], new_version)
    
    def test_search_hash_consistency_after_rotation(self):
        """Test that search hashes remain consistent after key rotation."""
        # Get search hash before rotation
        backend = get_encryption_backend()
        search_value = "Test User 0"
        hash_before = backend.create_search_hash(search_value)
        
        # Rotate key
        key_manager = KeyManager()
        key_manager.rotate_key()
        
        # Get search hash after rotation
        hash_after = backend.create_search_hash(search_value)
        
        # Search hashes should be the same (uses non-rotating search key)
        self.assertEqual(hash_before, hash_after)
        
        # Should still be able to find by search hash
        found = KeyRotationTestModel.objects.filter(
            encrypted_name_search_hash=hash_after
        ).first()
        self.assertIsNotNone(found)
        self.assertEqual(found.encrypted_name, search_value)
    
    def test_bulk_re_encryption(self):
        """Test bulk re-encryption of data with new key."""
        key_manager = KeyManager()
        old_key = key_manager.get_current_key()
        
        # Rotate key
        new_key = key_manager.rotate_key()
        
        # Manually re-encrypt all data
        backend = get_encryption_backend()
        
        with transaction.atomic():
            for obj in KeyRotationTestModel.objects.all():
                # Decrypt with appropriate key version
                name_plain = obj.encrypted_name
                data_plain = obj.encrypted_data
                
                # Re-encrypt with new key
                obj.encrypted_name = name_plain
                obj.encrypted_data = data_plain
                obj.save()
        
        # Verify all data now uses new key version
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT encrypted_name FROM test_key_rotation")
            
            for row in cursor.fetchall():
                encrypted_data = json.loads(base64.b64decode(row[0]))
                self.assertEqual(encrypted_data['v'], new_key.version)
    
    def test_rotation_rollback_on_error(self):
        """Test that key rotation is rolled back on error."""
        key_manager = KeyManager()
        initial_version = key_manager.get_current_key().version
        
        # Mock to cause error during rotation
        with patch.object(key_manager.key_store, 'generate_new_key') as mock_generate:
            mock_generate.side_effect = Exception("Rotation failed!")
            
            with self.assertRaises(KeyRotationError):
                key_manager.rotate_key()
        
        # Key version should not have changed
        current_version = key_manager.get_current_key().version
        self.assertEqual(current_version, initial_version)
    
    def test_rotate_encryption_keys_utility(self):
        """Test the rotate_encryption_keys utility function."""
        # Test dry run
        result = rotate_encryption_keys(dry_run=True)
        
        self.assertEqual(result['status'], 'dry_run')
        self.assertIn('current_version', result)
        self.assertIn('new_version', result)
        
        # Test actual rotation
        result = rotate_encryption_keys(dry_run=False)
        
        self.assertEqual(result['status'], 'success')
        self.assertIn('old_version', result)
        self.assertIn('new_version', result)
        self.assertEqual(result['new_version'], result['old_version'] + 1)


class DatabaseKeyStoreTests(TestCase):
    """Test DatabaseKeyStore functionality (mocked)."""
    
    @patch('core.encryption.keys.StoredEncryptionKey')
    def test_database_key_store_operations(self, mock_model):
        """Test basic DatabaseKeyStore operations."""
        # Mock the model
        mock_key = MagicMock()
        mock_key.version = 1
        mock_key.to_encryption_key.return_value = EncryptionKey(
            key_material=b'0' * 32,
            version=1,
            created_at=datetime.utcnow(),
            is_primary=True
        )
        
        mock_model.objects.filter.return_value.order_by.return_value.first.return_value = mock_key
        mock_model.objects.get.return_value = mock_key
        
        # Test get current key
        key_store = DatabaseKeyStore()
        current = key_store.get_current_key()
        
        self.assertEqual(current.version, 1)
        mock_model.objects.filter.assert_called_with(is_primary=True, is_active=True)
    
    @patch('core.encryption.keys.StoredEncryptionKey')
    def test_database_key_generation(self, mock_model):
        """Test key generation in database store."""
        mock_model.objects.aggregate.return_value = {'max_version': 1}
        
        # Mock the create method
        new_mock_key = MagicMock()
        new_mock_key.to_encryption_key.return_value = EncryptionKey(
            key_material=b'1' * 32,
            version=2,
            created_at=datetime.utcnow(),
            is_primary=True
        )
        mock_model.objects.create.return_value = new_mock_key
        
        key_store = DatabaseKeyStore()
        new_key = key_store.generate_new_key()
        
        self.assertEqual(new_key.version, 2)
        
        # Verify old keys were marked as not primary
        mock_model.objects.filter.assert_called_with(is_primary=True)
        mock_model.objects.filter.return_value.update.assert_called_with(is_primary=False)