"""
Integration tests for encryption with Django models and ORM.

Tests real-world usage scenarios with actual Django models.
"""

from django.test import TestCase, TransactionTestCase, override_settings
from django.db import models, transaction, connection
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import datetime, date

from platform_core.core.encryption.fields import (
    EncryptedCharField,
    EncryptedTextField,
    EncryptedEmailField,
    EncryptedDecimalField,
    EncryptedJSONField,
    EncryptedDateField,
)
from platform_core.core.encryption.backends import get_encryption_backend, reset_encryption_backend
from accounts.models import Group


# Test models that simulate real-world usage
class Customer(models.Model):
    """Customer model with PII encryption."""
    
    # Public fields
    customer_id = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    # Encrypted PII fields
    first_name = EncryptedCharField(max_length=50)
    last_name = EncryptedCharField(max_length=50)
    email = EncryptedEmailField(searchable=True, unique=True)
    phone = EncryptedCharField(max_length=20, searchable=True, null=True, blank=True)
    ssn = EncryptedCharField(max_length=11, searchable=True)
    date_of_birth = EncryptedDateField()
    
    # Encrypted sensitive data
    credit_card_last4 = EncryptedCharField(max_length=4, null=True, blank=True)
    annual_income = EncryptedDecimalField(max_digits=10, decimal_places=2, null=True)
    notes = EncryptedTextField(blank=True)
    preferences = EncryptedJSONField(default=dict, blank=True)
    
    class Meta:
        app_label = 'core'
        db_table = 'test_customer'
        indexes = [
            models.Index(fields=['customer_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.customer_id}: {self.first_name} {self.last_name}"
    
    def get_full_name(self):
        """Get decrypted full name."""
        return f"{self.first_name} {self.last_name}"


class HealthRecord(models.Model):
    """Health record model with HIPAA-compliant encryption."""
    
    # Relations
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='health_records')
    
    # Public fields
    record_number = models.CharField(max_length=50, unique=True)
    visit_date = models.DateField()
    
    # Encrypted health information
    diagnosis = EncryptedTextField()
    treatment = EncryptedTextField()
    medications = EncryptedJSONField(default=list)
    test_results = EncryptedJSONField(default=dict)
    physician_notes = EncryptedTextField(blank=True)
    
    # Encrypted vitals
    blood_pressure = EncryptedCharField(max_length=20, null=True, blank=True)
    weight = EncryptedDecimalField(max_digits=5, decimal_places=2, null=True)
    
    class Meta:
        app_label = 'core'
        db_table = 'test_health_record'
        ordering = ['-visit_date']


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
    ENCRYPTION_BACKEND='aes'
)
class EncryptionIntegrationTests(TestCase):
    """Integration tests for encryption with Django ORM."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
        
        # Create test data
        self.customer = Customer.objects.create(
            customer_id="CUST001",
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
            phone="+1-555-0123",
            ssn="123-45-6789",
            date_of_birth=date(1980, 5, 15),
            credit_card_last4="1234",
            annual_income=Decimal("75000.00"),
            notes="VIP customer, handle with care",
            preferences={
                "contact_method": "email",
                "newsletter": True,
                "language": "en"
            }
        )
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_model_creation_and_retrieval(self):
        """Test creating and retrieving encrypted model data."""
        # Verify data was saved
        self.assertIsNotNone(self.customer.pk)
        
        # Retrieve from database
        customer_from_db = Customer.objects.get(pk=self.customer.pk)
        
        # Verify all fields decrypt correctly
        self.assertEqual(customer_from_db.first_name, "John")
        self.assertEqual(customer_from_db.last_name, "Doe")
        self.assertEqual(customer_from_db.email, "john.doe@example.com")
        self.assertEqual(customer_from_db.phone, "+1-555-0123")
        self.assertEqual(customer_from_db.ssn, "123-45-6789")
        self.assertEqual(customer_from_db.date_of_birth, date(1980, 5, 15))
        self.assertEqual(customer_from_db.credit_card_last4, "1234")
        self.assertEqual(customer_from_db.annual_income, Decimal("75000.00"))
        self.assertEqual(customer_from_db.notes, "VIP customer, handle with care")
        self.assertEqual(customer_from_db.preferences["contact_method"], "email")
        
        # Verify data is encrypted in database
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT first_name, email, ssn FROM test_customer WHERE id = %s",
                [self.customer.pk]
            )
            row = cursor.fetchone()
            
            # Raw values should be encrypted
            self.assertNotEqual(row[0], "John")
            self.assertNotEqual(row[1], "john.doe@example.com")
            self.assertNotEqual(row[2], "123-45-6789")
    
    def test_searchable_field_queries(self):
        """Test querying searchable encrypted fields."""
        # Create additional customers
        Customer.objects.create(
            customer_id="CUST002",
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
            phone="+1-555-0456",
            ssn="987-65-4321",
            date_of_birth=date(1985, 8, 20)
        )
        
        # Search by email (searchable field)
        email_hash = self.backend.create_search_hash("jane.smith@example.com")
        found = Customer.objects.filter(email_search_hash=email_hash).first()
        
        self.assertIsNotNone(found)
        self.assertEqual(found.customer_id, "CUST002")
        self.assertEqual(found.email, "jane.smith@example.com")
        
        # Search by SSN (searchable field)
        ssn_hash = self.backend.create_search_hash("123-45-6789")
        found = Customer.objects.filter(ssn_search_hash=ssn_hash).first()
        
        self.assertIsNotNone(found)
        self.assertEqual(found.customer_id, "CUST001")
        self.assertEqual(found.ssn, "123-45-6789")
    
    def test_foreign_key_relations(self):
        """Test encrypted fields with foreign key relations."""
        # Create health records
        record1 = HealthRecord.objects.create(
            customer=self.customer,
            record_number="HR001",
            visit_date=date(2024, 1, 15),
            diagnosis="Hypertension",
            treatment="Prescribed medication and lifestyle changes",
            medications=["Lisinopril 10mg", "Aspirin 81mg"],
            test_results={
                "blood_pressure": "140/90",
                "cholesterol": 220,
                "glucose": 95
            },
            physician_notes="Patient responding well to treatment",
            blood_pressure="140/90",
            weight=Decimal("180.5")
        )
        
        record2 = HealthRecord.objects.create(
            customer=self.customer,
            record_number="HR002",
            visit_date=date(2024, 2, 15),
            diagnosis="Hypertension - Follow up",
            treatment="Continue current medication",
            medications=["Lisinopril 10mg", "Aspirin 81mg"],
            test_results={
                "blood_pressure": "130/85",
                "cholesterol": 200
            },
            blood_pressure="130/85",
            weight=Decimal("178.0")
        )
        
        # Query through relationship
        records = self.customer.health_records.all()
        self.assertEqual(records.count(), 2)
        
        # Verify encryption works through relationships
        latest_record = records.first()  # Ordered by -visit_date
        self.assertEqual(latest_record.record_number, "HR002")
        self.assertEqual(latest_record.diagnosis, "Hypertension - Follow up")
        self.assertEqual(latest_record.blood_pressure, "130/85")
        self.assertEqual(latest_record.weight, Decimal("178.0"))
        
        # Test reverse relationship
        customer_via_record = latest_record.customer
        self.assertEqual(customer_via_record.email, "john.doe@example.com")
    
    def test_queryset_methods(self):
        """Test various QuerySet methods with encrypted fields."""
        # Create more test data
        customers = []
        for i in range(10):
            customer = Customer.objects.create(
                customer_id=f"CUST{i:03d}",
                first_name=f"Customer{i}",
                last_name=f"Test{i}",
                email=f"customer{i}@example.com",
                ssn=f"{i:03d}-00-0000",
                date_of_birth=date(1990 + i, 1, 1),
                annual_income=Decimal(f"{50000 + i * 5000}.00") if i % 2 == 0 else None
            )
            customers.append(customer)
        
        # Test count()
        total_count = Customer.objects.count()
        self.assertGreaterEqual(total_count, 11)  # Original + 10 new
        
        # Test exists()
        exists = Customer.objects.filter(customer_id="CUST005").exists()
        self.assertTrue(exists)
        
        # Test first() and last()
        first_customer = Customer.objects.order_by('customer_id').first()
        last_customer = Customer.objects.order_by('customer_id').last()
        
        self.assertIsNotNone(first_customer)
        self.assertIsNotNone(last_customer)
        self.assertNotEqual(first_customer.pk, last_customer.pk)
        
        # Test filter with multiple conditions
        results = Customer.objects.filter(
            is_active=True,
            annual_income__isnull=False
        )
        
        self.assertGreater(results.count(), 0)
        
        # Test exclude()
        excluded = Customer.objects.exclude(customer_id="CUST001")
        self.assertEqual(excluded.count(), total_count - 1)
        
        # Test order_by() on non-encrypted field
        ordered = Customer.objects.order_by('-created_at')
        self.assertEqual(ordered.count(), total_count)
    
    def test_model_validation(self):
        """Test model validation with encrypted fields."""
        # Test unique constraint on encrypted email
        with self.assertRaises(Exception):  # IntegrityError
            Customer.objects.create(
                customer_id="CUSTDUP",
                first_name="Duplicate",
                last_name="Email",
                email="john.doe@example.com",  # Already exists
                ssn="999-99-9999",
                date_of_birth=date(1990, 1, 1)
            )
        
        # Test email validation
        customer = Customer(
            customer_id="CUSTINV",
            first_name="Invalid",
            last_name="Email",
            email="not-an-email",  # Invalid email
            ssn="888-88-8888",
            date_of_birth=date(1990, 1, 1)
        )
        
        with self.assertRaises(ValidationError):
            customer.full_clean()
    
    def test_model_update(self):
        """Test updating encrypted fields."""
        # Update single field
        self.customer.annual_income = Decimal("85000.00")
        self.customer.save()
        
        # Verify update
        updated = Customer.objects.get(pk=self.customer.pk)
        self.assertEqual(updated.annual_income, Decimal("85000.00"))
        
        # Update multiple fields
        Customer.objects.filter(pk=self.customer.pk).update(
            phone="+1-555-9999",
            notes="Updated notes for VIP customer"
        )
        
        # Verify updates
        updated = Customer.objects.get(pk=self.customer.pk)
        self.assertEqual(updated.phone, "+1-555-9999")
        self.assertEqual(updated.notes, "Updated notes for VIP customer")
        
        # Verify search hash was updated for searchable field
        phone_hash = self.backend.create_search_hash("+1-555-9999")
        found = Customer.objects.filter(phone_search_hash=phone_hash).first()
        self.assertEqual(found.pk, self.customer.pk)
    
    def test_model_deletion(self):
        """Test deleting models with encrypted fields."""
        customer_id = self.customer.customer_id
        customer_pk = self.customer.pk
        
        # Create related records
        HealthRecord.objects.create(
            customer=self.customer,
            record_number="HR-DEL-001",
            visit_date=date.today(),
            diagnosis="Test",
            treatment="Test"
        )
        
        # Delete customer (should cascade to health records)
        self.customer.delete()
        
        # Verify deletion
        self.assertFalse(Customer.objects.filter(pk=customer_pk).exists())
        self.assertFalse(HealthRecord.objects.filter(customer_id=customer_pk).exists())
        
        # Verify search hashes are also gone
        email_hash = self.backend.create_search_hash("john.doe@example.com")
        self.assertFalse(Customer.objects.filter(email_search_hash=email_hash).exists())
    
    def test_complex_json_operations(self):
        """Test complex operations on encrypted JSON fields."""
        # Create customer with complex preferences
        customer = Customer.objects.create(
            customer_id="CUST-JSON",
            first_name="JSON",
            last_name="Test",
            email="json.test@example.com",
            ssn="111-11-1111",
            date_of_birth=date(1990, 1, 1),
            preferences={
                "contact": {
                    "email": True,
                    "sms": False,
                    "phone": True
                },
                "interests": ["technology", "finance", "travel"],
                "settings": {
                    "theme": "dark",
                    "language": "en-US",
                    "timezone": "America/New_York"
                },
                "metadata": {
                    "source": "web",
                    "campaign": "summer2024",
                    "tags": ["vip", "early-adopter"]
                }
            }
        )
        
        # Retrieve and verify
        retrieved = Customer.objects.get(customer_id="CUST-JSON")
        
        # Access nested data
        self.assertTrue(retrieved.preferences["contact"]["email"])
        self.assertFalse(retrieved.preferences["contact"]["sms"])
        self.assertIn("technology", retrieved.preferences["interests"])
        self.assertEqual(retrieved.preferences["settings"]["theme"], "dark")
        self.assertIn("vip", retrieved.preferences["metadata"]["tags"])
        
        # Update JSON field
        retrieved.preferences["settings"]["theme"] = "light"
        retrieved.preferences["interests"].append("sports")
        retrieved.save()
        
        # Verify update
        updated = Customer.objects.get(customer_id="CUST-JSON")
        self.assertEqual(updated.preferences["settings"]["theme"], "light")
        self.assertIn("sports", updated.preferences["interests"])


class EncryptionTransactionTests(TransactionTestCase):
    """Test encryption with database transactions."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_transaction_atomicity(self):
        """Test that encryption works correctly with transaction atomicity."""
        initial_count = Customer.objects.count()
        
        try:
            with transaction.atomic():
                # Create customers
                c1 = Customer.objects.create(
                    customer_id="TRANS001",
                    first_name="Transaction",
                    last_name="Test1",
                    email="trans1@example.com",
                    ssn="111-11-1111",
                    date_of_birth=date(1990, 1, 1)
                )
                
                c2 = Customer.objects.create(
                    customer_id="TRANS002",
                    first_name="Transaction",
                    last_name="Test2",
                    email="trans2@example.com",
                    ssn="222-22-2222",
                    date_of_birth=date(1990, 2, 2)
                )
                
                # Create health record
                HealthRecord.objects.create(
                    customer=c1,
                    record_number="TRANS-HR001",
                    visit_date=date.today(),
                    diagnosis="Test diagnosis",
                    treatment="Test treatment"
                )
                
                # Force an error to trigger rollback
                raise Exception("Rollback test")
                
        except Exception:
            pass
        
        # Verify rollback
        self.assertEqual(Customer.objects.count(), initial_count)
        self.assertFalse(Customer.objects.filter(customer_id__startswith="TRANS").exists())
        self.assertFalse(HealthRecord.objects.filter(record_number="TRANS-HR001").exists())
    
    def test_concurrent_access(self):
        """Test concurrent access to encrypted fields."""
        # Create initial customer
        customer = Customer.objects.create(
            customer_id="CONCURRENT",
            first_name="Concurrent",
            last_name="Test",
            email="concurrent@example.com",
            ssn="333-33-3333",
            date_of_birth=date(1990, 3, 3),
            annual_income=Decimal("50000.00")
        )
        
        # Simulate concurrent updates
        # In a real test, this would use threading or multiprocessing
        
        # Update 1
        c1 = Customer.objects.get(pk=customer.pk)
        c1.annual_income = Decimal("60000.00")
        c1.save()
        
        # Update 2 (simulating another process)
        c2 = Customer.objects.get(pk=customer.pk)
        c2.notes = "Updated by concurrent process"
        c2.save()
        
        # Verify both updates succeeded
        final = Customer.objects.get(pk=customer.pk)
        self.assertEqual(final.annual_income, Decimal("60000.00"))
        self.assertEqual(final.notes, "Updated by concurrent process")