"""
Management command to revoke API keys.

Usage:
    python manage.py revoke_api_key --key-id=<uuid>
    python manage.py revoke_api_key --user=user@example.com --all
    python manage.py revoke_api_key --expired  # Revoke all expired keys
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone

from api_keys.models import APIKey

User = get_user_model()


class Command(BaseCommand):
    help = 'Revoke API keys'

    def add_arguments(self, parser):
        parser.add_argument(
            '--key-id',
            type=str,
            help='Specific API key ID to revoke'
        )
        parser.add_argument(
            '--user',
            type=str,
            help='User email to revoke keys for'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Revoke all keys for the specified user'
        )
        parser.add_argument(
            '--expired',
            action='store_true',
            help='Revoke all expired keys'
        )
        parser.add_argument(
            '--reason',
            type=str,
            default='Revoked via management command',
            help='Reason for revocation'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be revoked without actually doing it'
        )

    def handle(self, *args, **options):
        # Determine which keys to revoke
        keys_to_revoke = []

        if options['key_id']:
            try:
                key = APIKey.objects.get(id=options['key_id'])
                if not key.is_active:
                    raise CommandError(f"API key is already revoked")
                keys_to_revoke = [key]
            except APIKey.DoesNotExist:
                raise CommandError(f"API key with ID '{options['key_id']}' does not exist")

        elif options['user']:
            try:
                user = User.objects.get(email=options['user'])
                if options['all']:
                    keys_to_revoke = list(APIKey.objects.filter(user=user, is_active=True))
                else:
                    raise CommandError("Must specify --all when using --user")
            except User.DoesNotExist:
                raise CommandError(f"User '{options['user']}' does not exist")

        elif options['expired']:
            keys_to_revoke = list(
                APIKey.objects.filter(
                    is_active=True,
                    expires_at__lt=timezone.now()
                )
            )

        else:
            raise CommandError(
                'Must specify one of: --key-id, --user --all, or --expired'
            )

        if not keys_to_revoke:
            self.stdout.write(self.style.WARNING('No API keys found to revoke'))
            return

        # Show what will be revoked
        self.stdout.write(f'Found {len(keys_to_revoke)} API key(s) to revoke:')
        
        for key in keys_to_revoke:
            owner = key.user.email if key.user else key.application_name
            status = 'Expired' if key.is_expired else 'Active'
            self.stdout.write(f'  - {key.name} ({key.key_prefix}...) - {owner} [{status}]')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('DRY RUN - No keys were actually revoked'))
            return

        # Ask for confirmation unless it's a single key
        if len(keys_to_revoke) > 1:
            confirm = input(f'\nRevoke {len(keys_to_revoke)} API keys? (y/N): ')
            if confirm.lower() != 'y':
                self.stdout.write('Revocation cancelled')
                return

        # Revoke the keys
        revoked_count = 0
        failed_count = 0

        for key in keys_to_revoke:
            try:
                owner = key.user.email if key.user else key.application_name
                self.stdout.write(f'Revoking key: {key.name} ({owner})...')
                
                key.revoke(reason=options['reason'])
                
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ Revoked successfully')
                )
                revoked_count += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Failed to revoke: {str(e)}')
                )
                failed_count += 1

        # Summary
        self.stdout.write('')
        self.stdout.write(f'Revocation complete:')
        self.stdout.write(f'  - Successfully revoked: {revoked_count}')
        if failed_count > 0:
            self.stdout.write(f'  - Failed: {failed_count}')