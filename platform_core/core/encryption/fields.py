"""
Custom Django field types that provide transparent encryption.
"""

import json
from decimal import Decimal
from typing import Any, Optional, Dict
from django.db import models
from django.core import exceptions
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.translation import gettext_lazy as _

from .backends import get_encryption_backend
from .utils import prepare_value_for_encryption, restore_value_from_decryption
from .exceptions import DecryptionError, EncryptionError


class EncryptedFieldMixin:
    """
    Base mixin for all encrypted fields.
    
    Provides transparent encryption/decryption for Django model fields.
    """
    
    def __init__(self, *args, searchable: bool = False, **kwargs):
        """
        Initialize encrypted field.
        
        Args:
            searchable: If True, creates a search hash for exact match queries
        """
        self.searchable = searchable
        
        # Remove our custom kwargs before passing to parent
        kwargs.pop('searchable', None)
        
        # Store original max_length for char fields
        self._original_max_length = kwargs.get('max_length')
        
        super().__init__(*args, **kwargs)
    
    def contribute_to_class(self, cls, name, **kwargs):
        """
        Register this field with the model class.
        """
        super().contribute_to_class(cls, name, **kwargs)
        
        # Track encrypted fields on the model
        if not hasattr(cls, '_encrypted_fields'):
            cls._encrypted_fields = []
        cls._encrypted_fields.append(name)
        
        # Add search hash field if searchable
        if self.searchable:
            hash_field_name = f"{name}_search_hash"
            hash_field = models.CharField(
                max_length=64,
                null=True,
                blank=True,
                db_index=True,
                editable=False
            )
            hash_field.contribute_to_class(cls, hash_field_name)
    
    def pre_save(self, model_instance, add):
        """
        Called before saving - handle search hash generation.
        """
        value = super().pre_save(model_instance, add)
        
        if self.searchable and value is not None:
            # Generate and store search hash
            backend = get_encryption_backend()
            search_hash = backend.create_search_hash(str(value))
            hash_field_name = f"{self.attname}_search_hash"
            setattr(model_instance, hash_field_name, search_hash)
        
        return value
    
    def get_prep_value(self, value):
        """
        Encrypt value before saving to database.
        """
        if value is None:
            return value
        
        try:
            backend = get_encryption_backend()
            prepared_value = self.prepare_value_for_encryption(value)
            encrypted = backend.encrypt(prepared_value)
            
            return encrypted
            
        except Exception as e:
            raise EncryptionError(f"Failed to encrypt {self.name}: {str(e)}")
    
    def from_db_value(self, value, expression, connection):
        """
        Decrypt value when loading from database.
        """
        if value is None:
            return value
        
        try:
            backend = get_encryption_backend()
            decrypted = backend.decrypt(value)
            return self.to_python(decrypted)
            
        except Exception as e:
            raise DecryptionError(f"Failed to decrypt {self.name}: {str(e)}")
    
    def prepare_value_for_encryption(self, value: Any) -> str:
        """
        Convert value to string for encryption.
        
        Can be overridden by subclasses for custom serialization.
        """
        return prepare_value_for_encryption(value)


class EncryptedCharField(EncryptedFieldMixin, models.CharField):
    """
    Encrypted version of CharField.
    
    Automatically expands max_length to accommodate encryption overhead.
    """
    
    def __init__(self, *args, **kwargs):
        # Expand max_length for encryption overhead (roughly 3x)
        if 'max_length' in kwargs:
            kwargs['max_length'] = min(kwargs['max_length'] * 3, 1000)
        
        super().__init__(*args, **kwargs)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        
        # Restore original max_length for migrations
        if self._original_max_length:
            kwargs['max_length'] = self._original_max_length
        
        # Add our custom kwargs
        kwargs['searchable'] = self.searchable
        
        return name, path, args, kwargs


class EncryptedTextField(EncryptedFieldMixin, models.TextField):
    """
    Encrypted version of TextField.
    
    No length restrictions, suitable for large text content.
    """
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs


class EncryptedEmailField(EncryptedFieldMixin, models.EmailField):
    """
    Encrypted version of EmailField with searchable option.
    
    Defaults to searchable=True since emails are commonly searched.
    """
    
    def __init__(self, *args, **kwargs):
        # Emails are often searched, default to searchable
        kwargs.setdefault('searchable', True)
        
        # Expand max_length for encryption
        if 'max_length' in kwargs:
            self._original_max_length = kwargs['max_length']
            kwargs['max_length'] = min(kwargs['max_length'] * 3, 1000)
        
        super().__init__(*args, **kwargs)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        
        # Restore original max_length
        if hasattr(self, '_original_max_length'):
            kwargs['max_length'] = self._original_max_length
        
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs


class EncryptedDecimalField(EncryptedFieldMixin, models.DecimalField):
    """
    Encrypted version of DecimalField.
    
    Preserves decimal precision through encryption/decryption.
    """
    
    def __init__(self, *args, **kwargs):
        # Store original field attributes for proper decimal handling
        self._max_digits = kwargs.get('max_digits')
        self._decimal_places = kwargs.get('decimal_places')
        
        super().__init__(*args, **kwargs)
    
    def prepare_value_for_encryption(self, value: Any) -> str:
        """
        Serialize Decimal for encryption preserving precision.
        """
        if isinstance(value, Decimal):
            # Use string representation to preserve exact precision
            return str(value)
        return str(value) if value is not None else None
    
    def to_python(self, value):
        """
        Convert decrypted value back to Decimal.
        """
        if value is None:
            return value
        
        if isinstance(value, Decimal):
            return value
        
        if isinstance(value, str):
            try:
                # Try to parse as decimal
                decimal_value = Decimal(value)
                
                # Validate against field constraints
                if self._max_digits and self._decimal_places:
                    # Check total digits
                    digits = abs(decimal_value.as_tuple().exponent)
                    integer_digits = len(str(abs(int(decimal_value))))
                    
                    if integer_digits > (self._max_digits - self._decimal_places):
                        raise exceptions.ValidationError(
                            _("Ensure that there are no more than %(max)s digits before the decimal point."),
                            code='max_digits',
                            params={'max': self._max_digits - self._decimal_places},
                        )
                
                return decimal_value
                
            except (ValueError, ArithmeticError) as e:
                raise exceptions.ValidationError(
                    _("Invalid decimal value: %(value)s"),
                    code='invalid',
                    params={'value': value},
                )
        
        # Fall back to parent implementation
        return super().to_python(value)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs


class EncryptedJSONField(EncryptedFieldMixin, models.JSONField):
    """
    Encrypted version of JSONField.
    
    Encrypts the entire JSON structure as a string.
    """
    
    def prepare_value_for_encryption(self, value: Any) -> str:
        """
        Serialize JSON for encryption.
        """
        if value is None:
            return None
        
        # Use DjangoJSONEncoder to handle special types
        return json.dumps(value, cls=DjangoJSONEncoder)
    
    def to_python(self, value):
        """
        Convert decrypted value back to Python object.
        """
        if value is None:
            return value
        
        if isinstance(value, str):
            try:
                # Try to parse as JSON
                return json.loads(value)
            except json.JSONDecodeError:
                # If it fails, might be double-encoded or invalid
                # Try parent's to_python
                pass
        
        # For non-string values or failed parsing, use parent implementation
        return super().to_python(value)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs


class EncryptedIntegerField(EncryptedFieldMixin, models.IntegerField):
    """
    Encrypted version of IntegerField.
    """
    
    def to_python(self, value):
        """
        Convert decrypted value back to integer.
        """
        if value is None:
            return value
        
        if isinstance(value, str):
            try:
                return int(value)
            except (ValueError, TypeError):
                raise exceptions.ValidationError(
                    _("Invalid integer value: %(value)s"),
                    code='invalid',
                    params={'value': value},
                )
        
        return super().to_python(value)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs


class EncryptedFloatField(EncryptedFieldMixin, models.FloatField):
    """
    Encrypted version of FloatField.
    """
    
    def to_python(self, value):
        """
        Convert decrypted value back to float.
        """
        if value is None:
            return value
        
        if isinstance(value, str):
            try:
                return float(value)
            except (ValueError, TypeError):
                raise exceptions.ValidationError(
                    _("Invalid float value: %(value)s"),
                    code='invalid',
                    params={'value': value},
                )
        
        return super().to_python(value)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs


class EncryptedBooleanField(EncryptedFieldMixin, models.BooleanField):
    """
    Encrypted version of BooleanField.
    """
    
    def to_python(self, value):
        """
        Convert decrypted value back to boolean.
        """
        if value is None:
            return value
        
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on', 't')
        
        return super().to_python(value)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs


class EncryptedDateField(EncryptedFieldMixin, models.DateField):
    """
    Encrypted version of DateField.
    """
    
    def prepare_value_for_encryption(self, value: Any) -> str:
        """
        Serialize date for encryption.
        """
        if value is None:
            return None
        
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        
        return str(value)
    
    def to_python(self, value):
        """
        Convert decrypted value back to date.
        """
        if value is None:
            return value
        
        if isinstance(value, str):
            # Try to parse ISO format date
            try:
                from datetime import date
                return date.fromisoformat(value)
            except (ValueError, TypeError):
                # Fall back to parent parsing
                pass
        
        return super().to_python(value)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs


class EncryptedDateTimeField(EncryptedFieldMixin, models.DateTimeField):
    """
    Encrypted version of DateTimeField.
    """
    
    def prepare_value_for_encryption(self, value: Any) -> str:
        """
        Serialize datetime for encryption.
        """
        if value is None:
            return None
        
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        
        return str(value)
    
    def to_python(self, value):
        """
        Convert decrypted value back to datetime.
        """
        if value is None:
            return value
        
        if isinstance(value, str):
            # Try to parse ISO format datetime
            try:
                from datetime import datetime
                return datetime.fromisoformat(value)
            except (ValueError, TypeError):
                # Fall back to parent parsing
                pass
        
        return super().to_python(value)
    
    def deconstruct(self):
        """
        Return enough information to recreate the field.
        """
        name, path, args, kwargs = super().deconstruct()
        kwargs['searchable'] = self.searchable
        return name, path, args, kwargs