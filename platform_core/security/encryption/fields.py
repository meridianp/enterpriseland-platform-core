"""
Encrypted Django Model Fields

Custom Django fields that automatically encrypt/decrypt data.
"""

import json
from typing import Any, Optional, Union
from django.db import models
from django.core import checks
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .crypto import FieldEncryptor, get_default_encryptor


class EncryptedFieldMixin:
    """
    Mixin for encrypted fields.
    """
    
    def __init__(self, *args, **kwargs):
        self.encryptor_class = kwargs.pop('encryptor_class', None)
        self.searchable = kwargs.pop('searchable', False)
        self.deterministic = kwargs.pop('deterministic', False)
        super().__init__(*args, **kwargs)
        
        # Get encryptor instance
        if self.encryptor_class:
            self.encryptor = self.encryptor_class()
        else:
            self.encryptor = get_default_encryptor(
                deterministic=self.deterministic
            )
    
    def check(self, **kwargs):
        errors = super().check(**kwargs)
        errors.extend(self._check_encryption_settings())
        return errors
    
    def _check_encryption_settings(self):
        """Check encryption configuration"""
        errors = []
        
        if self.searchable and not self.deterministic:
            errors.append(
                checks.Error(
                    'Searchable encrypted fields must use deterministic encryption',
                    obj=self,
                    id='fields.E901',
                )
            )
        
        return errors
    
    def get_internal_type(self):
        """Store as text in database"""
        return "TextField"
    
    def from_db_value(self, value, expression, connection):
        """Decrypt when loading from database"""
        if value is None:
            return value
        
        try:
            decrypted = self.encryptor.decrypt(value)
            return self.to_python(decrypted)
        except Exception as e:
            # Log decryption error but don't break
            import logging
            logging.error(f"Failed to decrypt field: {e}")
            return None
    
    def get_prep_value(self, value):
        """Encrypt before saving to database"""
        if value is None:
            return value
        
        # Convert to string for encryption
        if not isinstance(value, str):
            value = self.value_to_string(value)
        
        # Encrypt the value
        encrypted = self.encryptor.encrypt(value)
        
        # Store searchable hash if needed
        if self.searchable:
            self._store_search_hash(value, encrypted)
        
        return encrypted
    
    def value_to_string(self, obj):
        """Convert value to string for encryption"""
        value = self.value_from_object(obj)
        return str(value) if value is not None else ''
    
    def _store_search_hash(self, plaintext: str, ciphertext: str):
        """Store hash for searchable fields"""
        # This would store a hash in a separate field/table
        # Implementation depends on search requirements
        pass


class EncryptedCharField(EncryptedFieldMixin, models.CharField):
    """
    Encrypted version of CharField.
    
    Usage:
        ssn = EncryptedCharField(max_length=11)
        email = EncryptedCharField(max_length=255, searchable=True, deterministic=True)
    """
    
    def __init__(self, *args, **kwargs):
        # Increase max_length to accommodate encryption overhead
        if 'max_length' in kwargs:
            kwargs['max_length'] = kwargs['max_length'] * 3
        super().__init__(*args, **kwargs)
    
    def to_python(self, value):
        """Convert decrypted value to Python string"""
        if isinstance(value, str) or value is None:
            return value
        return str(value)


class EncryptedTextField(EncryptedFieldMixin, models.TextField):
    """
    Encrypted version of TextField.
    
    Usage:
        notes = EncryptedTextField()
        medical_history = EncryptedTextField(blank=True)
    """
    
    def to_python(self, value):
        """Convert decrypted value to Python string"""
        if isinstance(value, str) or value is None:
            return value
        return str(value)


class EncryptedEmailField(EncryptedFieldMixin, models.EmailField):
    """
    Encrypted version of EmailField with validation.
    
    Usage:
        personal_email = EncryptedEmailField(searchable=True, deterministic=True)
    """
    
    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = kwargs.get('max_length', 254) * 3
        super().__init__(*args, **kwargs)
    
    def to_python(self, value):
        """Validate email after decryption"""
        value = super(models.EmailField, self).to_python(value)
        if value is None:
            return value
        
        # Validate email format
        from django.core.validators import validate_email
        try:
            validate_email(value)
        except ValidationError:
            return None
        
        return value


class EncryptedIntegerField(EncryptedFieldMixin, models.IntegerField):
    """
    Encrypted version of IntegerField.
    
    Usage:
        salary = EncryptedIntegerField()
        age = EncryptedIntegerField(null=True, blank=True)
    """
    
    def to_python(self, value):
        """Convert decrypted value to Python integer"""
        if value is None:
            return value
        
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValidationError(
                _("Invalid integer value after decryption"),
                code='invalid',
                params={'value': value},
            )
    
    def value_to_string(self, obj):
        """Convert integer to string for encryption"""
        value = self.value_from_object(obj)
        return str(value) if value is not None else ''


class EncryptedDecimalField(EncryptedFieldMixin, models.DecimalField):
    """
    Encrypted version of DecimalField.
    
    Usage:
        balance = EncryptedDecimalField(max_digits=12, decimal_places=2)
        tax_rate = EncryptedDecimalField(max_digits=5, decimal_places=4)
    """
    
    def to_python(self, value):
        """Convert decrypted value to Python Decimal"""
        if value is None:
            return value
        
        from decimal import Decimal, InvalidOperation
        try:
            return Decimal(value)
        except InvalidOperation:
            raise ValidationError(
                _("Invalid decimal value after decryption"),
                code='invalid',
                params={'value': value},
            )
    
    def value_to_string(self, obj):
        """Convert decimal to string for encryption"""
        value = self.value_from_object(obj)
        return str(value) if value is not None else ''


class EncryptedDateField(EncryptedFieldMixin, models.DateField):
    """
    Encrypted version of DateField.
    
    Usage:
        birth_date = EncryptedDateField()
        expiry_date = EncryptedDateField(null=True, blank=True)
    """
    
    def to_python(self, value):
        """Convert decrypted value to Python date"""
        if value is None:
            return value
        
        # Parse the date string
        from django.utils.dateparse import parse_date
        result = parse_date(value)
        
        if result is None:
            raise ValidationError(
                _("Invalid date value after decryption"),
                code='invalid',
                params={'value': value},
            )
        
        return result
    
    def value_to_string(self, obj):
        """Convert date to ISO format string for encryption"""
        value = self.value_from_object(obj)
        if value is None:
            return ''
        
        return value.isoformat()


class EncryptedDateTimeField(EncryptedFieldMixin, models.DateTimeField):
    """
    Encrypted version of DateTimeField.
    
    Usage:
        last_login_encrypted = EncryptedDateTimeField()
        sensitive_timestamp = EncryptedDateTimeField(auto_now_add=True)
    """
    
    def to_python(self, value):
        """Convert decrypted value to Python datetime"""
        if value is None:
            return value
        
        # Parse the datetime string
        from django.utils.dateparse import parse_datetime
        result = parse_datetime(value)
        
        if result is None:
            raise ValidationError(
                _("Invalid datetime value after decryption"),
                code='invalid',
                params={'value': value},
            )
        
        # Make timezone aware if needed
        from django.utils import timezone
        if timezone.is_naive(result):
            result = timezone.make_aware(result)
        
        return result
    
    def value_to_string(self, obj):
        """Convert datetime to ISO format string for encryption"""
        value = self.value_from_object(obj)
        if value is None:
            return ''
        
        return value.isoformat()


class EncryptedJSONField(EncryptedFieldMixin, models.JSONField):
    """
    Encrypted version of JSONField.
    
    Usage:
        preferences = EncryptedJSONField(default=dict)
        sensitive_data = EncryptedJSONField(null=True, blank=True)
    """
    
    def to_python(self, value):
        """Convert decrypted value to Python object"""
        if value is None:
            return value
        
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            raise ValidationError(
                _("Invalid JSON value after decryption"),
                code='invalid',
                params={'value': value},
            )
    
    def value_to_string(self, obj):
        """Convert object to JSON string for encryption"""
        value = self.value_from_object(obj)
        if value is None:
            return ''
        
        return json.dumps(value, cls=self.encoder)


class EncryptedBooleanField(EncryptedFieldMixin, models.BooleanField):
    """
    Encrypted version of BooleanField.
    
    Usage:
        is_verified = EncryptedBooleanField(default=False)
        has_criminal_record = EncryptedBooleanField(null=True)
    """
    
    def to_python(self, value):
        """Convert decrypted value to Python boolean"""
        if value is None:
            return value
        
        if value.lower() in ('true', '1', 'yes', 'on'):
            return True
        elif value.lower() in ('false', '0', 'no', 'off'):
            return False
        else:
            raise ValidationError(
                _("Invalid boolean value after decryption"),
                code='invalid',
                params={'value': value},
            )
    
    def value_to_string(self, obj):
        """Convert boolean to string for encryption"""
        value = self.value_from_object(obj)
        return 'true' if value else 'false'


class EncryptedFilePathField(EncryptedFieldMixin, models.FilePathField):
    """
    Encrypted version of FilePathField.
    
    Usage:
        document_path = EncryptedFilePathField(path='/secure/documents/')
    """
    
    def to_python(self, value):
        """Convert decrypted value to file path"""
        if value is None:
            return value
        
        # Validate path exists if required
        if self.match is not None:
            import re
            if not re.search(self.match, value):
                raise ValidationError(
                    _("Invalid file path after decryption"),
                    code='invalid',
                    params={'value': value},
                )
        
        return value


# Searchable encrypted field support
class SearchableEncryptedField:
    """
    Base class for searchable encrypted fields.
    
    Creates a companion hash field for searching.
    """
    
    def contribute_to_class(self, cls, name, **kwargs):
        super().contribute_to_class(cls, name, **kwargs)
        
        # Add hash field for searching
        if self.searchable:
            hash_field_name = f"_{name}_hash"
            hash_field = models.CharField(
                max_length=64,
                db_index=True,
                null=True,
                editable=False
            )
            cls.add_to_class(hash_field_name, hash_field)
            
            # Override save to update hash
            original_save = cls.save
            
            def save_with_hash(instance, *args, **kwargs):
                # Update hash before saving
                value = getattr(instance, name)
                if value is not None:
                    hash_value = self.encryptor.hash_for_search(str(value))
                    setattr(instance, hash_field_name, hash_value)
                else:
                    setattr(instance, hash_field_name, None)
                
                original_save(instance, *args, **kwargs)
            
            cls.save = save_with_hash