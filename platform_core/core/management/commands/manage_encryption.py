"""
Management command for encryption key management and testing.
"""

import json
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from platform_core.core.encryption import get_encryption_backend, KeyManager
from platform_core.core.encryption.utils import (
    generate_encryption_key, 
    validate_encryption_config,
    audit_encryption_usage,
    rotate_encryption_keys
)


class Command(BaseCommand):
    help = 'Manage field-level encryption keys and configuration'
    
    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(
            dest='subcommand',
            help='Encryption management subcommands'
        )
        
        # Test encryption
        test_parser = subparsers.add_parser('test', help='Test encryption/decryption')
        test_parser.add_argument(
            '--value',
            type=str,
            default='Hello, World!',
            help='Value to encrypt and decrypt'
        )
        
        # Generate key
        generate_parser = subparsers.add_parser('generate-key', help='Generate a new encryption key')
        
        # List keys
        list_parser = subparsers.add_parser('list-keys', help='List all encryption keys')
        
        # Rotate keys
        rotate_parser = subparsers.add_parser('rotate-keys', help='Rotate encryption keys')
        rotate_parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate key rotation without making changes'
        )
        
        # Validate config
        validate_parser = subparsers.add_parser('validate', help='Validate encryption configuration')
        
        # Audit usage
        audit_parser = subparsers.add_parser('audit', help='Audit encryption usage in models')
    
    def handle(self, *args, **options):
        subcommand = options.get('subcommand')
        
        if not subcommand:
            self.print_help('manage.py', 'manage_encryption')
            return
        
        if subcommand == 'test':
            self.test_encryption(options['value'])
        elif subcommand == 'generate-key':
            self.generate_key()
        elif subcommand == 'list-keys':
            self.list_keys()
        elif subcommand == 'rotate-keys':
            self.rotate_keys(options['dry_run'])
        elif subcommand == 'validate':
            self.validate_config()
        elif subcommand == 'audit':
            self.audit_usage()
    
    def test_encryption(self, test_value):
        """Test encryption and decryption."""
        self.stdout.write(self.style.NOTICE(f"Testing encryption with value: {test_value}"))
        
        try:
            backend = get_encryption_backend()
            
            # Test encryption
            encrypted = backend.encrypt(test_value)
            self.stdout.write(f"Encrypted: {encrypted[:50]}..." if len(encrypted) > 50 else encrypted)
            
            # Test decryption
            decrypted = backend.decrypt(encrypted)
            self.stdout.write(f"Decrypted: {decrypted}")
            
            # Verify
            if decrypted == test_value:
                self.stdout.write(self.style.SUCCESS("✓ Encryption/decryption successful!"))
            else:
                self.stdout.write(self.style.ERROR("✗ Decrypted value doesn't match original!"))
            
            # Test search hash
            if hasattr(backend, 'create_search_hash'):
                search_hash = backend.create_search_hash(test_value)
                self.stdout.write(f"Search hash: {search_hash}")
                
                # Verify search hash
                verified = backend.verify_search_hash(test_value, search_hash)
                if verified:
                    self.stdout.write(self.style.SUCCESS("✓ Search hash verification successful!"))
                else:
                    self.stdout.write(self.style.ERROR("✗ Search hash verification failed!"))
            
        except Exception as e:
            raise CommandError(f"Encryption test failed: {str(e)}")
    
    def generate_key(self):
        """Generate a new encryption key."""
        self.stdout.write(self.style.NOTICE("Generating new encryption key..."))
        
        new_key = generate_encryption_key()
        
        self.stdout.write(self.style.SUCCESS(f"Generated key (base64): {new_key}"))
        self.stdout.write("\nAdd this to your settings:")
        self.stdout.write(f"ENCRYPTION_MASTER_KEY = '{new_key}'")
        
        self.stdout.write(self.style.WARNING("\n⚠️  Store this key securely!"))
        self.stdout.write("- Use environment variables in production")
        self.stdout.write("- Never commit keys to version control")
        self.stdout.write("- Consider using AWS KMS or HashiCorp Vault")
    
    def list_keys(self):
        """List all encryption keys."""
        self.stdout.write(self.style.NOTICE("Listing encryption keys..."))
        
        try:
            key_manager = KeyManager()
            keys = key_manager.list_keys()
            
            if not keys:
                self.stdout.write("No encryption keys found.")
                return
            
            self.stdout.write(f"\nFound {len(keys)} key(s):\n")
            
            for key in keys:
                status = "PRIMARY" if key.is_primary else "ACTIVE" if key.is_active else "EXPIRED"
                self.stdout.write(
                    f"  Version {key.version}: {status} "
                    f"(created: {key.created_at.strftime('%Y-%m-%d %H:%M')})"
                )
                if key.expires_at:
                    self.stdout.write(f"    Expires: {key.expires_at.strftime('%Y-%m-%d %H:%M')}")
            
            # Show current key
            current = key_manager.get_current_key()
            self.stdout.write(f"\nCurrent key: Version {current.version}")
            
        except Exception as e:
            raise CommandError(f"Failed to list keys: {str(e)}")
    
    def rotate_keys(self, dry_run):
        """Rotate encryption keys."""
        if dry_run:
            self.stdout.write(self.style.NOTICE("DRY RUN: Simulating key rotation..."))
        else:
            self.stdout.write(self.style.WARNING("Rotating encryption keys..."))
        
        try:
            result = rotate_encryption_keys(dry_run=dry_run)
            
            if result['status'] == 'success':
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Key rotation completed: v{result['old_version']} → v{result['new_version']}"
                ))
            else:
                self.stdout.write(self.style.NOTICE(
                    f"Dry run completed: would rotate v{result['current_version']} → v{result['new_version']}"
                ))
            
            if not dry_run:
                self.stdout.write(self.style.WARNING(
                    "\n⚠️  Important: Update your key configuration to include the new key!"
                ))
            
        except Exception as e:
            raise CommandError(f"Key rotation failed: {str(e)}")
    
    def validate_config(self):
        """Validate encryption configuration."""
        self.stdout.write(self.style.NOTICE("Validating encryption configuration..."))
        
        try:
            validate_encryption_config()
            
            # Show current configuration
            self.stdout.write(self.style.SUCCESS("✓ Configuration is valid!"))
            
            self.stdout.write("\nCurrent configuration:")
            self.stdout.write(f"  Environment: {settings.DEBUG and 'Development' or 'Production'}")
            self.stdout.write(f"  Key store: {getattr(settings, 'ENCRYPTION_KEY_STORE', 'local')}")
            self.stdout.write(f"  Backend: {getattr(settings, 'ENCRYPTION_BACKEND', 'aes')}")
            
            # Check for master key
            has_master = bool(getattr(settings, 'ENCRYPTION_MASTER_KEY', None))
            if has_master:
                self.stdout.write("  Master key: Configured ✓")
            else:
                self.stdout.write(self.style.WARNING("  Master key: Not configured ⚠️"))
            
            # Check for key versions
            key_configs = getattr(settings, 'ENCRYPTION_KEYS', {})
            if key_configs:
                self.stdout.write(f"  Key versions: {len(key_configs)} configured")
            else:
                self.stdout.write("  Key versions: Using default configuration")
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Configuration invalid: {str(e)}"))
            raise CommandError("Please fix the configuration errors above")
    
    def audit_usage(self):
        """Audit encryption usage across models."""
        self.stdout.write(self.style.NOTICE("Auditing encryption usage..."))
        
        try:
            stats = audit_encryption_usage()
            
            self.stdout.write(f"\nEncryption Usage Summary:")
            self.stdout.write(f"  Total models: {stats['total_models']}")
            self.stdout.write(f"  Models with encryption: {stats['encrypted_models']}")
            self.stdout.write(f"  Total fields: {stats['total_fields']}")
            self.stdout.write(f"  Encrypted fields: {stats['encrypted_fields']}")
            
            if stats['fields_by_type']:
                self.stdout.write("\nEncrypted field types:")
                for field_type, count in stats['fields_by_type'].items():
                    self.stdout.write(f"  {field_type}: {count}")
            
            if stats['models']:
                self.stdout.write("\nModels with encrypted fields:")
                for model_info in stats['models']:
                    self.stdout.write(
                        f"\n  {model_info['app_label']}.{model_info['model_name']}:"
                    )
                    for field in model_info['encrypted_fields']:
                        searchable = "searchable" if field['searchable'] else "not searchable"
                        self.stdout.write(
                            f"    - {field['name']} ({field['type']}, {searchable})"
                        )
            
            # Calculate coverage percentage
            if stats['total_models'] > 0:
                coverage = (stats['encrypted_models'] / stats['total_models']) * 100
                self.stdout.write(f"\nEncryption coverage: {coverage:.1f}%")
            
        except Exception as e:
            raise CommandError(f"Audit failed: {str(e)}")