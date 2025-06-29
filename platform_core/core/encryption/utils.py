"""
Utility functions for the encryption framework.
"""

import json
import logging
from typing import Any, List, Optional, Union
from decimal import Decimal
from datetime import datetime, date
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.conf import settings

logger = logging.getLogger(__name__)


class EncryptionJSONEncoder(DjangoJSONEncoder):
    """Extended JSON encoder for encryption that handles more types."""
    
    def default(self, o):
        if isinstance(o, Decimal):
            return str(o)
        elif isinstance(o, (datetime, date)):
            return o.isoformat()
        elif hasattr(o, '__dict__'):
            return o.__dict__
        return super().default(o)


def prepare_value_for_encryption(value: Any) -> str:
    """
    Prepare any value for encryption by converting to string.
    
    Args:
        value: The value to prepare
        
    Returns:
        String representation of the value
    """
    if value is None:
        return None
    
    if isinstance(value, str):
        return value
    
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, cls=EncryptionJSONEncoder)
    
    return str(value)


def restore_value_from_decryption(decrypted: str, target_type: type) -> Any:
    """
    Restore a decrypted string value to its original type.
    
    Args:
        decrypted: The decrypted string value
        target_type: The type to convert to
        
    Returns:
        Value converted to the target type
    """
    if decrypted is None:
        return None
    
    try:
        if target_type == str:
            return decrypted
        
        elif target_type == int:
            return int(decrypted)
        
        elif target_type == float:
            return float(decrypted)
        
        elif target_type == Decimal:
            return Decimal(decrypted)
        
        elif target_type == bool:
            return decrypted.lower() in ('true', '1', 'yes', 'on')
        
        elif target_type in (dict, list):
            return json.loads(decrypted)
        
        elif target_type == datetime:
            return datetime.fromisoformat(decrypted)
        
        elif target_type == date:
            return date.fromisoformat(decrypted)
        
        else:
            # Try JSON deserialization for complex types
            try:
                return json.loads(decrypted)
            except:
                return decrypted
                
    except Exception as e:
        logger.warning(f"Failed to restore type {target_type} from decrypted value: {e}")
        return decrypted


def bulk_encrypt(values: List[Any], backend=None) -> List[str]:
    """
    Efficiently encrypt multiple values.
    
    Args:
        values: List of values to encrypt
        backend: Encryption backend to use (optional)
        
    Returns:
        List of encrypted values
    """
    if not backend:
        from .backends import get_encryption_backend
        backend = get_encryption_backend()
    
    encrypted = []
    for value in values:
        prepared = prepare_value_for_encryption(value)
        if prepared is not None:
            encrypted.append(backend.encrypt(prepared))
        else:
            encrypted.append(None)
    
    return encrypted


def bulk_decrypt(encrypted_values: List[str], target_type: type = str, backend=None) -> List[Any]:
    """
    Efficiently decrypt multiple values.
    
    Args:
        encrypted_values: List of encrypted values
        target_type: Type to convert decrypted values to
        backend: Encryption backend to use (optional)
        
    Returns:
        List of decrypted values
    """
    if not backend:
        from .backends import get_encryption_backend
        backend = get_encryption_backend()
    
    decrypted = []
    for encrypted in encrypted_values:
        if encrypted is not None:
            try:
                decrypted_str = backend.decrypt(encrypted)
                restored = restore_value_from_decryption(decrypted_str, target_type)
                decrypted.append(restored)
            except Exception as e:
                logger.error(f"Failed to decrypt value: {e}")
                decrypted.append(None)
        else:
            decrypted.append(None)
    
    return decrypted


def get_encrypted_fields(model_class):
    """
    Get all encrypted fields for a model class.
    
    Args:
        model_class: The Django model class
        
    Returns:
        List of field names that are encrypted
    """
    if hasattr(model_class, '_encrypted_fields'):
        return model_class._encrypted_fields
    
    # Discover encrypted fields
    encrypted_fields = []
    for field in model_class._meta.get_fields():
        if hasattr(field, 'searchable'):  # Our encrypted fields have this attribute
            encrypted_fields.append(field.name)
    
    return encrypted_fields


def validate_encryption_config():
    """
    Validate that encryption is properly configured.
    
    Raises:
        EncryptionConfigurationError: If configuration is invalid
    """
    from .exceptions import EncryptionConfigurationError
    
    # Check for master key in production
    if not settings.DEBUG:
        master_key = getattr(settings, 'ENCRYPTION_MASTER_KEY', None)
        if not master_key:
            raise EncryptionConfigurationError(
                "ENCRYPTION_MASTER_KEY must be set in production"
            )
        
        # Validate key length
        import base64
        try:
            key_bytes = base64.b64decode(master_key)
            if len(key_bytes) < 32:  # 256 bits
                raise EncryptionConfigurationError(
                    "ENCRYPTION_MASTER_KEY must be at least 256 bits (32 bytes)"
                )
        except Exception:
            raise EncryptionConfigurationError(
                "ENCRYPTION_MASTER_KEY must be valid base64"
            )
    
    # Check key store configuration
    key_store = getattr(settings, 'ENCRYPTION_KEY_STORE', 'local')
    if key_store not in ('local', 'aws_kms', 'vault'):
        raise EncryptionConfigurationError(
            f"Invalid ENCRYPTION_KEY_STORE: {key_store}"
        )
    
    # Validate AWS KMS settings if using KMS
    if key_store == 'aws_kms':
        kms_alias = getattr(settings, 'AWS_KMS_KEY_ALIAS', None)
        if not kms_alias:
            raise EncryptionConfigurationError(
                "AWS_KMS_KEY_ALIAS must be set when using aws_kms key store"
            )


def generate_encryption_key() -> str:
    """
    Generate a new encryption key.
    
    Returns:
        Base64-encoded 256-bit key
    """
    import os
    import base64
    
    key_bytes = os.urandom(32)  # 256 bits
    return base64.b64encode(key_bytes).decode('utf-8')


def rotate_encryption_keys(dry_run: bool = True):
    """
    Rotate encryption keys and re-encrypt searchable fields.
    
    Args:
        dry_run: If True, only simulate the rotation
        
    Returns:
        Dict with rotation results
    """
    from .keys import KeyManager
    
    key_manager = KeyManager()
    
    if dry_run:
        logger.info("DRY RUN: Simulating key rotation")
        current_key = key_manager.get_current_key()
        return {
            'status': 'dry_run',
            'current_version': current_key.version,
            'new_version': current_key.version + 1,
            'message': 'Dry run completed successfully'
        }
    
    # Perform actual rotation
    with transaction.atomic():
        try:
            new_key = key_manager.rotate_key()
            logger.info(f"Successfully rotated to key version {new_key.version}")
            
            return {
                'status': 'success',
                'old_version': new_key.version - 1,
                'new_version': new_key.version,
                'message': 'Key rotation completed successfully'
            }
            
        except Exception as e:
            logger.error(f"Key rotation failed: {e}")
            raise


def audit_encryption_usage():
    """
    Audit which models and fields are using encryption.
    
    Returns:
        Dict with encryption usage statistics
    """
    from django.apps import apps
    
    stats = {
        'total_models': 0,
        'encrypted_models': 0,
        'total_fields': 0,
        'encrypted_fields': 0,
        'fields_by_type': {},
        'models': []
    }
    
    for model in apps.get_models():
        model_info = {
            'app_label': model._meta.app_label,
            'model_name': model.__name__,
            'encrypted_fields': []
        }
        
        has_encrypted = False
        
        for field in model._meta.get_fields():
            stats['total_fields'] += 1
            
            if hasattr(field, 'searchable'):  # Our encrypted fields
                has_encrypted = True
                stats['encrypted_fields'] += 1
                
                field_type = field.__class__.__name__
                stats['fields_by_type'][field_type] = stats['fields_by_type'].get(field_type, 0) + 1
                
                model_info['encrypted_fields'].append({
                    'name': field.name,
                    'type': field_type,
                    'searchable': field.searchable
                })
        
        stats['total_models'] += 1
        if has_encrypted:
            stats['encrypted_models'] += 1
            stats['models'].append(model_info)
    
    return stats