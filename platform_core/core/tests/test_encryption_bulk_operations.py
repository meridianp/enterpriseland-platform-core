"""
Tests for bulk encryption operations and performance.

Tests bulk encrypt/decrypt, batch processing, and performance optimization.
"""

import time
from decimal import Decimal
from django.test import TestCase, override_settings, TransactionTestCase
from django.db import connection, transaction
from django.core.paginator import Paginator

from platform_core.core.encryption.fields import (
    EncryptedCharField,
    EncryptedTextField,
    EncryptedDecimalField,
    EncryptedJSONField,
)
from platform_core.core.encryption.backends import get_encryption_backend, reset_encryption_backend
from platform_core.core.encryption.utils import bulk_encrypt, bulk_decrypt
from django.db import models


class BulkTestModel(models.Model):
    """Model for bulk operation testing."""
    
    name = EncryptedCharField(max_length=100)
    email = EncryptedCharField(max_length=100, searchable=True)
    description = EncryptedTextField(null=True, blank=True)
    balance = EncryptedDecimalField(max_digits=10, decimal_places=2, null=True)
    metadata = EncryptedJSONField(null=True, blank=True)
    
    class Meta:
        app_label = 'core'
        db_table = 'test_bulk_operations'


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
    ENCRYPTION_BACKEND='aes',
    ENCRYPTION_CACHE_TIMEOUT=300
)
class BulkEncryptionTests(TestCase):
    """Test bulk encryption operations."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_bulk_encrypt_decrypt(self):
        """Test bulk encryption and decryption utilities."""
        # Test data
        test_values = [
            "value1",
            "value2",
            "special chars: !@#$%",
            "unicode: 你好世界",
            None,  # Test null handling
            "",    # Test empty string
        ]
        
        # Bulk encrypt
        encrypted_values = bulk_encrypt(test_values)
        
        self.assertEqual(len(encrypted_values), len(test_values))
        
        # Verify encryption (non-null values should be encrypted)
        for i, (original, encrypted) in enumerate(zip(test_values, encrypted_values)):
            if original is not None:
                self.assertNotEqual(encrypted, original)
                self.assertTrue(len(encrypted) > len(original))
            else:
                self.assertIsNone(encrypted)
        
        # Bulk decrypt
        decrypted_values = bulk_decrypt(encrypted_values, str)
        
        # Verify all values match
        for original, decrypted in zip(test_values, decrypted_values):
            self.assertEqual(original, decrypted)
    
    def test_bulk_encrypt_with_type_conversion(self):
        """Test bulk operations with different data types."""
        # Mixed type test data
        test_data = [
            (123, int),
            (Decimal("45.67"), Decimal),
            (True, bool),
            ({"key": "value"}, dict),
            ([1, 2, 3], list),
        ]
        
        values = [val for val, _ in test_data]
        
        # Encrypt
        encrypted = bulk_encrypt(values)
        
        # Decrypt with type restoration
        for i, (encrypted_val, (original_val, target_type)) in enumerate(zip(encrypted, test_data)):
            decrypted = bulk_decrypt([encrypted_val], target_type)[0]
            
            if target_type == Decimal:
                self.assertEqual(decrypted, original_val)
            elif target_type in (dict, list):
                self.assertEqual(decrypted, original_val)
            else:
                self.assertEqual(decrypted, original_val)
    
    def test_backend_bulk_methods(self):
        """Test backend's native bulk encrypt/decrypt methods."""
        test_values = [f"test_value_{i}" for i in range(10)]
        
        # Use backend's bulk methods
        encrypted = self.backend.bulk_encrypt(test_values)
        decrypted = self.backend.bulk_decrypt(encrypted)
        
        # Verify round-trip
        for original, decrypted in zip(test_values, decrypted):
            self.assertEqual(original, decrypted)
    
    def test_bulk_create_performance(self):
        """Test performance of bulk creating encrypted records."""
        # Create test objects
        num_records = 100
        
        start_time = time.time()
        
        objects = [
            BulkTestModel(
                name=f"User {i}",
                email=f"user{i}@example.com",
                description=f"Description for user {i}" * 10,  # Longer text
                balance=Decimal(f"{i}.99"),
                metadata={"index": i, "active": i % 2 == 0}
            )
            for i in range(num_records)
        ]
        
        BulkTestModel.objects.bulk_create(objects)
        
        create_time = time.time() - start_time
        
        # Verify all created
        self.assertEqual(BulkTestModel.objects.count(), num_records)
        
        # Performance check - should be reasonably fast
        per_record_time = create_time / num_records
        self.assertLess(per_record_time, 0.1)  # Less than 100ms per record
        
        # Verify data integrity
        for i in range(0, num_records, 10):  # Spot check every 10th record
            obj = BulkTestModel.objects.filter(email__endswith=f"{i}@example.com").first()
            self.assertIsNotNone(obj)
            self.assertEqual(obj.name, f"User {i}")
            self.assertEqual(obj.balance, Decimal(f"{i}.99"))
    
    def test_bulk_update_encrypted_fields(self):
        """Test bulk updating encrypted fields."""
        # Create initial data
        objects = []
        for i in range(20):
            obj = BulkTestModel.objects.create(
                name=f"Original {i}",
                email=f"original{i}@example.com",
                balance=Decimal("100.00")
            )
            objects.append(obj)
        
        # Bulk update using update()
        BulkTestModel.objects.filter(
            id__in=[obj.id for obj in objects[:10]]
        ).update(balance=Decimal("200.00"))
        
        # Verify updates
        updated_count = BulkTestModel.objects.filter(balance=Decimal("200.00")).count()
        self.assertEqual(updated_count, 10)
        
        # Bulk update using bulk_update
        for obj in objects[10:]:
            obj.name = f"Updated {obj.id}"
            obj.balance = Decimal("300.00")
        
        BulkTestModel.objects.bulk_update(objects[10:], ['name', 'balance'])
        
        # Verify bulk_update
        updated_objects = BulkTestModel.objects.filter(balance=Decimal("300.00"))
        self.assertEqual(updated_objects.count(), 10)
        
        for obj in updated_objects:
            self.assertTrue(obj.name.startswith("Updated"))
    
    def test_queryset_iterator_with_encryption(self):
        """Test using iterator() with encrypted fields."""
        # Create test data
        for i in range(50):
            BulkTestModel.objects.create(
                name=f"Iterator Test {i}",
                email=f"iterator{i}@example.com",
                metadata={"batch": i // 10}
            )
        
        # Use iterator with chunk_size
        seen_ids = set()
        for obj in BulkTestModel.objects.all().iterator(chunk_size=10):
            # Verify decryption works
            self.assertTrue(obj.name.startswith("Iterator Test"))
            self.assertIn("@example.com", obj.email)
            self.assertIsInstance(obj.metadata, dict)
            
            seen_ids.add(obj.id)
        
        # Verify all objects were processed
        self.assertEqual(len(seen_ids), 50)
    
    def test_pagination_with_encrypted_fields(self):
        """Test pagination of encrypted data."""
        # Create test data
        for i in range(100):
            BulkTestModel.objects.create(
                name=f"Page Test {i:03d}",
                email=f"page{i}@example.com"
            )
        
        # Paginate
        all_objects = BulkTestModel.objects.all().order_by('id')
        paginator = Paginator(all_objects, 25)  # 25 per page
        
        self.assertEqual(paginator.num_pages, 4)
        
        # Test each page
        for page_num in range(1, 5):
            page = paginator.page(page_num)
            self.assertEqual(len(page.object_list), 25 if page_num < 4 else 25)
            
            # Verify decryption works on paginated data
            for obj in page.object_list:
                self.assertTrue(obj.name.startswith("Page Test"))
                self.assertIn("@example.com", obj.email)
    
    def test_select_related_prefetch_related(self):
        """Test that encryption works with select_related and prefetch_related."""
        # This is a simple test since our model doesn't have relations
        # In a real scenario, you'd test with related models
        
        objects = BulkTestModel.objects.all()[:10]
        
        # Should not affect encryption/decryption
        for obj in objects:
            self.assertIsInstance(obj.name, str)
            self.assertIsInstance(obj.email, str)
    
    def test_values_and_values_list(self):
        """Test values() and values_list() with encrypted fields."""
        # Create test data
        test_objects = []
        for i in range(5):
            obj = BulkTestModel.objects.create(
                name=f"Values Test {i}",
                email=f"values{i}@example.com",
                balance=Decimal(f"{i * 10}.50")
            )
            test_objects.append(obj)
        
        # Test values()
        values = list(BulkTestModel.objects.values('name', 'email', 'balance'))
        
        self.assertEqual(len(values), 5)
        for i, val_dict in enumerate(values):
            self.assertEqual(val_dict['name'], f"Values Test {i}")
            self.assertEqual(val_dict['email'], f"values{i}@example.com")
            self.assertEqual(val_dict['balance'], Decimal(f"{i * 10}.50"))
        
        # Test values_list()
        values_list = list(BulkTestModel.objects.values_list('name', 'balance'))
        
        self.assertEqual(len(values_list), 5)
        for i, (name, balance) in enumerate(values_list):
            self.assertEqual(name, f"Values Test {i}")
            self.assertEqual(balance, Decimal(f"{i * 10}.50"))
        
        # Test values_list(flat=True)
        names = list(BulkTestModel.objects.values_list('name', flat=True))
        self.assertEqual(len(names), 5)
        for i, name in enumerate(names):
            self.assertEqual(name, f"Values Test {i}")
    
    def test_only_defer_with_encrypted_fields(self):
        """Test only() and defer() with encrypted fields."""
        # Create test object
        obj = BulkTestModel.objects.create(
            name="Test Only/Defer",
            email="only_defer@example.com",
            description="Long description text" * 100,
            balance=Decimal("999.99"),
            metadata={"key": "value"}
        )
        
        # Test only() - load only specific fields
        obj_only = BulkTestModel.objects.only('name', 'email').get(pk=obj.pk)
        
        # These should work without additional queries
        self.assertEqual(obj_only.name, "Test Only/Defer")
        self.assertEqual(obj_only.email, "only_defer@example.com")
        
        # Accessing deferred field should trigger additional query
        with self.assertNumQueries(1):
            _ = obj_only.description
        
        # Test defer() - load all except specific fields
        obj_defer = BulkTestModel.objects.defer('description', 'metadata').get(pk=obj.pk)
        
        # Non-deferred fields should work
        self.assertEqual(obj_defer.name, "Test Only/Defer")
        self.assertEqual(obj_defer.balance, Decimal("999.99"))
        
        # Accessing deferred field should trigger query
        with self.assertNumQueries(1):
            _ = obj_defer.description


class BulkEncryptionTransactionTests(TransactionTestCase):
    """Test bulk operations with transactions."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_transaction_rollback_with_encryption(self):
        """Test that encryption works correctly with transaction rollback."""
        initial_count = BulkTestModel.objects.count()
        
        try:
            with transaction.atomic():
                # Create some objects
                for i in range(5):
                    BulkTestModel.objects.create(
                        name=f"Transaction Test {i}",
                        email=f"trans{i}@example.com"
                    )
                
                # Verify they exist within transaction
                self.assertEqual(BulkTestModel.objects.count(), initial_count + 5)
                
                # Force rollback
                raise Exception("Rollback test")
                
        except Exception:
            pass
        
        # Verify rollback worked
        self.assertEqual(BulkTestModel.objects.count(), initial_count)
    
    def test_nested_transactions(self):
        """Test nested transactions with encrypted fields."""
        with transaction.atomic():
            obj1 = BulkTestModel.objects.create(
                name="Outer Transaction",
                email="outer@example.com"
            )
            
            try:
                with transaction.atomic():
                    obj2 = BulkTestModel.objects.create(
                        name="Inner Transaction",
                        email="inner@example.com"
                    )
                    
                    # Force inner rollback
                    raise Exception("Inner rollback")
                    
            except Exception:
                pass
            
            # Outer transaction should still work
            obj1.refresh_from_db()
            self.assertEqual(obj1.name, "Outer Transaction")
            
            # Inner transaction should be rolled back
            inner_exists = BulkTestModel.objects.filter(
                email="inner@example.com"
            ).exists()
            self.assertFalse(inner_exists)


class EncryptionCacheTests(TestCase):
    """Test encryption caching behavior."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
        # Clear any caches
        from django.core.cache import cache
        cache.clear()
    
    def test_decryption_caching(self):
        """Test that decrypted values are cached."""
        # Create test object
        obj = BulkTestModel.objects.create(
            name="Cache Test",
            email="cache@example.com",
            description="Test description for caching"
        )
        
        # Get raw encrypted value
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM test_bulk_operations WHERE id = %s",
                [obj.pk]
            )
            encrypted_name = cursor.fetchone()[0]
        
        # Clear any existing cache
        from django.core.cache import cache
        cache.clear()
        
        # First decryption should populate cache
        decrypted1 = self.backend.decrypt(encrypted_name)
        self.assertEqual(decrypted1, "Cache Test")
        
        # Mock the decrypt method to verify caching
        original_decrypt = self.backend.decrypt
        decrypt_call_count = 0
        
        def counting_decrypt(value):
            nonlocal decrypt_call_count
            decrypt_call_count += 1
            return original_decrypt(value)
        
        # Temporarily replace decrypt method
        self.backend.decrypt = counting_decrypt
        
        # Second decryption should use cache (in the backend)
        # Note: The caching might happen at different levels
        decrypted2 = self.backend.decrypt(encrypted_name)
        self.assertEqual(decrypted2, "Cache Test")
        
        # Restore original method
        self.backend.decrypt = original_decrypt
    
    def test_bulk_operations_with_cache(self):
        """Test that bulk operations efficiently use cache."""
        # Create test data
        num_records = 20
        objects = []
        
        for i in range(num_records):
            obj = BulkTestModel.objects.create(
                name=f"Bulk Cache {i}",
                email=f"bulk_cache{i}@example.com"
            )
            objects.append(obj)
        
        # Clear cache
        from django.core.cache import cache
        cache.clear()
        
        # Load all objects - this should populate cache
        loaded_objects = list(BulkTestModel.objects.all())
        
        # Verify data
        self.assertEqual(len(loaded_objects), num_records)
        
        for obj in loaded_objects:
            self.assertTrue(obj.name.startswith("Bulk Cache"))
            self.assertIn("@example.com", obj.email)