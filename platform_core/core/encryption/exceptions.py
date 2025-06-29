"""
Custom exceptions for the encryption framework.
"""


class EncryptionError(Exception):
    """Base exception for encryption-related errors."""
    pass


class DecryptionError(EncryptionError):
    """Raised when decryption fails."""
    pass


class KeyRotationError(EncryptionError):
    """Raised when key rotation fails."""
    pass


class KeyNotFoundError(EncryptionError):
    """Raised when a required encryption key is not found."""
    pass


class InvalidKeyVersionError(EncryptionError):
    """Raised when an invalid key version is requested."""
    pass


class EncryptionConfigurationError(EncryptionError):
    """Raised when encryption is misconfigured."""
    pass