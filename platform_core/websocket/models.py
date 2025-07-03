"""
WebSocket Models

Defines models for WebSocket connections, rooms, and messages.
"""

import uuid
from typing import Dict, Any, List
from datetime import timedelta
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from platform_core.common.models import BaseModel, TenantFilteredModel

User = get_user_model()


class WebSocketConnection(TenantFilteredModel):
    """
    Tracks active WebSocket connections.
    """
    
    CONNECTION_STATES = [
        ('connecting', 'Connecting'),
        ('open', 'Open'),
        ('closing', 'Closing'),
        ('closed', 'Closed'),
    ]
    
    # Connection identification
    connection_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        help_text=_("Unique connection identifier")
    )
    channel_name = models.CharField(
        max_length=255,
        unique=True,
        help_text=_("Django Channels channel name")
    )
    
    # User and session
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='websocket_connections'
    )
    session_key = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Django session key")
    )
    
    # Connection info
    state = models.CharField(
        max_length=20,
        choices=CONNECTION_STATES,
        default='connecting'
    )
    ip_address = models.GenericIPAddressField(
        help_text=_("Client IP address")
    )
    user_agent = models.TextField(
        blank=True,
        help_text=_("Client user agent")
    )
    
    # Protocol info
    protocol = models.CharField(
        max_length=50,
        default='ws',
        help_text=_("WebSocket protocol (ws/wss)")
    )
    path = models.CharField(
        max_length=255,
        help_text=_("Connection path")
    )
    query_params = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Query parameters")
    )
    
    # Timing
    connected_at = models.DateTimeField(
        auto_now_add=True
    )
    last_seen_at = models.DateTimeField(
        auto_now=True
    )
    disconnected_at = models.DateTimeField(
        null=True,
        blank=True
    )
    
    # Subscriptions
    subscribed_rooms = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text=_("List of subscribed room names")
    )
    subscribed_channels = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text=_("List of subscribed channel patterns")
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional connection metadata")
    )
    
    class Meta:
        db_table = 'websocket_connections'
        verbose_name = 'WebSocket Connection'
        verbose_name_plural = 'WebSocket Connections'
        indexes = [
            models.Index(fields=['user', 'state']),
            models.Index(fields=['connected_at']),
            models.Index(fields=['last_seen_at']),
        ]
        ordering = ['-connected_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.connection_id}"
    
    def close(self):
        """Mark connection as closed."""
        self.state = 'closed'
        self.disconnected_at = timezone.now()
        self.save(update_fields=['state', 'disconnected_at'])
    
    def add_room(self, room_name: str):
        """Add room to subscriptions."""
        if room_name not in self.subscribed_rooms:
            self.subscribed_rooms.append(room_name)
            self.save(update_fields=['subscribed_rooms'])
    
    def remove_room(self, room_name: str):
        """Remove room from subscriptions."""
        if room_name in self.subscribed_rooms:
            self.subscribed_rooms.remove(room_name)
            self.save(update_fields=['subscribed_rooms'])
    
    @property
    def duration(self):
        """Get connection duration."""
        if self.disconnected_at:
            return self.disconnected_at - self.connected_at
        return timezone.now() - self.connected_at


class WebSocketRoom(TenantFilteredModel):
    """
    Represents a WebSocket room/channel for grouping connections.
    """
    
    ROOM_TYPES = [
        ('public', 'Public Room'),
        ('private', 'Private Room'),
        ('direct', 'Direct Message'),
        ('broadcast', 'Broadcast Channel'),
        ('presence', 'Presence Channel'),
    ]
    
    # Room identification
    name = models.CharField(
        max_length=100,
        validators=[RegexValidator(r'^[a-zA-Z0-9._-]+$')],
        help_text=_("Room name identifier")
    )
    display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Human-readable room name")
    )
    room_type = models.CharField(
        max_length=20,
        choices=ROOM_TYPES,
        default='public'
    )
    
    # Configuration
    description = models.TextField(
        blank=True
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Room is active and accepting connections")
    )
    is_persistent = models.BooleanField(
        default=True,
        help_text=_("Room persists when empty")
    )
    
    # Access control
    owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='owned_rooms'
    )
    allowed_users = models.ManyToManyField(
        User,
        blank=True,
        related_name='allowed_rooms',
        help_text=_("Users allowed to join (empty = public)")
    )
    require_authentication = models.BooleanField(
        default=True,
        help_text=_("Require authentication to join")
    )
    
    # Limits
    max_connections = models.IntegerField(
        default=0,
        help_text=_("Maximum connections (0 = unlimited)")
    )
    message_retention_days = models.IntegerField(
        default=7,
        help_text=_("Days to retain messages")
    )
    
    # Settings
    enable_presence = models.BooleanField(
        default=True,
        help_text=_("Track user presence")
    )
    enable_history = models.BooleanField(
        default=True,
        help_text=_("Store message history")
    )
    enable_typing = models.BooleanField(
        default=True,
        help_text=_("Show typing indicators")
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True
    )
    
    class Meta:
        db_table = 'websocket_rooms'
        verbose_name = 'WebSocket Room'
        verbose_name_plural = 'WebSocket Rooms'
        unique_together = [('group', 'name')]
        indexes = [
            models.Index(fields=['room_type', 'is_active']),
            models.Index(fields=['name']),
        ]
    
    def __str__(self):
        return self.display_name or self.name
    
    def can_join(self, user: User) -> bool:
        """Check if user can join room."""
        if not self.is_active:
            return False
        
        if not self.require_authentication:
            return True
        
        if not user.is_authenticated:
            return False
        
        if self.owner == user:
            return True
        
        if not self.allowed_users.exists():
            return True  # Public room
        
        return self.allowed_users.filter(id=user.id).exists()
    
    def get_active_connections(self):
        """Get active connections in room."""
        return WebSocketConnection.objects.filter(
            subscribed_rooms__contains=[self.name],
            state='open'
        )
    
    @property
    def connection_count(self):
        """Get number of active connections."""
        return self.get_active_connections().count()


class WebSocketMessage(TenantFilteredModel):
    """
    Stores WebSocket messages for history and offline delivery.
    """
    
    MESSAGE_TYPES = [
        ('text', 'Text Message'),
        ('json', 'JSON Message'),
        ('binary', 'Binary Message'),
        ('system', 'System Message'),
        ('presence', 'Presence Update'),
        ('typing', 'Typing Indicator'),
    ]
    
    DELIVERY_STATUS = [
        ('pending', 'Pending'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('expired', 'Expired'),
    ]
    
    # Message identification
    message_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True
    )
    
    # Source
    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_websocket_messages'
    )
    connection = models.ForeignKey(
        WebSocketConnection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages'
    )
    
    # Destination
    room = models.ForeignKey(
        WebSocketRoom,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='messages'
    )
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='received_websocket_messages',
        help_text=_("For direct messages")
    )
    
    # Message content
    message_type = models.CharField(
        max_length=20,
        choices=MESSAGE_TYPES,
        default='text'
    )
    content = models.TextField(
        help_text=_("Message content (text or JSON)")
    )
    
    # Delivery
    delivery_status = models.CharField(
        max_length=20,
        choices=DELIVERY_STATUS,
        default='pending'
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Message expiration time")
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True
    )
    
    class Meta:
        db_table = 'websocket_messages'
        verbose_name = 'WebSocket Message'
        verbose_name_plural = 'WebSocket Messages'
        indexes = [
            models.Index(fields=['room', 'created_at']),
            models.Index(fields=['recipient', 'delivery_status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['expires_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.sender} - {self.message_type} - {self.created_at}"
    
    def mark_delivered(self):
        """Mark message as delivered."""
        self.delivery_status = 'delivered'
        self.delivered_at = timezone.now()
        self.save(update_fields=['delivery_status', 'delivered_at'])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for WebSocket transmission."""
        return {
            'id': str(self.message_id),
            'type': self.message_type,
            'content': self.content,
            'sender': {
                'id': str(self.sender.id),
                'username': self.sender.username
            } if self.sender else None,
            'room': self.room.name if self.room else None,
            'timestamp': self.created_at.isoformat(),
            'metadata': self.metadata
        }


class WebSocketPresence(TenantFilteredModel):
    """
    Tracks user presence in rooms.
    """
    
    PRESENCE_STATUS = [
        ('online', 'Online'),
        ('away', 'Away'),
        ('busy', 'Busy'),
        ('offline', 'Offline'),
    ]
    
    # User and room
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='websocket_presence'
    )
    room = models.ForeignKey(
        WebSocketRoom,
        on_delete=models.CASCADE,
        related_name='presence_records'
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=PRESENCE_STATUS,
        default='online'
    )
    status_message = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Custom status message")
    )
    
    # Timing
    joined_at = models.DateTimeField(
        auto_now_add=True
    )
    last_activity_at = models.DateTimeField(
        auto_now=True
    )
    
    # Connection tracking
    connection_count = models.IntegerField(
        default=1,
        help_text=_("Number of active connections")
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional presence data")
    )
    
    class Meta:
        db_table = 'websocket_presence'
        verbose_name = 'WebSocket Presence'
        verbose_name_plural = 'WebSocket Presence Records'
        unique_together = [('user', 'room')]
        indexes = [
            models.Index(fields=['room', 'status']),
            models.Index(fields=['last_activity_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} in {self.room.name} ({self.status})"
    
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity_at = timezone.now()
        self.save(update_fields=['last_activity_at'])
    
    def increment_connections(self):
        """Increment connection count."""
        self.connection_count += 1
        self.save(update_fields=['connection_count'])
    
    def decrement_connections(self):
        """Decrement connection count and clean up if needed."""
        self.connection_count = max(0, self.connection_count - 1)
        if self.connection_count == 0:
            self.status = 'offline'
        self.save(update_fields=['connection_count', 'status'])