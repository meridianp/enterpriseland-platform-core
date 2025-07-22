"""
Management command to list API keys.

Usage:
    python manage.py list_api_keys                  # List all keys
    python manage.py list_api_keys --user=user@example.com
    python manage.py list_api_keys --expired        # List expired keys
    python manage.py list_api_keys --expiring-soon  # List keys expiring soon
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from api_keys.models import APIKey

User = get_user_model()


class Command(BaseCommand):
    help = 'List API keys'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Filter by user email'
        )
        parser.add_argument(
            '--application',
            type=str,
            help='Filter by application name'
        )
        parser.add_argument(
            '--expired',
            action='store_true',
            help='Show only expired keys'
        )
        parser.add_argument(
            '--expiring-soon',
            action='store_true',
            help='Show only keys expiring within 7 days'
        )
        parser.add_argument(
            '--active-only',
            action='store_true',
            help='Show only active keys'
        )
        parser.add_argument(
            '--format',
            choices=['table', 'json'],
            default='table',
            help='Output format (default: table)'
        )

    def handle(self, *args, **options):
        # Start with all keys
        queryset = APIKey.objects.all().select_related('user')

        # Apply filters
        if options['user']:
            try:
                user = User.objects.get(email=options['user'])
                queryset = queryset.filter(user=user)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"User '{options['user']}' not found")
                )
                return

        if options['application']:
            queryset = queryset.filter(application_name__icontains=options['application'])

        if options['expired']:
            queryset = queryset.filter(expires_at__lt=timezone.now())
        
        if options['expiring_soon']:
            queryset = queryset.expiring_soon(days=7)
        
        if options['active_only']:
            queryset = queryset.active()

        # Order by creation date
        queryset = queryset.order_by('-created_at')

        if not queryset.exists():
            self.stdout.write(self.style.WARNING('No API keys found'))
            return

        if options['format'] == 'json':
            self._output_json(queryset)
        else:
            self._output_table(queryset)

    def _output_table(self, queryset):
        """Output keys in table format."""
        # Header
        self.stdout.write('')
        self.stdout.write(f"{'Name':<30} {'Owner':<25} {'Type':<12} {'Status':<10} {'Expires':<12} {'Scopes'}")
        self.stdout.write('-' * 120)

        # Rows
        for key in queryset:
            owner = key.user.email if key.user else key.application_name
            if len(owner) > 24:
                owner = owner[:21] + '...'
            
            key_type = 'Application' if key.application_name else 'User'
            
            if key.is_expired:
                status = 'Expired'
                status_color = self.style.ERROR
            elif not key.is_active:
                status = 'Revoked'
                status_color = self.style.WARNING
            else:
                status = 'Active'
                status_color = self.style.SUCCESS
            
            expires_str = key.expires_at.strftime('%Y-%m-%d')
            scopes_str = ', '.join(key.scopes[:3])  # Show first 3 scopes
            if len(key.scopes) > 3:
                scopes_str += f' (+{len(key.scopes) - 3})'

            name = key.name
            if len(name) > 29:
                name = name[:26] + '...'

            self.stdout.write(
                f"{name:<30} {owner:<25} {key_type:<12} "
                f"{status_color(status):<10} {expires_str:<12} {scopes_str}"
            )

        self.stdout.write('')
        self.stdout.write(f'Total: {queryset.count()} API keys')

    def _output_json(self, queryset):
        """Output keys in JSON format."""
        import json
        
        keys_data = []
        for key in queryset:
            keys_data.append({
                'id': str(key.id),
                'name': key.name,
                'key_prefix': key.key_prefix,
                'owner': key.user.email if key.user else key.application_name,
                'type': 'application' if key.application_name else 'user',
                'scopes': key.scopes,
                'is_active': key.is_active,
                'is_expired': key.is_expired,
                'expires_at': key.expires_at.isoformat(),
                'last_used_at': key.last_used_at.isoformat() if key.last_used_at else None,
                'usage_count': key.usage_count,
                'rate_limit_per_hour': key.rate_limit_per_hour,
                'created_at': key.created_at.isoformat(),
            })
        
        self.stdout.write(json.dumps(keys_data, indent=2))