"""
Tests for WebSocket Models
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from platform_core.websocket.models import (
    WebSocketConnection,
    WebSocketRoom,
    WebSocketMessage,
    WebSocketPresence
)

User = get_user_model()


class WebSocketConnectionTestCase(TestCase):
    """Test WebSocketConnection model."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.connection = WebSocketConnection.objects.create(
            user=self.user,
            channel_name='test-channel-123',
            ip_address='127.0.0.1',
            user_agent='TestAgent/1.0',
            state='open'
        )
    
    def test_connection_creation(self):
        """Test connection is created correctly."""
        self.assertIsNotNone(self.connection.connection_id)
        self.assertEqual(self.connection.state, 'open')
        self.assertEqual(self.connection.user, self.user)
        self.assertEqual(self.connection.ip_address, '127.0.0.1')
    
    def test_close_connection(self):
        """Test closing connection."""
        self.connection.close()
        
        self.assertEqual(self.connection.state, 'closed')
        self.assertIsNotNone(self.connection.disconnected_at)
    
    def test_add_remove_room(self):
        """Test room subscription management."""
        self.connection.add_room('general')
        self.connection.add_room('notifications')
        
        self.assertIn('general', self.connection.subscribed_rooms)
        self.assertIn('notifications', self.connection.subscribed_rooms)
        
        self.connection.remove_room('general')
        self.assertNotIn('general', self.connection.subscribed_rooms)
        self.assertIn('notifications', self.connection.subscribed_rooms)
    
    def test_duration_property(self):
        """Test connection duration calculation."""
        # Open connection
        duration = self.connection.duration
        self.assertIsNotNone(duration)
        
        # Closed connection
        self.connection.disconnected_at = self.connection.connected_at + timedelta(minutes=5)
        duration = self.connection.duration
        self.assertEqual(duration.total_seconds(), 300)  # 5 minutes


class WebSocketRoomTestCase(TestCase):
    """Test WebSocketRoom model."""
    
    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='ownerpass'
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        self.public_room = WebSocketRoom.objects.create(
            name='general',
            display_name='General Chat',
            room_type='public',
            owner=self.owner,
            require_authentication=True
        )
        
        self.private_room = WebSocketRoom.objects.create(
            name='private-room',
            room_type='private',
            owner=self.owner,
            require_authentication=True
        )
    
    def test_room_creation(self):
        """Test room is created correctly."""
        self.assertEqual(self.public_room.name, 'general')
        self.assertEqual(self.public_room.display_name, 'General Chat')
        self.assertTrue(self.public_room.is_active)
        self.assertTrue(self.public_room.enable_presence)
        self.assertTrue(self.public_room.enable_history)
    
    def test_can_join_public_room(self):
        """Test joining public room."""
        # Authenticated user can join public room
        self.assertTrue(self.public_room.can_join(self.user))
        
        # Owner can always join
        self.assertTrue(self.public_room.can_join(self.owner))
    
    def test_can_join_private_room(self):
        """Test joining private room."""
        # User cannot join private room by default
        self.assertFalse(self.private_room.can_join(self.user))
        
        # Add user to allowed list
        self.private_room.allowed_users.add(self.user)
        self.assertTrue(self.private_room.can_join(self.user))
        
        # Owner can always join
        self.assertTrue(self.private_room.can_join(self.owner))
    
    def test_inactive_room(self):
        """Test inactive room access."""
        self.public_room.is_active = False
        self.public_room.save()
        
        # No one can join inactive room
        self.assertFalse(self.public_room.can_join(self.user))
        self.assertFalse(self.public_room.can_join(self.owner))
    
    def test_connection_count(self):
        """Test connection count property."""
        # Create connections
        WebSocketConnection.objects.create(
            user=self.user,
            channel_name='channel-1',
            state='open',
            subscribed_rooms=['general']
        )
        WebSocketConnection.objects.create(
            user=self.owner,
            channel_name='channel-2',
            state='open',
            subscribed_rooms=['general', 'other']
        )
        WebSocketConnection.objects.create(
            user=self.user,
            channel_name='channel-3',
            state='closed',  # Closed connection
            subscribed_rooms=['general']
        )
        
        # Should only count open connections
        self.assertEqual(self.public_room.connection_count, 2)


class WebSocketMessageTestCase(TestCase):
    """Test WebSocketMessage model."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        
        self.room = WebSocketRoom.objects.create(
            name='test-room',
            room_type='public'
        )
        
        self.message = WebSocketMessage.objects.create(
            sender=self.user,
            room=self.room,
            message_type='text',
            content='Hello, world!'
        )
    
    def test_message_creation(self):
        """Test message is created correctly."""
        self.assertIsNotNone(self.message.message_id)
        self.assertEqual(self.message.sender, self.user)
        self.assertEqual(self.message.room, self.room)
        self.assertEqual(self.message.content, 'Hello, world!')
        self.assertEqual(self.message.delivery_status, 'pending')
    
    def test_mark_delivered(self):
        """Test marking message as delivered."""
        self.message.mark_delivered()
        
        self.assertEqual(self.message.delivery_status, 'delivered')
        self.assertIsNotNone(self.message.delivered_at)
    
    def test_to_dict(self):
        """Test message serialization."""
        data = self.message.to_dict()
        
        self.assertEqual(data['type'], 'text')
        self.assertEqual(data['content'], 'Hello, world!')
        self.assertEqual(data['sender']['username'], 'testuser')
        self.assertEqual(data['room'], 'test-room')
        self.assertIn('timestamp', data)


class WebSocketPresenceTestCase(TestCase):
    """Test WebSocketPresence model."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        
        self.room = WebSocketRoom.objects.create(
            name='presence-room',
            enable_presence=True
        )
        
        self.presence = WebSocketPresence.objects.create(
            user=self.user,
            room=self.room,
            status='online'
        )
    
    def test_presence_creation(self):
        """Test presence is created correctly."""
        self.assertEqual(self.presence.user, self.user)
        self.assertEqual(self.presence.room, self.room)
        self.assertEqual(self.presence.status, 'online')
        self.assertEqual(self.presence.connection_count, 1)
    
    def test_update_activity(self):
        """Test activity update."""
        old_activity = self.presence.last_activity_at
        
        # Wait a bit
        import time
        time.sleep(0.1)
        
        self.presence.update_activity()
        self.assertGreater(self.presence.last_activity_at, old_activity)
    
    def test_connection_count_management(self):
        """Test connection count increment/decrement."""
        # Increment
        self.presence.increment_connections()
        self.assertEqual(self.presence.connection_count, 2)
        
        # Decrement
        self.presence.decrement_connections()
        self.assertEqual(self.presence.connection_count, 1)
        
        # Decrement to zero sets offline
        self.presence.decrement_connections()
        self.assertEqual(self.presence.connection_count, 0)
        self.assertEqual(self.presence.status, 'offline')
    
    def test_unique_constraint(self):
        """Test unique constraint on user/room."""
        with self.assertRaises(Exception):
            WebSocketPresence.objects.create(
                user=self.user,
                room=self.room,
                status='online'
            )