"""Tests for communication services."""

import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.core.exceptions import ValidationError

from ..models import (
    Channel, ChannelMember, Message, Thread,
    Notification, NotificationPreference, Meeting
)
from ..services import (
    MessageService, ChannelService, NotificationService, MeetingService
)

User = get_user_model()


class MessageServiceTests(TestCase):
    """Test MessageService."""
    
    def setUp(self):
        """Set up test data."""
        self.service = MessageService()
        
        self.user1 = User.objects.create_user(
            username="user1",
            email="user1@example.com"
        )
        self.user2 = User.objects.create_user(
            username="user2",
            email="user2@example.com"
        )
        
        self.group = self.user1.groups.create(name="Test Group")
        self.user2.groups.add(self.group)
        
        self.channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        self.channel.add_member(self.user1)
        self.channel.add_member(self.user2)
    
    @patch('communication.services.RealtimeService')
    @patch('communication.services.MessageSearchService')
    def test_send_message(self, mock_search, mock_realtime):
        """Test sending a message."""
        message = self.service.send_message(
            channel=self.channel,
            sender=self.user1,
            content="Hello, world!"
        )
        
        self.assertEqual(message.content, "Hello, world!")
        self.assertEqual(message.sender, self.user1)
        self.assertEqual(message.channel, self.channel)
        
        # Check that real-time update was sent
        mock_realtime.return_value.broadcast_to_channel.assert_called()
    
    def test_send_message_non_member(self):
        """Test sending message as non-member fails."""
        user3 = User.objects.create_user(username="user3")
        
        with self.assertRaises(ValidationError):
            self.service.send_message(
                channel=self.channel,
                sender=user3,
                content="Hello"
            )
    
    @patch('communication.services.RealtimeService')
    def test_send_message_with_mentions(self, mock_realtime):
        """Test sending message with mentions."""
        message = self.service.send_message(
            channel=self.channel,
            sender=self.user1,
            content="Hello @user2, how are you?"
        )
        
        self.assertIn("user2", message.mentions)
        
        # Check notification was created
        notification = Notification.objects.filter(
            recipient=self.user2,
            notification_type="MENTION"
        ).first()
        self.assertIsNotNone(notification)
    
    @patch('communication.services.RealtimeService')
    def test_edit_message(self, mock_realtime):
        """Test editing a message."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user1,
            content="Original content",
            group=self.group
        )
        
        edited = self.service.edit_message(
            message=message,
            user=self.user1,
            new_content="Edited content"
        )
        
        self.assertEqual(edited.content, "Edited content")
        self.assertTrue(edited.is_edited)
        self.assertIsNotNone(edited.edited_at)
    
    def test_edit_message_no_permission(self):
        """Test editing message without permission fails."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user1,
            content="Test",
            group=self.group
        )
        
        with self.assertRaises(ValidationError):
            self.service.edit_message(
                message=message,
                user=self.user2,
                new_content="Hacked!"
            )
    
    @patch('communication.services.MessageSearchService')
    def test_search_messages(self, mock_search):
        """Test searching messages."""
        mock_search.return_value.search.return_value = []
        
        results = self.service.search_messages(
            query="test",
            user=self.user1,
            channel=self.channel
        )
        
        mock_search.return_value.search.assert_called_once()


class ChannelServiceTests(TestCase):
    """Test ChannelService."""
    
    def setUp(self):
        """Set up test data."""
        self.service = ChannelService()
        
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        self.group = self.user.groups.create(name="Test Group")
    
    @patch('communication.services.RealtimeService')
    def test_create_channel(self, mock_realtime):
        """Test creating a channel."""
        channel = self.service.create_channel(
            name="New Channel",
            channel_type="PUBLIC",
            creator=self.user,
            group=self.group,
            description="Test channel"
        )
        
        self.assertEqual(channel.name, "New Channel")
        self.assertEqual(channel.channel_type, "PUBLIC")
        self.assertIsNotNone(channel.slug)
        
        # Check creator is added as owner
        member = channel.members.get(user=self.user)
        self.assertEqual(member.role, "OWNER")
    
    def test_create_direct_message_channel(self):
        """Test creating a direct message channel."""
        user2 = User.objects.create_user(username="user2")
        user2.groups.add(self.group)
        
        channel = self.service.create_direct_message_channel(
            user1=self.user,
            user2=user2,
            group=self.group
        )
        
        self.assertEqual(channel.channel_type, "DIRECT")
        self.assertEqual(channel.members.count(), 2)
    
    def test_create_direct_message_channel_existing(self):
        """Test getting existing direct message channel."""
        user2 = User.objects.create_user(username="user2")
        user2.groups.add(self.group)
        
        # Create first time
        channel1 = self.service.create_direct_message_channel(
            user1=self.user,
            user2=user2,
            group=self.group
        )
        
        # Try to create again
        channel2 = self.service.create_direct_message_channel(
            user1=self.user,
            user2=user2,
            group=self.group
        )
        
        self.assertEqual(channel1.id, channel2.id)
    
    @patch('communication.services.RealtimeService')
    def test_add_members(self, mock_realtime):
        """Test adding members to channel."""
        channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        channel.add_member(self.user, role="OWNER")
        
        new_users = [
            User.objects.create_user(username="user2"),
            User.objects.create_user(username="user3"),
        ]
        for u in new_users:
            u.groups.add(self.group)
        
        members = self.service.add_members(
            channel=channel,
            users=new_users,
            added_by=self.user
        )
        
        self.assertEqual(len(members), 2)
        self.assertEqual(channel.members.count(), 3)  # Including owner
        
        # Check notifications created
        notifications = Notification.objects.filter(
            notification_type="CHANNEL_INVITE"
        )
        self.assertEqual(notifications.count(), 2)
    
    def test_archive_channel(self):
        """Test archiving a channel."""
        channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        channel.add_member(self.user, role="OWNER")
        
        archived = self.service.archive_channel(
            channel=channel,
            archived_by=self.user
        )
        
        self.assertTrue(archived.is_archived)
    
    def test_get_user_channels(self):
        """Test getting user's channels."""
        # Create channels
        for i in range(3):
            channel = Channel.objects.create(
                name=f"Channel {i}",
                group=self.group
            )
            channel.add_member(self.user)
        
        # Create archived channel
        archived = Channel.objects.create(
            name="Archived Channel",
            is_archived=True,
            group=self.group
        )
        archived.add_member(self.user)
        
        # Get active channels
        channels = self.service.get_user_channels(
            user=self.user,
            group=self.group,
            include_archived=False
        )
        self.assertEqual(channels.count(), 3)
        
        # Get all channels
        all_channels = self.service.get_user_channels(
            user=self.user,
            group=self.group,
            include_archived=True
        )
        self.assertEqual(all_channels.count(), 4)


class NotificationServiceTests(TestCase):
    """Test NotificationService."""
    
    def setUp(self):
        """Set up test data."""
        self.service = NotificationService()
        
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        self.group = self.user.groups.create(name="Test Group")
        
        # Create preferences
        self.preferences = NotificationPreference.objects.create(
            user=self.user,
            group=self.group
        )
    
    @patch('communication.notifications.NotificationDispatcher')
    def test_send_notification(self, mock_dispatcher):
        """Test sending a notification."""
        notification = self.service.send_notification(
            recipient=self.user,
            notification_type="MESSAGE",
            title="Test Notification",
            content="This is a test"
        )
        
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.notification_type, "MESSAGE")
        self.assertIn("in_app", notification.channels)
        
        # Check dispatcher was called
        mock_dispatcher.return_value.dispatch.assert_called_once()
    
    def test_send_scheduled_notification(self):
        """Test scheduling a notification."""
        future_time = timezone.now() + timedelta(hours=1)
        
        notification = self.service.send_notification(
            recipient=self.user,
            notification_type="MESSAGE",
            title="Scheduled",
            content="Future notification",
            schedule_for=future_time
        )
        
        self.assertEqual(notification.scheduled_for, future_time)
        self.assertFalse(notification.is_read)
    
    def test_send_bulk_notification(self):
        """Test sending bulk notifications."""
        users = [
            User.objects.create_user(username=f"user{i}")
            for i in range(3)
        ]
        for u in users:
            u.groups.add(self.group)
        
        notifications = self.service.send_bulk_notification(
            recipients=users,
            notification_type="SYSTEM",
            title="Bulk Test",
            content="Bulk notification"
        )
        
        self.assertEqual(len(notifications), 3)
    
    def test_mark_notifications_read(self):
        """Test marking notifications as read."""
        # Create notifications
        for i in range(3):
            Notification.objects.create(
                recipient=self.user,
                notification_type="MESSAGE",
                title=f"Test {i}",
                content="Test",
                group=self.group
            )
        
        count = self.service.mark_notifications_read(self.user)
        
        self.assertEqual(count, 3)
        
        # Check all are marked read
        unread = Notification.objects.filter(
            recipient=self.user,
            is_read=False
        ).count()
        self.assertEqual(unread, 0)
    
    def test_get_unread_count(self):
        """Test getting unread count."""
        # Create notifications
        for i in range(5):
            Notification.objects.create(
                recipient=self.user,
                notification_type="MESSAGE",
                title=f"Test {i}",
                content="Test",
                group=self.group
            )
        
        count = self.service.get_unread_count(self.user)
        self.assertEqual(count, 5)


class MeetingServiceTests(TestCase):
    """Test MeetingService."""
    
    def setUp(self):
        """Set up test data."""
        self.service = MeetingService()
        
        self.organizer = User.objects.create_user(
            username="organizer",
            email="organizer@example.com"
        )
        self.participant = User.objects.create_user(
            username="participant",
            email="participant@example.com"
        )
        
        self.group = self.organizer.groups.create(name="Test Group")
        self.participant.groups.add(self.group)
    
    @patch('communication.services.VideoProvider')
    @patch('communication.services.NotificationService')
    def test_schedule_meeting(self, mock_notif, mock_video):
        """Test scheduling a meeting."""
        mock_video.return_value.create_room.return_value = {
            "url": "https://meet.example.com/test",
            "room_id": "test-room",
            "passcode": "123456"
        }
        
        start_time = timezone.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)
        
        meeting = self.service.schedule_meeting(
            title="Test Meeting",
            organizer=self.organizer,
            participants=[self.participant],
            scheduled_start=start_time,
            scheduled_end=end_time
        )
        
        self.assertEqual(meeting.title, "Test Meeting")
        self.assertEqual(meeting.status, "SCHEDULED")
        self.assertEqual(meeting.meeting_participants.count(), 2)  # Organizer + participant
        
        # Check room was created
        mock_video.return_value.create_room.assert_called_once()
    
    @patch('communication.services.VideoProvider')
    def test_start_instant_meeting(self, mock_video):
        """Test starting an instant meeting."""
        mock_video.return_value.create_room.return_value = {
            "url": "https://meet.example.com/instant",
            "room_id": "instant-room"
        }
        
        meeting, call = self.service.start_instant_meeting(
            organizer=self.organizer,
            participants=[self.participant],
            call_type="VIDEO"
        )
        
        self.assertEqual(meeting.status, "IN_PROGRESS")
        self.assertEqual(call.status, "IN_PROGRESS")
        self.assertEqual(call.call_type, "VIDEO")
    
    @patch('communication.services.VideoProvider')
    def test_join_meeting(self, mock_video):
        """Test joining a meeting."""
        mock_video.return_value.generate_access_token.return_value = "test-token"
        
        meeting = Meeting.objects.create(
            title="Test Meeting",
            scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
            organizer=self.organizer,
            meeting_id="test-room",
            meeting_url="https://meet.example.com/test",
            group=self.group
        )
        meeting.meeting_participants.create(
            user=self.participant,
            role="PARTICIPANT"
        )
        
        join_data = self.service.join_meeting(meeting, self.participant)
        
        self.assertEqual(join_data["room_id"], "test-room")
        self.assertEqual(join_data["access_token"], "test-token")
        
        # Check participant joined
        participant = meeting.meeting_participants.get(user=self.participant)
        self.assertIsNotNone(participant.joined_at)
    
    def test_end_meeting(self):
        """Test ending a meeting."""
        meeting = Meeting.objects.create(
            title="Test Meeting",
            scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
            organizer=self.organizer,
            group=self.group
        )
        meeting.start_meeting()
        
        ended = self.service.end_meeting(meeting, self.organizer)
        
        self.assertEqual(ended.status, "COMPLETED")
        self.assertIsNotNone(ended.actual_end)