"""
WebSocket Consumers

Django Channels consumers for handling WebSocket connections.
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from channels.auth import login
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    WebSocketConnection,
    WebSocketRoom,
    WebSocketMessage,
    WebSocketPresence
)
from .exceptions import (
    WebSocketAuthenticationError,
    WebSocketPermissionError,
    WebSocketRoomError
)
from .middleware import RateLimitMiddleware
from .serializers import MessageSerializer

User = get_user_model()
logger = logging.getLogger(__name__)


class BaseWebSocketConsumer(AsyncJsonWebsocketConsumer):
    """
    Base WebSocket consumer with common functionality.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.connection = None
        self.rooms = set()
        self.rate_limiter = RateLimitMiddleware()
    
    async def connect(self):
        """Handle WebSocket connection."""
        # Authenticate user
        self.user = self.scope.get('user')
        
        if not self.user or isinstance(self.user, AnonymousUser):
            await self.close(code=4001, reason='Authentication required')
            return
        
        # Create connection record
        self.connection = await self.create_connection()
        
        # Accept connection
        await self.accept()
        
        # Send welcome message
        await self.send_json({
            'type': 'connection.established',
            'connection_id': str(self.connection.connection_id),
            'user': {
                'id': str(self.user.id),
                'username': self.user.username
            }
        })
        
        logger.info(f"WebSocket connection established: {self.connection.connection_id}")
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if self.connection:
            # Leave all rooms
            for room_name in list(self.rooms):
                await self.leave_room(room_name)
            
            # Close connection
            await self.close_connection()
            
            logger.info(f"WebSocket connection closed: {self.connection.connection_id}")
    
    async def receive_json(self, content, **kwargs):
        """Handle incoming WebSocket message."""
        # Rate limiting
        if not await self.rate_limiter.check_rate_limit(self.user):
            await self.send_json({
                'type': 'error',
                'error': 'Rate limit exceeded'
            })
            return
        
        # Route message by type
        message_type = content.get('type')
        
        if not message_type:
            await self.send_json({
                'type': 'error',
                'error': 'Message type required'
            })
            return
        
        # Convert dots to underscores for method names
        handler_name = f"handle_{message_type.replace('.', '_')}"
        handler = getattr(self, handler_name, None)
        
        if handler:
            try:
                await handler(content)
            except Exception as e:
                logger.error(f"Error handling message {message_type}: {e}")
                await self.send_json({
                    'type': 'error',
                    'error': str(e)
                })
        else:
            await self.send_json({
                'type': 'error',
                'error': f'Unknown message type: {message_type}'
            })
    
    async def join_room(self, room_name: str):
        """Join a room."""
        # Check if room exists and user can join
        room = await self.get_room(room_name)
        if not room:
            raise WebSocketRoomError(f"Room {room_name} not found")
        
        if not await self.can_join_room(room):
            raise WebSocketPermissionError(f"Cannot join room {room_name}")
        
        # Add to channel layer group
        await self.channel_layer.group_add(
            room_name,
            self.channel_name
        )
        
        # Update connection
        await self.add_room_to_connection(room_name)
        
        # Track presence
        await self.update_presence(room, 'online')
        
        self.rooms.add(room_name)
        
        # Notify room members
        await self.channel_layer.group_send(
            room_name,
            {
                'type': 'user.joined',
                'user': {
                    'id': str(self.user.id),
                    'username': self.user.username
                },
                'room': room_name
            }
        )
        
        logger.info(f"User {self.user.username} joined room {room_name}")
    
    async def leave_room(self, room_name: str):
        """Leave a room."""
        if room_name not in self.rooms:
            return
        
        # Update presence
        room = await self.get_room(room_name)
        if room:
            await self.update_presence(room, 'offline')
        
        # Remove from channel layer group
        await self.channel_layer.group_discard(
            room_name,
            self.channel_name
        )
        
        # Update connection
        await self.remove_room_from_connection(room_name)
        
        self.rooms.discard(room_name)
        
        # Notify room members
        await self.channel_layer.group_send(
            room_name,
            {
                'type': 'user.left',
                'user': {
                    'id': str(self.user.id),
                    'username': self.user.username
                },
                'room': room_name
            }
        )
        
        logger.info(f"User {self.user.username} left room {room_name}")
    
    # Database operations
    @database_sync_to_async
    def create_connection(self):
        """Create connection record."""
        return WebSocketConnection.objects.create(
            user=self.user,
            channel_name=self.channel_name,
            ip_address=self.scope.get('client', ['', ''])[0],
            user_agent=dict(self.scope.get('headers', {})).get(b'user-agent', b'').decode(),
            protocol=self.scope.get('type', 'websocket'),
            path=self.scope.get('path', ''),
            query_params=dict(parse_qs(self.scope.get('query_string', b'').decode())),
            state='open'
        )
    
    @database_sync_to_async
    def close_connection(self):
        """Close connection record."""
        if self.connection:
            self.connection.close()
    
    @database_sync_to_async
    def get_room(self, room_name: str) -> Optional[WebSocketRoom]:
        """Get room by name."""
        try:
            return WebSocketRoom.objects.get(
                name=room_name,
                is_active=True
            )
        except WebSocketRoom.DoesNotExist:
            return None
    
    @database_sync_to_async
    def can_join_room(self, room: WebSocketRoom) -> bool:
        """Check if user can join room."""
        return room.can_join(self.user)
    
    @database_sync_to_async
    def add_room_to_connection(self, room_name: str):
        """Add room to connection subscriptions."""
        if self.connection:
            self.connection.add_room(room_name)
    
    @database_sync_to_async
    def remove_room_from_connection(self, room_name: str):
        """Remove room from connection subscriptions."""
        if self.connection:
            self.connection.remove_room(room_name)
    
    @database_sync_to_async
    def update_presence(self, room: WebSocketRoom, status: str):
        """Update user presence in room."""
        if not room.enable_presence:
            return
        
        presence, created = WebSocketPresence.objects.get_or_create(
            user=self.user,
            room=room,
            defaults={'status': status}
        )
        
        if not created:
            if status == 'online':
                presence.increment_connections()
            elif status == 'offline':
                presence.decrement_connections()
            else:
                presence.status = status
                presence.save()
    
    # Message handlers (to be implemented by subclasses)
    async def user_joined(self, event):
        """Handle user joined event."""
        await self.send_json(event)
    
    async def user_left(self, event):
        """Handle user left event."""
        await self.send_json(event)


class NotificationConsumer(BaseWebSocketConsumer):
    """
    Consumer for real-time notifications.
    """
    
    async def connect(self):
        """Connect and join user's notification channel."""
        await super().connect()
        
        # Join user's personal notification channel
        user_channel = f"notifications.user.{self.user.id}"
        await self.channel_layer.group_add(
            user_channel,
            self.channel_name
        )
        
        # Send pending notifications
        await self.send_pending_notifications()
    
    async def disconnect(self, close_code):
        """Disconnect from notification channel."""
        if self.user and not isinstance(self.user, AnonymousUser):
            user_channel = f"notifications.user.{self.user.id}"
            await self.channel_layer.group_discard(
                user_channel,
                self.channel_name
            )
        
        await super().disconnect(close_code)
    
    async def handle_notification_read(self, message):
        """Mark notification as read."""
        notification_id = message.get('notification_id')
        if notification_id:
            await self.mark_notification_read(notification_id)
            await self.send_json({
                'type': 'notification.read',
                'notification_id': notification_id
            })
    
    async def handle_notification_read_all(self, message):
        """Mark all notifications as read."""
        count = await self.mark_all_notifications_read()
        await self.send_json({
            'type': 'notification.read_all',
            'count': count
        })
    
    @database_sync_to_async
    def send_pending_notifications(self):
        """Send pending notifications."""
        # This would integrate with the notifications app
        pass
    
    @database_sync_to_async
    def mark_notification_read(self, notification_id: str):
        """Mark notification as read."""
        # This would integrate with the notifications app
        pass
    
    @database_sync_to_async
    def mark_all_notifications_read(self):
        """Mark all notifications as read."""
        # This would integrate with the notifications app
        return 0
    
    # Channel layer handlers
    async def notification_new(self, event):
        """Handle new notification."""
        await self.send_json(event)
    
    async def notification_update(self, event):
        """Handle notification update."""
        await self.send_json(event)


class EventConsumer(BaseWebSocketConsumer):
    """
    Consumer for real-time event streaming.
    """
    
    async def connect(self):
        """Connect and set up event subscriptions."""
        await super().connect()
        
        # Get event types from query params
        query_params = dict(parse_qs(self.scope.get('query_string', b'').decode()))
        event_types = query_params.get('events', [])
        
        # Subscribe to requested event types
        for event_type in event_types:
            await self.subscribe_to_event(event_type)
    
    async def handle_subscribe(self, message):
        """Subscribe to event type."""
        event_type = message.get('event_type')
        if event_type:
            await self.subscribe_to_event(event_type)
            await self.send_json({
                'type': 'subscription.created',
                'event_type': event_type
            })
    
    async def handle_unsubscribe(self, message):
        """Unsubscribe from event type."""
        event_type = message.get('event_type')
        if event_type:
            await self.unsubscribe_from_event(event_type)
            await self.send_json({
                'type': 'subscription.removed',
                'event_type': event_type
            })
    
    async def subscribe_to_event(self, event_type: str):
        """Subscribe to event type."""
        # Validate permission
        if not await self.can_subscribe_to_event(event_type):
            raise WebSocketPermissionError(f"Cannot subscribe to {event_type}")
        
        # Join event channel
        event_channel = f"events.{event_type}"
        await self.channel_layer.group_add(
            event_channel,
            self.channel_name
        )
    
    async def unsubscribe_from_event(self, event_type: str):
        """Unsubscribe from event type."""
        event_channel = f"events.{event_type}"
        await self.channel_layer.group_discard(
            event_channel,
            self.channel_name
        )
    
    @database_sync_to_async
    def can_subscribe_to_event(self, event_type: str) -> bool:
        """Check if user can subscribe to event type."""
        # Implement permission logic
        return True
    
    # Channel layer handlers
    async def event_published(self, event):
        """Handle published event."""
        await self.send_json(event)


class ChatConsumer(BaseWebSocketConsumer):
    """
    Consumer for real-time chat functionality.
    """
    
    async def handle_join_room(self, message):
        """Join a chat room."""
        room_name = message.get('room')
        if room_name:
            await self.join_room(room_name)
            
            # Send room history
            history = await self.get_room_history(room_name)
            await self.send_json({
                'type': 'room.joined',
                'room': room_name,
                'history': history
            })
    
    async def handle_leave_room(self, message):
        """Leave a chat room."""
        room_name = message.get('room')
        if room_name:
            await self.leave_room(room_name)
            await self.send_json({
                'type': 'room.left',
                'room': room_name
            })
    
    async def handle_message_send(self, message):
        """Send a message to a room."""
        room_name = message.get('room')
        content = message.get('content')
        message_type = message.get('message_type', 'text')
        
        if not room_name or room_name not in self.rooms:
            raise WebSocketRoomError("Not in room")
        
        if not content:
            raise ValidationError("Message content required")
        
        # Save message
        saved_message = await self.save_message(
            room_name,
            content,
            message_type
        )
        
        # Broadcast to room
        await self.channel_layer.group_send(
            room_name,
            {
                'type': 'message.new',
                'message': saved_message
            }
        )
    
    async def handle_typing_start(self, message):
        """Handle typing start indicator."""
        room_name = message.get('room')
        if room_name and room_name in self.rooms:
            await self.channel_layer.group_send(
                room_name,
                {
                    'type': 'typing.start',
                    'user': {
                        'id': str(self.user.id),
                        'username': self.user.username
                    },
                    'room': room_name
                }
            )
    
    async def handle_typing_stop(self, message):
        """Handle typing stop indicator."""
        room_name = message.get('room')
        if room_name and room_name in self.rooms:
            await self.channel_layer.group_send(
                room_name,
                {
                    'type': 'typing.stop',
                    'user': {
                        'id': str(self.user.id),
                        'username': self.user.username
                    },
                    'room': room_name
                }
            )
    
    @database_sync_to_async
    def get_room_history(self, room_name: str, limit: int = 50) -> List[Dict]:
        """Get room message history."""
        room = WebSocketRoom.objects.get(name=room_name)
        
        if not room.enable_history:
            return []
        
        messages = WebSocketMessage.objects.filter(
            room=room
        ).order_by('-created_at')[:limit]
        
        serializer = MessageSerializer(messages, many=True)
        return serializer.data
    
    @database_sync_to_async
    def save_message(self, room_name: str, content: str, message_type: str) -> Dict:
        """Save a message."""
        room = WebSocketRoom.objects.get(name=room_name)
        
        message = WebSocketMessage.objects.create(
            sender=self.user,
            room=room,
            connection=self.connection,
            message_type=message_type,
            content=content,
            delivery_status='delivered'
        )
        
        serializer = MessageSerializer(message)
        return serializer.data
    
    # Channel layer handlers
    async def message_new(self, event):
        """Handle new message."""
        await self.send_json(event)
    
    async def typing_start(self, event):
        """Handle typing start."""
        if event['user']['id'] != str(self.user.id):
            await self.send_json(event)
    
    async def typing_stop(self, event):
        """Handle typing stop."""
        if event['user']['id'] != str(self.user.id):
            await self.send_json(event)


class PresenceConsumer(BaseWebSocketConsumer):
    """
    Consumer for presence tracking.
    """
    
    async def handle_presence_update(self, message):
        """Update user presence."""
        status = message.get('status', 'online')
        status_message = message.get('status_message', '')
        
        # Update presence for all rooms
        for room_name in self.rooms:
            await self.update_room_presence(
                room_name,
                status,
                status_message
            )
    
    async def handle_presence_query(self, message):
        """Query presence for a room."""
        room_name = message.get('room')
        if room_name:
            presence_list = await self.get_room_presence(room_name)
            await self.send_json({
                'type': 'presence.list',
                'room': room_name,
                'presence': presence_list
            })
    
    @database_sync_to_async
    def update_room_presence(self, room_name: str, status: str, status_message: str):
        """Update presence in a room."""
        try:
            room = WebSocketRoom.objects.get(name=room_name)
            presence = WebSocketPresence.objects.get(
                user=self.user,
                room=room
            )
            presence.status = status
            presence.status_message = status_message
            presence.save()
            
            # Broadcast presence update
            self.channel_layer.group_send(
                room_name,
                {
                    'type': 'presence.update',
                    'user': {
                        'id': str(self.user.id),
                        'username': self.user.username
                    },
                    'status': status,
                    'status_message': status_message
                }
            )
        except (WebSocketRoom.DoesNotExist, WebSocketPresence.DoesNotExist):
            pass
    
    @database_sync_to_async
    def get_room_presence(self, room_name: str) -> List[Dict]:
        """Get presence list for a room."""
        try:
            room = WebSocketRoom.objects.get(name=room_name)
            presence_records = WebSocketPresence.objects.filter(
                room=room,
                status__in=['online', 'away', 'busy']
            ).select_related('user')
            
            return [
                {
                    'user': {
                        'id': str(p.user.id),
                        'username': p.user.username
                    },
                    'status': p.status,
                    'status_message': p.status_message,
                    'last_activity': p.last_activity_at.isoformat()
                }
                for p in presence_records
            ]
        except WebSocketRoom.DoesNotExist:
            return []
    
    # Channel layer handlers
    async def presence_update(self, event):
        """Handle presence update."""
        await self.send_json(event)