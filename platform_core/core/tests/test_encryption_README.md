# Field-Level Encryption Test Suite

This directory contains comprehensive tests for the field-level encryption framework implemented in the EnterpriseLand platform.

## Test Coverage

The test suite covers all aspects of the encryption framework:

### 1. Field Types (`test_encryption_fields.py`)
- **All encrypted field types**: CharField, TextField, EmailField, DecimalField, JSONField, IntegerField, FloatField, BooleanField, DateField, DateTimeField
- **Data type preservation**: Ensures values maintain their type through encryption/decryption
- **Null/empty value handling**: Tests null values, empty strings, and default values
- **Special characters**: Unicode, emojis, newlines, HTML entities
- **Field options**: max_length expansion, searchable flag, field tracking
- **Validation**: Email validation, decimal precision, unique constraints

### 2. Key Rotation (`test_encryption_key_rotation.py`)
- **Key management**: Creation, storage, retrieval of encryption keys
- **Key rotation**: Rotating keys while maintaining data accessibility
- **Multiple key versions**: Supporting data encrypted with different key versions
- **Key stores**: Local, Database, AWS KMS, HashiCorp Vault (mocked)
- **Cache management**: Key caching and cache invalidation
- **Backward compatibility**: Reading data encrypted with old keys

### 3. Search Functionality (`test_encryption_search.py`)
- **Search hash generation**: Deterministic hashes for exact match queries
- **Case-insensitive search**: Normalized search for consistent results
- **Whitespace handling**: Trimming and normalization
- **Hash security**: No collisions, constant-time comparison
- **Performance**: Indexed search hash fields for fast queries
- **Migration**: Adding search capability to existing encrypted data

### 4. Bulk Operations (`test_encryption_bulk_operations.py`)
- **Bulk encryption/decryption**: Efficient batch processing
- **Bulk create/update**: Django's bulk_create and bulk_update
- **QuerySet operations**: iterator(), values(), values_list(), only(), defer()
- **Pagination**: Working with large datasets
- **Transactions**: Atomicity and rollback handling
- **Caching**: Performance optimization through caching

### 5. Data Migration (`test_encryption_migration.py`)
- **Field-by-field migration**: Gradual migration strategy
- **Batch processing**: Migrating large datasets with progress tracking
- **Zero-downtime migration**: Dual-write strategy for seamless transition
- **Rollback handling**: Managing failed migrations
- **Search hash generation**: Adding search capability to existing data
- **Compatibility**: Supporting mixed encrypted/unencrypted data

### 6. Management Command (`test_encryption_management_command.py`)
- **Test encryption**: Testing encryption/decryption functionality
- **Key generation**: Creating new encryption keys
- **Key listing**: Viewing all encryption keys
- **Key rotation**: Rotating keys with dry-run support
- **Configuration validation**: Checking encryption setup
- **Usage audit**: Analyzing encryption usage across models

### 7. Django Integration (`test_encryption_integration.py`)
- **Model integration**: Real-world usage with Django models
- **ORM compatibility**: All QuerySet methods and operations
- **Relations**: Foreign keys, reverse relations
- **Validation**: Model validation with encrypted fields
- **Transactions**: Atomicity and concurrent access
- **Complex data**: Nested JSON, multiple data types

## Running the Tests

### Run All Encryption Tests
```bash
python manage.py test core.tests.test_encryption_fields \
                     core.tests.test_encryption_key_rotation \
                     core.tests.test_encryption_search \
                     core.tests.test_encryption_bulk_operations \
                     core.tests.test_encryption_migration \
                     core.tests.test_encryption_management_command \
                     core.tests.test_encryption_integration
```

### Run Individual Test Modules
```bash
# Field tests only
python manage.py test core.tests.test_encryption_fields

# Key rotation tests
python manage.py test core.tests.test_encryption_key_rotation

# Search functionality tests
python manage.py test core.tests.test_encryption_search
```

### Run with Coverage
```bash
# Run with coverage report
coverage run --source=core.encryption manage.py test core.tests.test_encryption_*
coverage report
coverage html  # Generate HTML report
```

### Using the Test Runner Script
```bash
# Run all encryption tests
python core/tests/run_encryption_tests.py

# Run specific test modules
python core/tests/run_encryption_tests.py fields search

# Run with verbose output
python core/tests/run_encryption_tests.py --verbose

# Run with coverage
python core/tests/run_encryption_tests.py --coverage

# Combine options
python core/tests/run_encryption_tests.py -vc fields
```

## Test Environment Setup

The tests use the following test settings:

```python
ENCRYPTION_MASTER_KEY = 'dGVzdF9tYXN0ZXJfa2V5X2Zvcl91bml0X3Rlc3Rpbmcx'  # Test key
ENCRYPTION_BACKEND = 'aes'  # AES-256-GCM encryption
ENCRYPTION_KEY_STORE = 'local'  # Local key storage for tests
```

## Test Models

The test suite uses several test models to simulate real-world usage:

1. **EncryptedFieldTestModel**: Tests all field types
2. **SearchTestModel**: Tests searchable fields
3. **BulkTestModel**: Tests bulk operations
4. **KeyRotationTestModel**: Tests key rotation
5. **Customer/HealthRecord**: Integration test models simulating real PII/PHI encryption

## Performance Benchmarks

The tests include performance checks to ensure encryption doesn't significantly impact performance:

- Single record encryption: < 10ms
- Bulk operations: < 100ms per record
- Search operations: < 100ms for indexed queries
- Key rotation: Depends on data volume

## Edge Cases Covered

- Null and empty values
- Unicode and special characters
- Very large text fields (>10KB)
- Decimal precision preservation
- Date/time timezone handling
- JSON with nested structures
- Concurrent access
- Transaction rollbacks
- Migration failures
- Key rotation errors

## Security Considerations Tested

- Data is actually encrypted in database
- Search hashes are one-way (non-reversible)
- Timing attack resistance in hash comparison
- Key rotation maintains data accessibility
- Proper error handling without data leakage
- Cache security and invalidation

## Debugging Failed Tests

If tests fail, check:

1. **Database**: Ensure test database supports required features (PostgreSQL recommended)
2. **Settings**: Verify encryption settings are properly configured
3. **Dependencies**: Check cryptography package is installed
4. **Permissions**: Ensure write permissions for test database
5. **Key Configuration**: Verify test encryption key is set

## Contributing New Tests

When adding new encryption features, ensure you:

1. Add corresponding tests in the appropriate test file
2. Test both positive and negative cases
3. Include performance benchmarks for critical operations
4. Document any new test models or fixtures
5. Update this README with new test coverage

## Continuous Integration

These tests should be run as part of CI/CD pipeline:

```yaml
# Example GitHub Actions configuration
- name: Run Encryption Tests
  run: |
    python manage.py test core.tests.test_encryption_* --parallel
    
- name: Check Coverage
  run: |
    coverage run --source=core.encryption manage.py test core.tests.test_encryption_*
    coverage report --fail-under=90
```

## Known Limitations

1. **Distinct queries**: Won't work on encrypted data (each encryption is unique)
2. **Aggregations**: Can't aggregate encrypted numeric fields directly
3. **Full-text search**: Not supported on encrypted text fields
4. **Performance**: Encryption adds ~5-10ms overhead per field