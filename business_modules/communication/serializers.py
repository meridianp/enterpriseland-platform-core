"""Communication module serializers."""

from typing import Dict, Any

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from platform_core.serializers import BaseSerializer
from .models import (
    Channel, ChannelMember, Message, MessageReaction, MessageAttachment,
    Thread, ThreadParticipant, Notification, NotificationPreference,
    Meeting, MeetingParticipant, VideoCall, CallParticipant
)

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user basic info."""
    
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    avatar_url = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name",
                  "full_name", "avatar_url"]
        read_only_fields = fields
    
    def get_avatar_url(self, obj) -> str:
        """Get user avatar URL."""
        # Implement based on your user model
        return f"https://ui-avatars.com/api/?name={obj.get_full_name()}&background=random"


class ChannelMemberSerializer(BaseSerializer):
    """Serializer for channel members."""
    
    user = UserSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True)
    unread_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ChannelMember
        fields = [
            "id", "user", "user_id", "role", "is_muted",
            "notification_level", "joined_at", "last_read_at",
            "unread_count", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "joined_at", "created_at", "updated_at"]
    
    def get_unread_count(self, obj) -> int:
        """Get unread message count."""
        return obj.channel.get_unread_count(obj.user)
    
    def create(self, validated_data):
        """Create channel member."""
        user = User.objects.get(id=validated_data.pop("user_id"))
        validated_data["user"] = user
        return super().create(validated_data)


class ChannelSerializer(BaseSerializer):
    """Serializer for channels."""
    
    created_by = UserSerializer(read_only=True)
    members = ChannelMemberSerializer(many=True, read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    message_count = serializers.IntegerField(read_only=True)
    last_message = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Channel
        fields = [
            "id", "name", "slug", "description", "channel_type",
            "is_archived", "is_read_only", "allow_guests",
            "allow_threading", "auto_join_new_members", "created_by",
            "avatar_url", "topic", "member_count", "message_count",
            "last_activity", "members", "last_message", "is_member",
            "unread_count", "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "slug", "member_count", "message_count",
            "last_activity", "created_at", "updated_at"
        ]
    
    def get_last_message(self, obj) -> Dict[str, Any]:
        """Get last message in channel."""
        last_message = obj.messages.filter(is_deleted=False).last()
        if last_message:
            return {
                "id": str(last_message.id),
                "content": last_message.content[:100],
                "sender": last_message.sender.get_full_name() if last_message.sender else "System",
                "created_at": last_message.created_at.isoformat(),
            }
        return None
    
    def get_is_member(self, obj) -> bool:
        """Check if current user is member."""
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.is_member(request.user)
        return False
    
    def get_unread_count(self, obj) -> int:
        """Get unread count for current user."""
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.get_unread_count(request.user)
        return 0


class MessageReactionSerializer(BaseSerializer):
    """Serializer for message reactions."""
    
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = MessageReaction
        fields = ["id", "user", "emoji", "created_at"]
        read_only_fields = ["id", "created_at"]


class MessageAttachmentSerializer(BaseSerializer):
    """Serializer for message attachments."""
    
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = MessageAttachment
        fields = [
            "id", "file", "file_url", "filename", "file_size",
            "mime_type", "thumbnail_url", "metadata", "is_scanned",
            "is_safe", "created_at"
        ]
        read_only_fields = [
            "id", "file_url", "file_size", "mime_type",
            "is_scanned", "is_safe", "created_at"
        ]
    
    def get_file_url(self, obj) -> str:
        """Get full file URL."""
        request = self.context.get("request")
        if request and obj.file:
            return request.build_absolute_uri(obj.file.url)
        return ""


class ThreadSerializer(BaseSerializer):
    """Serializer for message threads."""
    
    parent_message = serializers.SerializerMethodField()
    participants = UserSerializer(many=True, read_only=True)
    
    class Meta:
        model = Thread
        fields = [
            "id", "channel", "parent_message", "reply_count",
            "participant_count", "last_reply_at", "participants",
            "created_at", "updated_at"
        ]
        read_only_fields = fields
    
    def get_parent_message(self, obj) -> Dict[str, Any]:
        """Get parent message info."""
        return {
            "id": str(obj.parent_message.id),
            "content": obj.parent_message.content[:100],
            "sender": obj.parent_message.sender.get_full_name() if obj.parent_message.sender else "System",
        }


class MessageSerializer(BaseSerializer):
    """Serializer for messages."""
    
    sender = UserSerializer(read_only=True)
    reactions = MessageReactionSerializer(many=True, read_only=True)
    attachments = MessageAttachmentSerializer(many=True, read_only=True)
    thread_info = ThreadSerializer(source="thread", read_only=True)
    reply_to_info = serializers.SerializerMethodField()
    reaction_summary = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            "id", "channel", "sender", "content", "message_type",
            "thread", "thread_info", "reply_to", "reply_to_info",
            "metadata", "mentions", "is_edited", "edited_at",
            "is_deleted", "deleted_at", "reactions", "reaction_summary",
            "attachments", "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "is_edited", "edited_at", "is_deleted",
            "deleted_at", "created_at", "updated_at"
        ]
        extra_kwargs = {
            "channel": {"write_only": True},
            "thread": {"write_only": True},
            "reply_to": {"write_only": True},
        }
    
    def get_content(self, obj) -> str:
        """Get decrypted content if needed."""
        return obj.get_content()
    
    def get_reply_to_info(self, obj) -> Dict[str, Any]:
        """Get reply to message info."""
        if obj.reply_to:
            return {
                "id": str(obj.reply_to.id),
                "content": obj.reply_to.content[:50],
                "sender": obj.reply_to.sender.get_full_name() if obj.reply_to.sender else "System",
            }
        return None
    
    def get_reaction_summary(self, obj) -> Dict[str, int]:
        """Get reaction counts by emoji."""
        summary = {}
        for reaction in obj.reactions.all():
            emoji = reaction.emoji
            summary[emoji] = summary.get(emoji, 0) + 1
        return summary
    
    def create(self, validated_data):
        """Create message with proper sender."""
        request = self.context.get("request")
        validated_data["sender"] = request.user
        validated_data["group"] = validated_data["channel"].group
        return super().create(validated_data)


class NotificationSerializer(BaseSerializer):
    """Serializer for notifications."""
    
    recipient = UserSerializer(read_only=True)
    
    class Meta:
        model = Notification
        fields = [
            "id", "recipient", "notification_type", "title", "content",
            "priority", "related_object_type", "related_object_id",
            "action_url", "is_read", "read_at", "is_archived",
            "channels", "delivery_status", "scheduled_for", "expires_at",
            "metadata", "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "recipient", "is_read", "read_at",
            "delivery_status", "created_at", "updated_at"
        ]


class NotificationPreferenceSerializer(BaseSerializer):
    """Serializer for notification preferences."""
    
    class Meta:
        model = NotificationPreference
        fields = [
            "id", "email_enabled", "sms_enabled", "push_enabled",
            "in_app_enabled", "message_notifications", "mention_notifications",
            "task_notifications", "meeting_notifications", "system_notifications",
            "quiet_hours_enabled", "quiet_hours_start", "quiet_hours_end",
            "timezone", "batch_email_notifications", "batch_interval_minutes",
            "notification_sound", "desktop_notifications", "mobile_vibrate",
            "created_at", "updated_at"
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MeetingParticipantSerializer(BaseSerializer):
    """Serializer for meeting participants."""
    
    user = UserSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True)
    
    class Meta:
        model = MeetingParticipant
        fields = [
            "id", "user", "user_id", "role", "response_status",
            "response_message", "joined_at", "left_at", "duration",
            "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "joined_at", "left_at", "duration",
            "created_at", "updated_at"
        ]


class MeetingSerializer(BaseSerializer):
    """Serializer for meetings."""
    
    organizer = UserSerializer(read_only=True)
    participants = MeetingParticipantSerializer(
        source="meeting_participants",
        many=True,
        read_only=True
    )
    channel_info = serializers.SerializerMethodField()
    
    class Meta:
        model = Meeting
        fields = [
            "id", "title", "description", "scheduled_start", "scheduled_end",
            "actual_start", "actual_end", "organizer", "participants",
            "channel", "channel_info", "status", "meeting_url", "meeting_id",
            "passcode", "is_recurring", "recurrence_rule", "enable_recording",
            "enable_waiting_room", "max_participants", "calendar_event_id",
            "video_provider", "recording_url", "recording_duration",
            "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "actual_start", "actual_end", "meeting_url",
            "meeting_id", "passcode", "recording_url", "recording_duration",
            "created_at", "updated_at"
        ]
        extra_kwargs = {
            "channel": {"write_only": True},
        }
    
    def get_channel_info(self, obj) -> Dict[str, Any]:
        """Get channel info if linked."""
        if obj.channel:
            return {
                "id": str(obj.channel.id),
                "name": obj.channel.name,
                "type": obj.channel.channel_type,
            }
        return None
    
    def create(self, validated_data):
        """Create meeting with organizer."""
        request = self.context.get("request")
        validated_data["organizer"] = request.user
        validated_data["group"] = request.user.groups.first()
        return super().create(validated_data)


class CallParticipantSerializer(BaseSerializer):
    """Serializer for call participants."""
    
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = CallParticipant
        fields = [
            "id", "user", "joined_at", "left_at", "duration",
            "is_muted", "is_video_enabled", "is_screen_sharing",
            "connection_quality", "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "joined_at", "left_at", "duration",
            "created_at", "updated_at"
        ]


class VideoCallSerializer(BaseSerializer):
    """Serializer for video calls."""
    
    initiator = UserSerializer(read_only=True)
    participants = CallParticipantSerializer(
        source="call_participants",
        many=True,
        read_only=True
    )
    channel_info = serializers.SerializerMethodField()
    
    class Meta:
        model = VideoCall
        fields = [
            "id", "channel", "channel_info", "call_type", "status",
            "initiator", "participants", "started_at", "ended_at",
            "duration", "room_id", "recording_enabled", "recording_url",
            "max_participants", "quality_metrics", "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "status", "started_at", "ended_at", "duration",
            "room_id", "recording_url", "quality_metrics",
            "created_at", "updated_at"
        ]
        extra_kwargs = {
            "channel": {"write_only": True},
        }
    
    def get_channel_info(self, obj) -> Dict[str, Any]:
        """Get channel info if linked."""
        if obj.channel:
            return {
                "id": str(obj.channel.id),
                "name": obj.channel.name,
                "type": obj.channel.channel_type,
            }
        return None


# Bulk action serializers
class BulkMessageSerializer(serializers.Serializer):
    """Serializer for bulk message operations."""
    
    message_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100
    )
    action = serializers.ChoiceField(
        choices=["delete", "mark_read", "mark_unread"]
    )


class MessageSearchSerializer(serializers.Serializer):
    """Serializer for message search."""
    
    query = serializers.CharField(required=True, min_length=2)
    channel_id = serializers.UUIDField(required=False)
    sender_id = serializers.UUIDField(required=False)
    date_from = serializers.DateTimeField(required=False)
    date_to = serializers.DateTimeField(required=False)
    message_type = serializers.ChoiceField(
        choices=Message.MessageType.choices,
        required=False
    )
    limit = serializers.IntegerField(default=50, min_value=1, max_value=200)


class TypingIndicatorSerializer(serializers.Serializer):
    """Serializer for typing indicators."""
    
    channel_id = serializers.UUIDField(required=True)
    is_typing = serializers.BooleanField(default=True)


class PresenceSerializer(serializers.Serializer):
    """Serializer for user presence."""
    
    status = serializers.ChoiceField(
        choices=["online", "away", "busy", "offline"],
        default="online"
    )
    status_message = serializers.CharField(required=False, max_length=100)