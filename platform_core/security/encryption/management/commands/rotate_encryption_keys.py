"""
Encryption Key Rotation Command

Management command to rotate encryption keys for encrypted fields.
"""

import os
from typing import List, Tuple
from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import transaction
from django.conf import settings
import base64

from platform_core.security.encryption.crypto import KeyRotationManager
from platform_core.security.encryption.fields import EncryptedFieldMixin


class Command(BaseCommand):
    help = 'Rotate encryption keys for all encrypted fields'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--old-key',
            type=str,
            help='Old encryption key (base64 encoded)'
        )
        parser.add_argument(
            '--new-key',
            type=str,
            help='New encryption key (base64 encoded)'
        )
        parser.add_argument(
            '--generate-key',
            action='store_true',
            help='Generate a new encryption key'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be rotated without making changes'
        )
        parser.add_argument(
            '--model',
            type=str,
            help='Rotate keys for specific model (app_label.ModelName)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of records to process at once'
        )
    
    def handle(self, *args, **options):
        if options['generate_key']:
            self.generate_new_key()
            return
        
        # Get keys
        old_key = options['old_key'] or getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
        new_key = options['new_key']
        
        if not old_key:
            self.stderr.write("Old key not provided and FIELD_ENCRYPTION_KEY not set")
            return
        
        if not new_key:
            self.stderr.write("New key must be provided with --new-key")
            return
        
        # Find models with encrypted fields
        encrypted_models = self.find_encrypted_models()
        
        if options['model']:
            # Filter to specific model
            app_label, model_name = options['model'].split('.')
            encrypted_models = [
                (model, fields) for model, fields in encrypted_models
                if model._meta.app_label == app_label and model.__name__ == model_name
            ]
        
        if not encrypted_models:
            self.stdout.write("No models with encrypted fields found")
            return
        
        # Show what will be rotated
        self.stdout.write("\nModels with encrypted fields:")
        for model, fields in encrypted_models:
            self.stdout.write(
                f"  - {model._meta.app_label}.{model.__name__}: "
                f"{', '.join(fields)}"
            )
        
        if options['dry_run']:
            self.stdout.write("\nDry run complete. No changes made.")
            return
        
        # Confirm rotation
        if not self._confirm_rotation(encrypted_models):
            self.stdout.write("Rotation cancelled")
            return
        
        # Perform rotation
        self.rotate_keys(old_key, new_key, encrypted_models, options['batch_size'])
    
    def generate_new_key(self):
        """Generate a new encryption key"""
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        
        self.stdout.write("\nGenerated new encryption key:")
        self.stdout.write(self.style.SUCCESS(key))
        self.stdout.write("\nAdd this to your settings:")
        self.stdout.write(f"FIELD_ENCRYPTION_KEY = '{key}'")
        self.stdout.write("\nFor key rotation, keep old keys:")
        self.stdout.write("FIELD_ENCRYPTION_KEYS = [")
        self.stdout.write(f"    '{key}',  # New key (first)")
        self.stdout.write("    'old_key_here',  # Old key(s)")
        self.stdout.write("]")
    
    def find_encrypted_models(self) -> List[Tuple]:
        """Find all models with encrypted fields"""
        encrypted_models = []
        
        for model in apps.get_models():
            encrypted_fields = []
            
            for field in model._meta.get_fields():
                if hasattr(field, '__class__') and any(
                    isinstance(field, base) or base in field.__class__.__bases__
                    for base in [EncryptedFieldMixin]
                ):
                    encrypted_fields.append(field.name)
            
            if encrypted_fields:
                encrypted_models.append((model, encrypted_fields))
        
        return encrypted_models
    
    def _confirm_rotation(self, encrypted_models) -> bool:
        """Confirm rotation with user"""
        total_records = sum(
            model.objects.count() for model, _ in encrypted_models
        )
        
        self.stdout.write(f"\nThis will rotate keys for {total_records:,} records")
        self.stdout.write(self.style.WARNING("This operation cannot be undone!"))
        
        response = input("\nProceed with rotation? [y/N]: ")
        return response.lower() == 'y'
    
    def rotate_keys(self, old_key: str, new_key: str, 
                   encrypted_models: List[Tuple], batch_size: int):
        """Perform key rotation"""
        self.stdout.write("\nStarting key rotation...")
        
        manager = KeyRotationManager(old_key, new_key)
        
        for model, fields in encrypted_models:
            self.stdout.write(
                f"\nRotating {model._meta.app_label}.{model.__name__}..."
            )
            
            try:
                manager.rotate_model(model, fields, batch_size)
                self.stdout.write(self.style.SUCCESS("✓ Complete"))
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"✗ Failed: {e}")
                )
        
        self.stdout.write(self.style.SUCCESS("\nKey rotation complete!"))
        self.stdout.write("\nNext steps:")
        self.stdout.write("1. Update FIELD_ENCRYPTION_KEY with the new key")
        self.stdout.write("2. Keep old key in FIELD_ENCRYPTION_KEYS for decryption")
        self.stdout.write("3. Test that decryption still works")
        self.stdout.write("4. Remove old key after verification")