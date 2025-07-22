"""Communication module services."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin

from asgiref.sync import async_to_sync, sync_to_async
from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, F, Count, Avg
from django.template.loader import render_to_string
from django.utils import timezone

from platform_core.services import BaseService
from .models import (
    Channel, ChannelMember, Message, Thread, Notification,
    NotificationPreference, NotificationTemplate, Meeting,
    VideoCall, MessageAttachment
)
from .notifications import NotificationDispatcher
from .realtime import RealtimeService
from .search import MessageSearchService

User = get_user_model()
logger = logging.getLogger(__name__)


class MessageService(BaseService):
    """Service for managing messages."""
    
    def __init__(self):
        """Initialize the message service."""
        super().__init__()
        self.realtime_service = RealtimeService()
        self.search_service = MessageSearchService()
    
    @transaction.atomic
    def send_message(
        self,
        channel: Channel,
        sender: User,
        content: str,
        message_type: str = "TEXT",
        thread: Optional[Thread] = None,
        reply_to: Optional[Message] = None,
        attachments: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None
    ) -> Message:
        """Send a message to a channel."""
        # Validate sender is member of channel
        if not channel.is_member(sender):
            raise ValidationError("User is not a member of this channel")
        
        # Create message
        message = Message.objects.create(
            channel=channel,
            sender=sender,
            content=content,
            message_type=message_type,
            thread=thread,
            reply_to=reply_to,
            metadata=metadata or {},
            group=channel.group
        )
        
        # Process mentions
        mentions = self._extract_mentions(content)
        if mentions:
            message.mentions = mentions
            message.save(update_fields=["mentions"])
        
        # Handle attachments
        if attachments:
            for attachment_data in attachments:
                MessageAttachment.objects.create(
                    message=message,
                    group=channel.group,
                    **attachment_data
                )
        
        # Update thread if this is a reply
        if thread:
            thread.reply_count = F("reply_count") + 1
            thread.last_reply_at = timezone.now()
            thread.save(update_fields=["reply_count", "last_reply_at"])
            thread.add_participant(sender)
        
        # Send real-time notification
        self._send_realtime_update(message)
        
        # Create notifications for mentions
        if mentions:
            self._create_mention_notifications(message, mentions)
        
        # Update search index
        self.search_service.index_message(message)
        
        return message
    
    def edit_message(
        self,
        message: Message,
        user: User,
        new_content: str
    ) -> Message:
        """Edit an existing message."""
        # Validate permissions
        if message.sender != user and not user.has_perm("communication.change_message"):
            raise ValidationError("You don't have permission to edit this message")
        
        # Update message
        message.content = new_content
        message.is_edited = True
        message.edited_at = timezone.now()
        message.save()
        
        # Update mentions
        new_mentions = self._extract_mentions(new_content)
        if new_mentions != message.mentions:
            message.mentions = new_mentions
            message.save(update_fields=["mentions"])
            self._create_mention_notifications(message, new_mentions)
        
        # Send real-time update
        self._send_realtime_update(message, action="edit")
        
        # Update search index
        self.search_service.index_message(message)
        
        return message
    
    def delete_message(
        self,
        message: Message,
        user: User,
        hard_delete: bool = False
    ) -> bool:
        """Delete a message."""
        # Validate permissions
        if message.sender != user and not user.has_perm("communication.delete_message"):
            raise ValidationError("You don't have permission to delete this message")
        
        if hard_delete and user.has_perm("communication.hard_delete_message"):
            message.delete()
        else:
            message.soft_delete()
        
        # Send real-time update
        self._send_realtime_update(message, action="delete")
        
        # Remove from search index
        self.search_service.remove_message(message)
        
        return True
    
    def search_messages(
        self,
        query: str,
        user: User,
        channel: Optional[Channel] = None,
        sender: Optional[User] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50
    ) -> List[Message]:
        """Search messages."""
        return self.search_service.search(
            query=query,
            user=user,
            channel=channel,
            sender=sender,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )
    
    def _extract_mentions(self, content: str) -> List[str]:
        """Extract @mentions from message content."""
        import re
        pattern = r'@([a-zA-Z0-9_.-]+)'
        return list(set(re.findall(pattern, content)))
    
    def _send_realtime_update(self, message: Message, action: str = "create"):
        """Send real-time update for message."""
        data = {
            "action": action,
            "message": {
                "id": str(message.id),
                "channel_id": str(message.channel_id),
                "sender_id": str(message.sender_id) if message.sender else None,
                "content": message.get_content(),
                "created_at": message.created_at.isoformat(),
                "is_edited": message.is_edited,
                "is_deleted": message.is_deleted,
            }
        }
        
        # Send to channel members
        async_to_sync(self.realtime_service.broadcast_to_channel)(
            message.channel,
            "message",
            data
        )
    
    def _create_mention_notifications(self, message: Message, mentions: List[str]):
        """Create notifications for mentioned users."""
        mentioned_users = User.objects.filter(
            username__in=mentions,
            groups=message.channel.group
        )
        
        for user in mentioned_users:
            if user != message.sender:
                Notification.objects.create(
                    recipient=user,
                    notification_type="MENTION",
                    title=f"You were mentioned by {message.sender.get_full_name()}",
                    content=f"In #{message.channel.name}: {message.content[:100]}...",
                    related_object_type="message",
                    related_object_id=str(message.id),
                    action_url=f"/messages/{message.channel.id}?message={message.id}",
                    group=message.channel.group
                )


class ChannelService(BaseService):
    """Service for managing channels."""
    
    def __init__(self):
        """Initialize the channel service."""
        super().__init__()
        self.realtime_service = RealtimeService()
    
    @transaction.atomic
    def create_channel(
        self,
        name: str,
        channel_type: str,
        creator: User,
        group,
        description: str = "",
        members: Optional[List[User]] = None,
        settings: Optional[Dict] = None
    ) -> Channel:
        """Create a new channel."""
        # Generate slug
        from django.utils.text import slugify
        base_slug = slugify(name)
        slug = base_slug
        counter = 1
        while Channel.objects.filter(group=group, slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        # Create channel
        channel = Channel.objects.create(
            name=name,
            slug=slug,
            description=description,
            channel_type=channel_type,
            created_by=creator,
            group=group
        )
        
        # Apply settings
        if settings:
            for key, value in settings.items():
                if hasattr(channel, key):
                    setattr(channel, key, value)
            channel.save()
        
        # Add creator as owner
        channel.add_member(creator, role="OWNER")
        
        # Add additional members
        if members:
            for member in members:
                channel.add_member(member)
        
        # Send notification
        self._send_channel_created_notification(channel, creator)
        
        return channel
    
    def create_direct_message_channel(
        self,
        user1: User,
        user2: User,
        group
    ) -> Channel:
        """Create or get a direct message channel between two users."""
        # Check if channel already exists
        existing = Channel.objects.filter(
            channel_type="DIRECT",
            group=group
        ).filter(
            members__user=user1
        ).filter(
            members__user=user2
        ).first()
        
        if existing:
            return existing
        
        # Create new DM channel
        channel = self.create_channel(
            name=f"DM: {user1.get_full_name()} & {user2.get_full_name()}",
            channel_type="DIRECT",
            creator=user1,
            group=group,
            members=[user2]
        )
        
        return channel
    
    def add_members(
        self,
        channel: Channel,
        users: List[User],
        added_by: User,
        role: str = "MEMBER"
    ) -> List[ChannelMember]:
        """Add multiple members to a channel."""
        # Validate permissions
        if not channel.members.filter(
            user=added_by,
            role__in=["OWNER", "ADMIN"]
        ).exists():
            raise ValidationError("You don't have permission to add members")
        
        members = []
        for user in users:
            member = channel.add_member(user, role)
            members.append(member)
            
            # Send invitation notification
            Notification.objects.create(
                recipient=user,
                notification_type="CHANNEL_INVITE",
                title=f"You've been added to #{channel.name}",
                content=f"{added_by.get_full_name()} added you to the channel",
                related_object_type="channel",
                related_object_id=str(channel.id),
                action_url=f"/channels/{channel.id}",
                group=channel.group
            )
        
        # Send real-time update
        async_to_sync(self.realtime_service.broadcast_to_channel)(
            channel,
            "members_added",
            {"users": [str(u.id) for u in users]}
        )
        
        return members
    
    def archive_channel(
        self,
        channel: Channel,
        archived_by: User
    ) -> Channel:
        """Archive a channel."""
        # Validate permissions
        if not channel.members.filter(
            user=archived_by,
            role__in=["OWNER", "ADMIN"]
        ).exists():
            raise ValidationError("You don't have permission to archive this channel")
        
        channel.is_archived = True
        channel.save(update_fields=["is_archived"])
        
        # Send notification to members
        for member in channel.members.all():
            Notification.objects.create(
                recipient=member.user,
                notification_type="SYSTEM",
                title=f"Channel #{channel.name} archived",
                content=f"This channel has been archived by {archived_by.get_full_name()}",
                group=channel.group
            )
        
        return channel
    
    def get_user_channels(
        self,
        user: User,
        group,
        include_archived: bool = False
    ) -> List[Channel]:
        """Get all channels a user is a member of."""
        channels = Channel.objects.filter(
            group=group,
            members__user=user
        )
        
        if not include_archived:
            channels = channels.filter(is_archived=False)
        
        return channels.distinct()
    
    def get_channel_statistics(self, channel: Channel) -> Dict[str, Any]:
        """Get statistics for a channel."""
        stats = {
            "member_count": channel.member_count,
            "message_count": channel.message_count,
            "active_members_today": channel.members.filter(
                last_read_at__gte=timezone.now() - timedelta(days=1)
            ).count(),
            "messages_today": channel.messages.filter(
                created_at__gte=timezone.now() - timedelta(days=1),
                is_deleted=False
            ).count(),
            "threads_count": channel.threads.count(),
            "files_count": MessageAttachment.objects.filter(
                message__channel=channel
            ).count()
        }
        
        return stats
    
    def _send_channel_created_notification(self, channel: Channel, creator: User):
        """Send notification when a channel is created."""
        # Only for public channels
        if channel.channel_type == "PUBLIC":
            # Notify all group members
            users = User.objects.filter(
                groups=channel.group
            ).exclude(id=creator.id)
            
            for user in users:
                Notification.objects.create(
                    recipient=user,
                    notification_type="SYSTEM",
                    title=f"New channel: #{channel.name}",
                    content=f"{creator.get_full_name()} created a new channel",
                    related_object_type="channel",
                    related_object_id=str(channel.id),
                    action_url=f"/channels/{channel.id}",
                    group=channel.group
                )


class NotificationService(BaseService):
    """Service for managing notifications."""
    
    def __init__(self):
        """Initialize the notification service."""
        super().__init__()
        self.dispatcher = NotificationDispatcher()
    
    def send_notification(
        self,
        recipient: User,
        notification_type: str,
        title: str,
        content: str,
        priority: str = "MEDIUM",
        channels: Optional[List[str]] = None,
        template_id: Optional[str] = None,
        template_data: Optional[Dict] = None,
        schedule_for: Optional[datetime] = None,
        **kwargs
    ) -> Notification:
        """Send a notification to a user."""
        # Get user preferences
        try:
            preferences = recipient.notification_preferences
        except NotificationPreference.DoesNotExist:
            preferences = NotificationPreference.objects.create(
                user=recipient,
                group=recipient.groups.first()
            )
        
        # Determine channels
        if not channels:
            channels = self._get_default_channels(preferences, notification_type)
        
        # Use template if provided
        if template_id:
            notification_data = self._render_template(
                template_id,
                template_data or {}
            )
            title = notification_data.get("title", title)
            content = notification_data.get("content", content)
        
        # Create notification
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            content=content,
            priority=priority,
            channels=channels,
            scheduled_for=schedule_for,
            group=recipient.groups.first(),
            **kwargs
        )
        
        # Send immediately if not scheduled
        if not schedule_for:
            self._dispatch_notification(notification)
        else:
            # Schedule for later
            send_scheduled_notification.apply_async(
                args=[notification.id],
                eta=schedule_for
            )
        
        return notification
    
    def send_bulk_notification(
        self,
        recipients: List[User],
        notification_type: str,
        title: str,
        content: str,
        **kwargs
    ) -> List[Notification]:
        """Send notification to multiple recipients."""
        notifications = []
        
        with transaction.atomic():
            for recipient in recipients:
                notification = self.send_notification(
                    recipient=recipient,
                    notification_type=notification_type,
                    title=title,
                    content=content,
                    **kwargs
                )
                notifications.append(notification)
        
        return notifications
    
    def mark_notifications_read(
        self,
        user: User,
        notification_ids: Optional[List[str]] = None
    ) -> int:
        """Mark notifications as read."""
        notifications = Notification.objects.filter(
            recipient=user,
            is_read=False
        )
        
        if notification_ids:
            notifications = notifications.filter(id__in=notification_ids)
        
        count = notifications.update(
            is_read=True,
            read_at=timezone.now()
        )
        
        return count
    
    def get_unread_count(self, user: User) -> int:
        """Get unread notification count for a user."""
        cache_key = f"notification_unread_{user.id}"
        count = cache.get(cache_key)
        
        if count is None:
            count = Notification.objects.filter(
                recipient=user,
                is_read=False,
                is_archived=False
            ).count()
            cache.set(cache_key, count, 300)  # Cache for 5 minutes
        
        return count
    
    def _get_default_channels(
        self,
        preferences: NotificationPreference,
        notification_type: str
    ) -> List[str]:
        """Get default notification channels based on preferences."""
        channels = []
        
        if preferences.in_app_enabled:
            channels.append("in_app")
        
        # Check if we should send other channels
        if preferences.should_send_notification(notification_type, "email"):
            channels.append("email")
        
        if preferences.should_send_notification(notification_type, "push"):
            channels.append("push")
        
        if preferences.should_send_notification(notification_type, "sms"):
            channels.append("sms")
        
        return channels
    
    def _render_template(
        self,
        template_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, str]:
        """Render notification from template."""
        try:
            template = NotificationTemplate.objects.get(
                template_id=template_id,
                is_active=True
            )
            
            # Render subject and body
            from django.template import Template, Context
            
            subject_template = Template(template.subject_template)
            body_template = Template(template.body_template)
            
            context = Context(data)
            
            return {
                "title": subject_template.render(context),
                "content": body_template.render(context),
                "email_subject": template.email_subject or subject_template.render(context),
                "email_body": template.email_body or body_template.render(context),
                "sms_content": template.sms_template,
                "push_content": template.push_template,
            }
        except NotificationTemplate.DoesNotExist:
            logger.warning(f"Notification template {template_id} not found")
            return {}
    
    def _dispatch_notification(self, notification: Notification):
        """Dispatch notification through various channels."""
        self.dispatcher.dispatch(notification)


class MeetingService(BaseService):
    """Service for managing meetings and video calls."""
    
    def __init__(self):
        """Initialize the meeting service."""
        super().__init__()
        from .video import VideoProvider
        self.video_provider = VideoProvider()
    
    @transaction.atomic
    def schedule_meeting(
        self,
        title: str,
        organizer: User,
        participants: List[User],
        scheduled_start: datetime,
        scheduled_end: datetime,
        channel: Optional[Channel] = None,
        description: str = "",
        enable_recording: bool = False,
        **kwargs
    ) -> Meeting:
        """Schedule a new meeting."""
        # Create meeting
        meeting = Meeting.objects.create(
            title=title,
            description=description,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            organizer=organizer,
            channel=channel,
            enable_recording=enable_recording,
            group=organizer.groups.first(),
            **kwargs
        )
        
        # Generate meeting room
        room_data = self.video_provider.create_room(
            room_id=str(meeting.id),
            settings={
                "recording": enable_recording,
                "max_participants": meeting.max_participants,
            }
        )
        
        meeting.meeting_url = room_data["url"]
        meeting.meeting_id = room_data["room_id"]
        meeting.passcode = room_data.get("passcode", "")
        meeting.save()
        
        # Add participants
        for participant in participants:
            meeting.meeting_participants.create(
                user=participant,
                role="PARTICIPANT" if participant != organizer else "HOST"
            )
        
        # Send invitations
        self._send_meeting_invitations(meeting)
        
        # Schedule reminder
        reminder_time = scheduled_start - timedelta(minutes=15)
        send_meeting_reminder.apply_async(
            args=[meeting.id],
            eta=reminder_time
        )
        
        return meeting
    
    def start_instant_meeting(
        self,
        organizer: User,
        participants: List[User],
        channel: Optional[Channel] = None,
        call_type: str = "VIDEO"
    ) -> Tuple[Meeting, VideoCall]:
        """Start an instant meeting/call."""
        # Create meeting
        meeting = Meeting.objects.create(
            title=f"Instant {call_type.lower()} call",
            scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
            organizer=organizer,
            channel=channel,
            group=organizer.groups.first()
        )
        
        # Create video call
        room_id = f"instant_{meeting.id}"
        video_call = VideoCall.objects.create(
            channel=channel,
            call_type=call_type,
            initiator=organizer,
            room_id=room_id,
            group=organizer.groups.first()
        )
        
        # Generate room
        room_data = self.video_provider.create_room(
            room_id=room_id,
            settings={
                "type": call_type.lower(),
                "instant": True,
            }
        )
        
        meeting.meeting_url = room_data["url"]
        meeting.meeting_id = room_id
        meeting.save()
        
        # Add participants
        for participant in [organizer] + participants:
            video_call.call_participants.create(user=participant)
            if participant != organizer:
                # Send call notification
                Notification.objects.create(
                    recipient=participant,
                    notification_type="SYSTEM",
                    title=f"Incoming {call_type.lower()} call",
                    content=f"{organizer.get_full_name()} is calling you",
                    priority="URGENT",
                    related_object_type="video_call",
                    related_object_id=str(video_call.id),
                    action_url=meeting.meeting_url,
                    group=participant.groups.first()
                )
        
        # Start the call
        meeting.start_meeting()
        video_call.start_call()
        
        return meeting, video_call
    
    def join_meeting(
        self,
        meeting: Meeting,
        user: User
    ) -> Dict[str, Any]:
        """Join a meeting."""
        # Check if user is participant
        participant = meeting.meeting_participants.filter(user=user).first()
        if not participant:
            raise ValidationError("You are not invited to this meeting")
        
        # Update participant status
        participant.joined_at = timezone.now()
        participant.save(update_fields=["joined_at"])
        
        # Generate access token
        access_token = self.video_provider.generate_access_token(
            room_id=meeting.meeting_id,
            user_id=str(user.id),
            role=participant.role.lower()
        )
        
        return {
            "meeting_url": meeting.meeting_url,
            "access_token": access_token,
            "room_id": meeting.meeting_id,
            "role": participant.role,
        }
    
    def end_meeting(self, meeting: Meeting, ended_by: User) -> Meeting:
        """End a meeting."""
        # Validate permissions
        if meeting.organizer != ended_by:
            participant = meeting.meeting_participants.filter(
                user=ended_by,
                role__in=["HOST", "CO_HOST"]
            ).first()
            if not participant:
                raise ValidationError("You don't have permission to end this meeting")
        
        # End meeting
        meeting.end_meeting()
        
        # End associated video call if any
        video_calls = VideoCall.objects.filter(
            room_id=meeting.meeting_id,
            status="IN_PROGRESS"
        )
        for call in video_calls:
            call.end_call()
        
        # Process recording if enabled
        if meeting.enable_recording:
            process_meeting_recording.delay(meeting.id)
        
        return meeting
    
    def _send_meeting_invitations(self, meeting: Meeting):
        """Send meeting invitations to participants."""
        for participant in meeting.meeting_participants.all():
            # Create calendar event
            calendar_data = {
                "title": meeting.title,
                "description": meeting.description,
                "start": meeting.scheduled_start,
                "end": meeting.scheduled_end,
                "location": meeting.meeting_url,
                "attendees": [p.user.email for p in meeting.meeting_participants.all()],
            }
            
            # Send notification
            self.notification_service.send_notification(
                recipient=participant.user,
                notification_type="MEETING_REMINDER",
                title=f"Meeting scheduled: {meeting.title}",
                content=render_to_string(
                    "communication/meeting_invitation.html",
                    {
                        "meeting": meeting,
                        "participant": participant,
                        "calendar_data": calendar_data,
                    }
                ),
                related_object_type="meeting",
                related_object_id=str(meeting.id),
                action_url=f"/meetings/{meeting.id}",
                metadata={"calendar_data": calendar_data}
            )


# Celery tasks
@shared_task
def send_scheduled_notification(notification_id: str):
    """Send a scheduled notification."""
    try:
        notification = Notification.objects.get(id=notification_id)
        if not notification.is_read:
            service = NotificationService()
            service._dispatch_notification(notification)
    except Notification.DoesNotExist:
        logger.error(f"Scheduled notification {notification_id} not found")


@shared_task
def send_meeting_reminder(meeting_id: str):
    """Send meeting reminder notifications."""
    try:
        meeting = Meeting.objects.get(id=meeting_id)
        if meeting.status == "SCHEDULED":
            service = NotificationService()
            for participant in meeting.meeting_participants.filter(
                response_status__in=["ACCEPTED", "TENTATIVE"]
            ):
                service.send_notification(
                    recipient=participant.user,
                    notification_type="MEETING_REMINDER",
                    title=f"Meeting starting soon: {meeting.title}",
                    content=f"Your meeting starts in 15 minutes",
                    priority="HIGH",
                    related_object_type="meeting",
                    related_object_id=str(meeting.id),
                    action_url=f"/meetings/{meeting.id}/join"
                )
    except Meeting.DoesNotExist:
        logger.error(f"Meeting {meeting_id} not found for reminder")


@shared_task
def process_meeting_recording(meeting_id: str):
    """Process meeting recording."""
    try:
        meeting = Meeting.objects.get(id=meeting_id)
        service = MeetingService()
        
        # Get recording from video provider
        recording_data = service.video_provider.get_recording(meeting.meeting_id)
        
        if recording_data:
            meeting.recording_url = recording_data["url"]
            meeting.recording_duration = timedelta(seconds=recording_data["duration"])
            meeting.save()
            
            # Notify participants
            notification_service = NotificationService()
            for participant in meeting.meeting_participants.all():
                notification_service.send_notification(
                    recipient=participant.user,
                    notification_type="SYSTEM",
                    title="Meeting recording available",
                    content=f"The recording for '{meeting.title}' is now available",
                    related_object_type="meeting",
                    related_object_id=str(meeting.id),
                    action_url=f"/meetings/{meeting.id}/recording"
                )
    except Meeting.DoesNotExist:
        logger.error(f"Meeting {meeting_id} not found for recording processing")


@shared_task
def cleanup_old_messages():
    """Clean up old messages based on retention policy."""
    retention_days = getattr(settings, "MESSAGE_RETENTION_DAYS", 365)
    cutoff_date = timezone.now() - timedelta(days=retention_days)
    
    # Hard delete old soft-deleted messages
    deleted_count = Message.objects.filter(
        is_deleted=True,
        deleted_at__lt=cutoff_date
    ).delete()[0]
    
    logger.info(f"Cleaned up {deleted_count} old deleted messages")
    
    # Archive old messages
    archived_count = Message.objects.filter(
        created_at__lt=cutoff_date,
        is_deleted=False
    ).update(
        metadata=F("metadata").update({"archived": True})
    )
    
    logger.info(f"Archived {archived_count} old messages")


@shared_task
def update_channel_statistics():
    """Update channel statistics."""
    for channel in Channel.objects.filter(is_archived=False):
        channel.member_count = channel.members.count()
        channel.message_count = channel.messages.filter(is_deleted=False).count()
        channel.save(update_fields=["member_count", "message_count"])
    
    logger.info("Channel statistics updated")


@shared_task
def process_message_attachments(message_id: str):
    """Process message attachments (scan, generate thumbnails, etc)."""
    try:
        message = Message.objects.get(id=message_id)
        
        for attachment in message.attachments.all():
            # Scan for viruses
            # Generate thumbnails for images
            # Extract metadata
            pass
            
    except Message.DoesNotExist:
        logger.error(f"Message {message_id} not found for attachment processing")