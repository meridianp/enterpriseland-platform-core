"""
Encryption backend implementations.
"""

import base64
import json
import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.backends import default_backend
from django.conf import settings
from django.core.cache import cache
from django.utils.functional import SimpleLazyObject

from .exceptions import EncryptionError, DecryptionError
from .keys import KeyManager

logger = logging.getLogger(__name__)


class AESEncryptionBackend:
    """
    AES-256-GCM encryption backend with authentication.
    
    Provides authenticated encryption using AES in GCM mode, which provides
    both confidentiality and authenticity of the encrypted data.
    """
    
    def __init__(self):
        """Initialize the encryption backend."""
        self.key_manager = KeyManager()
        self._cache_timeout = getattr(settings, 'ENCRYPTION_CACHE_TIMEOUT', 300)
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext using AES-256-GCM.
        
        Args:
            plaintext: The string to encrypt
            
        Returns:
            Base64-encoded encrypted data with metadata
            
        Raises:
            EncryptionError: If encryption fails
        """
        if not plaintext:
            return plaintext
        
        try:
            # Get current encryption key
            key = self.key_manager.get_current_key()
            
            # Generate random IV (96 bits for GCM)
            iv = os.urandom(12)
            
            # Create cipher
            cipher = Cipher(
                algorithms.AES(key.key_material),
                modes.GCM(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            
            # Encrypt data
            plaintext_bytes = plaintext.encode('utf-8')
            ciphertext = encryptor.update(plaintext_bytes) + encryptor.finalize()
            
            # Create encrypted data structure
            encrypted_data = {
                'v': key.version,  # Key version for rotation support
                'iv': base64.b64encode(iv).decode('utf-8'),
                'ct': base64.b64encode(ciphertext).decode('utf-8'),
                'tag': base64.b64encode(encryptor.tag).decode('utf-8')
            }
            
            # Return as base64-encoded JSON
            return base64.b64encode(
                json.dumps(encrypted_data).encode('utf-8')
            ).decode('utf-8')
            
        except Exception as e:
            logger.error(f"Encryption failed: {str(e)}")
            raise EncryptionError(f"Failed to encrypt data: {str(e)}")
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt ciphertext using appropriate key version.
        
        Args:
            ciphertext: Base64-encoded encrypted data
            
        Returns:
            Decrypted plaintext string
            
        Raises:
            DecryptionError: If decryption fails
        """
        if not ciphertext:
            return ciphertext
        
        # Check cache first
        cache_key = f"decrypted:{hash(ciphertext)}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        try:
            # Decode the encrypted data
            encrypted_data = json.loads(
                base64.b64decode(ciphertext.encode('utf-8'))
            )
            
            # Get the appropriate key version
            key = self.key_manager.get_key_by_version(encrypted_data['v'])
            
            # Decode components
            iv = base64.b64decode(encrypted_data['iv'])
            ct = base64.b64decode(encrypted_data['ct'])
            tag = base64.b64decode(encrypted_data['tag'])
            
            # Create cipher
            cipher = Cipher(
                algorithms.AES(key.key_material),
                modes.GCM(iv, tag),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            
            # Decrypt
            plaintext_bytes = decryptor.update(ct) + decryptor.finalize()
            plaintext = plaintext_bytes.decode('utf-8')
            
            # Cache the result
            cache.set(cache_key, plaintext, self._cache_timeout)
            
            return plaintext
            
        except Exception as e:
            logger.error(f"Decryption failed: {str(e)}")
            raise DecryptionError(f"Failed to decrypt data: {str(e)}")
    
    def create_search_hash(self, value: str) -> str:
        """
        Create searchable hash using HMAC.
        
        Creates a deterministic hash that can be used for exact match searches
        on encrypted fields.
        
        Args:
            value: The value to create a search hash for
            
        Returns:
            Base64-encoded hash suitable for searching
        """
        if not value:
            return value
        
        try:
            # Use a separate search key that doesn't rotate
            search_key = self.key_manager.get_search_key()
            
            # Create HMAC for searchable hash
            h = hmac.HMAC(search_key, hashes.SHA256(), backend=default_backend())
            
            # Normalize value for case-insensitive search
            normalized_value = value.lower().strip().encode('utf-8')
            h.update(normalized_value)
            
            # Return base64-encoded hash
            return base64.b64encode(h.finalize()).decode('utf-8')
            
        except Exception as e:
            logger.error(f"Failed to create search hash: {str(e)}")
            raise EncryptionError(f"Failed to create search hash: {str(e)}")
    
    def verify_search_hash(self, value: str, hash_to_verify: str) -> bool:
        """
        Verify that a value matches a search hash.
        
        Args:
            value: The plaintext value
            hash_to_verify: The hash to verify against
            
        Returns:
            True if the value matches the hash
        """
        try:
            computed_hash = self.create_search_hash(value)
            
            # Use constant-time comparison to prevent timing attacks
            import hmac as hmac_module
            return hmac_module.compare_digest(computed_hash, hash_to_verify)
            
        except Exception:
            return False
    
    def bulk_encrypt(self, plaintexts: list) -> list:
        """
        Efficiently encrypt multiple values.
        
        Args:
            plaintexts: List of strings to encrypt
            
        Returns:
            List of encrypted values
        """
        # Get key once for all operations
        key = self.key_manager.get_current_key()
        
        encrypted_values = []
        for plaintext in plaintexts:
            if plaintext is None:
                encrypted_values.append(None)
            else:
                encrypted_values.append(self.encrypt(plaintext))
        
        return encrypted_values
    
    def bulk_decrypt(self, ciphertexts: list) -> list:
        """
        Efficiently decrypt multiple values.
        
        Args:
            ciphertexts: List of encrypted values
            
        Returns:
            List of decrypted values
        """
        decrypted_values = []
        
        # Group by key version for efficiency
        by_version = {}
        for i, ciphertext in enumerate(ciphertexts):
            if ciphertext is None:
                continue
            
            try:
                encrypted_data = json.loads(
                    base64.b64decode(ciphertext.encode('utf-8'))
                )
                version = encrypted_data['v']
                
                if version not in by_version:
                    by_version[version] = []
                by_version[version].append((i, ciphertext))
                
            except Exception:
                decrypted_values.append(None)
        
        # Decrypt by version
        results = [None] * len(ciphertexts)
        
        for version, items in by_version.items():
            key = self.key_manager.get_key_by_version(version)
            
            for index, ciphertext in items:
                try:
                    results[index] = self.decrypt(ciphertext)
                except Exception:
                    results[index] = None
        
        return results


class FernetEncryptionBackend:
    """
    Alternative backend using Fernet symmetric encryption.
    
    Fernet is a simpler encryption scheme that may be preferred for
    some use cases. It provides authenticated encryption but with
    less flexibility than AES-GCM.
    """
    
    def __init__(self):
        """Initialize the Fernet backend."""
        from cryptography.fernet import Fernet
        
        self.key_manager = KeyManager()
        self._fernet_cache = {}
    
    def _get_fernet(self, key_version: Optional[int] = None):
        """Get Fernet instance for a key version."""
        from cryptography.fernet import Fernet
        
        if key_version is None:
            key = self.key_manager.get_current_key()
            key_version = key.version
        else:
            key = self.key_manager.get_key_by_version(key_version)
        
        if key_version not in self._fernet_cache:
            # Fernet requires a 32-byte key, base64-encoded
            fernet_key = base64.urlsafe_b64encode(key.key_material)
            self._fernet_cache[key_version] = Fernet(fernet_key)
        
        return self._fernet_cache[key_version], key_version
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt using Fernet."""
        if not plaintext:
            return plaintext
        
        try:
            fernet, version = self._get_fernet()
            
            # Encrypt
            encrypted = fernet.encrypt(plaintext.encode('utf-8'))
            
            # Add version information
            versioned_data = {
                'v': version,
                'data': base64.b64encode(encrypted).decode('utf-8')
            }
            
            return base64.b64encode(
                json.dumps(versioned_data).encode('utf-8')
            ).decode('utf-8')
            
        except Exception as e:
            raise EncryptionError(f"Fernet encryption failed: {str(e)}")
    
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt using Fernet."""
        if not ciphertext:
            return ciphertext
        
        try:
            # Extract version and data
            versioned_data = json.loads(
                base64.b64decode(ciphertext.encode('utf-8'))
            )
            
            version = versioned_data['v']
            encrypted = base64.b64decode(versioned_data['data'])
            
            # Get appropriate Fernet instance
            fernet, _ = self._get_fernet(version)
            
            # Decrypt
            decrypted = fernet.decrypt(encrypted)
            return decrypted.decode('utf-8')
            
        except Exception as e:
            raise DecryptionError(f"Fernet decryption failed: {str(e)}")
    
    def create_search_hash(self, value: str) -> str:
        """Create search hash (same as AES backend)."""
        return AESEncryptionBackend().create_search_hash(value)


# Singleton instance management
_backend_instance = None


def get_encryption_backend():
    """
    Get the configured encryption backend instance.
    
    Returns:
        Configured encryption backend
    """
    global _backend_instance
    
    if _backend_instance is None:
        backend_class = getattr(settings, 'ENCRYPTION_BACKEND', 'aes')
        
        if backend_class == 'aes':
            _backend_instance = AESEncryptionBackend()
        elif backend_class == 'fernet':
            _backend_instance = FernetEncryptionBackend()
        else:
            raise ValueError(f"Unknown encryption backend: {backend_class}")
    
    return _backend_instance


def reset_encryption_backend():
    """
    Reset the backend instance (useful for testing).
    """
    global _backend_instance
    _backend_instance = None
    
    # Clear any caches
    cache.delete_pattern("decrypted:*")