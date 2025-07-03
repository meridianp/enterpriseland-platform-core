"""
WebSocket Cleanup Management Command
"""

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from platform_core.websocket.models import (
    WebSocketConnection,
    WebSocketMessage,
    WebSocketPresence
)


class Command(BaseCommand):
    help = 'Clean up old WebSocket data'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--connection-hours',
            type=int,
            default=24,
            help='Remove closed connections older than N hours (default: 24)'
        )
        parser.add_argument(
            '--message-days',
            type=int,
            default=7,
            help='Remove messages older than N days (default: 7)'
        )
        parser.add_argument(
            '--presence-hours',
            type=int,
            default=72,
            help='Remove offline presence older than N hours (default: 72)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without deleting'
        )
    
    def handle(self, *args, **options):
        """Handle cleanup command."""
        connection_hours = options['connection_hours']
        message_days = options['message_days']
        presence_hours = options['presence_hours']
        dry_run = options['dry_run']
        
        now = timezone.now()
        
        # Clean up old closed connections
        connection_cutoff = now - timedelta(hours=connection_hours)
        old_connections = WebSocketConnection.objects.filter(
            state='closed',
            disconnected_at__lt=connection_cutoff
        )
        
        connection_count = old_connections.count()
        if connection_count > 0:
            if dry_run:
                self.stdout.write(
                    f"Would delete {connection_count} closed connections"
                )
            else:
                old_connections.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deleted {connection_count} closed connections"
                    )
                )
        
        # Clean up old messages based on room retention settings
        for room in WebSocketMessage.objects.values('room').distinct():
            if room['room']:
                # Get room retention setting
                from platform_core.websocket.models import WebSocketRoom
                try:
                    room_obj = WebSocketRoom.objects.get(id=room['room'])
                    retention_days = room_obj.message_retention_days
                    
                    if retention_days > 0:
                        message_cutoff = now - timedelta(days=retention_days)
                        old_messages = WebSocketMessage.objects.filter(
                            room=room_obj,
                            created_at__lt=message_cutoff
                        )
                        
                        message_count = old_messages.count()
                        if message_count > 0:
                            if dry_run:
                                self.stdout.write(
                                    f"Would delete {message_count} messages "
                                    f"from room {room_obj.name}"
                                )
                            else:
                                old_messages.delete()
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"Deleted {message_count} messages "
                                        f"from room {room_obj.name}"
                                    )
                                )
                except WebSocketRoom.DoesNotExist:
                    pass
        
        # Also clean up messages older than global limit
        global_message_cutoff = now - timedelta(days=message_days)
        old_global_messages = WebSocketMessage.objects.filter(
            created_at__lt=global_message_cutoff
        )
        
        global_message_count = old_global_messages.count()
        if global_message_count > 0:
            if dry_run:
                self.stdout.write(
                    f"Would delete {global_message_count} old messages globally"
                )
            else:
                old_global_messages.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deleted {global_message_count} old messages globally"
                    )
                )
        
        # Clean up offline presence records
        presence_cutoff = now - timedelta(hours=presence_hours)
        old_presence = WebSocketPresence.objects.filter(
            status='offline',
            last_activity_at__lt=presence_cutoff,
            connection_count=0
        )
        
        presence_count = old_presence.count()
        if presence_count > 0:
            if dry_run:
                self.stdout.write(
                    f"Would delete {presence_count} offline presence records"
                )
            else:
                old_presence.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deleted {presence_count} offline presence records"
                    )
                )
        
        # Mark stale connections as closed
        stale_cutoff = now - timedelta(minutes=5)
        stale_connections = WebSocketConnection.objects.filter(
            state='open',
            last_seen_at__lt=stale_cutoff
        )
        
        stale_count = stale_connections.count()
        if stale_count > 0:
            if dry_run:
                self.stdout.write(
                    f"Would mark {stale_count} stale connections as closed"
                )
            else:
                for conn in stale_connections:
                    conn.close()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Marked {stale_count} stale connections as closed"
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS('WebSocket cleanup completed')
        )