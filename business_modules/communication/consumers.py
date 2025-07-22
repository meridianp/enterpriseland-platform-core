"""WebSocket consumers for real-time communication."""

import json
import logging
from typing import Dict, Any

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from .models import Channel, ChannelMember, Message, Notification
from .services import MessageService, NotificationService
from .realtime import RealtimeService, PresenceService

User = get_user_model()
logger = logging.getLogger(__name__)


class BaseConsumer(AsyncWebsocketConsumer):
    """Base WebSocket consumer with authentication."""
    
    async def connect(self):
        """Handle WebSocket connection."""
        # Get user from scope
        self.user = self.scope["user"]
        
        if isinstance(self.user, AnonymousUser):
            await self.close()
            return
        
        # Accept connection
        await self.accept()
        
        # Add user to their personal group
        self.user_group = f"user_{self.user.id}"
        await self.channel_layer.group_add(
            self.user_group,
            self.channel_name
        )
        
        await self.on_connect()
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "user_group"):
            await self.channel_layer.group_discard(
                self.user_group,
                self.channel_name
            )
        
        await self.on_disconnect(close_code)
    
    async def on_connect(self):
        """Override in subclasses for connection logic."""
        pass
    
    async def on_disconnect(self, close_code):
        """Override in subclasses for disconnection logic."""
        pass
    
    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            message_type = data.get("type")
            
            if message_type:
                handler = getattr(self, f"handle_{message_type}", None)
                if handler:
                    await handler(data)
                else:
                    await self.send_error(f"Unknown message type: {message_type}")
            else:
                await self.send_error("Message type is required")
        
        except json.JSONDecodeError:
            await self.send_error("Invalid JSON")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await self.send_error("Internal server error")
    
    async def send_error(self, error: str):
        """Send error message to client."""
        await self.send(text_data=json.dumps({
            "type": "error",
            "error": error
        }))
    
    # Channel layer message handlers
    async def communication_message(self, event):
        """Handle communication messages from channel layer."""
        await self.send(text_data=json.dumps({
            "type": event["event"],
            "data": event["data"]
        }))


class MessageConsumer(BaseConsumer):
    """WebSocket consumer for real-time messaging."""
    
    def __init__(self, *args, **kwargs):
        """Initialize consumer."""
        super().__init__(*args, **kwargs)
        self.channel_groups = set()
        self.realtime_service = RealtimeService()
    
    async def on_connect(self):
        """Handle connection for messaging."""
        # Get user's channels and join groups
        channels = await self.get_user_channels()
        
        for channel in channels:
            channel_group = f"channel_{channel.id}"
            self.channel_groups.add(channel_group)
            await self.channel_layer.group_add(
                channel_group,
                self.channel_name
            )
        
        # Send connection confirmation
        await self.send(text_data=json.dumps({
            "type": "connected",
            "channels": [str(c.id) for c in channels]
        }))
    
    async def on_disconnect(self, close_code):
        """Handle disconnection for messaging."""
        # Leave all channel groups
        for channel_group in self.channel_groups:
            await self.channel_layer.group_discard(
                channel_group,
                self.channel_name
            )
    
    async def handle_message(self, data: Dict[str, Any]):
        """Handle sending a message."""
        channel_id = data.get("channel_id")
        content = data.get("content")
        
        if not channel_id or not content:
            await self.send_error("channel_id and content are required")
            return
        
        # Send message via service
        message = await self.send_message(
            channel_id=channel_id,
            content=content,
            message_type=data.get("message_type", "TEXT"),
            metadata=data.get("metadata", {})
        )
        
        if message:
            # Broadcast to channel
            await self.realtime_service.broadcast_to_channel(
                message.channel,
                "message",
                {
                    "id": str(message.id),
                    "channel_id": str(message.channel_id),
                    "sender_id": str(message.sender_id),
                    "content": message.content,
                    "created_at": message.created_at.isoformat(),
                }
            )
    
    async def handle_typing(self, data: Dict[str, Any]):
        """Handle typing indicator."""
        channel_id = data.get("channel_id")
        is_typing = data.get("is_typing", True)
        
        if not channel_id:
            await self.send_error("channel_id is required")
            return
        
        # Broadcast typing indicator
        await self.channel_layer.group_send(
            f"channel_{channel_id}",
            {
                "type": "communication_message",
                "event": "typing_indicator",
                "data": {
                    "user_id": str(self.user.id),
                    "user_name": self.user.get_full_name(),
                    "is_typing": is_typing,
                }
            }
        )
    
    async def handle_mark_read(self, data: Dict[str, Any]):
        """Handle marking channel as read."""
        channel_id = data.get("channel_id")
        
        if not channel_id:
            await self.send_error("channel_id is required")
            return
        
        # Mark channel as read
        await self.mark_channel_read(channel_id)
        
        # Send confirmation
        await self.send(text_data=json.dumps({
            "type": "marked_read",
            "channel_id": channel_id
        }))
    
    @database_sync_to_async
    def get_user_channels(self):
        """Get user's channels."""
        return list(Channel.objects.filter(
            members__user=self.user,
            is_archived=False
        ).distinct())
    
    @database_sync_to_async
    def send_message(self, channel_id: str, content: str, **kwargs) -> Message:
        """Send a message through the service."""
        try:
            channel = Channel.objects.get(id=channel_id)
            service = MessageService()
            return service.send_message(
                channel=channel,
                sender=self.user,
                content=content,
                **kwargs
            )
        except Channel.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return None
    
    @database_sync_to_async
    def mark_channel_read(self, channel_id: str):
        """Mark channel as read."""
        try:
            member = ChannelMember.objects.get(
                channel_id=channel_id,
                user=self.user
            )
            member.mark_as_read()
        except ChannelMember.DoesNotExist:
            pass


class NotificationConsumer(BaseConsumer):
    """WebSocket consumer for real-time notifications."""
    
    async def on_connect(self):
        """Handle connection for notifications."""
        # Send unread count
        unread_count = await self.get_unread_count()
        
        await self.send(text_data=json.dumps({
            "type": "connected",
            "unread_count": unread_count
        }))
    
    async def handle_mark_read(self, data: Dict[str, Any]):
        """Handle marking notifications as read."""
        notification_ids = data.get("notification_ids", [])
        
        if notification_ids:
            count = await self.mark_notifications_read(notification_ids)
        else:
            # Mark all as read
            count = await self.mark_all_read()
        
        # Send updated unread count
        unread_count = await self.get_unread_count()
        
        await self.send(text_data=json.dumps({
            "type": "marked_read",
            "marked_count": count,
            "unread_count": unread_count
        }))
    
    @database_sync_to_async
    def get_unread_count(self) -> int:
        """Get unread notification count."""
        return Notification.objects.filter(
            recipient=self.user,
            is_read=False,
            is_archived=False
        ).count()
    
    @database_sync_to_async
    def mark_notifications_read(self, notification_ids: list) -> int:
        """Mark specific notifications as read."""
        from django.utils import timezone
        return Notification.objects.filter(
            id__in=notification_ids,
            recipient=self.user,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
    
    @database_sync_to_async
    def mark_all_read(self) -> int:
        """Mark all notifications as read."""
        service = NotificationService()
        return service.mark_notifications_read(self.user)


class PresenceConsumer(BaseConsumer):
    """WebSocket consumer for user presence."""
    
    def __init__(self, *args, **kwargs):
        """Initialize consumer."""
        super().__init__(*args, **kwargs)
        self.presence_service = PresenceService()
    
    async def on_connect(self):
        """Handle connection for presence."""
        # Update user presence
        await self.update_presence("online")
        
        # Get online users
        online_users = await self.get_online_users()
        
        await self.send(text_data=json.dumps({
            "type": "connected",
            "online_users": online_users
        }))
    
    async def on_disconnect(self, close_code):
        """Handle disconnection for presence."""
        # Update user presence
        await self.update_presence("offline")
    
    async def handle_update_status(self, data: Dict[str, Any]):
        """Handle status update."""
        status = data.get("status", "online")
        status_message = data.get("status_message", "")
        
        await self.update_presence(status, status_message)
        
        # Broadcast to contacts
        await self.broadcast_presence_update(status, status_message)
    
    async def handle_heartbeat(self, data: Dict[str, Any]):
        """Handle heartbeat to maintain presence."""
        await self.update_presence("online")
        
        await self.send(text_data=json.dumps({
            "type": "heartbeat_ack",
            "timestamp": data.get("timestamp")
        }))
    
    @database_sync_to_async
    def update_presence(self, status: str, status_message: str = ""):
        """Update user presence."""
        self.presence_service.update_presence(
            self.user,
            status,
            status_message
        )
    
    @database_sync_to_async
    def get_online_users(self) -> list:
        """Get online users in group."""
        return self.presence_service.get_online_users(
            self.user.groups.first()
        )
    
    async def broadcast_presence_update(self, status: str, status_message: str):
        """Broadcast presence update to contacts."""
        # Get user's channels
        channels = await self.get_user_channels()
        
        # Get unique users from channels
        user_ids = set()
        for channel in channels:
            members = await self.get_channel_members(channel)
            user_ids.update(str(m.user_id) for m in members if m.user_id != self.user.id)
        
        # Send to each user
        for user_id in user_ids:
            await self.channel_layer.group_send(
                f"user_{user_id}",
                {
                    "type": "communication_message",
                    "event": "presence_update",
                    "data": {
                        "user_id": str(self.user.id),
                        "status": status,
                        "status_message": status_message,
                    }
                }
            )
    
    @database_sync_to_async
    def get_user_channels(self):
        """Get user's channels for presence updates."""
        return list(Channel.objects.filter(
            members__user=self.user,
            channel_type__in=["DIRECT", "PRIVATE"]
        ).distinct())
    
    @database_sync_to_async
    def get_channel_members(self, channel):
        """Get channel members."""
        return list(channel.members.all())