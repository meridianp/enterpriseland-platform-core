"""Tests for communication models."""

import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError

from ..models import (
    Channel, ChannelMember, Message, MessageReaction, MessageAttachment,
    Thread, Notification, NotificationPreference, Meeting, VideoCall
)

User = get_user_model()


class ChannelModelTests(TestCase):
    """Test Channel model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.group = self.user.groups.create(name="Test Group")
        
    def test_create_channel(self):
        """Test creating a channel."""
        channel = Channel.objects.create(
            name="Test Channel",
            channel_type="PUBLIC",
            created_by=self.user,
            group=self.group
        )
        
        self.assertEqual(channel.name, "Test Channel")
        self.assertEqual(channel.channel_type, "PUBLIC")
        self.assertIsNotNone(channel.slug)
        self.assertEqual(channel.member_count, 0)
        self.assertEqual(channel.message_count, 0)
    
    def test_add_member(self):
        """Test adding members to channel."""
        channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        
        member = channel.add_member(self.user, role="MEMBER")
        
        self.assertEqual(channel.member_count, 1)
        self.assertTrue(channel.is_member(self.user))
        self.assertEqual(member.role, "MEMBER")
    
    def test_remove_member(self):
        """Test removing members from channel."""
        channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        channel.add_member(self.user)
        
        removed = channel.remove_member(self.user)
        
        self.assertTrue(removed)
        self.assertEqual(channel.member_count, 0)
        self.assertFalse(channel.is_member(self.user))
    
    def test_get_unread_count(self):
        """Test getting unread message count."""
        channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        member = channel.add_member(self.user)
        
        # Create messages after last read
        member.last_read_at = timezone.now() - timedelta(hours=1)
        member.save()
        
        Message.objects.create(
            channel=channel,
            sender=self.user,
            content="Test message",
            group=self.group
        )
        
        self.assertEqual(channel.get_unread_count(self.user), 1)
    
    def test_channel_types(self):
        """Test different channel types."""
        for channel_type, _ in Channel.ChannelType.choices:
            channel = Channel.objects.create(
                name=f"Test {channel_type}",
                channel_type=channel_type,
                group=self.group
            )
            self.assertEqual(channel.channel_type, channel_type)


class MessageModelTests(TestCase):
    """Test Message model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        self.group = self.user.groups.create(name="Test Group")
        self.channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        self.channel.add_member(self.user)
    
    def test_create_message(self):
        """Test creating a message."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="Hello, world!",
            group=self.group
        )
        
        self.assertEqual(message.content, "Hello, world!")
        self.assertEqual(message.message_type, "TEXT")
        self.assertFalse(message.is_edited)
        self.assertFalse(message.is_deleted)
    
    def test_soft_delete(self):
        """Test soft deleting a message."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="Test message",
            group=self.group
        )
        
        message.soft_delete()
        
        self.assertTrue(message.is_deleted)
        self.assertIsNotNone(message.deleted_at)
    
    def test_add_reaction(self):
        """Test adding reactions to message."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="Test message",
            group=self.group
        )
        
        reaction = message.add_reaction(self.user, "👍")
        
        self.assertEqual(reaction.emoji, "👍")
        self.assertEqual(message.reactions.count(), 1)
    
    def test_message_with_mentions(self):
        """Test message with mentions."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="Hello @john and @jane!",
            mentions=["john", "jane"],
            group=self.group
        )
        
        self.assertEqual(len(message.mentions), 2)
        self.assertIn("john", message.mentions)
        self.assertIn("jane", message.mentions)
    
    def test_message_types(self):
        """Test different message types."""
        for msg_type, _ in Message.MessageType.choices:
            message = Message.objects.create(
                channel=self.channel,
                sender=self.user if msg_type != "SYSTEM" else None,
                content=f"Test {msg_type}",
                message_type=msg_type,
                group=self.group
            )
            self.assertEqual(message.message_type, msg_type)


class ThreadModelTests(TestCase):
    """Test Thread model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        self.group = self.user.groups.create(name="Test Group")
        self.channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        self.parent_message = Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="Parent message",
            group=self.group
        )
    
    def test_create_thread(self):
        """Test creating a thread."""
        thread = Thread.objects.create(
            channel=self.channel,
            parent_message=self.parent_message,
            group=self.group
        )
        
        self.assertEqual(thread.reply_count, 0)
        self.assertEqual(thread.participant_count, 0)
    
    def test_add_participant(self):
        """Test adding participants to thread."""
        thread = Thread.objects.create(
            channel=self.channel,
            parent_message=self.parent_message,
            group=self.group
        )
        
        thread.add_participant(self.user)
        
        self.assertEqual(thread.participant_count, 1)
        self.assertTrue(thread.participants.filter(id=self.user.id).exists())


class NotificationModelTests(TestCase):
    """Test Notification model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        self.group = self.user.groups.create(name="Test Group")
    
    def test_create_notification(self):
        """Test creating a notification."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type="MESSAGE",
            title="New Message",
            content="You have a new message",
            group=self.group
        )
        
        self.assertEqual(notification.notification_type, "MESSAGE")
        self.assertFalse(notification.is_read)
        self.assertEqual(notification.priority, "MEDIUM")
    
    def test_mark_as_read(self):
        """Test marking notification as read."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type="MESSAGE",
            title="Test",
            content="Test",
            group=self.group
        )
        
        notification.mark_as_read()
        
        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)
    
    def test_is_expired(self):
        """Test notification expiration."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type="MESSAGE",
            title="Test",
            content="Test",
            expires_at=timezone.now() - timedelta(hours=1),
            group=self.group
        )
        
        self.assertTrue(notification.is_expired())
    
    def test_notification_priorities(self):
        """Test notification priorities."""
        for priority, _ in Notification.NotificationPriority.choices:
            notification = Notification.objects.create(
                recipient=self.user,
                notification_type="MESSAGE",
                title="Test",
                content="Test",
                priority=priority,
                group=self.group
            )
            self.assertEqual(notification.priority, priority)


class MeetingModelTests(TestCase):
    """Test Meeting model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        self.group = self.user.groups.create(name="Test Group")
    
    def test_create_meeting(self):
        """Test creating a meeting."""
        start_time = timezone.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)
        
        meeting = Meeting.objects.create(
            title="Test Meeting",
            scheduled_start=start_time,
            scheduled_end=end_time,
            organizer=self.user,
            group=self.group
        )
        
        self.assertEqual(meeting.status, "SCHEDULED")
        self.assertFalse(meeting.is_recurring)
        self.assertTrue(meeting.enable_waiting_room)
    
    def test_start_meeting(self):
        """Test starting a meeting."""
        meeting = Meeting.objects.create(
            title="Test Meeting",
            scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
            organizer=self.user,
            group=self.group
        )
        
        meeting.start_meeting()
        
        self.assertEqual(meeting.status, "IN_PROGRESS")
        self.assertIsNotNone(meeting.actual_start)
    
    def test_end_meeting(self):
        """Test ending a meeting."""
        meeting = Meeting.objects.create(
            title="Test Meeting",
            scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
            organizer=self.user,
            group=self.group
        )
        
        meeting.start_meeting()
        meeting.end_meeting()
        
        self.assertEqual(meeting.status, "COMPLETED")
        self.assertIsNotNone(meeting.actual_end)


class VideoCallModelTests(TestCase):
    """Test VideoCall model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        self.group = self.user.groups.create(name="Test Group")
    
    def test_create_video_call(self):
        """Test creating a video call."""
        call = VideoCall.objects.create(
            call_type="VIDEO",
            initiator=self.user,
            room_id="test-room-123",
            group=self.group
        )
        
        self.assertEqual(call.status, "INITIATING")
        self.assertEqual(call.call_type, "VIDEO")
        self.assertEqual(call.max_participants, 10)
    
    def test_start_call(self):
        """Test starting a call."""
        call = VideoCall.objects.create(
            call_type="VIDEO",
            initiator=self.user,
            room_id="test-room-123",
            group=self.group
        )
        
        call.start_call()
        
        self.assertEqual(call.status, "IN_PROGRESS")
        self.assertIsNotNone(call.started_at)
    
    def test_end_call(self):
        """Test ending a call."""
        call = VideoCall.objects.create(
            call_type="VIDEO",
            initiator=self.user,
            room_id="test-room-123",
            group=self.group
        )
        
        call.start_call()
        call.end_call()
        
        self.assertEqual(call.status, "COMPLETED")
        self.assertIsNotNone(call.ended_at)
        self.assertIsNotNone(call.duration)