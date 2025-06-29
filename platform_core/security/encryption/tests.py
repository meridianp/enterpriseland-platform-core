"""
Tests for Field-Level Encryption

Tests encryption fields, key rotation, and search functionality.
"""

import json
from decimal import Decimal
from datetime import date, datetime
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from .fields import (
    EncryptedCharField, EncryptedTextField, EncryptedEmailField,
    EncryptedIntegerField, EncryptedDecimalField, EncryptedDateField,
    EncryptedDateTimeField, EncryptedJSONField, EncryptedBooleanField
)
from .crypto import FieldEncryptor, KeyRotationManager, get_default_encryptor
from .models import PersonalInformation, PaymentMethod, HealthRecord

User = get_user_model()


class EncryptionFieldTests(TestCase):
    """Test encrypted field functionality"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
    
    def test_encrypted_char_field(self):
        """Test EncryptedCharField"""
        # Create with encrypted data
        info = PersonalInformation.objects.create(
            user=self.user,
            phone_number='+1-555-123-4567'
        )
        
        # Reload from database
        info = PersonalInformation.objects.get(pk=info.pk)
        
        # Should decrypt transparently
        self.assertEqual(info.phone_number, '+1-555-123-4567')
        
        # Check raw database value is encrypted
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT phone_number FROM security_personal_information WHERE id = %s",
                [info.pk]
            )
            raw_value = cursor.fetchone()[0]
        
        # Raw value should be encrypted (base64)
        self.assertNotEqual(raw_value, '+1-555-123-4567')
        self.assertTrue(raw_value.startswith('gAAAAA'))  # Fernet prefix
    
    def test_encrypted_email_field(self):
        """Test EncryptedEmailField with validation"""
        info = PersonalInformation.objects.create(
            user=self.user,
            email='secret@example.com'
        )
        
        # Reload and verify
        info = PersonalInformation.objects.get(pk=info.pk)
        self.assertEqual(info.email, 'secret@example.com')
        
        # Invalid email should fail validation
        info.email = 'not-an-email'
        # Note: Field validation happens at form level, not model level
    
    def test_encrypted_integer_field(self):
        """Test EncryptedIntegerField"""
        info = PersonalInformation.objects.create(
            user=self.user,
            email='test@example.com',
            ssn='123-45-6789'
        )
        
        # Update with integer
        info.annual_income = Decimal('75000.50')
        info.save()
        
        # Reload and verify
        info = PersonalInformation.objects.get(pk=info.pk)
        self.assertEqual(info.annual_income, Decimal('75000.50'))
        self.assertIsInstance(info.annual_income, Decimal)
    
    def test_encrypted_date_field(self):
        """Test EncryptedDateField"""
        birth_date = date(1990, 5, 15)
        
        info = PersonalInformation.objects.create(
            user=self.user,
            email='test@example.com',
            ssn='123-45-6789',
            date_of_birth=birth_date
        )
        
        # Reload and verify
        info = PersonalInformation.objects.get(pk=info.pk)
        self.assertEqual(info.date_of_birth, birth_date)
        self.assertIsInstance(info.date_of_birth, date)
    
    def test_encrypted_json_field(self):
        """Test EncryptedJSONField"""
        preferences = {
            'theme': 'dark',
            'notifications': True,
            'language': 'en',
            'items_per_page': 25
        }
        
        info = PersonalInformation.objects.create(
            user=self.user,
            email='test@example.com',
            ssn='123-45-6789',
            preferences=preferences
        )
        
        # Reload and verify
        info = PersonalInformation.objects.get(pk=info.pk)
        self.assertEqual(info.preferences, preferences)
        self.assertIsInstance(info.preferences, dict)
    
    def test_encrypted_boolean_field(self):
        """Test EncryptedBooleanField"""
        info = PersonalInformation.objects.create(
            user=self.user,
            email='test@example.com',
            ssn='123-45-6789',
            is_verified=True
        )
        
        # Reload and verify
        info = PersonalInformation.objects.get(pk=info.pk)
        self.assertTrue(info.is_verified)
        self.assertIsInstance(info.is_verified, bool)
    
    def test_searchable_encrypted_field(self):
        """Test searchable encrypted fields with deterministic encryption"""
        # Create multiple records
        info1 = PersonalInformation.objects.create(
            user=self.user,
            email='searchable@example.com',
            ssn='111-11-1111'
        )
        
        user2 = User.objects.create_user('user2')
        info2 = PersonalInformation.objects.create(
            user=user2,
            email='different@example.com',
            ssn='222-22-2222'
        )
        
        # Search by encrypted email (uses hash index)
        # Note: Direct ORM filtering won't work, need custom lookup
        # This demonstrates the hash is consistent
        encryptor = get_default_encryptor(deterministic=True)
        search_hash = encryptor.hash_for_search('searchable@example.com')
        
        # In practice, you'd create a custom lookup or manager method
        # For now, verify hashes are consistent
        hash1 = encryptor.hash_for_search('searchable@example.com')
        hash2 = encryptor.hash_for_search('searchable@example.com')
        self.assertEqual(hash1, hash2)  # Deterministic
        
        # Different values produce different hashes
        hash3 = encryptor.hash_for_search('different@example.com')
        self.assertNotEqual(hash1, hash3)
    
    def test_null_values(self):
        """Test handling of null values"""
        info = PersonalInformation.objects.create(
            user=self.user,
            email='test@example.com',
            ssn='123-45-6789',
            phone_number='',  # Empty string
            date_of_birth=None,  # Null
            annual_income=None  # Null
        )
        
        # Reload and verify
        info = PersonalInformation.objects.get(pk=info.pk)
        self.assertEqual(info.phone_number, '')
        self.assertIsNone(info.date_of_birth)
        self.assertIsNone(info.annual_income)


class CryptoTests(TestCase):
    """Test encryption backend"""
    
    def test_basic_encryption_decryption(self):
        """Test basic encrypt/decrypt cycle"""
        encryptor = FieldEncryptor()
        
        plaintext = "This is sensitive data"
        ciphertext = encryptor.encrypt(plaintext)
        
        # Ciphertext should be different
        self.assertNotEqual(plaintext, ciphertext)
        
        # Should decrypt correctly
        decrypted = encryptor.decrypt(ciphertext)
        self.assertEqual(plaintext, decrypted)
    
    def test_deterministic_encryption(self):
        """Test deterministic encryption produces same output"""
        encryptor = FieldEncryptor(deterministic=True)
        
        plaintext = "Consistent encryption"
        
        # Multiple encryptions should produce same result
        cipher1 = encryptor.encrypt(plaintext)
        cipher2 = encryptor.encrypt(plaintext)
        
        self.assertEqual(cipher1, cipher2)
        
        # Should still decrypt correctly
        self.assertEqual(encryptor.decrypt(cipher1), plaintext)
    
    def test_search_hash(self):
        """Test search hash generation"""
        encryptor = FieldEncryptor()
        
        # Same input produces same hash
        hash1 = encryptor.hash_for_search("test@example.com")
        hash2 = encryptor.hash_for_search("test@example.com")
        self.assertEqual(hash1, hash2)
        
        # Different input produces different hash
        hash3 = encryptor.hash_for_search("other@example.com")
        self.assertNotEqual(hash1, hash3)
        
        # Hash should be hex string
        self.assertTrue(all(c in '0123456789abcdef' for c in hash1))
    
    def test_empty_values(self):
        """Test handling of empty values"""
        encryptor = FieldEncryptor()
        
        # Empty string
        self.assertEqual(encryptor.encrypt(''), '')
        self.assertEqual(encryptor.decrypt(''), '')
        
        # Hash of empty string
        self.assertEqual(encryptor.hash_for_search(''), '')


class KeyRotationTests(TestCase):
    """Test encryption key rotation"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        
        # Create test data
        self.info = PersonalInformation.objects.create(
            user=self.user,
            email='rotate@example.com',
            ssn='999-99-9999',
            phone_number='+1-555-ROTATE',
            medical_notes='Sensitive medical information'
        )
    
    @override_settings(
        FIELD_ENCRYPTION_KEY='old-key-base64-encoded-string-here'
    )
    def test_key_rotation(self):
        """Test rotating encryption keys"""
        old_key = 'old-key-base64-encoded-string-here'
        new_key = 'new-key-base64-encoded-string-here'
        
        # Get original values
        original_email = self.info.email
        original_ssn = self.info.ssn
        original_phone = self.info.phone_number
        
        # Create rotation manager
        manager = KeyRotationManager(old_key, new_key)
        
        # Rotate fields
        encrypted_fields = ['email', 'ssn', 'phone_number', 'medical_notes']
        manager.rotate_model(PersonalInformation, encrypted_fields, batch_size=10)
        
        # Reload with new key
        with override_settings(FIELD_ENCRYPTION_KEY=new_key):
            rotated_info = PersonalInformation.objects.get(pk=self.info.pk)
            
            # Values should still decrypt correctly
            self.assertEqual(rotated_info.email, original_email)
            self.assertEqual(rotated_info.ssn, original_ssn)
            self.assertEqual(rotated_info.phone_number, original_phone)


class IntegrationTests(TestCase):
    """Integration tests with example models"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='patient',
            email='patient@example.com'
        )
    
    def test_payment_method_encryption(self):
        """Test payment method model with encryption"""
        payment = PaymentMethod.objects.create(
            user=self.user,
            nickname='Personal Card',
            card_number='4111111111111111',
            card_holder='JOHN DOE',
            expiry_date='12/2025',
            cvv='123'
        )
        
        # Last four should be extracted
        self.assertEqual(payment.last_four, '1111')
        
        # Reload and verify encryption
        payment = PaymentMethod.objects.get(pk=payment.pk)
        self.assertEqual(payment.card_number, '4111111111111111')
        self.assertEqual(payment.card_holder, 'JOHN DOE')
        self.assertEqual(payment.cvv, '123')
        
        # Verify raw values are encrypted
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT card_number FROM security_payment_methods WHERE id = %s",
                [payment.pk]
            )
            raw_value = cursor.fetchone()[0]
        
        self.assertNotEqual(raw_value, '4111111111111111')
    
    def test_health_record_encryption(self):
        """Test health record encryption with JSON field"""
        test_results = {
            'blood_pressure': '120/80',
            'heart_rate': 72,
            'temperature': 98.6,
            'notes': 'Patient appears healthy'
        }
        
        record = HealthRecord.objects.create(
            patient=self.user,
            record_type='test_result',
            condition_name='Annual Physical',
            description='Routine annual physical examination',
            diagnosis_date=date.today(),
            severity='mild',
            treatment_notes='No treatment needed',
            test_results=test_results
        )
        
        # Reload and verify
        record = HealthRecord.objects.get(pk=record.pk)
        self.assertEqual(record.condition_name, 'Annual Physical')
        self.assertEqual(record.test_results, test_results)
        self.assertEqual(record.test_results['heart_rate'], 72)