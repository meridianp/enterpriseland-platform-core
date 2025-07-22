"""Real-time communication service."""

import json
import logging
from typing import Dict, Any, List, Optional

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from .models import Channel, ChannelMember

User = get_user_model()
logger = logging.getLogger(__name__)


class RealtimeService:
    """Service for real-time communication features."""
    
    def __init__(self):
        """Initialize the realtime service."""
        self.channel_layer = get_channel_layer()
    
    async def broadcast_to_channel(self, channel: Channel, event_type: str, data: Dict[str, Any]):
        """Broadcast message to all channel members."""
        # Get all active members
        member_ids = await self._get_channel_member_ids(channel)
        
        # Send to each member's personal channel
        for user_id in member_ids:
            await self.send_to_user(user_id, event_type, {
                "channel_id": str(channel.id),
                **data
            })
    
    async def send_to_user(self, user_id: str, event_type: str, data: Dict[str, Any]):
        """Send message to specific user."""
        channel_name = f"user_{user_id}"
        
        try:
            await self.channel_layer.group_send(
                channel_name,
                {
                    "type": "communication_message",
                    "event": event_type,
                    "data": data,
                }
            )
        except Exception as e:
            logger.error(f"Failed to send real-time message to user {user_id}: {e}")
    
    async def add_user_to_channel(self, user_id: str, channel_id: str):
        """Add user to channel group for real-time updates."""
        channel_name = f"channel_{channel_id}"
        user_channel = f"user_{user_id}"
        
        await self.channel_layer.group_add(
            channel_name,
            user_channel
        )
    
    async def remove_user_from_channel(self, user_id: str, channel_id: str):
        """Remove user from channel group."""
        channel_name = f"channel_{channel_id}"
        user_channel = f"user_{user_id}"
        
        await self.channel_layer.group_discard(
            channel_name,
            user_channel
        )
    
    def send_typing_indicator(self, channel: Channel, user: User, is_typing: bool):
        """Send typing indicator to channel members."""
        data = {
            "user_id": str(user.id),
            "user_name": user.get_full_name(),
            "is_typing": is_typing,
        }
        
        async_to_sync(self.broadcast_to_channel)(
            channel,
            "typing_indicator",
            data
        )
    
    def send_presence_update(self, user: User, status: str, status_message: str = ""):
        """Send presence update to user's contacts."""
        data = {
            "user_id": str(user.id),
            "status": status,
            "status_message": status_message,
        }
        
        # Get user's channels
        channels = Channel.objects.filter(
            members__user=user,
            channel_type__in=["DIRECT", "PRIVATE"]
        ).distinct()
        
        # Send to each channel
        for channel in channels:
            async_to_sync(self.broadcast_to_channel)(
                channel,
                "presence_update",
                data
            )
    
    async def _get_channel_member_ids(self, channel: Channel) -> List[str]:
        """Get list of channel member IDs."""
        # Try cache first
        cache_key = f"channel_members_{channel.id}"
        member_ids = cache.get(cache_key)
        
        if member_ids is None:
            # Get from database
            member_ids = list(
                ChannelMember.objects.filter(
                    channel=channel
                ).values_list("user_id", flat=True)
            )
            # Convert UUIDs to strings
            member_ids = [str(uid) for uid in member_ids]
            
            # Cache for 5 minutes
            cache.set(cache_key, member_ids, 300)
        
        return member_ids
    
    def invalidate_channel_cache(self, channel: Channel):
        """Invalidate channel member cache."""
        cache_key = f"channel_members_{channel.id}"
        cache.delete(cache_key)


class PresenceService:
    """Service for managing user presence."""
    
    PRESENCE_TTL = 300  # 5 minutes
    
    def __init__(self):
        """Initialize presence service."""
        self.cache = cache
    
    def update_presence(self, user: User, status: str = "online", status_message: str = ""):
        """Update user presence."""
        key = f"presence_{user.id}"
        data = {
            "user_id": str(user.id),
            "status": status,
            "status_message": status_message,
            "last_seen": timezone.now().isoformat(),
        }
        
        self.cache.set(key, data, self.PRESENCE_TTL)
        
        # Send real-time update
        realtime = RealtimeService()
        realtime.send_presence_update(user, status, status_message)
    
    def get_presence(self, user_id: str) -> Dict[str, Any]:
        """Get user presence."""
        key = f"presence_{user_id}"
        data = self.cache.get(key)
        
        if data:
            return data
        
        return {
            "user_id": user_id,
            "status": "offline",
            "status_message": "",
            "last_seen": None,
        }
    
    def get_online_users(self, group) -> List[Dict[str, Any]]:
        """Get all online users in a group."""
        # Get all users in group
        users = User.objects.filter(groups=group)
        
        online_users = []
        for user in users:
            presence = self.get_presence(str(user.id))
            if presence["status"] in ["online", "away", "busy"]:
                online_users.append({
                    "user_id": str(user.id),
                    "username": user.username,
                    "full_name": user.get_full_name(),
                    "status": presence["status"],
                    "status_message": presence["status_message"],
                })
        
        return online_users
    
    def mark_offline(self, user: User):
        """Mark user as offline."""
        self.update_presence(user, "offline")


class MessageQueue:
    """Queue for handling high-volume message delivery."""
    
    def __init__(self):
        """Initialize message queue."""
        self.cache = cache
    
    def enqueue(self, user_id: str, message: Dict[str, Any]):
        """Add message to user's queue."""
        key = f"message_queue_{user_id}"
        
        # Get existing queue
        queue = self.cache.get(key, [])
        queue.append(message)
        
        # Save back to cache
        self.cache.set(key, queue, 3600)  # Keep for 1 hour
    
    def dequeue_all(self, user_id: str) -> List[Dict[str, Any]]:
        """Get and clear all messages for user."""
        key = f"message_queue_{user_id}"
        messages = self.cache.get(key, [])
        self.cache.delete(key)
        return messages
    
    def get_queue_size(self, user_id: str) -> int:
        """Get number of queued messages."""
        key = f"message_queue_{user_id}"
        queue = self.cache.get(key, [])
        return len(queue)