"""Encryption service for document security."""

import os
import base64
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding, hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from django.conf import settings
from django.core.cache import cache


class EncryptionService:
    """Service for encrypting and decrypting documents."""
    
    def __init__(self):
        self.backend = default_backend()
        self.block_size = 128  # AES block size in bits
        self.key_size = 256    # AES key size in bits
        
        # Master key for key derivation (should be stored securely)
        self.master_key = self._get_master_key()
    
    def _get_master_key(self) -> bytes:
        """Get or generate master encryption key."""
        master_key_b64 = getattr(settings, 'DOCUMENTS_MASTER_KEY', None)
        
        if master_key_b64:
            return base64.b64decode(master_key_b64)
        else:
            # Generate a new key (only for development)
            import secrets
            key = secrets.token_bytes(32)
            print(f"Generated master key: {base64.b64encode(key).decode()}")
            print("WARNING: Add DOCUMENTS_MASTER_KEY to settings for production")
            return key
    
    def encrypt_file(self, file_content: bytes) -> Dict[str, Any]:
        """Encrypt file content."""
        try:
            # Generate unique key for this file
            salt = os.urandom(16)
            key = self._derive_key(salt)
            
            # Generate IV
            iv = os.urandom(16)
            
            # Create cipher
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=self.backend
            )
            encryptor = cipher.encryptor()
            
            # Pad content to block size
            padder = padding.PKCS7(self.block_size).padder()
            padded_content = padder.update(file_content) + padder.finalize()
            
            # Encrypt
            encrypted_content = encryptor.update(padded_content) + encryptor.finalize()
            
            # Combine salt, iv, and encrypted content
            final_content = salt + iv + encrypted_content
            
            # Generate key ID for tracking
            key_id = base64.urlsafe_b64encode(salt).decode()
            
            return {
                'encrypted_content': final_content,
                'key_id': key_id,
                'algorithm': 'AES-256-CBC',
                'success': True
            }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def decrypt_file(self, encrypted_content: bytes, key_id: str) -> bytes:
        """Decrypt file content."""
        try:
            # Extract components
            salt = encrypted_content[:16]
            iv = encrypted_content[16:32]
            ciphertext = encrypted_content[32:]
            
            # Verify key ID matches
            expected_key_id = base64.urlsafe_b64encode(salt).decode()
            if key_id != expected_key_id:
                raise ValueError("Key ID mismatch")
            
            # Derive key
            key = self._derive_key(salt)
            
            # Create cipher
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=self.backend
            )
            decryptor = cipher.decryptor()
            
            # Decrypt
            padded_content = decryptor.update(ciphertext) + decryptor.finalize()
            
            # Remove padding
            unpadder = padding.PKCS7(self.block_size).unpadder()
            content = unpadder.update(padded_content) + unpadder.finalize()
            
            return content
        
        except Exception as e:
            raise Exception(f"Decryption failed: {str(e)}")
    
    def _derive_key(self, salt: bytes) -> bytes:
        """Derive encryption key from master key and salt."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.key_size // 8,
            salt=salt,
            iterations=100000,
            backend=self.backend
        )
        return kdf.derive(self.master_key)
    
    def encrypt_metadata(self, metadata: Dict[str, Any]) -> str:
        """Encrypt metadata dictionary."""
        try:
            import json
            
            # Convert to JSON
            json_data = json.dumps(metadata).encode()
            
            # Encrypt
            result = self.encrypt_file(json_data)
            
            if result['success']:
                # Base64 encode for storage
                encrypted_b64 = base64.b64encode(result['encrypted_content']).decode()
                return f"{result['key_id']}:{encrypted_b64}"
            else:
                raise Exception(result['error'])
        
        except Exception as e:
            raise Exception(f"Metadata encryption failed: {str(e)}")
    
    def decrypt_metadata(self, encrypted_metadata: str) -> Dict[str, Any]:
        """Decrypt metadata string."""
        try:
            import json
            
            # Parse key ID and content
            key_id, encrypted_b64 = encrypted_metadata.split(':', 1)
            encrypted_content = base64.b64decode(encrypted_b64)
            
            # Decrypt
            decrypted = self.decrypt_file(encrypted_content, key_id)
            
            # Parse JSON
            return json.loads(decrypted.decode())
        
        except Exception as e:
            raise Exception(f"Metadata decryption failed: {str(e)}")
    
    def generate_file_key(self) -> Dict[str, str]:
        """Generate a new file encryption key."""
        key = os.urandom(32)  # 256-bit key
        key_b64 = base64.b64encode(key).decode()
        
        # Generate key ID
        key_id = base64.urlsafe_b64encode(os.urandom(16)).decode()
        
        # Cache key for retrieval
        cache_key = f"file_key:{key_id}"
        cache.set(cache_key, key_b64, timeout=3600)  # 1 hour
        
        return {
            'key_id': key_id,
            'key': key_b64
        }
    
    def rotate_encryption_key(self, old_content: bytes, old_key_id: str) -> Dict[str, Any]:
        """Re-encrypt content with a new key."""
        try:
            # Decrypt with old key
            decrypted = self.decrypt_file(old_content, old_key_id)
            
            # Encrypt with new key
            return self.encrypt_file(decrypted)
        
        except Exception as e:
            return {
                'success': False,
                'error': f"Key rotation failed: {str(e)}"
            }
    
    def secure_delete(self, data: bytes) -> None:
        """Securely overwrite data in memory."""
        if isinstance(data, bytearray):
            for i in range(len(data)):
                data[i] = 0
        # Note: For bytes objects, we can't modify in place
        # This is a limitation in Python
    
    def get_encryption_info(self) -> Dict[str, Any]:
        """Get information about encryption configuration."""
        return {
            'enabled': getattr(settings, 'DOCUMENTS_ENCRYPTION_ENABLED', True),
            'algorithm': 'AES-256-CBC',
            'key_derivation': 'PBKDF2-HMAC-SHA256',
            'iterations': 100000,
            'master_key_configured': bool(getattr(settings, 'DOCUMENTS_MASTER_KEY', None))
        }
    
    def encrypt_filename(self, filename: str) -> str:
        """Encrypt a filename while preserving extension."""
        try:
            # Split name and extension
            name, ext = os.path.splitext(filename)
            
            # Encrypt name part only
            name_bytes = name.encode()
            result = self.encrypt_file(name_bytes)
            
            if result['success']:
                # Use URL-safe base64 for filename
                encrypted_name = base64.urlsafe_b64encode(
                    result['encrypted_content']
                ).decode().rstrip('=')
                
                # Limit length and add extension
                if len(encrypted_name) > 200:
                    encrypted_name = encrypted_name[:200]
                
                return f"{encrypted_name}{ext}"
            else:
                return filename
        
        except Exception:
            return filename
    
    def verify_encryption(self, encrypted_content: bytes, key_id: str) -> bool:
        """Verify that content can be decrypted."""
        try:
            # Try to decrypt a small portion
            if len(encrypted_content) > 1024:
                test_content = encrypted_content[:1024]
            else:
                test_content = encrypted_content
            
            self.decrypt_file(test_content, key_id)
            return True
        
        except Exception:
            return False