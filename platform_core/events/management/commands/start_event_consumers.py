"""
Start Event Consumers Management Command
"""

import signal
import sys
import time
from django.core.management.base import BaseCommand
from django.conf import settings

from platform_core.events.consumers import consumer_manager


class Command(BaseCommand):
    help = 'Start event consumers for all active subscriptions'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--subscription',
            type=str,
            help='Start only specific subscription by name'
        )
        parser.add_argument(
            '--no-daemon',
            action='store_true',
            help='Run in foreground (for development)'
        )
    
    def handle(self, *args, **options):
        """Handle command execution."""
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        subscription_name = options.get('subscription')
        
        if subscription_name:
            # Start specific subscription
            from platform_core.events.models import EventSubscription
            
            try:
                subscription = EventSubscription.objects.get(
                    name=subscription_name,
                    is_active=True
                )
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Starting consumer for subscription: {subscription_name}'
                    )
                )
                
                consumer_manager.start_consumer(subscription)
                
            except EventSubscription.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(
                        f'Subscription "{subscription_name}" not found or inactive'
                    )
                )
                return
        else:
            # Start all active subscriptions
            self.stdout.write(
                self.style.SUCCESS('Starting all event consumers...')
            )
            
            consumer_manager.start_all()
        
        # Get status
        status = consumer_manager.get_status()
        self.stdout.write(
            self.style.SUCCESS(
                f'Started {status["active_consumers"]} consumers'
            )
        )
        
        # List active consumers
        for name, info in status['consumers'].items():
            self.stdout.write(
                f'  - {name}: {", ".join(info["event_types"])}'
            )
        
        # Keep running if not daemon mode
        if not options.get('no_daemon'):
            self.stdout.write(
                self.style.SUCCESS(
                    'Event consumers started. Press Ctrl+C to stop.'
                )
            )
            
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.stdout.write(
            self.style.WARNING('Shutting down event consumers...')
        )
        
        self.running = False
        consumer_manager.stop_all()
        
        self.stdout.write(
            self.style.SUCCESS('Event consumers stopped.')
        )
        
        sys.exit(0)