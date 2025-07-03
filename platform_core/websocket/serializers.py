"""
WebSocket Serializers
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import (
    WebSocketConnection,
    WebSocketRoom,
    WebSocketMessage,
    WebSocketPresence
)

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user info in WebSocket context."""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = fields


class WebSocketConnectionSerializer(serializers.ModelSerializer):
    """Serializer for WebSocket connections."""
    
    user = UserSerializer(read_only=True)
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = WebSocketConnection
        fields = [
            'id',
            'connection_id',
            'user',
            'state',
            'ip_address',
            'user_agent',
            'protocol',
            'path',
            'connected_at',
            'last_seen_at',
            'disconnected_at',
            'duration',
            'subscribed_rooms',
            'subscribed_channels',
            'metadata'
        ]
        read_only_fields = fields
    
    def get_duration(self, obj):
        """Get connection duration in seconds."""
        duration = obj.duration
        return duration.total_seconds() if duration else None


class WebSocketRoomSerializer(serializers.ModelSerializer):
    """Serializer for WebSocket rooms."""
    
    owner = UserSerializer(read_only=True)
    connection_count = serializers.SerializerMethodField()
    can_join = serializers.SerializerMethodField()
    
    class Meta:
        model = WebSocketRoom
        fields = [
            'id',
            'name',
            'display_name',
            'room_type',
            'description',
            'is_active',
            'is_persistent',
            'owner',
            'require_authentication',
            'max_connections',
            'connection_count',
            'can_join',
            'enable_presence',
            'enable_history',
            'enable_typing',
            'metadata',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'connection_count', 'can_join', 'created_at', 'updated_at']
    
    def get_connection_count(self, obj):
        """Get current connection count."""
        return obj.connection_count
    
    def get_can_join(self, obj):
        """Check if current user can join."""
        request = self.context.get('request')
        if request and request.user:
            return obj.can_join(request.user)
        return False


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for WebSocket messages."""
    
    sender = UserSerializer(read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    
    class Meta:
        model = WebSocketMessage
        fields = [
            'id',
            'message_id',
            'sender',
            'room',
            'room_name',
            'recipient',
            'message_type',
            'content',
            'delivery_status',
            'delivered_at',
            'created_at',
            'metadata'
        ]
        read_only_fields = [
            'id',
            'message_id',
            'sender',
            'room_name',
            'delivery_status',
            'delivered_at',
            'created_at'
        ]
    
    def validate_content(self, value):
        """Validate message content."""
        if not value or not value.strip():
            raise serializers.ValidationError("Message content cannot be empty")
        
        # Check message size
        max_size = 65536  # 64KB
        if len(value) > max_size:
            raise serializers.ValidationError(f"Message too large (max {max_size} bytes)")
        
        return value


class WebSocketPresenceSerializer(serializers.ModelSerializer):
    """Serializer for WebSocket presence."""
    
    user = UserSerializer(read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    
    class Meta:
        model = WebSocketPresence
        fields = [
            'id',
            'user',
            'room',
            'room_name',
            'status',
            'status_message',
            'joined_at',
            'last_activity_at',
            'connection_count',
            'metadata'
        ]
        read_only_fields = [
            'id',
            'user',
            'room_name',
            'joined_at',
            'last_activity_at',
            'connection_count'
        ]


class SendMessageSerializer(serializers.Serializer):
    """Serializer for sending messages via API."""
    
    room = serializers.CharField(max_length=100)
    content = serializers.CharField()
    message_type = serializers.ChoiceField(
        choices=['text', 'json', 'system'],
        default='text'
    )
    metadata = serializers.JSONField(required=False, default=dict)
    
    def validate_room(self, value):
        """Validate room exists and user can send."""
        try:
            room = WebSocketRoom.objects.get(name=value, is_active=True)
            request = self.context.get('request')
            if request and not room.can_join(request.user):
                raise serializers.ValidationError("You don't have access to this room")
        except WebSocketRoom.DoesNotExist:
            raise serializers.ValidationError("Room not found")
        
        return value


class BroadcastMessageSerializer(serializers.Serializer):
    """Serializer for broadcasting messages."""
    
    rooms = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=[]
    )
    users = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=[]
    )
    content = serializers.CharField()
    message_type = serializers.ChoiceField(
        choices=['notification', 'alert', 'system'],
        default='notification'
    )
    priority = serializers.ChoiceField(
        choices=['low', 'normal', 'high', 'urgent'],
        default='normal'
    )
    metadata = serializers.JSONField(required=False, default=dict)
    
    def validate(self, attrs):
        """Validate broadcast targets."""
        if not attrs.get('rooms') and not attrs.get('users'):
            raise serializers.ValidationError(
                "At least one room or user must be specified"
            )
        return attrs