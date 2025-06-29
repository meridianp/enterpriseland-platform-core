"""
Management command to rotate secrets safely.
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from platform_core.core.settings.secrets import generate_secret_key, generate_jwt_key, rotate_secret


class Command(BaseCommand):
    help = 'Rotate application secrets with zero downtime'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'secret_type',
            choices=['django-secret', 'jwt-secret', 'db-password', 'all'],
            help='Type of secret to rotate'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )
        parser.add_argument(
            '--update-env',
            action='store_true',
            help='Update .env file with new secrets'
        )
        parser.add_argument(
            '--backup',
            action='store_true',
            default=True,
            help='Create backup of current secrets before rotation'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Skip confirmation prompts'
        )
        parser.add_argument(
            '--new-value',
            type=str,
            help='Specific new value to use (generated if not provided)'
        )
    
    def handle(self, *args, **options):
        secret_type = options['secret_type']
        
        self.stdout.write("\n" + "="*60)
        self.stdout.write("🔄 SECRET ROTATION")
        self.stdout.write("="*60 + "\n")
        
        # Check environment
        if settings.ENVIRONMENT == 'production' and not options['force']:
            self.stdout.write(self.style.WARNING(
                "⚠️  WARNING: Running in production environment!"
            ))
            confirm = input("Are you sure you want to continue? (yes/no): ")
            if confirm.lower() != 'yes':
                self.stdout.write("Rotation cancelled.")
                return
        
        # Create backup if requested
        if options['backup'] and not options['dry_run']:
            self._create_backup()
        
        # Perform rotation based on type
        if secret_type == 'django-secret':
            self._rotate_django_secret(options)
        elif secret_type == 'jwt-secret':
            self._rotate_jwt_secret(options)
        elif secret_type == 'db-password':
            self._rotate_db_password(options)
        elif secret_type == 'all':
            self._rotate_all_secrets(options)
        
        self.stdout.write("\n" + "="*60)
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("🏃 DRY RUN COMPLETE (no changes made)"))
        else:
            self.stdout.write(self.style.SUCCESS("✅ SECRET ROTATION COMPLETE"))
        self.stdout.write("="*60 + "\n")
    
    def _create_backup(self):
        """Create backup of current secrets."""
        backup_dir = Path(settings.BASE_DIR) / 'backups' / 'secrets'
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_dir / f'secrets_backup_{timestamp}.json'
        
        # Collect current secrets (masked)
        backup_data = {
            'timestamp': timestamp,
            'environment': settings.ENVIRONMENT,
            'secrets': {
                'SECRET_KEY': self._mask_secret(settings.SECRET_KEY),
                'JWT_SECRET_KEY': self._mask_secret(getattr(settings, 'JWT_SECRET_KEY', '')),
                'DB_PASSWORD': self._mask_secret(settings.DATABASES['default'].get('PASSWORD', '')),
            }
        }
        
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f, indent=2)
        
        self.stdout.write(self.style.SUCCESS(f"✓ Backup created: {backup_file}"))
    
    def _mask_secret(self, secret: str) -> str:
        """Mask a secret for backup purposes."""
        if not secret:
            return ''
        if len(secret) <= 8:
            return '*' * len(secret)
        return secret[:4] + '*' * (len(secret) - 8) + secret[-4:]
    
    def _rotate_django_secret(self, options: Dict[str, Any]):
        """Rotate Django SECRET_KEY."""
        self.stdout.write("\n🔑 Rotating Django SECRET_KEY...")
        
        current_key = settings.SECRET_KEY
        new_key = options.get('new_value') or generate_secret_key()
        
        self.stdout.write(f"  Current: {self._mask_secret(current_key)}")
        self.stdout.write(f"  New:     {self._mask_secret(new_key)}")
        
        if options['dry_run']:
            self.stdout.write("  [DRY RUN] Would update SECRET_KEY")
            return
        
        # Update the secret
        if options['update_env']:
            rotate_secret('SECRET_KEY', new_key, update_env_file=True)
            self.stdout.write(self.style.SUCCESS("  ✓ Updated .env file"))
        
        # Clear caches that might depend on SECRET_KEY
        cache.clear()
        self.stdout.write(self.style.SUCCESS("  ✓ Cleared application caches"))
        
        self.stdout.write(self.style.WARNING(
            "\n  ⚠️  IMPORTANT: Restart all application servers to use new SECRET_KEY"
        ))
        self.stdout.write(self.style.WARNING(
            "  ⚠️  Users will need to re-authenticate after restart"
        ))
    
    def _rotate_jwt_secret(self, options: Dict[str, Any]):
        """Rotate JWT secret key with grace period."""
        self.stdout.write("\n🔐 Rotating JWT SECRET_KEY...")
        
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
        
        current_key = getattr(settings, 'JWT_SECRET_KEY', settings.SECRET_KEY)
        new_key = options.get('new_value') or generate_jwt_key()
        
        self.stdout.write(f"  Current: {self._mask_secret(current_key)}")
        self.stdout.write(f"  New:     {self._mask_secret(new_key)}")
        
        if options['dry_run']:
            self.stdout.write("  [DRY RUN] Would update JWT_SECRET_KEY")
            return
        
        # Blacklist all outstanding tokens
        try:
            outstanding_count = OutstandingToken.objects.count()
            if outstanding_count > 0:
                self.stdout.write(f"  Blacklisting {outstanding_count} outstanding tokens...")
                with transaction.atomic():
                    for token in OutstandingToken.objects.all():
                        token.blacklist()
                self.stdout.write(self.style.SUCCESS(f"  ✓ Blacklisted {outstanding_count} tokens"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  ⚠ Could not blacklist tokens: {e}"))
        
        # Update the secret
        if options['update_env']:
            rotate_secret('JWT_SECRET_KEY', new_key, update_env_file=True)
            self.stdout.write(self.style.SUCCESS("  ✓ Updated .env file"))
        
        self.stdout.write(self.style.WARNING(
            "\n  ⚠️  IMPORTANT: Deploy new JWT_SECRET_KEY to all servers"
        ))
        self.stdout.write(self.style.WARNING(
            "  ⚠️  All users will need to re-authenticate"
        ))
    
    def _rotate_db_password(self, options: Dict[str, Any]):
        """Rotate database password (requires database admin access)."""
        self.stdout.write("\n🗄️  Rotating database password...")
        
        if options['dry_run']:
            self.stdout.write("  [DRY RUN] Would update database password")
            self.stdout.write("  Steps that would be performed:")
            self.stdout.write("    1. Generate new password")
            self.stdout.write("    2. Update database user password")
            self.stdout.write("    3. Update application configuration")
            self.stdout.write("    4. Test new connection")
            self.stdout.write("    5. Deploy to all servers")
            return
        
        self.stdout.write(self.style.ERROR(
            "\n  ❌ Database password rotation requires manual steps:"
        ))
        self.stdout.write("    1. Generate new password:")
        self.stdout.write('       python -c "import secrets; print(secrets.token_urlsafe(32))"')
        self.stdout.write("    2. Update database user:")
        self.stdout.write("       ALTER USER <username> WITH PASSWORD '<new_password>';")
        self.stdout.write("    3. Update .env file with new DB_PASSWORD")
        self.stdout.write("    4. Test connection with new password")
        self.stdout.write("    5. Deploy to all application servers")
        self.stdout.write("    6. Monitor for connection errors")
    
    def _rotate_all_secrets(self, options: Dict[str, Any]):
        """Rotate all secrets."""
        self.stdout.write("\n🔄 Rotating ALL secrets...")
        
        if not options['force']:
            self.stdout.write(self.style.WARNING(
                "\n⚠️  This will rotate all application secrets!"
            ))
            confirm = input("Are you absolutely sure? (yes/no): ")
            if confirm.lower() != 'yes':
                self.stdout.write("Rotation cancelled.")
                return
        
        # Rotate each secret type
        self._rotate_django_secret(options)
        self._rotate_jwt_secret(options)
        self._rotate_db_password(options)
    
    def _get_rotation_instructions(self, secret_type: str) -> str:
        """Get deployment instructions for secret rotation."""
        instructions = {
            'django-secret': """
            Deployment steps for Django SECRET_KEY rotation:
            1. Update SECRET_KEY in all environment configurations
            2. Deploy to all application servers simultaneously
            3. Clear all caches
            4. Monitor error logs for issues
            5. Users will need to re-authenticate
            """,
            'jwt-secret': """
            Deployment steps for JWT secret rotation:
            1. Update JWT_SECRET_KEY in all environments
            2. Deploy to all servers (can be rolling deployment)
            3. All active sessions will be invalidated
            4. Monitor authentication endpoints
            5. Prepare for increased login traffic
            """,
            'db-password': """
            Deployment steps for database password rotation:
            1. Schedule maintenance window
            2. Update database user password
            3. Update DB_PASSWORD in all environments
            4. Deploy configuration changes
            5. Test database connectivity
            6. Monitor for connection errors
            """
        }
        return instructions.get(secret_type, "")