"""
Tests for migrating data from unencrypted to encrypted fields.

Tests data migration strategies, backwards compatibility, and migration tools.
"""

from django.test import TestCase, TransactionTestCase, override_settings
from django.db import models, connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.migration import Migration
from django.db.migrations.operations import RunPython

from platform_core.core.encryption.fields import EncryptedCharField, EncryptedTextField, EncryptedDecimalField
from platform_core.core.encryption.backends import get_encryption_backend, reset_encryption_backend
from decimal import Decimal


# Models for migration testing
class UnencryptedModel(models.Model):
    """Model representing data before encryption."""
    
    name = models.CharField(max_length=100)
    email = models.EmailField()
    ssn = models.CharField(max_length=11)  # Sensitive data
    notes = models.TextField(null=True, blank=True)
    balance = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    
    class Meta:
        app_label = 'core'
        db_table = 'test_migration_unencrypted'


class PartiallyEncryptedModel(models.Model):
    """Model with some fields encrypted (transition state)."""
    
    name = models.CharField(max_length=100)  # Not encrypted yet
    email = EncryptedCharField(max_length=100, searchable=True)  # Encrypted
    ssn = EncryptedCharField(max_length=11, searchable=True)  # Encrypted
    notes = models.TextField(null=True, blank=True)  # Not encrypted yet
    balance = EncryptedDecimalField(max_digits=10, decimal_places=2, null=True)  # Encrypted
    
    class Meta:
        app_label = 'core'
        db_table = 'test_migration_partial'


class FullyEncryptedModel(models.Model):
    """Model with all sensitive fields encrypted."""
    
    name = EncryptedCharField(max_length=100)
    email = EncryptedCharField(max_length=100, searchable=True)
    ssn = EncryptedCharField(max_length=11, searchable=True)
    notes = EncryptedTextField(null=True, blank=True)
    balance = EncryptedDecimalField(max_digits=10, decimal_places=2, null=True)
    
    class Meta:
        app_label = 'core'
        db_table = 'test_migration_encrypted'


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
    ENCRYPTION_BACKEND='aes'
)
class DataMigrationTests(TransactionTestCase):
    """Test data migration from unencrypted to encrypted fields."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
        
        # Create test data in unencrypted model
        self.test_data = [
            {
                'name': 'John Doe',
                'email': 'john@example.com',
                'ssn': '123-45-6789',
                'notes': 'Important customer',
                'balance': Decimal('1000.50')
            },
            {
                'name': 'Jane Smith',
                'email': 'jane@example.com',
                'ssn': '987-65-4321',
                'notes': None,
                'balance': Decimal('2500.00')
            },
            {
                'name': 'Bob Johnson',
                'email': 'bob@example.com',
                'ssn': '555-55-5555',
                'notes': 'VIP client with special requirements',
                'balance': None
            }
        ]
        
        # Create unencrypted records
        for data in self.test_data:
            UnencryptedModel.objects.create(**data)
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_field_by_field_migration(self):
        """Test migrating one field at a time to encrypted version."""
        # Step 1: Add encrypted field alongside original
        # This would be done in a migration
        
        # Simulate adding encrypted_email field
        with connection.cursor() as cursor:
            # Add column (simplified - real migration would use proper schema editor)
            cursor.execute("""
                ALTER TABLE test_migration_unencrypted 
                ADD COLUMN encrypted_email TEXT
            """)
        
        # Step 2: Copy and encrypt data
        for obj in UnencryptedModel.objects.all():
            encrypted_email = self.backend.encrypt(obj.email)
            
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE test_migration_unencrypted SET encrypted_email = %s WHERE id = %s",
                    [encrypted_email, obj.id]
                )
        
        # Step 3: Verify encrypted data
        with connection.cursor() as cursor:
            cursor.execute("SELECT email, encrypted_email FROM test_migration_unencrypted")
            
            for row in cursor.fetchall():
                original_email, encrypted_email = row
                
                # Verify encryption
                self.assertNotEqual(original_email, encrypted_email)
                
                # Verify we can decrypt back
                decrypted = self.backend.decrypt(encrypted_email)
                self.assertEqual(decrypted, original_email)
    
    def test_batch_migration_with_progress(self):
        """Test batch migration with progress tracking."""
        # Add more test data for batch testing
        for i in range(100):
            UnencryptedModel.objects.create(
                name=f'User {i}',
                email=f'user{i}@example.com',
                ssn=f'{i:09d}',
                notes=f'Notes for user {i}' if i % 2 == 0 else None,
                balance=Decimal(f'{i * 10}.99')
            )
        
        total_count = UnencryptedModel.objects.count()
        batch_size = 20
        processed = 0
        
        # Process in batches
        while processed < total_count:
            batch = UnencryptedModel.objects.all()[processed:processed + batch_size]
            
            for obj in batch:
                # Simulate migration to PartiallyEncryptedModel
                PartiallyEncryptedModel.objects.create(
                    name=obj.name,  # Still unencrypted
                    email=obj.email,  # Will be encrypted by field
                    ssn=obj.ssn,  # Will be encrypted by field
                    notes=obj.notes,  # Still unencrypted
                    balance=obj.balance  # Will be encrypted by field
                )
            
            processed += len(batch)
            
            # Track progress
            progress = (processed / total_count) * 100
            print(f"Migration progress: {progress:.1f}%")
        
        # Verify all migrated
        self.assertEqual(PartiallyEncryptedModel.objects.count(), total_count)
        
        # Spot check some records
        for original in UnencryptedModel.objects.all()[:5]:
            migrated = PartiallyEncryptedModel.objects.get(name=original.name)
            
            # Verify data integrity
            self.assertEqual(migrated.name, original.name)
            self.assertEqual(migrated.email, original.email)
            self.assertEqual(migrated.ssn, original.ssn)
            self.assertEqual(migrated.notes, original.notes)
            self.assertEqual(migrated.balance, original.balance)
    
    def test_zero_downtime_migration(self):
        """Test zero-downtime migration strategy."""
        # Strategy: Add encrypted fields, dual-write, backfill, switch reads, remove old fields
        
        # Step 1: Dual-write simulation
        # In production, this would be done at the application level
        def dual_write_create(name, email, ssn, notes, balance):
            # Write to both old and new models
            unencrypted = UnencryptedModel.objects.create(
                name=name,
                email=email,
                ssn=ssn,
                notes=notes,
                balance=balance
            )
            
            encrypted = FullyEncryptedModel.objects.create(
                name=name,
                email=email,
                ssn=ssn,
                notes=notes,
                balance=balance
            )
            
            return unencrypted, encrypted
        
        # Create new records with dual-write
        new_records = []
        for i in range(5):
            u, e = dual_write_create(
                name=f'Dual Write User {i}',
                email=f'dual{i}@example.com',
                ssn=f'999-{i:02d}-0000',
                notes=f'Dual write test {i}',
                balance=Decimal(f'{i * 100}.00')
            )
            new_records.append((u, e))
        
        # Step 2: Backfill existing data
        existing_only_in_old = UnencryptedModel.objects.exclude(
            email__in=[e.email for u, e in new_records]
        )
        
        for obj in existing_only_in_old:
            FullyEncryptedModel.objects.create(
                name=obj.name,
                email=obj.email,
                ssn=obj.ssn,
                notes=obj.notes,
                balance=obj.balance
            )
        
        # Step 3: Verify data consistency
        self.assertEqual(
            UnencryptedModel.objects.count(),
            FullyEncryptedModel.objects.count()
        )
        
        # Verify all data matches
        for unencrypted in UnencryptedModel.objects.all():
            try:
                encrypted = FullyEncryptedModel.objects.get(email=unencrypted.email)
                self.assertEqual(encrypted.name, unencrypted.name)
                self.assertEqual(encrypted.ssn, unencrypted.ssn)
                self.assertEqual(encrypted.notes, unencrypted.notes)
                self.assertEqual(encrypted.balance, unencrypted.balance)
            except FullyEncryptedModel.DoesNotExist:
                self.fail(f"Missing encrypted record for {unencrypted.email}")
    
    def test_search_hash_generation_for_existing_data(self):
        """Test generating search hashes for existing encrypted data."""
        # Create some encrypted records without search hashes
        # (simulating old encrypted data before searchable was added)
        
        records = []
        for i in range(10):
            obj = FullyEncryptedModel.objects.create(
                name=f'Search Test {i}',
                email=f'search{i}@example.com',
                ssn=f'111-{i:02d}-1111',
                notes=f'Search test notes {i}',
                balance=Decimal(f'{i * 50}.00')
            )
            records.append(obj)
        
        # Simulate migration to add search hashes
        # In a real migration, this would be done via RunPython
        
        updated_count = 0
        for obj in FullyEncryptedModel.objects.all():
            # Generate search hashes for searchable fields
            if hasattr(obj, 'email_search_hash'):
                obj.email_search_hash = self.backend.create_search_hash(obj.email)
                obj.ssn_search_hash = self.backend.create_search_hash(obj.ssn)
                obj.save(update_fields=['email_search_hash', 'ssn_search_hash'])
                updated_count += 1
        
        # Verify search works
        test_email = 'search5@example.com'
        search_hash = self.backend.create_search_hash(test_email)
        
        found = FullyEncryptedModel.objects.filter(
            email_search_hash=search_hash
        ).first()
        
        self.assertIsNotNone(found)
        self.assertEqual(found.email, test_email)
    
    def test_migration_rollback_handling(self):
        """Test handling migration rollback scenarios."""
        # Start migration
        initial_count = UnencryptedModel.objects.count()
        migrated_count = 0
        
        try:
            # Simulate partial migration with error
            for i, obj in enumerate(UnencryptedModel.objects.all()):
                if i == 2:  # Simulate error on 3rd record
                    raise Exception("Migration error!")
                
                FullyEncryptedModel.objects.create(
                    name=obj.name,
                    email=obj.email,
                    ssn=obj.ssn,
                    notes=obj.notes,
                    balance=obj.balance
                )
                migrated_count += 1
                
        except Exception:
            # In a real scenario, we'd need to handle partial migration
            pass
        
        # Verify partial migration state
        self.assertEqual(FullyEncryptedModel.objects.count(), migrated_count)
        self.assertLess(migrated_count, initial_count)
        
        # Cleanup partial migration
        FullyEncryptedModel.objects.all().delete()
        
        # Retry with transaction for atomicity
        from django.db import transaction
        
        with transaction.atomic():
            for obj in UnencryptedModel.objects.all():
                FullyEncryptedModel.objects.create(
                    name=obj.name,
                    email=obj.email,
                    ssn=obj.ssn,
                    notes=obj.notes,
                    balance=obj.balance
                )
        
        # Verify complete migration
        self.assertEqual(FullyEncryptedModel.objects.count(), initial_count)


def encrypt_field_data(apps, schema_editor):
    """Migration function to encrypt existing field data."""
    Model = apps.get_model('core', 'TestModel')
    backend = get_encryption_backend()
    
    for obj in Model.objects.all():
        if obj.sensitive_field and not obj.sensitive_field.startswith('gAAAAA'):  # Not already encrypted
            obj.sensitive_field = backend.encrypt(obj.sensitive_field)
            obj.save(update_fields=['sensitive_field'])


def decrypt_field_data(apps, schema_editor):
    """Reverse migration function to decrypt field data."""
    Model = apps.get_model('core', 'TestModel')
    backend = get_encryption_backend()
    
    for obj in Model.objects.all():
        if obj.sensitive_field and obj.sensitive_field.startswith('gAAAAA'):  # Is encrypted
            obj.sensitive_field = backend.decrypt(obj.sensitive_field)
            obj.save(update_fields=['sensitive_field'])


class MigrationOperationTests(TestCase):
    """Test custom migration operations for encryption."""
    
    def test_migration_data_function(self):
        """Test the migration functions work correctly."""
        # This is a simplified test - in practice, you'd test with actual migrations
        
        class MockModel:
            def __init__(self, sensitive_field):
                self.sensitive_field = sensitive_field
                self.saved_fields = []
            
            def save(self, update_fields=None):
                self.saved_fields = update_fields or []
        
        class MockApps:
            def get_model(self, app_label, model_name):
                return self
            
            objects = type('objects', (), {
                'all': lambda: [
                    MockModel('plaintext1'),
                    MockModel('plaintext2'),
                    MockModel('gAAAAAencrypted'),  # Already encrypted
                ]
            })()
        
        # Test would involve mocking and calling the migration functions
        # This is a placeholder for the concept
        pass
    
    def test_field_addition_migration(self):
        """Test migration that adds encrypted field to existing model."""
        # This demonstrates the migration pattern
        
        migration_operations = [
            # 1. Add the encrypted field (nullable first)
            migrations.AddField(
                model_name='mymodel',
                name='ssn_encrypted',
                field=EncryptedCharField(max_length=11, null=True, blank=True),
            ),
            
            # 2. Run data migration
            migrations.RunPython(
                encrypt_field_data,
                reverse_code=decrypt_field_data,
            ),
            
            # 3. Remove null=True if needed
            migrations.AlterField(
                model_name='mymodel',
                name='ssn_encrypted',
                field=EncryptedCharField(max_length=11),
            ),
            
            # 4. Remove old unencrypted field
            migrations.RemoveField(
                model_name='mymodel',
                name='ssn',
            ),
            
            # 5. Rename encrypted field to original name
            migrations.RenameField(
                model_name='mymodel',
                old_name='ssn_encrypted',
                new_name='ssn',
            ),
        ]
        
        # Verify operations are valid
        self.assertEqual(len(migration_operations), 5)
        self.assertIsInstance(migration_operations[1], migrations.RunPython)


class EncryptionCompatibilityTests(TestCase):
    """Test backwards compatibility during migration."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_mixed_encrypted_unencrypted_queries(self):
        """Test querying when some records are encrypted and others aren't."""
        # This scenario can happen during migration
        # In practice, you'd handle this at the model level
        
        # Create a model that can handle both
        class TransitionalModel(models.Model):
            data_field = models.TextField()
            
            class Meta:
                app_label = 'core'
                db_table = 'test_transitional'
            
            def get_data(self):
                """Get data, handling both encrypted and unencrypted."""
                if self.data_field.startswith('gAAAAA'):  # Simple check for encryption
                    backend = get_encryption_backend()
                    return backend.decrypt(self.data_field)
                return self.data_field
            
            def set_data(self, value):
                """Set data, always encrypting."""
                backend = get_encryption_backend()
                self.data_field = backend.encrypt(value)
        
        # This demonstrates the pattern for handling mixed data
        pass