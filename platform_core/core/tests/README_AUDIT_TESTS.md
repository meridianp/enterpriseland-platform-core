# Audit Logging Test Suite

Comprehensive test suite for the EnterpriseLand audit logging system, achieving >90% code coverage for all audit components.

## Test Files

### 1. `test_audit_logging.py`
Tests for audit log models and core functionality:
- **AuditLogModelTestCase**: Basic CRUD operations, formatting, critical action detection
- **AuditLogQuerySetTestCase**: Custom queryset methods and filtering
- **AuditLogEntryTestCase**: Field-level change tracking and sensitive data handling
- **SystemMetricsTestCase**: Performance and system metrics recording
- **AuditLogPerformanceTestCase**: Bulk operations and query performance
- **AuditLogEdgeCaseTestCase**: Edge cases, error handling, Unicode, concurrent access

### 2. `test_audit_middleware.py`
Tests for audit middleware and context management:
- **AuditContextTestCase**: Context manager functionality
- **UtilityFunctionTestCase**: IP extraction, field serialization, sensitive field detection
- **AuditMiddlewareTestCase**: Request/response processing, exception handling
- **AsyncAuditLoggingTestCase**: Asynchronous audit log creation
- **ManualAuditLoggingTestCase**: Manual audit logging functions
- **AuditConfigurationTestCase**: Settings and configuration handling
- **IPAddressExtractionTestCase**: IPv4/IPv6 and edge cases for IP extraction

### 3. `test_audit_signals.py`
Tests for Django signal handlers:
- **SignalSetupTestCase**: Signal connection verification
- **ModelChangeSignalTestCase**: Create, update, delete, M2M signals
- **AuthenticationSignalTestCase**: Login, logout, failed login signals
- **UtilityFunctionSignalTestCase**: Bulk operations, permissions, exports
- **AsyncSignalTestCase**: Asynchronous signal handling
- **SignalErrorHandlingTestCase**: Error resilience
- **SignalThreadSafetyTestCase**: Concurrent operations
- **RequestSignalTestCase**: Request lifecycle signals

## Running Tests

### Run All Audit Tests
```bash
python manage.py test core.tests -v 2
```

### Run Specific Test Module
```bash
# Model tests only
python manage.py test core.tests.test_audit_logging -v 2

# Middleware tests only
python manage.py test core.tests.test_audit_middleware -v 2

# Signal tests only
python manage.py test core.tests.test_audit_signals -v 2
```

### Run Specific Test Case
```bash
# Run only the performance tests
python manage.py test core.tests.test_audit_logging.AuditLogPerformanceTestCase -v 2

# Run only authentication signal tests
python manage.py test core.tests.test_audit_signals.AuthenticationSignalTestCase -v 2
```

### Run with Coverage
```bash
# Run all tests with coverage
coverage run --source='core' manage.py test core.tests

# Generate coverage report
coverage report -m

# Generate HTML coverage report
coverage html
```

### Use the Test Script
```bash
# Run comprehensive test suite with coverage reporting
./scripts/test_audit_logging.sh
```

## Test Coverage Goals

The test suite aims for >90% coverage of:
- `core/models.py` - Audit log models
- `core/middleware/audit.py` - Audit middleware
- `core/signals.py` - Django signals
- `core/management/commands/audit_report.py` - Management command

## Key Testing Patterns

### 1. Multi-Tenancy Testing
All tests verify group-based filtering:
```python
log = AuditLog.objects.create_log(
    action=AuditLog.Action.CREATE,
    group=self.group
)
# Verify logs are filtered by group
```

### 2. Sensitive Data Testing
Tests verify sensitive field masking:
```python
sensitive_changes = {
    'password': 'secret123',
    'api_token': 'token-xyz'
}
masked = audit_log.mask_sensitive_data()
self.assertEqual(masked['password'], '***MASKED***')
```

### 3. Performance Testing
Tests verify operation performance:
```python
# Bulk creation should complete quickly
start_time = time.time()
AuditLog.objects.bulk_create(logs)
duration = time.time() - start_time
self.assertLess(duration, 5.0)
```

### 4. Error Resilience Testing
Tests verify error handling doesn't crash the app:
```python
with patch('core.models.AuditLog.objects.create_log') as mock:
    mock.side_effect = Exception("Database error")
    # Operation should still succeed
    partner = DevelopmentPartner.objects.create(...)
    self.assertIsNotNone(partner.id)
```

### 5. Async Testing
Tests verify async audit logging:
```python
async def test_async_creation():
    await create_audit_log_async(
        action='CREATE',
        user=self.user
    )
```

### 6. Configuration Testing
Tests verify settings behavior:
```python
@override_settings(AUDIT_LOGGING={'ENABLED': False})
def test_auditing_disabled(self):
    # No logs should be created
```

## Test Data Setup

Each test class sets up minimal required data:
```python
def setUp(self):
    self.group = Group.objects.create(name="Test Group")
    self.user = User.objects.create_user(
        email="test@example.com",
        password="TestPass123!"
    )
    self.user.groups.add(self.group)
```

## Mocking External Dependencies

Tests mock external dependencies for isolation:
```python
@patch('core.middleware.audit.get_client_ip')
@patch('core.middleware.audit.get_user_agent')
def test_with_mocks(self, mock_user_agent, mock_client_ip):
    mock_client_ip.return_value = '192.168.1.1'
    mock_user_agent.return_value = 'TestBrowser/1.0'
```

## Edge Cases Covered

- Null values and empty strings
- Extremely long values (>1000 chars)
- Unicode and emoji handling
- Circular references
- Deleted object references
- Concurrent access
- IPv6 addresses
- Malformed headers
- Database errors
- No event loop scenarios

## Integration Points

The tests verify integration with:
- Django's signal system
- Django's middleware system
- Django's authentication system
- Django's ORM and GenericForeignKey
- Async/await functionality
- Thread-local storage
- JSON serialization
- Management commands