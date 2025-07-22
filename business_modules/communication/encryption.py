"""Message encryption utilities."""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings
from django.core.cache import cache


class MessageEncryption:
    """Handle message encryption and decryption."""
    
    _fernet = None
    
    @classmethod
    def _get_fernet(cls) -> Fernet:
        """Get or create Fernet instance."""
        if cls._fernet is None:
            # Get encryption key from settings or generate
            key = getattr(settings, "MESSAGE_ENCRYPTION_KEY", None)
            
            if not key:
                # Generate key from secret key
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=b'stable_salt',  # In production, use proper salt management
                    iterations=100000,
                )
                key = base64.urlsafe_b64encode(
                    kdf.derive(settings.SECRET_KEY.encode())
                )
            
            cls._fernet = Fernet(key)
        
        return cls._fernet
    
    @classmethod
    def encrypt(cls, message: str) -> str:
        """Encrypt a message."""
        if not message:
            return message
        
        fernet = cls._get_fernet()
        encrypted = fernet.encrypt(message.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    
    @classmethod
    def decrypt(cls, encrypted_message: str) -> str:
        """Decrypt a message."""
        if not encrypted_message:
            return encrypted_message
        
        try:
            fernet = cls._get_fernet()
            decoded = base64.urlsafe_b64decode(encrypted_message.encode())
            decrypted = fernet.decrypt(decoded)
            return decrypted.decode()
        except Exception:
            # If decryption fails, return empty string
            return ""
    
    @classmethod
    def rotate_key(cls, old_key: bytes, new_key: bytes) -> None:
        """Rotate encryption keys."""
        # This would be used in a key rotation process
        # Implementation depends on your key management strategy
        pass


class EndToEndEncryption:
    """Handle end-to-end encryption for direct messages."""
    
    @staticmethod
    def generate_key_pair():
        """Generate public/private key pair for user."""
        # This would implement proper E2E encryption
        # Using libraries like PyNaCl or similar
        pass
    
    @staticmethod
    def encrypt_for_recipients(message: str, recipient_public_keys: list) -> dict:
        """Encrypt message for multiple recipients."""
        # Each recipient gets their own encrypted copy
        pass
    
    @staticmethod
    def decrypt_with_private_key(encrypted_data: dict, private_key: bytes) -> str:
        """Decrypt message with private key."""
        pass