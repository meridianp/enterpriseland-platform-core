"""
WebSocket Signals

Django signals for WebSocket events.
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver, Signal
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import WebSocketConnection, WebSocketMessage, WebSocketPresence

# Custom signals
websocket_connected = Signal()  # Sent when WebSocket connects
websocket_disconnected = Signal()  # Sent when WebSocket disconnects
websocket_message_sent = Signal()  # Sent when message is sent
websocket_room_joined = Signal()  # Sent when user joins room
websocket_room_left = Signal()  # Sent when user leaves room
websocket_presence_updated = Signal()  # Sent when presence is updated


@receiver(post_save, sender=WebSocketConnection)
def handle_connection_change(sender, instance, created, **kwargs):
    """Handle connection creation or update."""
    if created:
        websocket_connected.send(
            sender=WebSocketConnection,
            connection=instance,
            user=instance.user
        )
    elif instance.state == 'closed' and 'state' in kwargs.get('update_fields', []):
        websocket_disconnected.send(
            sender=WebSocketConnection,
            connection=instance,
            user=instance.user
        )


@receiver(post_save, sender=WebSocketMessage)
def handle_message_sent(sender, instance, created, **kwargs):
    """Handle message creation."""
    if created:
        websocket_message_sent.send(
            sender=WebSocketMessage,
            message=instance,
            user=instance.sender,
            room=instance.room
        )


@receiver(post_save, sender=WebSocketPresence)
def handle_presence_update(sender, instance, created, **kwargs):
    """Handle presence update."""
    websocket_presence_updated.send(
        sender=WebSocketPresence,
        presence=instance,
        user=instance.user,
        room=instance.room,
        created=created
    )
    
    # Broadcast presence update to room
    if instance.room.enable_presence:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            instance.room.name,
            {
                'type': 'presence.update',
                'user': {
                    'id': str(instance.user.id),
                    'username': instance.user.username
                },
                'status': instance.status,
                'status_message': instance.status_message
            }
        )