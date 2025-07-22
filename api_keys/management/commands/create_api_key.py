"""
Management command to create API keys.

Usage:
    python manage.py create_api_key --user=user@example.com --name="My API Key" --scopes=read,write
    python manage.py create_api_key --application="My App" --scopes=read --rate-limit=500
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from api_keys.models import APIKey

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a new API key'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='User email to create the key for (mutually exclusive with --application)'
        )
        parser.add_argument(
            '--application',
            type=str,
            help='Application name to create the key for (mutually exclusive with --user)'
        )
        parser.add_argument(
            '--name',
            type=str,
            required=True,
            help='Name for the API key'
        )
        parser.add_argument(
            '--scopes',
            type=str,
            required=True,
            help='Comma-separated list of scopes (e.g., read,write,assessments:read)'
        )
        parser.add_argument(
            '--expires-in-days',
            type=int,
            default=365,
            help='Number of days until expiration (default: 365)'
        )
        parser.add_argument(
            '--rate-limit',
            type=int,
            default=1000,
            help='Rate limit per hour (default: 1000)'
        )
        parser.add_argument(
            '--allowed-ips',
            type=str,
            help='Comma-separated list of allowed IP addresses'
        )

    def handle(self, *args, **options):
        # Validate arguments
        if not options['user'] and not options['application']:
            raise CommandError('Either --user or --application must be specified')
        
        if options['user'] and options['application']:
            raise CommandError('Cannot specify both --user and --application')

        # Get user if specified
        user = None
        if options['user']:
            try:
                user = User.objects.get(email=options['user'])
            except User.DoesNotExist:
                raise CommandError(f"User with email '{options['user']}' does not exist")

        # Parse scopes
        scopes = [scope.strip() for scope in options['scopes'].split(',')]
        
        # Validate scopes
        valid_scopes = [choice[0] for choice in APIKey.Scope.choices]
        invalid_scopes = [scope for scope in scopes if scope not in valid_scopes]
        if invalid_scopes:
            raise CommandError(f"Invalid scopes: {', '.join(invalid_scopes)}")

        # Parse allowed IPs
        allowed_ips = []
        if options['allowed_ips']:
            allowed_ips = [ip.strip() for ip in options['allowed_ips'].split(',')]

        try:
            # Create the API key
            api_key, raw_key = APIKey.objects.create_key(
                user=user,
                name=options['name'],
                scopes=scopes,
                expires_in_days=options['expires_in_days'],
                rate_limit=options['rate_limit'],
                application_name=options['application'] or '',
                allowed_ips=allowed_ips
            )

            self.stdout.write(
                self.style.SUCCESS(f'API key created successfully!')
            )
            self.stdout.write(f'ID: {api_key.id}')
            self.stdout.write(f'Name: {api_key.name}')
            self.stdout.write(f'Owner: {user.email if user else options["application"]}')
            self.stdout.write(f'Scopes: {", ".join(scopes)}')
            self.stdout.write(f'Expires: {api_key.expires_at}')
            self.stdout.write(f'Rate Limit: {api_key.rate_limit_per_hour}/hour')
            self.stdout.write('')
            self.stdout.write(
                self.style.WARNING('API Key (store this securely - it will not be shown again):')
            )
            self.stdout.write(self.style.HTTP_INFO(raw_key))

        except Exception as e:
            raise CommandError(f'Failed to create API key: {str(e)}')