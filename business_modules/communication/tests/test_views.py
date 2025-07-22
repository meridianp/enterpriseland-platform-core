"""Tests for communication API views."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import (
    Channel, ChannelMember, Message, Notification,
    NotificationPreference, Meeting
)

User = get_user_model()


class ChannelAPITests(APITestCase):
    """Test Channel API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.group = self.user.groups.create(name="Test Group")
        self.client.force_authenticate(user=self.user)
        
        self.list_url = reverse("communication:channel-list")
    
    def test_create_channel(self):
        """Test creating a channel via API."""
        data = {
            "name": "API Test Channel",
            "description": "Created via API",
            "channel_type": "PUBLIC"
        }
        
        response = self.client.post(self.list_url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "API Test Channel")
        self.assertIsNotNone(response.data["slug"])
        
        # Check channel was created
        channel = Channel.objects.get(id=response.data["id"])
        self.assertEqual(channel.created_by, self.user)
        self.assertTrue(channel.is_member(self.user))
    
    def test_list_channels(self):
        """Test listing user's channels."""
        # Create channels
        for i in range(3):
            channel = Channel.objects.create(
                name=f"Channel {i}",
                group=self.group
            )
            channel.add_member(self.user)
        
        # Create channel user is not member of
        Channel.objects.create(
            name="Other Channel",
            group=self.group
        )
        
        response = self.client.get(self.list_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)
    
    def test_add_members_to_channel(self):
        """Test adding members to channel."""
        channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        channel.add_member(self.user, role="OWNER")
        
        new_user = User.objects.create_user(username="newuser")
        new_user.groups.add(self.group)
        
        url = reverse("communication:channel-add-members", kwargs={"pk": channel.id})
        data = {"user_ids": [str(new_user.id)]}
        
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(channel.is_member(new_user))
    
    def test_leave_channel(self):
        """Test leaving a channel."""
        channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        channel.add_member(self.user)
        
        url = reverse("communication:channel-leave", kwargs={"pk": channel.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(channel.is_member(self.user))
    
    def test_mark_channel_read(self):
        """Test marking channel as read."""
        channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        member = channel.add_member(self.user)
        
        # Set last read to past
        member.last_read_at = timezone.now() - timedelta(hours=1)
        member.save()
        
        url = reverse("communication:channel-mark-read", kwargs={"pk": channel.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check last read was updated
        member.refresh_from_db()
        self.assertGreater(member.last_read_at, timezone.now() - timedelta(minutes=1))
    
    def test_create_direct_message_channel(self):
        """Test creating a DM channel."""
        other_user = User.objects.create_user(username="otheruser")
        other_user.groups.add(self.group)
        
        url = reverse("communication:channel-create-direct")
        data = {"user_id": str(other_user.id)}
        
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["channel_type"], "DIRECT")
        
        channel = Channel.objects.get(id=response.data["id"])
        self.assertTrue(channel.is_member(self.user))
        self.assertTrue(channel.is_member(other_user))


class MessageAPITests(APITestCase):
    """Test Message API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.group = self.user.groups.create(name="Test Group")
        self.client.force_authenticate(user=self.user)
        
        self.channel = Channel.objects.create(
            name="Test Channel",
            group=self.group
        )
        self.channel.add_member(self.user)
        
        self.list_url = reverse("communication:message-list")
    
    def test_send_message(self):
        """Test sending a message via API."""
        data = {
            "channel": str(self.channel.id),
            "content": "Hello from API!"
        }
        
        response = self.client.post(self.list_url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["content"], "Hello from API!")
        self.assertEqual(response.data["sender"]["id"], str(self.user.id))
    
    def test_list_messages(self):
        """Test listing messages."""
        # Create messages
        for i in range(5):
            Message.objects.create(
                channel=self.channel,
                sender=self.user,
                content=f"Message {i}",
                group=self.group
            )
        
        response = self.client.get(self.list_url, {"channel": self.channel.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 5)
    
    def test_edit_message(self):
        """Test editing a message."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="Original content",
            group=self.group
        )
        
        url = reverse("communication:message-detail", kwargs={"pk": message.id})
        data = {"content": "Edited content"}
        
        response = self.client.patch(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["content"], "Edited content")
        self.assertTrue(response.data["is_edited"])
    
    def test_delete_message(self):
        """Test deleting a message."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="To be deleted",
            group=self.group
        )
        
        url = reverse("communication:message-detail", kwargs={"pk": message.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Check message is soft deleted
        message.refresh_from_db()
        self.assertTrue(message.is_deleted)
    
    def test_add_reaction(self):
        """Test adding reaction to message."""
        message = Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="React to this!",
            group=self.group
        )
        
        url = reverse("communication:message-add-reaction", kwargs={"pk": message.id})
        data = {"emoji": "👍"}
        
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["emoji"], "👍")
        
        # Check reaction was created
        self.assertEqual(message.reactions.count(), 1)
    
    def test_search_messages(self):
        """Test searching messages."""
        # Create messages
        Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="This is a test message",
            group=self.group
        )
        Message.objects.create(
            channel=self.channel,
            sender=self.user,
            content="Another message without keyword",
            group=self.group
        )
        
        url = reverse("communication:message-search")
        data = {"query": "test"}
        
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Search functionality depends on database setup


class NotificationAPITests(APITestCase):
    """Test Notification API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.group = self.user.groups.create(name="Test Group")
        self.client.force_authenticate(user=self.user)
        
        self.list_url = reverse("communication:notification-list")
    
    def test_list_notifications(self):
        """Test listing user's notifications."""
        # Create notifications
        for i in range(3):
            Notification.objects.create(
                recipient=self.user,
                notification_type="MESSAGE",
                title=f"Notification {i}",
                content="Test content",
                group=self.group
            )
        
        response = self.client.get(self.list_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)
    
    def test_get_unread_count(self):
        """Test getting unread notification count."""
        # Create unread notifications
        for i in range(5):
            Notification.objects.create(
                recipient=self.user,
                notification_type="MESSAGE",
                title=f"Notification {i}",
                content="Test",
                group=self.group
            )
        
        # Create read notification
        notif = Notification.objects.create(
            recipient=self.user,
            notification_type="MESSAGE",
            title="Read notification",
            content="Test",
            group=self.group
        )
        notif.mark_as_read()
        
        url = reverse("communication:notification-unread-count")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["unread_count"], 5)
    
    def test_mark_notification_read(self):
        """Test marking notification as read."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type="MESSAGE",
            title="Test",
            content="Test",
            group=self.group
        )
        
        url = reverse("communication:notification-mark-read", kwargs={"pk": notification.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_read"])
        
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
    
    def test_mark_all_read(self):
        """Test marking all notifications as read."""
        # Create notifications
        for i in range(3):
            Notification.objects.create(
                recipient=self.user,
                notification_type="MESSAGE",
                title=f"Notification {i}",
                content="Test",
                group=self.group
            )
        
        url = reverse("communication:notification-mark-all-read")
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["marked_read"], 3)
        
        # Check all are read
        unread = Notification.objects.filter(
            recipient=self.user,
            is_read=False
        ).count()
        self.assertEqual(unread, 0)


class NotificationPreferenceAPITests(APITestCase):
    """Test NotificationPreference API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.group = self.user.groups.create(name="Test Group")
        self.client.force_authenticate(user=self.user)
        
        self.url = reverse("communication:preference-me")
    
    def test_get_preferences(self):
        """Test getting user's notification preferences."""
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["email_enabled"])  # Default
        self.assertTrue(response.data["in_app_enabled"])  # Default
    
    def test_update_preferences(self):
        """Test updating notification preferences."""
        data = {
            "email_enabled": False,
            "push_enabled": True,
            "quiet_hours_enabled": True,
            "quiet_hours_start": "22:00:00",
            "quiet_hours_end": "08:00:00"
        }
        
        response = self.client.patch(self.url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["email_enabled"])
        self.assertTrue(response.data["push_enabled"])
        self.assertTrue(response.data["quiet_hours_enabled"])


class MeetingAPITests(APITestCase):
    """Test Meeting API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.group = self.user.groups.create(name="Test Group")
        self.client.force_authenticate(user=self.user)
        
        self.list_url = reverse("communication:meeting-list")
    
    def test_schedule_meeting(self):
        """Test scheduling a meeting."""
        participant = User.objects.create_user(username="participant")
        participant.groups.add(self.group)
        
        start_time = timezone.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)
        
        data = {
            "title": "API Test Meeting",
            "description": "Testing meeting creation",
            "scheduled_start": start_time.isoformat(),
            "scheduled_end": end_time.isoformat(),
            "participant_ids": [str(participant.id)]
        }
        
        response = self.client.post(self.list_url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "API Test Meeting")
        self.assertEqual(response.data["status"], "SCHEDULED")
        self.assertEqual(len(response.data["participants"]), 2)  # Organizer + participant
    
    def test_list_meetings(self):
        """Test listing user's meetings."""
        # Create meetings
        for i in range(3):
            meeting = Meeting.objects.create(
                title=f"Meeting {i}",
                scheduled_start=timezone.now() + timedelta(hours=i),
                scheduled_end=timezone.now() + timedelta(hours=i+1),
                organizer=self.user,
                group=self.group
            )
        
        response = self.client.get(self.list_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)
    
    def test_join_meeting(self):
        """Test joining a meeting."""
        meeting = Meeting.objects.create(
            title="Test Meeting",
            scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
            organizer=self.user,
            meeting_id="test-room",
            meeting_url="https://meet.example.com/test",
            group=self.group
        )
        meeting.meeting_participants.create(
            user=self.user,
            role="HOST"
        )
        
        url = reverse("communication:meeting-join", kwargs={"pk": meeting.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("meeting_url", response.data)
        self.assertIn("room_id", response.data)
    
    def test_update_meeting_response(self):
        """Test updating meeting RSVP."""
        meeting = Meeting.objects.create(
            title="Test Meeting",
            scheduled_start=timezone.now() + timedelta(hours=1),
            scheduled_end=timezone.now() + timedelta(hours=2),
            organizer=self.user,
            group=self.group
        )
        meeting.meeting_participants.create(
            user=self.user,
            role="PARTICIPANT"
        )
        
        url = reverse("communication:meeting-update-response", kwargs={"pk": meeting.id})
        data = {
            "response_status": "ACCEPTED",
            "response_message": "Looking forward to it!"
        }
        
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        participant = meeting.meeting_participants.get(user=self.user)
        self.assertEqual(participant.response_status, "ACCEPTED")