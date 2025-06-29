"""
Management command to generate a new Django secret key.
"""

from django.core.management.base import BaseCommand
from django.core.management.utils import get_random_secret_key


class Command(BaseCommand):
    help = 'Generate a new Django secret key'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--length',
            type=int,
            default=50,
            help='Length of the secret key (default: 50)'
        )
        parser.add_argument(
            '--jwt',
            action='store_true',
            help='Generate a JWT secret key instead'
        )
    
    def handle(self, *args, **options):
        if options['jwt']:
            # Generate JWT secret key
            import secrets
            key = secrets.token_urlsafe(64)
            self.stdout.write("\n🔐 Generated JWT Secret Key:")
            self.stdout.write(f"{key}\n")
            self.stdout.write("Add this to your .env file as:")
            self.stdout.write(f"JWT_SECRET_KEY={key}\n")
        else:
            # Generate Django secret key
            key = get_random_secret_key()
            
            # Ensure minimum length
            while len(key) < options['length']:
                key += get_random_secret_key()
            
            key = key[:options['length']]
            
            self.stdout.write("\n🔑 Generated Django Secret Key:")
            self.stdout.write(f"{key}\n")
            self.stdout.write("Add this to your .env file as:")
            self.stdout.write(f"SECRET_KEY={key}\n")