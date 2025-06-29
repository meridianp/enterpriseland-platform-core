"""
Field-level encryption framework for Django.

This module provides transparent encryption for sensitive fields in Django models
using AES-256-GCM encryption with support for key rotation and searchable fields.
"""

from .fields import (
    EncryptedCharField,
    EncryptedTextField,
    EncryptedEmailField,
    EncryptedDecimalField,
    EncryptedJSONField,
)
from .backends import get_encryption_backend, AESEncryptionBackend
from .keys import KeyManager, EncryptionKey
from .exceptions import (
    EncryptionError,
    DecryptionError,
    KeyRotationError,
    KeyNotFoundError,
)

__all__ = [
    # Fields
    'EncryptedCharField',
    'EncryptedTextField',
    'EncryptedEmailField',
    'EncryptedDecimalField',
    'EncryptedJSONField',
    
    # Backend
    'get_encryption_backend',
    'AESEncryptionBackend',
    
    # Key Management
    'KeyManager',
    'EncryptionKey',
    
    # Exceptions
    'EncryptionError',
    'DecryptionError',
    'KeyRotationError',
    'KeyNotFoundError',
]

# Version info
__version__ = '1.0.0'