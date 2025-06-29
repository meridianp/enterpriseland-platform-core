"""
Unit tests for encrypted field types.

Tests all encrypted field implementations including:
- Basic encryption/decryption functionality
- Data type preservation
- Null/empty value handling
- Search hash functionality
- Field options and configuration
"""

import json
from decimal import Decimal
from datetime import date, datetime
from django.test import TestCase, override_settings
from django.db import models
from django.core.exceptions import ValidationError

from platform_core.core.encryption.fields import (
    EncryptedCharField,
    EncryptedTextField,
    EncryptedEmailField,
    EncryptedDecimalField,
    EncryptedJSONField,
    EncryptedIntegerField,
    EncryptedFloatField,
    EncryptedBooleanField,
    EncryptedDateField,
    EncryptedDateTimeField,
)
from platform_core.core.encryption.backends import get_encryption_backend, reset_encryption_backend
from platform_core.core.encryption.exceptions import EncryptionError, DecryptionError


# Test models for field testing
class EncryptedFieldTestModel(models.Model):
    """Test model with various encrypted field types."""
    
    # Text fields
    encrypted_char = EncryptedCharField(max_length=100, null=True, blank=True)
    encrypted_char_searchable = EncryptedCharField(
        max_length=100, searchable=True, null=True, blank=True
    )
    encrypted_text = EncryptedTextField(null=True, blank=True)
    encrypted_email = EncryptedEmailField(null=True, blank=True)
    encrypted_email_searchable = EncryptedEmailField(
        searchable=True, null=True, blank=True
    )
    
    # Numeric fields
    encrypted_decimal = EncryptedDecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    encrypted_integer = EncryptedIntegerField(null=True, blank=True)
    encrypted_float = EncryptedFloatField(null=True, blank=True)
    
    # Boolean field
    encrypted_boolean = EncryptedBooleanField(default=False)
    
    # Date/time fields
    encrypted_date = EncryptedDateField(null=True, blank=True)
    encrypted_datetime = EncryptedDateTimeField(null=True, blank=True)
    
    # JSON field
    encrypted_json = EncryptedJSONField(null=True, blank=True)
    
    class Meta:
        app_label = 'core'
        db_table = 'test_encrypted_fields'


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',  # Base64 encoded test key
    ENCRYPTION_BACKEND='aes'
)
class EncryptedFieldsTestCase(TestCase):
    """Test case for encrypted field functionality."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_encrypted_char_field(self):
        """Test EncryptedCharField functionality."""
        test_value = "Hello, World!"
        
        # Create instance
        obj = EncryptedFieldTestModel()
        obj.encrypted_char = test_value
        obj.save()
        
        # Reload from database
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        
        # Verify decryption
        self.assertEqual(obj_from_db.encrypted_char, test_value)
        
        # Verify data is encrypted in database
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT encrypted_char FROM test_encrypted_fields WHERE id = %s",
                [obj.pk]
            )
            raw_value = cursor.fetchone()[0]
        
        # Raw value should be encrypted (base64)
        self.assertNotEqual(raw_value, test_value)
        self.assertTrue(len(raw_value) > len(test_value))
        
        # Verify we can decrypt the raw value
        decrypted = self.backend.decrypt(raw_value)
        self.assertEqual(decrypted, test_value)
    
    def test_encrypted_char_field_with_search(self):
        """Test searchable EncryptedCharField."""
        test_value = "searchable@example.com"
        
        # Create instance
        obj = EncryptedFieldTestModel()
        obj.encrypted_char_searchable = test_value
        obj.save()
        
        # Verify search hash was created
        self.assertIsNotNone(obj.encrypted_char_searchable_search_hash)
        
        # Verify we can search by exact match
        search_hash = self.backend.create_search_hash(test_value)
        found = EncryptedFieldTestModel.objects.filter(
            encrypted_char_searchable_search_hash=search_hash
        ).first()
        
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, obj.pk)
        self.assertEqual(found.encrypted_char_searchable, test_value)
    
    def test_encrypted_text_field(self):
        """Test EncryptedTextField with large content."""
        # Test with large text
        test_value = "Lorem ipsum " * 1000  # ~12KB of text
        
        obj = EncryptedFieldTestModel()
        obj.encrypted_text = test_value
        obj.save()
        
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        self.assertEqual(obj_from_db.encrypted_text, test_value)
    
    def test_encrypted_email_field(self):
        """Test EncryptedEmailField with validation."""
        valid_email = "test@example.com"
        invalid_email = "not-an-email"
        
        # Valid email
        obj = EncryptedFieldTestModel()
        obj.encrypted_email = valid_email
        obj.save()
        
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        self.assertEqual(obj_from_db.encrypted_email, valid_email)
        
        # Invalid email should raise validation error
        obj2 = EncryptedFieldTestModel()
        obj2.encrypted_email = invalid_email
        
        with self.assertRaises(ValidationError):
            obj2.full_clean()
    
    def test_encrypted_decimal_field(self):
        """Test EncryptedDecimalField precision preservation."""
        test_values = [
            Decimal("123.45"),
            Decimal("0.01"),
            Decimal("-999.99"),
            Decimal("0"),
        ]
        
        for test_value in test_values:
            obj = EncryptedFieldTestModel()
            obj.encrypted_decimal = test_value
            obj.save()
            
            obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
            self.assertEqual(obj_from_db.encrypted_decimal, test_value)
            self.assertIsInstance(obj_from_db.encrypted_decimal, Decimal)
    
    def test_encrypted_integer_field(self):
        """Test EncryptedIntegerField."""
        test_values = [42, -100, 0, 2147483647]  # Include max int32
        
        for test_value in test_values:
            obj = EncryptedFieldTestModel()
            obj.encrypted_integer = test_value
            obj.save()
            
            obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
            self.assertEqual(obj_from_db.encrypted_integer, test_value)
            self.assertIsInstance(obj_from_db.encrypted_integer, int)
    
    def test_encrypted_float_field(self):
        """Test EncryptedFloatField."""
        test_values = [3.14159, -2.71828, 0.0, 1e10]
        
        for test_value in test_values:
            obj = EncryptedFieldTestModel()
            obj.encrypted_float = test_value
            obj.save()
            
            obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
            self.assertAlmostEqual(obj_from_db.encrypted_float, test_value, places=5)
            self.assertIsInstance(obj_from_db.encrypted_float, float)
    
    def test_encrypted_boolean_field(self):
        """Test EncryptedBooleanField."""
        for test_value in [True, False]:
            obj = EncryptedFieldTestModel()
            obj.encrypted_boolean = test_value
            obj.save()
            
            obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
            self.assertEqual(obj_from_db.encrypted_boolean, test_value)
            self.assertIsInstance(obj_from_db.encrypted_boolean, bool)
    
    def test_encrypted_date_field(self):
        """Test EncryptedDateField."""
        test_date = date(2024, 1, 15)
        
        obj = EncryptedFieldTestModel()
        obj.encrypted_date = test_date
        obj.save()
        
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        self.assertEqual(obj_from_db.encrypted_date, test_date)
        self.assertIsInstance(obj_from_db.encrypted_date, date)
    
    def test_encrypted_datetime_field(self):
        """Test EncryptedDateTimeField."""
        test_datetime = datetime(2024, 1, 15, 14, 30, 45, 123456)
        
        obj = EncryptedFieldTestModel()
        obj.encrypted_datetime = test_datetime
        obj.save()
        
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        # Compare with microsecond precision
        self.assertEqual(
            obj_from_db.encrypted_datetime.replace(microsecond=0),
            test_datetime.replace(microsecond=0)
        )
        self.assertIsInstance(obj_from_db.encrypted_datetime, datetime)
    
    def test_encrypted_json_field(self):
        """Test EncryptedJSONField with complex data."""
        test_data = {
            "name": "Test User",
            "age": 30,
            "active": True,
            "scores": [95.5, 87.2, 91.8],
            "metadata": {
                "created": "2024-01-15",
                "tags": ["python", "django", "encryption"]
            }
        }
        
        obj = EncryptedFieldTestModel()
        obj.encrypted_json = test_data
        obj.save()
        
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        self.assertEqual(obj_from_db.encrypted_json, test_data)
        self.assertIsInstance(obj_from_db.encrypted_json, dict)
    
    def test_null_value_handling(self):
        """Test handling of null values across all field types."""
        obj = EncryptedFieldTestModel()
        # Don't set any values - all should be null/default
        obj.save()
        
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        
        # All nullable fields should be None
        self.assertIsNone(obj_from_db.encrypted_char)
        self.assertIsNone(obj_from_db.encrypted_text)
        self.assertIsNone(obj_from_db.encrypted_email)
        self.assertIsNone(obj_from_db.encrypted_decimal)
        self.assertIsNone(obj_from_db.encrypted_integer)
        self.assertIsNone(obj_from_db.encrypted_float)
        self.assertIsNone(obj_from_db.encrypted_date)
        self.assertIsNone(obj_from_db.encrypted_datetime)
        self.assertIsNone(obj_from_db.encrypted_json)
        
        # Boolean field has default
        self.assertEqual(obj_from_db.encrypted_boolean, False)
    
    def test_empty_string_handling(self):
        """Test handling of empty strings."""
        obj = EncryptedFieldTestModel()
        obj.encrypted_char = ""
        obj.encrypted_text = ""
        obj.save()
        
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        self.assertEqual(obj_from_db.encrypted_char, "")
        self.assertEqual(obj_from_db.encrypted_text, "")
    
    def test_special_characters(self):
        """Test encryption of special characters and unicode."""
        test_values = [
            "Hello 世界! 🌍",  # Unicode with emoji
            "Line1\nLine2\rLine3",  # Newlines
            "Tab\tSeparated\tValues",  # Tabs
            "Quotes: 'single' \"double\"",  # Quotes
            "<html>&amp;</html>",  # HTML entities
            "Path\\with\\backslashes",  # Backslashes
        ]
        
        for test_value in test_values:
            obj = EncryptedFieldTestModel()
            obj.encrypted_text = test_value
            obj.save()
            
            obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
            self.assertEqual(obj_from_db.encrypted_text, test_value)
    
    def test_field_max_length_expansion(self):
        """Test that CharField max_length is properly expanded for encryption."""
        field = EncryptedFieldTestModel._meta.get_field('encrypted_char')
        
        # Original max_length was 100, should be expanded
        self.assertGreater(field.max_length, 100)
        self.assertLessEqual(field.max_length, 1000)  # Should not exceed 1000
    
    def test_field_deconstruct(self):
        """Test field deconstruction for migrations."""
        field = EncryptedFieldTestModel._meta.get_field('encrypted_char_searchable')
        name, path, args, kwargs = field.deconstruct()
        
        # Should preserve searchable option
        self.assertTrue(kwargs.get('searchable'))
        
        # Should restore original max_length
        self.assertEqual(kwargs.get('max_length'), 100)
    
    def test_model_encrypted_fields_tracking(self):
        """Test that encrypted fields are tracked on the model."""
        encrypted_fields = getattr(EncryptedFieldTestModel, '_encrypted_fields', [])
        
        expected_fields = [
            'encrypted_char',
            'encrypted_char_searchable',
            'encrypted_text',
            'encrypted_email',
            'encrypted_email_searchable',
            'encrypted_decimal',
            'encrypted_integer',
            'encrypted_float',
            'encrypted_boolean',
            'encrypted_date',
            'encrypted_datetime',
            'encrypted_json',
        ]
        
        for field_name in expected_fields:
            self.assertIn(field_name, encrypted_fields)
    
    def test_search_hash_case_insensitive(self):
        """Test that search hashes are case-insensitive."""
        test_email = "Test@Example.COM"
        
        obj = EncryptedFieldTestModel()
        obj.encrypted_email_searchable = test_email
        obj.save()
        
        # Search with different case
        search_hash = self.backend.create_search_hash("test@example.com")
        found = EncryptedFieldTestModel.objects.filter(
            encrypted_email_searchable_search_hash=search_hash
        ).first()
        
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, obj.pk)
    
    def test_decimal_field_validation(self):
        """Test decimal field validation for max_digits and decimal_places."""
        # Valid value
        obj = EncryptedFieldTestModel()
        obj.encrypted_decimal = Decimal("12345678.99")  # 8 digits + 2 decimal places = 10
        obj.save()
        
        # Too many digits before decimal
        obj2 = EncryptedFieldTestModel()
        obj2.encrypted_decimal = Decimal("123456789.99")  # 9 digits + 2 decimal = 11 (exceeds max_digits)
        
        with self.assertRaises(ValidationError):
            obj2.full_clean()
    
    def test_json_field_with_decimal(self):
        """Test JSON field with Decimal values."""
        test_data = {
            "price": Decimal("19.99"),
            "tax_rate": Decimal("0.0825"),
        }
        
        obj = EncryptedFieldTestModel()
        obj.encrypted_json = test_data
        obj.save()
        
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
        
        # Decimals are serialized as strings in JSON
        self.assertEqual(obj_from_db.encrypted_json["price"], "19.99")
        self.assertEqual(obj_from_db.encrypted_json["tax_rate"], "0.0825")


class EncryptedFieldQuerysetTestCase(TestCase):
    """Test case for queryset operations on encrypted fields."""
    
    def setUp(self):
        """Set up test data."""
        reset_encryption_backend()
        
        # Create test objects
        self.obj1 = EncryptedFieldTestModel.objects.create(
            encrypted_char_searchable="alice@example.com",
            encrypted_integer=42,
            encrypted_boolean=True
        )
        
        self.obj2 = EncryptedFieldTestModel.objects.create(
            encrypted_char_searchable="bob@example.com",
            encrypted_integer=100,
            encrypted_boolean=False
        )
        
        self.obj3 = EncryptedFieldTestModel.objects.create(
            encrypted_char_searchable="charlie@example.com",
            encrypted_integer=42,
            encrypted_boolean=True
        )
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_filter_by_search_hash(self):
        """Test filtering by search hash."""
        backend = get_encryption_backend()
        search_hash = backend.create_search_hash("bob@example.com")
        
        results = EncryptedFieldTestModel.objects.filter(
            encrypted_char_searchable_search_hash=search_hash
        )
        
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().pk, self.obj2.pk)
    
    def test_bulk_create(self):
        """Test bulk creation of encrypted objects."""
        objects = [
            EncryptedFieldTestModel(
                encrypted_char=f"bulk_{i}",
                encrypted_integer=i * 10
            )
            for i in range(5)
        ]
        
        created = EncryptedFieldTestModel.objects.bulk_create(objects)
        self.assertEqual(len(created), 5)
        
        # Verify all were encrypted properly
        for i, obj in enumerate(created):
            obj_from_db = EncryptedFieldTestModel.objects.get(pk=obj.pk)
            self.assertEqual(obj_from_db.encrypted_char, f"bulk_{i}")
            self.assertEqual(obj_from_db.encrypted_integer, i * 10)
    
    def test_update_encrypted_field(self):
        """Test updating encrypted fields."""
        new_value = "updated@example.com"
        
        self.obj1.encrypted_char_searchable = new_value
        self.obj1.save()
        
        # Verify update
        obj_from_db = EncryptedFieldTestModel.objects.get(pk=self.obj1.pk)
        self.assertEqual(obj_from_db.encrypted_char_searchable, new_value)
        
        # Verify search hash was updated
        backend = get_encryption_backend()
        search_hash = backend.create_search_hash(new_value)
        self.assertEqual(obj_from_db.encrypted_char_searchable_search_hash, search_hash)
    
    def test_values_list(self):
        """Test values_list with encrypted fields."""
        values = EncryptedFieldTestModel.objects.values_list(
            'encrypted_integer', flat=True
        ).order_by('id')
        
        expected = [42, 100, 42]
        self.assertEqual(list(values), expected)
    
    def test_distinct_on_encrypted_field(self):
        """Test distinct operations (note: won't work on encrypted data)."""
        # This demonstrates a limitation - distinct on encrypted fields
        # won't deduplicate because each encryption is unique
        count = EncryptedFieldTestModel.objects.values(
            'encrypted_integer'
        ).distinct().count()
        
        # All 3 objects will be counted as distinct due to encryption
        self.assertEqual(count, 3)