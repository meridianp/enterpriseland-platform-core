"""
Management command to rotate API keys.

Usage:
    python manage.py rotate_api_keys --expiring-in-days=30  # Rotate keys expiring in 30 days
    python manage.py rotate_api_keys --all                  # Rotate all active keys
    python manage.py rotate_api_keys --key-id=<uuid>        # Rotate specific key
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import timedelta

from api_keys.models import APIKey


class Command(BaseCommand):
    help = 'Rotate API keys'

    def add_arguments(self, parser):
        parser.add_argument(
            '--expiring-in-days',
            type=int,
            help='Rotate keys expiring within this many days'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Rotate all active API keys'
        )
        parser.add_argument(
            '--key-id',
            type=str,
            help='Rotate specific API key by ID'
        )
        parser.add_argument(
            '--overlap-hours',
            type=int,
            default=24,
            help='Hours to keep old keys active during transition (default: 24)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be rotated without actually doing it'
        )

    def handle(self, *args, **options):
        # Determine which keys to rotate
        if options['key_id']:
            try:
                keys_to_rotate = [APIKey.objects.get(id=options['key_id'])]
            except APIKey.DoesNotExist:
                raise CommandError(f"API key with ID '{options['key_id']}' does not exist")
        
        elif options['expiring_in_days']:
            keys_to_rotate = APIKey.objects.expiring_soon(
                days=options['expiring_in_days']
            ).filter(is_active=True)
        
        elif options['all']:
            keys_to_rotate = APIKey.objects.active()
        
        else:
            raise CommandError(
                'Must specify one of: --expiring-in-days, --all, or --key-id'
            )

        if not keys_to_rotate:
            self.stdout.write(self.style.WARNING('No API keys found to rotate'))
            return

        self.stdout.write(f'Found {len(keys_to_rotate)} API key(s) to rotate:')
        
        for key in keys_to_rotate:
            owner = key.user.email if key.user else key.application_name
            self.stdout.write(f'  - {key.name} ({key.key_prefix}...) - {owner}')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('DRY RUN - No keys were actually rotated'))
            return

        # Ask for confirmation
        if not options['all'] and not options['key_id']:
            confirm = input('\nProceed with rotation? (y/N): ')
            if confirm.lower() != 'y':
                self.stdout.write('Rotation cancelled')
                return

        # Rotate the keys
        rotated_count = 0
        failed_count = 0

        for key in keys_to_rotate:
            try:
                owner = key.user.email if key.user else key.application_name
                self.stdout.write(f'Rotating key: {key.name} ({owner})...')
                
                new_key, raw_key = key.rotate()
                
                # Set overlap period
                if options['overlap_hours'] > 0:
                    key.expires_at = timezone.now() + timedelta(hours=options['overlap_hours'])
                    key.save(update_fields=['expires_at'])
                
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ New key created: {new_key.key_prefix}...')
                )
                self.stdout.write(f'  ✓ Old key will expire in {options["overlap_hours"]} hours')
                
                # Only show the raw key for single key rotations
                if options['key_id']:
                    self.stdout.write('')
                    self.stdout.write(
                        self.style.WARNING('New API Key (store securely):')
                    )
                    self.stdout.write(self.style.HTTP_INFO(raw_key))
                
                rotated_count += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Failed to rotate: {str(e)}')
                )
                failed_count += 1

        # Summary
        self.stdout.write('')
        self.stdout.write(f'Rotation complete:')
        self.stdout.write(f'  - Successfully rotated: {rotated_count}')
        if failed_count > 0:
            self.stdout.write(f'  - Failed: {failed_count}')
        
        if rotated_count > 1:
            self.stdout.write('')
            self.stdout.write(
                self.style.WARNING(
                    'New API keys have been created. '
                    'Update your applications with the new keys within '
                    f'{options["overlap_hours"]} hours.'
                )
            )