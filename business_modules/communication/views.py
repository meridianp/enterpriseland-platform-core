"""Communication module views."""

from datetime import datetime, timedelta
from typing import List, Dict, Any

from django.contrib.auth import get_user_model
from django.db import transaction, models
from django.db.models import Q, Count, Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import CursorPagination

from platform_core.views import BaseViewSet
from platform_core.permissions import IsGroupMember
from .models import (
    Channel, ChannelMember, Message, MessageReaction, MessageAttachment,
    Thread, Notification, NotificationPreference, Meeting, VideoCall
)
from .serializers import (
    ChannelSerializer, ChannelMemberSerializer, MessageSerializer,
    MessageReactionSerializer, MessageAttachmentSerializer, ThreadSerializer,
    NotificationSerializer, NotificationPreferenceSerializer,
    MeetingSerializer, VideoCallSerializer, MessageSearchSerializer,
    BulkMessageSerializer, TypingIndicatorSerializer, PresenceSerializer
)
from .services import (
    MessageService, ChannelService, NotificationService, MeetingService
)
from .permissions import (
    CanManageChannel, CanSendMessage, CanDeleteMessage,
    CanManageMeeting, CanViewNotification
)

User = get_user_model()


class MessagePagination(CursorPagination):
    """Cursor pagination for messages."""
    
    page_size = 50
    ordering = "created_at"
    cursor_query_param = "cursor"
    page_size_query_param = "page_size"
    max_page_size = 200


class ChannelFilter(filters.FilterSet):
    """Filter for channels."""
    
    channel_type = filters.ChoiceFilter(choices=Channel.ChannelType.choices)
    is_archived = filters.BooleanFilter()
    search = filters.CharFilter(method="filter_search")
    has_unread = filters.BooleanFilter(method="filter_has_unread")
    
    class Meta:
        model = Channel
        fields = ["channel_type", "is_archived"]
    
    def filter_search(self, queryset, name, value):
        """Search channels by name or description."""
        return queryset.filter(
            Q(name__icontains=value) | Q(description__icontains=value)
        )
    
    def filter_has_unread(self, queryset, name, value):
        """Filter channels with unread messages."""
        user = self.request.user
        if value:
            # Get channels with messages after last read
            return queryset.filter(
                members__user=user,
                messages__created_at__gt=models.F("members__last_read_at")
            ).distinct()
        return queryset


class ChannelViewSet(BaseViewSet):
    """ViewSet for managing channels."""
    
    queryset = Channel.objects.all()
    serializer_class = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated, IsGroupMember]
    filterset_class = ChannelFilter
    search_fields = ["name", "description"]
    ordering_fields = ["name", "last_activity", "created_at"]
    ordering = ["-last_activity"]
    
    def __init__(self, *args, **kwargs):
        """Initialize viewset."""
        super().__init__(*args, **kwargs)
        self.channel_service = ChannelService()
    
    def get_queryset(self):
        """Get channels user has access to."""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter to channels user is member of
        return queryset.filter(members__user=user).distinct()
    
    def perform_create(self, serializer):
        """Create a new channel."""
        channel = self.channel_service.create_channel(
            name=serializer.validated_data["name"],
            channel_type=serializer.validated_data.get("channel_type", "PUBLIC"),
            creator=self.request.user,
            group=self.get_group(),
            description=serializer.validated_data.get("description", ""),
            settings=serializer.validated_data
        )
        serializer.instance = channel
    
    @action(detail=True, methods=["post"], permission_classes=[CanManageChannel])
    def add_members(self, request, pk=None):
        """Add members to a channel."""
        channel = self.get_object()
        user_ids = request.data.get("user_ids", [])
        role = request.data.get("role", "MEMBER")
        
        users = User.objects.filter(id__in=user_ids, groups=self.get_group())
        members = self.channel_service.add_members(
            channel=channel,
            users=users,
            added_by=request.user,
            role=role
        )
        
        serializer = ChannelMemberSerializer(members, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=["post"])
    def remove_member(self, request, pk=None):
        """Remove a member from channel."""
        channel = self.get_object()
        user_id = request.data.get("user_id")
        
        # Check permissions
        member = channel.members.filter(user=request.user).first()
        if not member or member.role not in ["OWNER", "ADMIN"]:
            return Response(
                {"error": "You don't have permission to remove members"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user = get_object_or_404(User, id=user_id)
        removed = channel.remove_member(user)
        
        return Response({"removed": removed})
    
    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        """Leave a channel."""
        channel = self.get_object()
        removed = channel.remove_member(request.user)
        return Response({"left": removed})
    
    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark channel as read."""
        channel = self.get_object()
        member = channel.members.filter(user=request.user).first()
        if member:
            member.mark_as_read()
            return Response({"marked_read": True})
        return Response(
            {"error": "Not a member of this channel"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    @action(detail=True, methods=["post"], permission_classes=[CanManageChannel])
    def archive(self, request, pk=None):
        """Archive a channel."""
        channel = self.get_object()
        channel = self.channel_service.archive_channel(
            channel=channel,
            archived_by=request.user
        )
        serializer = self.get_serializer(channel)
        return Response(serializer.data)
    
    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        """Get channel statistics."""
        channel = self.get_object()
        stats = self.channel_service.get_channel_statistics(channel)
        return Response(stats)
    
    @action(detail=False, methods=["post"])
    def create_direct(self, request):
        """Create or get direct message channel."""
        other_user_id = request.data.get("user_id")
        other_user = get_object_or_404(User, id=other_user_id, groups=self.get_group())
        
        channel = self.channel_service.create_direct_message_channel(
            user1=request.user,
            user2=other_user,
            group=self.get_group()
        )
        
        serializer = self.get_serializer(channel)
        return Response(serializer.data)


class MessageFilter(filters.FilterSet):
    """Filter for messages."""
    
    channel = filters.UUIDFilter(field_name="channel__id")
    sender = filters.UUIDFilter(field_name="sender__id")
    thread = filters.UUIDFilter(field_name="thread__id")
    message_type = filters.ChoiceFilter(choices=Message.MessageType.choices)
    has_attachments = filters.BooleanFilter(method="filter_has_attachments")
    date_from = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")
    
    class Meta:
        model = Message
        fields = ["channel", "sender", "thread", "message_type"]
    
    def filter_has_attachments(self, queryset, name, value):
        """Filter messages with attachments."""
        if value:
            return queryset.filter(attachments__isnull=False).distinct()
        return queryset.filter(attachments__isnull=True)


class MessageViewSet(BaseViewSet):
    """ViewSet for managing messages."""
    
    queryset = Message.objects.filter(is_deleted=False)
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated, CanSendMessage]
    pagination_class = MessagePagination
    filterset_class = MessageFilter
    
    def __init__(self, *args, **kwargs):
        """Initialize viewset."""
        super().__init__(*args, **kwargs)
        self.message_service = MessageService()
    
    def get_queryset(self):
        """Get messages user has access to."""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter to messages in channels user is member of
        return queryset.filter(
            channel__members__user=user
        ).select_related(
            "sender", "channel", "thread", "reply_to"
        ).prefetch_related(
            "reactions__user", "attachments"
        ).distinct()
    
    def perform_create(self, serializer):
        """Send a message."""
        message = self.message_service.send_message(
            channel=serializer.validated_data["channel"],
            sender=self.request.user,
            content=serializer.validated_data["content"],
            message_type=serializer.validated_data.get("message_type", "TEXT"),
            thread=serializer.validated_data.get("thread"),
            reply_to=serializer.validated_data.get("reply_to"),
            metadata=serializer.validated_data.get("metadata", {})
        )
        serializer.instance = message
    
    def perform_update(self, serializer):
        """Edit a message."""
        message = self.message_service.edit_message(
            message=self.get_object(),
            user=self.request.user,
            new_content=serializer.validated_data["content"]
        )
        serializer.instance = message
    
    def perform_destroy(self, instance):
        """Delete a message."""
        self.message_service.delete_message(
            message=instance,
            user=self.request.user,
            hard_delete=self.request.query_params.get("hard", "false").lower() == "true"
        )
    
    @action(detail=False, methods=["post"])
    def search(self, request):
        """Search messages."""
        serializer = MessageSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        messages = self.message_service.search_messages(
            query=serializer.validated_data["query"],
            user=request.user,
            channel=Channel.objects.filter(
                id=serializer.validated_data.get("channel_id")
            ).first() if serializer.validated_data.get("channel_id") else None,
            sender=User.objects.filter(
                id=serializer.validated_data.get("sender_id")
            ).first() if serializer.validated_data.get("sender_id") else None,
            date_from=serializer.validated_data.get("date_from"),
            date_to=serializer.validated_data.get("date_to"),
            limit=serializer.validated_data.get("limit", 50)
        )
        
        serializer = MessageSerializer(messages, many=True, context={"request": request})
        return Response(serializer.data)
    
    @action(detail=False, methods=["post"])
    def bulk_action(self, request):
        """Perform bulk actions on messages."""
        serializer = BulkMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        message_ids = serializer.validated_data["message_ids"]
        action = serializer.validated_data["action"]
        
        messages = self.get_queryset().filter(id__in=message_ids)
        
        if action == "delete":
            for message in messages:
                self.message_service.delete_message(message, request.user)
            return Response({"deleted": len(messages)})
        
        elif action == "mark_read":
            # Update last read time for channels
            channels = messages.values_list("channel", flat=True).distinct()
            ChannelMember.objects.filter(
                user=request.user,
                channel__in=channels
            ).update(last_read_at=timezone.now())
            return Response({"marked_read": len(messages)})
        
        return Response(
            {"error": "Invalid action"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    @action(detail=True, methods=["post"])
    def add_reaction(self, request, pk=None):
        """Add reaction to a message."""
        message = self.get_object()
        emoji = request.data.get("emoji")
        
        if not emoji:
            return Response(
                {"error": "Emoji is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        reaction = message.add_reaction(request.user, emoji)
        serializer = MessageReactionSerializer(reaction)
        return Response(serializer.data)
    
    @action(detail=True, methods=["delete"])
    def remove_reaction(self, request, pk=None):
        """Remove reaction from a message."""
        message = self.get_object()
        emoji = request.query_params.get("emoji")
        
        deleted = MessageReaction.objects.filter(
            message=message,
            user=request.user,
            emoji=emoji
        ).delete()[0]
        
        return Response({"removed": bool(deleted)})
    
    @action(detail=True, methods=["post"])
    def create_thread(self, request, pk=None):
        """Create a thread from a message."""
        message = self.get_object()
        
        # Check if thread already exists
        if hasattr(message, "thread") and message.thread:
            serializer = ThreadSerializer(message.thread)
            return Response(serializer.data)
        
        # Create new thread
        thread = Thread.objects.create(
            channel=message.channel,
            parent_message=message,
            group=message.group
        )
        thread.add_participant(request.user)
        
        serializer = ThreadSerializer(thread)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class NotificationFilter(filters.FilterSet):
    """Filter for notifications."""
    
    notification_type = filters.ChoiceFilter(choices=Notification.NotificationType.choices)
    priority = filters.ChoiceFilter(choices=Notification.NotificationPriority.choices)
    is_read = filters.BooleanFilter()
    is_archived = filters.BooleanFilter()
    date_from = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")
    
    class Meta:
        model = Notification
        fields = ["notification_type", "priority", "is_read", "is_archived"]


class NotificationViewSet(BaseViewSet):
    """ViewSet for managing notifications."""
    
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated, CanViewNotification]
    filterset_class = NotificationFilter
    ordering_fields = ["created_at", "priority"]
    ordering = ["-created_at"]
    
    def __init__(self, *args, **kwargs):
        """Initialize viewset."""
        super().__init__(*args, **kwargs)
        self.notification_service = NotificationService()
    
    def get_queryset(self):
        """Get notifications for current user."""
        queryset = super().get_queryset()
        return queryset.filter(recipient=self.request.user)
    
    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        """Get unread notification count."""
        count = self.notification_service.get_unread_count(request.user)
        return Response({"unread_count": count})
    
    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        """Mark all notifications as read."""
        count = self.notification_service.mark_notifications_read(request.user)
        return Response({"marked_read": count})
    
    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark specific notification as read."""
        notification = self.get_object()
        notification.mark_as_read()
        serializer = self.get_serializer(notification)
        return Response(serializer.data)
    
    @action(detail=False, methods=["post"])
    def bulk_mark_read(self, request):
        """Mark multiple notifications as read."""
        notification_ids = request.data.get("notification_ids", [])
        count = self.notification_service.mark_notifications_read(
            request.user,
            notification_ids
        )
        return Response({"marked_read": count})
    
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        """Archive a notification."""
        notification = self.get_object()
        notification.is_archived = True
        notification.save(update_fields=["is_archived"])
        return Response({"archived": True})


class NotificationPreferenceViewSet(viewsets.GenericViewSet):
    """ViewSet for managing notification preferences."""
    
    serializer_class = NotificationPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        """Get or create preferences for current user."""
        obj, created = NotificationPreference.objects.get_or_create(
            user=self.request.user,
            defaults={"group": self.request.user.groups.first()}
        )
        return obj
    
    @action(detail=False, methods=["get", "put", "patch"])
    def me(self, request):
        """Get or update current user's preferences."""
        if request.method == "GET":
            preferences = self.get_object()
            serializer = self.get_serializer(preferences)
            return Response(serializer.data)
        
        else:  # PUT or PATCH
            preferences = self.get_object()
            serializer = self.get_serializer(
                preferences,
                data=request.data,
                partial=request.method == "PATCH"
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)


class MeetingFilter(filters.FilterSet):
    """Filter for meetings."""
    
    status = filters.ChoiceFilter(choices=Meeting.MeetingStatus.choices)
    organizer = filters.UUIDFilter(field_name="organizer__id")
    date_from = filters.DateTimeFilter(field_name="scheduled_start", lookup_expr="gte")
    date_to = filters.DateTimeFilter(field_name="scheduled_start", lookup_expr="lte")
    has_recording = filters.BooleanFilter(method="filter_has_recording")
    
    class Meta:
        model = Meeting
        fields = ["status", "organizer"]
    
    def filter_has_recording(self, queryset, name, value):
        """Filter meetings with recordings."""
        if value:
            return queryset.exclude(recording_url="")
        return queryset.filter(recording_url="")


class MeetingViewSet(BaseViewSet):
    """ViewSet for managing meetings."""
    
    queryset = Meeting.objects.all()
    serializer_class = MeetingSerializer
    permission_classes = [permissions.IsAuthenticated, IsGroupMember]
    filterset_class = MeetingFilter
    ordering_fields = ["scheduled_start", "created_at"]
    ordering = ["scheduled_start"]
    
    def __init__(self, *args, **kwargs):
        """Initialize viewset."""
        super().__init__(*args, **kwargs)
        self.meeting_service = MeetingService()
    
    def get_queryset(self):
        """Get meetings user has access to."""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter to meetings user is participant in
        return queryset.filter(
            Q(organizer=user) | Q(meeting_participants__user=user)
        ).distinct()
    
    def perform_create(self, serializer):
        """Schedule a meeting."""
        participant_ids = self.request.data.get("participant_ids", [])
        participants = User.objects.filter(
            id__in=participant_ids,
            groups=self.get_group()
        )
        
        meeting = self.meeting_service.schedule_meeting(
            title=serializer.validated_data["title"],
            organizer=self.request.user,
            participants=list(participants),
            scheduled_start=serializer.validated_data["scheduled_start"],
            scheduled_end=serializer.validated_data["scheduled_end"],
            channel=serializer.validated_data.get("channel"),
            description=serializer.validated_data.get("description", ""),
            enable_recording=serializer.validated_data.get("enable_recording", False)
        )
        serializer.instance = meeting
    
    @action(detail=True, methods=["post"])
    def join(self, request, pk=None):
        """Join a meeting."""
        meeting = self.get_object()
        join_data = self.meeting_service.join_meeting(meeting, request.user)
        return Response(join_data)
    
    @action(detail=True, methods=["post"], permission_classes=[CanManageMeeting])
    def end(self, request, pk=None):
        """End a meeting."""
        meeting = self.get_object()
        meeting = self.meeting_service.end_meeting(meeting, request.user)
        serializer = self.get_serializer(meeting)
        return Response(serializer.data)
    
    @action(detail=True, methods=["post"])
    def update_response(self, request, pk=None):
        """Update meeting response status."""
        meeting = self.get_object()
        response_status = request.data.get("response_status")
        response_message = request.data.get("response_message", "")
        
        participant = meeting.meeting_participants.filter(
            user=request.user
        ).first()
        
        if not participant:
            return Response(
                {"error": "You are not invited to this meeting"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        participant.response_status = response_status
        participant.response_message = response_message
        participant.save()
        
        return Response({"updated": True})
    
    @action(detail=False, methods=["post"])
    def instant(self, request):
        """Start an instant meeting/call."""
        participant_ids = request.data.get("participant_ids", [])
        participants = User.objects.filter(
            id__in=participant_ids,
            groups=self.get_group()
        )
        
        channel_id = request.data.get("channel_id")
        channel = None
        if channel_id:
            channel = Channel.objects.filter(
                id=channel_id,
                members__user=request.user
            ).first()
        
        meeting, video_call = self.meeting_service.start_instant_meeting(
            organizer=request.user,
            participants=list(participants),
            channel=channel,
            call_type=request.data.get("call_type", "VIDEO")
        )
        
        return Response({
            "meeting": MeetingSerializer(meeting).data,
            "video_call": VideoCallSerializer(video_call).data
        })


# WebSocket support views
class TypingIndicatorView(viewsets.GenericViewSet):
    """View for typing indicators."""
    
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TypingIndicatorSerializer
    
    @action(detail=False, methods=["post"])
    def update(self, request):
        """Update typing status."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        channel_id = serializer.validated_data["channel_id"]
        is_typing = serializer.validated_data["is_typing"]
        
        # Verify user is member of channel
        channel = get_object_or_404(
            Channel,
            id=channel_id,
            members__user=request.user
        )
        
        # Update typing status
        if is_typing:
            ChannelMember.objects.filter(
                channel=channel,
                user=request.user
            ).update(last_typed_at=timezone.now())
        
        # Send real-time update
        from .realtime import RealtimeService
        realtime_service = RealtimeService()
        realtime_service.send_typing_indicator(
            channel=channel,
            user=request.user,
            is_typing=is_typing
        )
        
        return Response({"updated": True})


class PresenceView(viewsets.GenericViewSet):
    """View for user presence."""
    
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PresenceSerializer
    
    @action(detail=False, methods=["post"])
    def update(self, request):
        """Update presence status."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Update user presence
        # This would typically update a cache or presence service
        
        return Response({"updated": True})
    
    @action(detail=False, methods=["get"])
    def online_users(self, request):
        """Get online users in group."""
        # This would typically query a presence service
        # For now, return empty list
        return Response({"users": []})