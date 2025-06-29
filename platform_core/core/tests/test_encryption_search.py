"""
Tests for searchable encrypted fields functionality.

Tests search hash generation, exact match queries, and search performance.
"""

from django.test import TestCase, override_settings
from django.db import models
from django.db.models import Q
import time

from platform_core.core.encryption.fields import EncryptedCharField, EncryptedEmailField, EncryptedTextField
from platform_core.core.encryption.backends import get_encryption_backend, reset_encryption_backend


class SearchTestModel(models.Model):
    """Model for testing searchable encrypted fields."""
    
    # Searchable fields
    email = EncryptedEmailField(searchable=True, unique=True)
    username = EncryptedCharField(max_length=50, searchable=True)
    phone = EncryptedCharField(max_length=20, searchable=True, null=True, blank=True)
    
    # Non-searchable fields
    full_name = EncryptedCharField(max_length=100, searchable=False)
    bio = EncryptedTextField(searchable=False, null=True, blank=True)
    
    # Regular field for comparison
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        app_label = 'core'
        db_table = 'test_search'
        indexes = [
            models.Index(fields=['email_search_hash']),
            models.Index(fields=['username_search_hash']),
        ]


@override_settings(
    ENCRYPTION_MASTER_KEY='dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx',
    ENCRYPTION_BACKEND='aes'
)
class SearchableFieldTests(TestCase):
    """Test searchable encrypted field functionality."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
        
        # Create test data
        self.users = []
        test_data = [
            ("alice@example.com", "alice", "+1234567890", "Alice Smith"),
            ("bob@example.com", "bob123", "+0987654321", "Bob Johnson"),
            ("charlie@example.com", "charlie", None, "Charlie Brown"),
            ("david@example.com", "david_99", "+1122334455", "David Wilson"),
            ("eve@example.com", "eve2024", "+9988776655", "Eve Davis"),
        ]
        
        for email, username, phone, name in test_data:
            user = SearchTestModel.objects.create(
                email=email,
                username=username,
                phone=phone,
                full_name=name,
                bio=f"Bio for {name}"
            )
            self.users.append(user)
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_search_hash_creation(self):
        """Test that search hashes are created for searchable fields."""
        user = self.users[0]
        
        # Searchable fields should have hashes
        self.assertIsNotNone(user.email_search_hash)
        self.assertIsNotNone(user.username_search_hash)
        
        # Verify hash format (base64)
        self.assertTrue(len(user.email_search_hash) > 20)
        self.assertTrue(len(user.username_search_hash) > 20)
        
        # Non-searchable fields should not have search hash fields
        self.assertFalse(hasattr(user, 'full_name_search_hash'))
        self.assertFalse(hasattr(user, 'bio_search_hash'))
    
    def test_exact_match_search(self):
        """Test exact match searching on encrypted fields."""
        # Search by email
        search_email = "bob@example.com"
        hash_value = self.backend.create_search_hash(search_email)
        
        found = SearchTestModel.objects.filter(
            email_search_hash=hash_value
        ).first()
        
        self.assertIsNotNone(found)
        self.assertEqual(found.email, search_email)
        self.assertEqual(found.username, "bob123")
    
    def test_case_insensitive_search(self):
        """Test that searches are case-insensitive."""
        # Search with different case
        search_values = [
            "Alice@Example.com",
            "alice@example.com",
            "ALICE@EXAMPLE.COM",
            "aLiCe@eXaMpLe.CoM"
        ]
        
        for search_value in search_values:
            hash_value = self.backend.create_search_hash(search_value)
            found = SearchTestModel.objects.filter(
                email_search_hash=hash_value
            ).first()
            
            self.assertIsNotNone(found, f"Failed to find with {search_value}")
            self.assertEqual(found.email.lower(), "alice@example.com")
    
    def test_search_with_whitespace(self):
        """Test that search normalizes whitespace."""
        # Create user with whitespace
        user = SearchTestModel.objects.create(
            email="spaces@example.com",
            username="  spaced_user  ",  # Leading/trailing spaces
            full_name="Test User"
        )
        
        # Search should normalize whitespace
        search_hash = self.backend.create_search_hash("spaced_user")
        found = SearchTestModel.objects.filter(
            username_search_hash=search_hash
        ).first()
        
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, user.pk)
    
    def test_null_value_search(self):
        """Test searching for null values."""
        # Charlie has null phone
        users_with_phone = SearchTestModel.objects.exclude(
            phone__isnull=True
        ).count()
        
        users_without_phone = SearchTestModel.objects.filter(
            phone__isnull=True
        ).count()
        
        self.assertEqual(users_with_phone, 4)
        self.assertEqual(users_without_phone, 1)
    
    def test_search_performance(self):
        """Test search performance with larger dataset."""
        # Create more test data
        for i in range(100):
            SearchTestModel.objects.create(
                email=f"user{i}@example.com",
                username=f"user_{i}",
                full_name=f"User Number {i}"
            )
        
        # Time exact match search
        search_email = "user50@example.com"
        search_hash = self.backend.create_search_hash(search_email)
        
        start_time = time.time()
        found = SearchTestModel.objects.filter(
            email_search_hash=search_hash
        ).first()
        search_time = time.time() - start_time
        
        self.assertIsNotNone(found)
        self.assertEqual(found.email, search_email)
        
        # Search should be fast (< 100ms)
        self.assertLess(search_time, 0.1)
    
    def test_update_maintains_search_hash(self):
        """Test that updating a searchable field updates its hash."""
        user = self.users[0]
        old_email = user.email
        old_hash = user.email_search_hash
        
        # Update email
        new_email = "alice.new@example.com"
        user.email = new_email
        user.save()
        
        # Reload from database
        user.refresh_from_db()
        
        # Verify email was updated
        self.assertEqual(user.email, new_email)
        
        # Verify hash was updated
        self.assertNotEqual(user.email_search_hash, old_hash)
        
        # Verify new hash works
        new_hash = self.backend.create_search_hash(new_email)
        self.assertEqual(user.email_search_hash, new_hash)
        
        # Old hash should not find anything
        old_result = SearchTestModel.objects.filter(
            email_search_hash=old_hash
        ).first()
        self.assertIsNone(old_result)
    
    def test_bulk_create_with_search_hashes(self):
        """Test bulk creation generates search hashes."""
        new_users = [
            SearchTestModel(
                email=f"bulk{i}@example.com",
                username=f"bulk_user_{i}",
                full_name=f"Bulk User {i}"
            )
            for i in range(5)
        ]
        
        created = SearchTestModel.objects.bulk_create(new_users)
        
        # Verify all have search hashes
        for i, user in enumerate(created):
            user_from_db = SearchTestModel.objects.get(pk=user.pk)
            
            expected_email = f"bulk{i}@example.com"
            self.assertEqual(user_from_db.email, expected_email)
            
            # Verify search hash exists and works
            search_hash = self.backend.create_search_hash(expected_email)
            found = SearchTestModel.objects.filter(
                email_search_hash=search_hash
            ).first()
            self.assertIsNotNone(found)
            self.assertEqual(found.pk, user.pk)
    
    def test_unique_constraint_with_search(self):
        """Test that unique constraints work with searchable fields."""
        # Try to create duplicate email
        with self.assertRaises(Exception):  # IntegrityError
            SearchTestModel.objects.create(
                email="alice@example.com",  # Already exists
                username="different_alice",
                full_name="Another Alice"
            )
    
    def test_complex_queries(self):
        """Test complex queries involving searchable fields."""
        # Search for specific user by email
        email_hash = self.backend.create_search_hash("david@example.com")
        
        # Combined query
        results = SearchTestModel.objects.filter(
            Q(email_search_hash=email_hash) |
            Q(phone__isnull=True)
        ).order_by('created_at')
        
        # Should find David (by email) and Charlie (null phone)
        self.assertEqual(results.count(), 2)
        
        usernames = [r.username for r in results]
        self.assertIn("david_99", usernames)
        self.assertIn("charlie", usernames)
    
    def test_search_hash_determinism(self):
        """Test that search hashes are deterministic."""
        test_value = "test@example.com"
        
        # Generate hash multiple times
        hashes = [
            self.backend.create_search_hash(test_value)
            for _ in range(10)
        ]
        
        # All should be the same
        self.assertEqual(len(set(hashes)), 1)
    
    def test_verify_search_hash(self):
        """Test search hash verification."""
        test_value = "verify@example.com"
        hash_value = self.backend.create_search_hash(test_value)
        
        # Verify correct value
        self.assertTrue(
            self.backend.verify_search_hash(test_value, hash_value)
        )
        
        # Verify incorrect value
        self.assertFalse(
            self.backend.verify_search_hash("wrong@example.com", hash_value)
        )
        
        # Verify with different case (should match)
        self.assertTrue(
            self.backend.verify_search_hash("VERIFY@EXAMPLE.COM", hash_value)
        )


class SearchableFieldMigrationTests(TestCase):
    """Test migrating existing data to searchable fields."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_generate_search_hashes_for_existing_data(self):
        """Test generating search hashes for existing encrypted data."""
        # Simulate existing data without search hashes
        # In real scenario, this would be done via data migration
        
        # Create objects
        users = []
        for i in range(10):
            user = SearchTestModel.objects.create(
                email=f"existing{i}@example.com",
                username=f"existing_{i}",
                full_name=f"Existing User {i}"
            )
            users.append(user)
        
        # Simulate migration process
        updated_count = 0
        for user in SearchTestModel.objects.all():
            # Generate search hashes if missing (normally they're auto-generated)
            if user.email and not user.email_search_hash:
                user.email_search_hash = self.backend.create_search_hash(user.email)
                updated_count += 1
            
            if user.username and not user.username_search_hash:
                user.username_search_hash = self.backend.create_search_hash(user.username)
                updated_count += 1
            
            if updated_count > 0:
                user.save(update_fields=['email_search_hash', 'username_search_hash'])
        
        # Verify all have search hashes
        for user in SearchTestModel.objects.all():
            self.assertIsNotNone(user.email_search_hash)
            self.assertIsNotNone(user.username_search_hash)
            
            # Verify searches work
            email_hash = self.backend.create_search_hash(user.email)
            found = SearchTestModel.objects.filter(
                email_search_hash=email_hash
            ).first()
            self.assertEqual(found.pk, user.pk)


class SearchHashCollisionTests(TestCase):
    """Test for hash collisions and security properties."""
    
    def setUp(self):
        """Set up test environment."""
        reset_encryption_backend()
        self.backend = get_encryption_backend()
    
    def tearDown(self):
        """Clean up after tests."""
        reset_encryption_backend()
    
    def test_no_hash_collisions(self):
        """Test that different values produce different hashes."""
        # Generate hashes for similar values
        test_values = [
            "user@example.com",
            "user@example.co",  # One character different
            "user@exampl3.com",  # One character substitution
            "user@example.com ",  # Trailing space
            "user@εxample.com",  # Unicode character
            "user+tag@example.com",  # Email with tag
        ]
        
        hashes = [self.backend.create_search_hash(val) for val in test_values]
        
        # All hashes should be unique
        self.assertEqual(len(hashes), len(set(hashes)))
    
    def test_hash_length_consistency(self):
        """Test that all hashes have consistent length."""
        test_values = [
            "a",  # Single character
            "a" * 100,  # Long string
            "unicode: 你好世界 🌍",  # Unicode
            "special!@#$%^&*()",  # Special characters
        ]
        
        hashes = [self.backend.create_search_hash(val) for val in test_values]
        
        # All should have the same length (base64 encoded SHA256)
        hash_lengths = [len(h) for h in hashes]
        self.assertEqual(len(set(hash_lengths)), 1)
    
    def test_timing_attack_resistance(self):
        """Test that hash verification is timing-attack resistant."""
        correct_value = "timing@example.com"
        correct_hash = self.backend.create_search_hash(correct_value)
        
        # Time correct verification
        import time
        correct_times = []
        for _ in range(100):
            start = time.perf_counter()
            self.backend.verify_search_hash(correct_value, correct_hash)
            correct_times.append(time.perf_counter() - start)
        
        # Time incorrect verification
        incorrect_times = []
        for _ in range(100):
            start = time.perf_counter()
            self.backend.verify_search_hash("wrong@example.com", correct_hash)
            incorrect_times.append(time.perf_counter() - start)
        
        # Average times should be similar (within 20%)
        avg_correct = sum(correct_times) / len(correct_times)
        avg_incorrect = sum(incorrect_times) / len(incorrect_times)
        
        ratio = max(avg_correct, avg_incorrect) / min(avg_correct, avg_incorrect)
        self.assertLess(ratio, 1.2)  # Less than 20% difference