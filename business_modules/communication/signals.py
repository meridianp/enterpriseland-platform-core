"""Communication module signals."""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver

from .models import (
    Channel, ChannelMember, Message, Notification,
    NotificationPreference, Meeting, VideoCall
)
from .realtime import RealtimeService, PresenceService
from .services import NotificationService

User = get_user_model()


@receiver(post_save, sender=User)
def create_notification_preferences(sender, instance, created, **kwargs):
    """Create default notification preferences for new users."""
    if created:
        NotificationPreference.objects.get_or_create(
            user=instance,
            defaults={
                "group": instance.groups.first() if instance.groups.exists() else None
            }
        )


@receiver(post_save, sender=ChannelMember)
def invalidate_channel_cache(sender, instance, **kwargs):
    """Invalidate channel member cache when membership changes."""
    realtime_service = RealtimeService()
    realtime_service.invalidate_channel_cache(instance.channel)


@receiver(post_delete, sender=ChannelMember)
def invalidate_channel_cache_on_delete(sender, instance, **kwargs):
    """Invalidate channel member cache when member is removed."""
    realtime_service = RealtimeService()
    realtime_service.invalidate_channel_cache(instance.channel)


@receiver(post_save, sender=Message)
def update_channel_activity(sender, instance, created, **kwargs):
    """Update channel activity when message is sent."""
    if created and not instance.is_deleted:
        # Update channel last_activity
        instance.channel.last_activity = instance.created_at
        instance.channel.save(update_fields=["last_activity"])


@receiver(post_save, sender=Meeting)
def send_meeting_notifications(sender, instance, created, **kwargs):
    """Send notifications when meeting is created or updated."""
    if created:
        # Meeting was just created, invitations are sent by the service
        pass
    else:
        # Check if meeting was cancelled
        if instance.status == "CANCELLED":
            notification_service = NotificationService()
            
            for participant in instance.meeting_participants.all():
                notification_service.send_notification(
                    recipient=participant.user,
                    notification_type="MEETING_REMINDER",
                    title=f"Meeting cancelled: {instance.title}",
                    content=f"The meeting '{instance.title}' scheduled for {instance.scheduled_start} has been cancelled.",
                    priority="HIGH",
                    related_object_type="meeting",
                    related_object_id=str(instance.id)
                )


@receiver(post_save, sender=VideoCall)
def handle_video_call_status(sender, instance, **kwargs):
    """Handle video call status changes."""
    if instance.status == "COMPLETED":
        # Update participant durations
        for participant in instance.call_participants.filter(left_at__isnull=True):
            participant.leave_call()


@receiver(m2m_changed, sender=Channel.members.through)
def handle_channel_membership_change(sender, instance, action, pk_set, **kwargs):
    """Handle channel membership changes."""
    if action == "post_add":
        # Users added to channel
        for user_id in pk_set:
            # Could send welcome message or notification
            pass
    
    elif action == "post_remove":
        # Users removed from channel
        for user_id in pk_set:
            # Could send removal notification
            pass


@receiver(post_save, sender=Notification)
def update_notification_cache(sender, instance, created, **kwargs):
    """Update notification count cache."""
    if created and not instance.is_read:
        # Invalidate unread count cache
        from django.core.cache import cache
        cache_key = f"notification_unread_{instance.recipient.id}"
        cache.delete(cache_key)


# Custom signals
from django.dispatch import Signal

# Message signals
message_sent = Signal()  # Arguments: message, sender, channel
message_edited = Signal()  # Arguments: message, editor, old_content
message_deleted = Signal()  # Arguments: message, deleter

# Channel signals
channel_created = Signal()  # Arguments: channel, creator
channel_archived = Signal()  # Arguments: channel, archiver
member_joined_channel = Signal()  # Arguments: channel, member
member_left_channel = Signal()  # Arguments: channel, member

# Meeting signals
meeting_started = Signal()  # Arguments: meeting, starter
meeting_ended = Signal()  # Arguments: meeting, ender
participant_joined_meeting = Signal()  # Arguments: meeting, participant
participant_left_meeting = Signal()  # Arguments: meeting, participant

# Notification signals
notification_sent = Signal()  # Arguments: notification, channels
notification_read = Signal()  # Arguments: notification, reader


# Signal handlers for custom signals
@receiver(message_sent)
def handle_message_sent(sender, message, channel, **kwargs):
    """Handle message sent signal."""
    # Could trigger additional processing
    pass


@receiver(member_joined_channel)
def handle_member_joined(sender, channel, member, **kwargs):
    """Handle member joining channel."""
    # Send system message
    if channel.channel_type not in ["DIRECT", "EXTERNAL"]:
        Message.objects.create(
            channel=channel,
            sender=None,
            content=f"{member.get_full_name()} joined the channel",
            message_type="SYSTEM",
            group=channel.group
        )


@receiver(member_left_channel)
def handle_member_left(sender, channel, member, **kwargs):
    """Handle member leaving channel."""
    # Send system message
    if channel.channel_type not in ["DIRECT", "EXTERNAL"]:
        Message.objects.create(
            channel=channel,
            sender=None,
            content=f"{member.get_full_name()} left the channel",
            message_type="SYSTEM",
            group=channel.group
        )