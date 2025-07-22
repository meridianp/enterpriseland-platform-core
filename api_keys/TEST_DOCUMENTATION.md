# API Key System Test Documentation

This document provides comprehensive documentation for the API Key system test suite, covering functional testing, security testing, integration testing, and edge case testing.

## Test Suite Overview

The API Key test suite consists of multiple test files, each focusing on specific aspects of the system:

### 1. Core Functionality Tests (`tests.py`)
- **APIKeyModelTests**: Model functionality, CRUD operations, relationships
- **APIKeySecurityTests**: Basic security features, hashing, expiration
- **APIKeyUsageTests**: Usage tracking, rate limiting, analytics
- **APIKeyAuthenticationTests**: Authentication backend functionality
- **APIKeyPermissionTests**: Permission classes and scope checking
- **APIKeyMiddlewareTests**: Middleware functionality and integration
- **APIKeyViewSetTests**: REST API endpoints and responses
- **APIKeyManagementCommandTests**: Management command functionality
- **APIKeyEdgeCaseTests**: Concurrent operations, bulk operations, edge cases
- **APIKeyIntegrationTests**: Integration with other system components
- **APIKeyPerformanceTests**: Performance characteristics and benchmarks

### 2. Management Command Tests (`test_commands.py`)
- **CreateAPIKeyCommandTests**: Key creation via management command
- **ListAPIKeysCommandTests**: Key listing with various filters
- **RevokeAPIKeyCommandTests**: Key revocation with different criteria
- **RotateAPIKeysCommandTests**: Key rotation workflows
- **CommandIntegrationTests**: Multi-command workflows
- **CommandErrorHandlingTests**: Error handling and edge cases

### 3. Serializer Tests (`test_serializers.py`)
- **APIKeyCreateSerializerTests**: Key creation serialization and validation
- **APIKeySerializerTests**: Full key serialization
- **APIKeyListSerializerTests**: List view serialization
- **APIKeyUpdateSerializerTests**: Key update operations
- **APIKeyRotateSerializerTests**: Rotation parameter validation
- **APIKeyUsageSerializerTests**: Usage data serialization
- **APIKeyUsageStatsSerializerTests**: Statistics serialization
- **APIKeyResponseSerializerTests**: Response formatting
- **SerializerValidationTests**: Advanced validation scenarios
- **SerializerPerformanceTests**: Performance with large datasets

### 4. Security Tests (`test_security.py`)
- **CryptographicSecurityTests**: Key generation, hashing, cryptographic security
- **TimingAttackTests**: Protection against timing attacks
- **RateLimitingSecurityTests**: Rate limiting and abuse prevention
- **InputValidationSecurityTests**: Input validation and sanitization
- **AccessControlSecurityTests**: Access control and authorization
- **AuditLoggingSecurityTests**: Security audit logging
- **ConcurrencySecurityTests**: Security under concurrent access

## Running Tests

### Quick Start
```bash
# Run all API key tests
python manage.py test api_keys

# Run with verbose output
python manage.py test api_keys --verbosity=2

# Run specific test file
python manage.py test api_keys.test_security

# Run specific test class
python manage.py test api_keys.tests.APIKeyModelTests

# Run specific test method
python manage.py test api_keys.tests.APIKeyModelTests.test_create_user_api_key
```

### Using the Test Runner
```bash
# Run all tests with coverage
python api_keys/test_runner.py --coverage

# Run only security tests
python api_keys/test_runner.py --security

# Run only performance tests
python api_keys/test_runner.py --performance

# Run only integration tests
python api_keys/test_runner.py --integration
```

### Coverage Requirements
- **Minimum Coverage**: 90% line coverage
- **Target Coverage**: 95% line coverage
- **Branch Coverage**: 85% minimum

## Test Categories

### 1. Functional Testing

#### API Key Generation
- ✅ User API key creation with proper prefixes (`sk_live_`)
- ✅ Application API key creation with proper prefixes (`ak_live_`)
- ✅ Scope assignment and validation
- ✅ Expiration date calculation
- ✅ Rate limit configuration
- ✅ IP restriction setup
- ✅ Metadata attachment
- ✅ Group association

#### Authentication
- ✅ Bearer token authentication
- ✅ X-API-Key header authentication
- ✅ Query parameter authentication
- ✅ Key verification with and without prefixes
- ✅ Expired key rejection
- ✅ Inactive key rejection
- ✅ IP restriction enforcement

#### Key Rotation
- ✅ Automatic rotation with same settings
- ✅ Overlap period configuration
- ✅ Old key expiration
- ✅ Replacement relationship tracking
- ✅ Metadata preservation and augmentation

#### Usage Tracking
- ✅ Request logging with detailed metadata
- ✅ Performance metrics tracking
- ✅ IP address recording
- ✅ Error logging
- ✅ Usage count incrementation
- ✅ Last used timestamp updates

#### Rate Limiting
- ✅ Hourly rate limit enforcement
- ✅ Window-based calculation
- ✅ Per-key isolation
- ✅ Distributed request tracking
- ✅ Rate limit reset after window expiry

### 2. Security Testing

#### Cryptographic Security
- ✅ Secure key generation with sufficient entropy
- ✅ SHA-256 hashing of stored keys
- ✅ No plaintext storage of keys
- ✅ Cryptographically secure random generation
- ✅ Key uniqueness across large datasets
- ✅ Proper handling of key prefixes

#### Timing Attack Prevention
- ✅ Constant-time key comparison
- ✅ Consistent authentication timing
- ✅ Database lookup timing consistency
- ✅ Hash calculation timing uniformity

#### Input Validation
- ✅ SQL injection prevention
- ✅ XSS attack mitigation
- ✅ Path traversal prevention
- ✅ Command injection prevention
- ✅ Unicode handling security
- ✅ Special character sanitization

#### Access Control
- ✅ User key isolation
- ✅ Scope-based access control
- ✅ Privilege escalation prevention
- ✅ IP restriction bypass prevention
- ✅ Group-based isolation
- ✅ Role-based access control

#### Audit Logging
- ✅ Key creation logging
- ✅ Key rotation logging
- ✅ Key revocation logging
- ✅ Failed authentication logging
- ✅ Usage tracking integrity
- ✅ Security event monitoring

### 3. Integration Testing

#### Django Integration
- ✅ Django REST Framework compatibility
- ✅ Django authentication backend integration
- ✅ Django permission system integration
- ✅ Django middleware integration
- ✅ Django management command integration

#### Database Integration
- ✅ PostgreSQL compatibility
- ✅ Transaction handling
- ✅ Index utilization
- ✅ Query optimization
- ✅ Concurrent access handling

#### External System Integration
- ✅ JWT authentication coexistence
- ✅ Group filtering integration
- ✅ Audit logging integration
- ✅ Multi-tenancy support

#### API Endpoint Integration
- ✅ ViewSet functionality
- ✅ Serializer integration
- ✅ Permission checking
- ✅ Error handling
- ✅ Response formatting

### 4. Edge Case Testing

#### Concurrent Operations
- ✅ Simultaneous key verification
- ✅ Race condition handling
- ✅ Thread safety
- ✅ Database consistency
- ✅ Rate limiting under load

#### Bulk Operations
- ✅ Large dataset handling
- ✅ Bulk key creation
- ✅ Bulk key expiration
- ✅ Performance with many keys
- ✅ Memory efficiency

#### Error Conditions
- ✅ Invalid scope handling
- ✅ Database connection failures
- ✅ Network timeout handling
- ✅ Malformed input handling
- ✅ Resource exhaustion scenarios

#### Data Integrity
- ✅ Unicode character handling
- ✅ Timezone handling
- ✅ Data corruption prevention
- ✅ Backup and recovery scenarios

## Test Data and Fixtures

### User Fixtures
```python
# Standard test user
user = User.objects.create_user(
    username='testuser',
    email='test@example.com',
    password='testpass123'
)

# Admin user for permission testing
admin_user = User.objects.create_user(
    username='admin',
    email='admin@example.com',
    password='adminpass123',
    role=User.Role.ADMIN
)
```

### API Key Fixtures
```python
# Basic user API key
api_key, raw_key = APIKey.objects.create_key(
    user=user,
    name='Test Key',
    scopes=['read', 'write'],
    expires_in_days=30
)

# Application API key
app_key, app_raw = APIKey.objects.create_key(
    application_name='Test App',
    name='App Key',
    scopes=['admin'],
    rate_limit=5000
)

# IP-restricted key
restricted_key, restricted_raw = APIKey.objects.create_key(
    user=user,
    name='IP Restricted',
    scopes=['read'],
    allowed_ips=['192.168.1.100']
)
```

## Performance Benchmarks

### Key Verification Performance
- **Target**: < 10ms per verification
- **Test Load**: 100 concurrent verifications
- **Memory Usage**: < 100MB for 1000 keys

### Rate Limiting Performance
- **Target**: < 5ms per rate limit check
- **Test Load**: 1000 usage logs per key
- **Query Efficiency**: Uses database indexes

### Serialization Performance
- **Target**: < 1s for 100 keys
- **Bulk Operations**: < 10s for 1000 keys
- **Memory Efficiency**: Linear memory usage

## Security Baselines

### Cryptographic Standards
- **Key Length**: 32 characters (256 bits)
- **Hash Algorithm**: SHA-256
- **Random Generation**: `secrets` module
- **Timing Attacks**: < 5x timing variance

### Rate Limiting Standards
- **Default Limit**: 1000 requests/hour
- **Minimum Limit**: 1 request/hour
- **Maximum Limit**: 1,000,000 requests/hour
- **Window Accuracy**: ±1 minute

### Access Control Standards
- **Scope Validation**: Strict whitelist
- **IP Validation**: IPv4 and IPv6 support
- **Group Isolation**: 100% separation
- **Privilege Escalation**: Zero tolerance

## Continuous Integration

### Test Automation
```yaml
# GitHub Actions example
name: API Key Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install coverage
      - name: Run tests with coverage
        run: |
          python api_keys/test_runner.py --coverage
      - name: Upload coverage
        uses: codecov/codecov-action@v1
```

### Quality Gates
- **All tests must pass**: 100% pass rate
- **Coverage threshold**: 90% minimum
- **Security tests**: All security tests must pass
- **Performance tests**: Must meet benchmarks
- **No critical security vulnerabilities**: Zero tolerance

## Test Maintenance

### Adding New Tests
1. Identify the component being tested
2. Choose the appropriate test file
3. Follow existing naming conventions
4. Include both positive and negative test cases
5. Add performance considerations if applicable
6. Update this documentation

### Test Review Checklist
- [ ] Tests cover both happy path and error cases
- [ ] Security implications are tested
- [ ] Performance impact is considered
- [ ] Integration points are verified
- [ ] Edge cases are covered
- [ ] Documentation is updated

### Known Limitations
- **Database Dependency**: Tests require PostgreSQL for array fields
- **Time Sensitivity**: Some timing tests may be flaky on slow systems
- **Concurrency**: Limited by test database transaction handling
- **External Dependencies**: Some tests mock external services

## Troubleshooting Common Issues

### Test Database Issues
```bash
# Reset test database
python manage.py migrate --run-syncdb --settings=core.settings.test

# Clear cache
python manage.py clear_cache --settings=core.settings.test
```

### Coverage Issues
```bash
# Generate detailed coverage report
coverage run --source='api_keys' manage.py test api_keys
coverage report --show-missing
coverage html
```

### Performance Test Issues
```bash
# Run only fast tests
python manage.py test api_keys --exclude-tag=slow

# Run with profiling
python -m cProfile -o profile.stats manage.py test api_keys
```

### Security Test Issues
```bash
# Run security tests in isolation
python api_keys/test_runner.py --security

# Check for timing test stability
python manage.py test api_keys.test_security.TimingAttackTests --repeat=10
```

## Future Test Enhancements

### Planned Additions
- [ ] Fuzz testing for input validation
- [ ] Load testing with realistic traffic patterns
- [ ] Security penetration testing automation
- [ ] Cross-browser API testing
- [ ] Mobile API client testing

### Performance Improvements
- [ ] Parallel test execution optimization
- [ ] Test data factory optimization
- [ ] Mock service improvements
- [ ] Test database optimization

### Security Enhancements
- [ ] Automated security scanning integration
- [ ] Vulnerability assessment automation
- [ ] Compliance testing (SOC2, PCI, etc.)
- [ ] Threat modeling validation