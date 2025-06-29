"""
Core test module for audit logging system and field-level encryption.

This package contains comprehensive unit tests for:
- Audit log models and functionality
- Audit middleware behavior
- Django signals for automatic audit logging
- Field-level encryption framework
- Encryption key management and rotation
- Searchable encrypted fields
- Bulk encryption operations
- Data migration to encrypted fields
- Encryption management commands
- Integration with Django ORM
"""

# Import all test cases to make them discoverable
from .test_audit_logging import *
from .test_audit_middleware import *
from .test_audit_signals import *
from .test_encryption_fields import *
from .test_encryption_key_rotation import *
from .test_encryption_search import *
from .test_encryption_bulk_operations import *
from .test_encryption_migration import *
from .test_encryption_management_command import *
from .test_encryption_integration import *