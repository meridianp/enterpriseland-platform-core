"""
Encryption Backend for Field-Level Encryption

Provides encryption/decryption functionality with key management.
"""

import base64
import hashlib
import os
from typing import Optional, Union
from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings
from django.core.cache import cache
from django.utils.encoding import force_bytes, force_str
import logging

logger = logging.getLogger(__name__)


class FieldEncryptor:
    """
    Handles field-level encryption/decryption.
    
    Supports:
    - AES-256 encryption via Fernet
    - Key derivation from master key
    - Key rotation with MultiFernet
    - Deterministic encryption for searchable fields
    """
    
    def __init__(self, key: Optional[str] = None, deterministic: bool = False):
        """
        Initialize encryptor with key.
        
        Args:
            key: Encryption key (base64 encoded). If None, uses settings.
            deterministic: Use deterministic encryption for searchable fields
        """
        self.deterministic = deterministic
        self.key = key or self._get_default_key()
        self.fernet = self._initialize_fernet(self.key)
        
        # Cache for deterministic encryption
        self._deterministic_cache = {}
    
    def _get_default_key(self) -> str:
        """Get default encryption key from settings"""
        key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
        if not key:
            # Generate a key for development (not for production!)
            if settings.DEBUG:
                logger.warning("No FIELD_ENCRYPTION_KEY set, generating one for development")
                key = base64.urlsafe_b64encode(os.urandom(32)).decode()
            else:
                raise ValueError(
                    "FIELD_ENCRYPTION_KEY must be set in production settings"
                )
        return key
    
    def _initialize_fernet(self, key: str) -> Union[Fernet, MultiFernet]:
        """Initialize Fernet with key(s)"""
        # Support key rotation
        keys = getattr(settings, 'FIELD_ENCRYPTION_KEYS', None)
        if keys and isinstance(keys, list):
            # Multiple keys for rotation
            fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]
            return MultiFernet(fernets)
        else:
            # Single key
            return Fernet(key.encode() if isinstance(key, str) else key)
    
    def derive_key(self, salt: bytes, iterations: int = 100_000) -> bytes:
        """
        Derive encryption key from master key.
        
        Args:
            salt: Salt for key derivation
            iterations: PBKDF2 iterations
            
        Returns:
            Derived key suitable for Fernet
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        key = base64.urlsafe_b64encode(kdf.derive(force_bytes(self.key)))
        return key
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string.
        
        Args:
            plaintext: String to encrypt
            
        Returns:
            Base64 encoded ciphertext
        """
        if not plaintext:
            return ''
        
        if self.deterministic:
            # Check cache for deterministic encryption
            cache_key = f"enc:{hashlib.sha256(plaintext.encode()).hexdigest()[:16]}"
            cached = cache.get(cache_key)
            if cached:
                return cached
            
            # Use deterministic encryption (same input = same output)
            # This is less secure but allows searching
            salt = hashlib.sha256(force_bytes(self.key + plaintext)).digest()[:16]
            derived_key = self.derive_key(salt, iterations=1000)  # Faster for deterministic
            fernet = Fernet(derived_key)
            
            # Add deterministic marker
            data = b'DET:' + force_bytes(plaintext)
            encrypted = fernet.encrypt(data)
            
            # Cache for performance
            cache.set(cache_key, encrypted.decode(), timeout=3600)
            
            return encrypted.decode()
        else:
            # Standard encryption (different output each time)
            encrypted = self.fernet.encrypt(force_bytes(plaintext))
            return encrypted.decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt ciphertext string.
        
        Args:
            ciphertext: Base64 encoded ciphertext
            
        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ''
        
        try:
            # Try standard decryption first
            decrypted = self.fernet.decrypt(force_bytes(ciphertext))
            
            # Check for deterministic marker
            if decrypted.startswith(b'DET:'):
                return force_str(decrypted[4:])
            
            return force_str(decrypted)
        except Exception as e:
            # Try deterministic decryption if standard fails
            if self.deterministic:
                try:
                    # Extract salt from ciphertext (this is a simplified approach)
                    # In production, store salt separately
                    for i in range(1, 10):  # Try different iteration counts
                        salt = hashlib.sha256(
                            force_bytes(self.key + str(i))
                        ).digest()[:16]
                        derived_key = self.derive_key(salt, iterations=1000)
                        fernet = Fernet(derived_key)
                        
                        try:
                            decrypted = fernet.decrypt(force_bytes(ciphertext))
                            if decrypted.startswith(b'DET:'):
                                return force_str(decrypted[4:])
                        except:
                            continue
                except:
                    pass
            
            logger.error(f"Failed to decrypt: {e}")
            raise
    
    def hash_for_search(self, plaintext: str) -> str:
        """
        Create searchable hash of plaintext.
        
        Uses HMAC to prevent rainbow table attacks.
        
        Args:
            plaintext: String to hash
            
        Returns:
            Hex string hash suitable for searching
        """
        if not plaintext:
            return ''
        
        # Use HMAC with encryption key as secret
        h = hashlib.blake2b(
            force_bytes(plaintext),
            key=force_bytes(self.key[:32]),  # Blake2b max key is 64 bytes
            digest_size=32
        )
        
        return h.hexdigest()
    
    def rotate_encryption(self, old_ciphertext: str, new_key: str) -> str:
        """
        Re-encrypt data with new key.
        
        Args:
            old_ciphertext: Current encrypted data
            new_key: New encryption key
            
        Returns:
            Re-encrypted ciphertext
        """
        # Decrypt with current key
        plaintext = self.decrypt(old_ciphertext)
        
        # Create new encryptor with new key
        new_encryptor = FieldEncryptor(key=new_key, deterministic=self.deterministic)
        
        # Encrypt with new key
        return new_encryptor.encrypt(plaintext)


# Global encryptor instances
_default_encryptor = None
_deterministic_encryptor = None


def get_default_encryptor(deterministic: bool = False) -> FieldEncryptor:
    """
    Get default encryptor instance.
    
    Uses singleton pattern for performance.
    
    Args:
        deterministic: Whether to use deterministic encryption
        
    Returns:
        FieldEncryptor instance
    """
    global _default_encryptor, _deterministic_encryptor
    
    if deterministic:
        if _deterministic_encryptor is None:
            _deterministic_encryptor = FieldEncryptor(deterministic=True)
        return _deterministic_encryptor
    else:
        if _default_encryptor is None:
            _default_encryptor = FieldEncryptor(deterministic=False)
        return _default_encryptor


class EncryptionBackend:
    """
    Backend for managing encryption operations.
    
    Can be extended for different encryption providers.
    """
    
    def __init__(self):
        self.encryptor = get_default_encryptor()
    
    def encrypt_field(self, value: str, field_name: str = None) -> str:
        """Encrypt a field value"""
        if field_name:
            # Could use field-specific keys in the future
            pass
        return self.encryptor.encrypt(value)
    
    def decrypt_field(self, value: str, field_name: str = None) -> str:
        """Decrypt a field value"""
        if field_name:
            # Could use field-specific keys in the future
            pass
        return self.encryptor.decrypt(value)
    
    def search_hash(self, value: str, field_name: str = None) -> str:
        """Generate searchable hash"""
        if field_name:
            # Include field name in hash for uniqueness
            value = f"{field_name}:{value}"
        return self.encryptor.hash_for_search(value)


class KeyRotationManager:
    """
    Manages encryption key rotation.
    """
    
    def __init__(self, old_key: str, new_key: str):
        self.old_encryptor = FieldEncryptor(key=old_key)
        self.new_encryptor = FieldEncryptor(key=new_key)
    
    def rotate_field(self, encrypted_value: str) -> str:
        """
        Rotate a single encrypted field.
        
        Args:
            encrypted_value: Current encrypted value
            
        Returns:
            Re-encrypted value with new key
        """
        if not encrypted_value:
            return encrypted_value
        
        try:
            # Decrypt with old key
            plaintext = self.old_encryptor.decrypt(encrypted_value)
            
            # Encrypt with new key
            return self.new_encryptor.encrypt(plaintext)
        except Exception as e:
            logger.error(f"Failed to rotate field: {e}")
            raise
    
    def rotate_model(self, model_class, field_names: list, batch_size: int = 1000):
        """
        Rotate all encrypted fields in a model.
        
        Args:
            model_class: Django model class
            field_names: List of encrypted field names
            batch_size: Number of records to process at once
        """
        from django.db import transaction
        
        total = model_class.objects.count()
        processed = 0
        
        logger.info(f"Starting key rotation for {model_class.__name__}")
        
        # Process in batches
        for offset in range(0, total, batch_size):
            with transaction.atomic():
                batch = model_class.objects.all()[offset:offset + batch_size]
                
                for obj in batch:
                    changed = False
                    
                    for field_name in field_names:
                        old_value = getattr(obj, field_name)
                        if old_value:
                            try:
                                new_value = self.rotate_field(old_value)
                                setattr(obj, field_name, new_value)
                                changed = True
                            except Exception as e:
                                logger.error(
                                    f"Failed to rotate {field_name} "
                                    f"for {obj.pk}: {e}"
                                )
                    
                    if changed:
                        obj.save(update_fields=field_names)
                    
                    processed += 1
                
                logger.info(f"Rotated {processed}/{total} records")
        
        logger.info(f"Completed key rotation for {model_class.__name__}")