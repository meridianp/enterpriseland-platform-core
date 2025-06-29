"""
Encryption key management with rotation support.
"""

import os
import base64
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from .exceptions import KeyNotFoundError, KeyRotationError, InvalidKeyVersionError

logger = logging.getLogger(__name__)


class EncryptionKey:
    """
    Represents an encryption key with metadata.
    """
    
    def __init__(self, 
                 key_material: bytes, 
                 version: int,
                 created_at: datetime,
                 expires_at: Optional[datetime] = None,
                 is_primary: bool = False):
        """
        Initialize encryption key.
        
        Args:
            key_material: The actual key bytes (32 bytes for AES-256)
            version: Key version number
            created_at: When the key was created
            expires_at: When the key expires (optional)
            is_primary: Whether this is the primary encryption key
        """
        self.key_material = key_material
        self.version = version
        self.created_at = created_at
        self.expires_at = expires_at
        self.is_primary = is_primary
    
    @property
    def is_expired(self) -> bool:
        """Check if the key has expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_active(self) -> bool:
        """Check if the key is active (not expired)."""
        return not self.is_expired
    
    def __repr__(self):
        return f"<EncryptionKey v{self.version} primary={self.is_primary} active={self.is_active}>"


class KeyManager:
    """
    Manages encryption keys with rotation support.
    """
    
    def __init__(self):
        """Initialize key manager."""
        self.key_store = self._get_key_store()
        self._key_cache = {}
        self._cache_timeout = getattr(settings, 'ENCRYPTION_KEY_CACHE_TIMEOUT', 3600)
    
    def _get_key_store(self):
        """Get the appropriate key store based on configuration."""
        key_store_type = getattr(settings, 'ENCRYPTION_KEY_STORE', 'local')
        
        if key_store_type == 'aws_kms':
            return AWSKMSKeyStore()
        elif key_store_type == 'vault':
            return HashiCorpVaultKeyStore()
        elif key_store_type == 'database':
            return DatabaseKeyStore()
        else:
            return LocalKeyStore()
    
    def get_current_key(self) -> EncryptionKey:
        """
        Get the current active encryption key.
        
        Returns:
            Current encryption key
            
        Raises:
            KeyNotFoundError: If no active key is available
        """
        # Check cache first
        cache_key = 'encryption_key:current'
        cached_key = cache.get(cache_key)
        if cached_key:
            return cached_key
        
        # Get from key store
        key = self.key_store.get_current_key()
        if not key:
            raise KeyNotFoundError("No active encryption key available")
        
        # Cache it
        cache.set(cache_key, key, self._cache_timeout)
        
        return key
    
    def get_key_by_version(self, version: int) -> EncryptionKey:
        """
        Get a specific key version for decryption.
        
        Args:
            version: Key version to retrieve
            
        Returns:
            Encryption key for the specified version
            
        Raises:
            KeyNotFoundError: If the key version doesn't exist
        """
        # Check cache
        cache_key = f'encryption_key:v{version}'
        cached_key = cache.get(cache_key)
        if cached_key:
            return cached_key
        
        # Get from key store
        key = self.key_store.get_key_by_version(version)
        if not key:
            raise KeyNotFoundError(f"Key version {version} not found")
        
        # Cache it
        cache.set(cache_key, key, self._cache_timeout)
        
        return key
    
    def get_search_key(self) -> bytes:
        """
        Get the key used for searchable hashes.
        
        This key doesn't rotate to maintain search consistency.
        
        Returns:
            32-byte key for HMAC operations
        """
        # Use cached search key
        cache_key = 'encryption_key:search'
        cached_key = cache.get(cache_key)
        if cached_key:
            return cached_key
        
        # Derive search key from master key
        master_key = self.key_store.get_master_key()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'enterpriseland_search_key_salt_v1',
            iterations=100000,
            backend=default_backend()
        )
        
        search_key = kdf.derive(master_key)
        
        # Cache it
        cache.set(cache_key, search_key, self._cache_timeout * 24)  # Cache longer
        
        return search_key
    
    def rotate_key(self) -> EncryptionKey:
        """
        Generate a new encryption key and trigger re-encryption.
        
        Returns:
            Newly generated key
            
        Raises:
            KeyRotationError: If rotation fails
        """
        try:
            # Generate new key
            new_key = self.key_store.generate_new_key()
            
            # Clear caches
            cache.delete_pattern('encryption_key:*')
            cache.delete_pattern('decrypted:*')
            
            # Log rotation
            logger.info(f"Rotated encryption key to version {new_key.version}")
            
            # Trigger background re-encryption of searchable fields
            if getattr(settings, 'ENCRYPTION_AUTO_REENCRYPT', True):
                from .tasks import reencrypt_searchable_fields
                reencrypt_searchable_fields.delay(new_key.version)
            
            return new_key
            
        except Exception as e:
            logger.error(f"Key rotation failed: {str(e)}")
            raise KeyRotationError(f"Failed to rotate key: {str(e)}")
    
    def list_keys(self) -> List[EncryptionKey]:
        """
        List all available encryption keys.
        
        Returns:
            List of encryption keys sorted by version
        """
        return self.key_store.list_keys()


class LocalKeyStore:
    """
    Local key storage using environment variables/settings.
    
    Suitable for development and simple deployments.
    """
    
    def __init__(self):
        """Initialize local key store."""
        self.keys = self._load_keys()
    
    def _load_keys(self) -> Dict[int, EncryptionKey]:
        """Load keys from environment/settings."""
        keys = {}
        
        # Load master key
        master_key_b64 = getattr(settings, 'ENCRYPTION_MASTER_KEY', None)
        if not master_key_b64:
            # Generate one for development
            if settings.DEBUG:
                master_key = os.urandom(32)
                master_key_b64 = base64.b64encode(master_key).decode('utf-8')
                logger.warning(f"Generated development encryption key: {master_key_b64}")
            else:
                raise KeyNotFoundError("ENCRYPTION_MASTER_KEY not configured")
        
        # Parse key versions from settings
        key_configs = getattr(settings, 'ENCRYPTION_KEYS', {})
        
        if key_configs:
            for version_str, key_data in key_configs.items():
                version = int(version_str)
                
                # Handle both string and dict configurations
                if isinstance(key_data, str):
                    # Simple format: just the base64 key
                    keys[version] = EncryptionKey(
                        key_material=base64.b64decode(key_data),
                        version=version,
                        created_at=datetime.utcnow(),
                        is_primary=(version == max(map(int, key_configs.keys())))
                    )
                else:
                    # Full format with metadata
                    keys[version] = EncryptionKey(
                        key_material=base64.b64decode(key_data['key']),
                        version=version,
                        created_at=datetime.fromisoformat(key_data['created_at']),
                        expires_at=datetime.fromisoformat(key_data['expires_at']) 
                                  if key_data.get('expires_at') else None,
                        is_primary=key_data.get('is_primary', False)
                    )
        else:
            # No keys configured, use master key as version 1
            keys[1] = EncryptionKey(
                key_material=base64.b64decode(master_key_b64),
                version=1,
                created_at=datetime.utcnow(),
                is_primary=True
            )
        
        return keys
    
    def get_current_key(self) -> EncryptionKey:
        """Get the highest version active key."""
        # Find primary key first
        primary_keys = [k for k in self.keys.values() if k.is_primary and k.is_active]
        if primary_keys:
            return primary_keys[0]
        
        # Fall back to highest version active key
        active_keys = [k for k in self.keys.values() if k.is_active]
        if not active_keys:
            raise KeyNotFoundError("No active encryption keys available")
        
        return max(active_keys, key=lambda k: k.version)
    
    def get_key_by_version(self, version: int) -> EncryptionKey:
        """Get a specific key version."""
        if version not in self.keys:
            raise InvalidKeyVersionError(f"Key version {version} not found")
        
        return self.keys[version]
    
    def get_master_key(self) -> bytes:
        """Get the master key for deriving other keys."""
        master_key_b64 = getattr(settings, 'ENCRYPTION_MASTER_KEY')
        if not master_key_b64:
            raise KeyNotFoundError("ENCRYPTION_MASTER_KEY not configured")
        
        return base64.b64decode(master_key_b64)
    
    def generate_new_key(self) -> EncryptionKey:
        """Generate a new key version."""
        # Find highest version
        max_version = max(self.keys.keys()) if self.keys else 0
        new_version = max_version + 1
        
        # Generate new key material
        new_key_material = os.urandom(32)  # 256-bit key
        
        # Mark old primary as not primary
        for key in self.keys.values():
            key.is_primary = False
        
        # Create new key
        new_key = EncryptionKey(
            key_material=new_key_material,
            version=new_version,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=365),  # 1 year validity
            is_primary=True
        )
        
        # Store in memory (in production, persist to secure storage)
        self.keys[new_version] = new_key
        
        # Log the new key (in production, save to secure storage)
        logger.info(f"Generated new encryption key version {new_version}")
        if settings.DEBUG:
            logger.info(f"New key (base64): {base64.b64encode(new_key_material).decode('utf-8')}")
        
        return new_key
    
    def list_keys(self) -> List[EncryptionKey]:
        """List all keys sorted by version."""
        return sorted(self.keys.values(), key=lambda k: k.version)


class DatabaseKeyStore:
    """
    Database-backed key storage for better persistence.
    
    Stores keys in a dedicated database table with proper access control.
    """
    
    def __init__(self):
        """Initialize database key store."""
        self._ensure_table_exists()
    
    def _ensure_table_exists(self):
        """Ensure the key storage table exists."""
        # This would be implemented as a Django model
        # For now, we'll use a simple implementation
        pass
    
    def get_current_key(self) -> EncryptionKey:
        """Get current key from database."""
        # Import here to avoid circular imports
        from .models import StoredEncryptionKey
        
        try:
            stored_key = StoredEncryptionKey.objects.filter(
                is_primary=True,
                is_active=True
            ).order_by('-version').first()
            
            if not stored_key:
                raise KeyNotFoundError("No active primary key in database")
            
            return stored_key.to_encryption_key()
            
        except Exception as e:
            logger.error(f"Failed to get key from database: {str(e)}")
            raise
    
    def get_key_by_version(self, version: int) -> EncryptionKey:
        """Get specific key version from database."""
        from .models import StoredEncryptionKey
        
        try:
            stored_key = StoredEncryptionKey.objects.get(version=version)
            return stored_key.to_encryption_key()
            
        except StoredEncryptionKey.DoesNotExist:
            raise InvalidKeyVersionError(f"Key version {version} not found in database")
    
    def get_master_key(self) -> bytes:
        """Get master key from secure storage."""
        # In production, this would fetch from a secure key management service
        master_key_b64 = getattr(settings, 'ENCRYPTION_MASTER_KEY')
        if not master_key_b64:
            raise KeyNotFoundError("ENCRYPTION_MASTER_KEY not configured")
        
        return base64.b64decode(master_key_b64)
    
    def generate_new_key(self) -> EncryptionKey:
        """Generate and store new key in database."""
        from .models import StoredEncryptionKey
        
        with transaction.atomic():
            # Get next version
            max_version = StoredEncryptionKey.objects.aggregate(
                max_version=models.Max('version')
            )['max_version'] or 0
            
            new_version = max_version + 1
            
            # Generate key material
            new_key_material = os.urandom(32)
            
            # Deactivate old primary keys
            StoredEncryptionKey.objects.filter(is_primary=True).update(is_primary=False)
            
            # Create new key
            stored_key = StoredEncryptionKey.objects.create(
                version=new_version,
                encrypted_key=self._encrypt_key_material(new_key_material),
                is_primary=True,
                is_active=True,
                expires_at=datetime.utcnow() + timedelta(days=365)
            )
            
            return stored_key.to_encryption_key()
    
    def _encrypt_key_material(self, key_material: bytes) -> str:
        """Encrypt key material using master key before storage."""
        # In production, use KMS or HSM for this
        master_key = self.get_master_key()
        
        # Simple XOR for demonstration (use proper encryption in production!)
        encrypted = bytes(a ^ b for a, b in zip(key_material, master_key))
        return base64.b64encode(encrypted).decode('utf-8')
    
    def list_keys(self) -> List[EncryptionKey]:
        """List all keys from database."""
        from .models import StoredEncryptionKey
        
        stored_keys = StoredEncryptionKey.objects.all().order_by('version')
        return [sk.to_encryption_key() for sk in stored_keys]


class AWSKMSKeyStore:
    """
    AWS KMS key storage for production use.
    
    Uses AWS Key Management Service for secure key storage and rotation.
    """
    
    def __init__(self):
        """Initialize AWS KMS key store."""
        import boto3
        self.kms_client = boto3.client('kms')
        self.ssm_client = boto3.client('ssm')
        self.key_alias = getattr(settings, 'AWS_KMS_KEY_ALIAS', 'alias/enterpriseland-encryption')
        self.parameter_prefix = getattr(settings, 'AWS_SSM_PARAMETER_PREFIX', '/enterpriseland/encryption/')
    
    def get_current_key(self) -> EncryptionKey:
        """Get current key from KMS."""
        try:
            # Get current version from parameter store
            version = self._get_current_version()
            
            # Generate data key
            response = self.kms_client.generate_data_key(
                KeyId=self.key_alias,
                KeySpec='AES_256'
            )
            
            return EncryptionKey(
                key_material=response['Plaintext'],
                version=version,
                created_at=datetime.utcnow(),
                is_primary=True
            )
            
        except Exception as e:
            logger.error(f"Failed to get key from KMS: {str(e)}")
            raise KeyNotFoundError(f"Failed to get key from KMS: {str(e)}")
    
    def get_key_by_version(self, version: int) -> EncryptionKey:
        """Get specific key version from KMS."""
        # In a real implementation, we'd store encrypted data keys in Parameter Store
        # and decrypt them using KMS
        return self.get_current_key()  # Simplified for now
    
    def get_master_key(self) -> bytes:
        """Get master key from KMS."""
        # KMS handles master key internally
        response = self.kms_client.generate_data_key(
            KeyId=self.key_alias,
            KeySpec='AES_256'
        )
        return response['Plaintext']
    
    def generate_new_key(self) -> EncryptionKey:
        """Generate new key using KMS."""
        # Update version in parameter store
        new_version = self._increment_version()
        
        # Generate new data key
        response = self.kms_client.generate_data_key(
            KeyId=self.key_alias,
            KeySpec='AES_256'
        )
        
        # Store encrypted data key in parameter store
        self.ssm_client.put_parameter(
            Name=f"{self.parameter_prefix}keys/v{new_version}",
            Value=base64.b64encode(response['CiphertextBlob']).decode('utf-8'),
            Type='SecureString',
            Overwrite=True
        )
        
        return EncryptionKey(
            key_material=response['Plaintext'],
            version=new_version,
            created_at=datetime.utcnow(),
            is_primary=True
        )
    
    def _get_current_version(self) -> int:
        """Get current key version from parameter store."""
        try:
            response = self.ssm_client.get_parameter(
                Name=f"{self.parameter_prefix}current_version"
            )
            return int(response['Parameter']['Value'])
        except:
            return 1
    
    def _increment_version(self) -> int:
        """Increment and store new version."""
        current = self._get_current_version()
        new_version = current + 1
        
        self.ssm_client.put_parameter(
            Name=f"{self.parameter_prefix}current_version",
            Value=str(new_version),
            Type='String',
            Overwrite=True
        )
        
        return new_version
    
    def list_keys(self) -> List[EncryptionKey]:
        """List available keys."""
        # Simplified - in production, enumerate parameter store
        current = self.get_current_key()
        return [current]


class HashiCorpVaultKeyStore:
    """
    HashiCorp Vault key storage for production use.
    
    Uses HashiCorp Vault for secure key storage and rotation.
    """
    
    def __init__(self):
        """Initialize Vault key store."""
        import hvac
        
        self.client = hvac.Client(
            url=getattr(settings, 'VAULT_URL', 'http://localhost:8200'),
            token=getattr(settings, 'VAULT_TOKEN', None)
        )
        self.mount_point = getattr(settings, 'VAULT_MOUNT_POINT', 'secret')
        self.key_path = getattr(settings, 'VAULT_KEY_PATH', 'enterpriseland/encryption')
    
    def get_current_key(self) -> EncryptionKey:
        """Get current key from Vault."""
        try:
            # Read current key metadata
            response = self.client.secrets.kv.v2.read_secret_version(
                path=f"{self.key_path}/current",
                mount_point=self.mount_point
            )
            
            data = response['data']['data']
            
            return EncryptionKey(
                key_material=base64.b64decode(data['key']),
                version=data['version'],
                created_at=datetime.fromisoformat(data['created_at']),
                is_primary=True
            )
            
        except Exception as e:
            logger.error(f"Failed to get key from Vault: {str(e)}")
            raise KeyNotFoundError(f"Failed to get key from Vault: {str(e)}")
    
    def get_key_by_version(self, version: int) -> EncryptionKey:
        """Get specific key version from Vault."""
        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=f"{self.key_path}/keys/v{version}",
                mount_point=self.mount_point
            )
            
            data = response['data']['data']
            
            return EncryptionKey(
                key_material=base64.b64decode(data['key']),
                version=version,
                created_at=datetime.fromisoformat(data['created_at']),
                expires_at=datetime.fromisoformat(data['expires_at'])
                          if data.get('expires_at') else None
            )
            
        except Exception as e:
            raise InvalidKeyVersionError(f"Key version {version} not found in Vault")
    
    def get_master_key(self) -> bytes:
        """Get master key from Vault."""
        response = self.client.secrets.kv.v2.read_secret_version(
            path=f"{self.key_path}/master",
            mount_point=self.mount_point
        )
        
        return base64.b64decode(response['data']['data']['key'])
    
    def generate_new_key(self) -> EncryptionKey:
        """Generate and store new key in Vault."""
        # Get current version
        try:
            current = self.get_current_key()
            new_version = current.version + 1
        except:
            new_version = 1
        
        # Generate new key
        new_key_material = os.urandom(32)
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(days=365)
        
        # Store in Vault
        self.client.secrets.kv.v2.create_or_update_secret(
            path=f"{self.key_path}/keys/v{new_version}",
            secret={
                'key': base64.b64encode(new_key_material).decode('utf-8'),
                'created_at': created_at.isoformat(),
                'expires_at': expires_at.isoformat()
            },
            mount_point=self.mount_point
        )
        
        # Update current key pointer
        self.client.secrets.kv.v2.create_or_update_secret(
            path=f"{self.key_path}/current",
            secret={
                'key': base64.b64encode(new_key_material).decode('utf-8'),
                'version': new_version,
                'created_at': created_at.isoformat()
            },
            mount_point=self.mount_point
        )
        
        return EncryptionKey(
            key_material=new_key_material,
            version=new_version,
            created_at=created_at,
            expires_at=expires_at,
            is_primary=True
        )
    
    def list_keys(self) -> List[EncryptionKey]:
        """List all keys from Vault."""
        # List all key versions
        try:
            response = self.client.secrets.kv.v2.list_secrets(
                path=f"{self.key_path}/keys",
                mount_point=self.mount_point
            )
            
            keys = []
            for key_name in response['data']['keys']:
                if key_name.startswith('v'):
                    version = int(key_name[1:])
                    try:
                        key = self.get_key_by_version(version)
                        keys.append(key)
                    except:
                        pass
            
            return sorted(keys, key=lambda k: k.version)
            
        except:
            # If listing fails, at least return current key
            return [self.get_current_key()]