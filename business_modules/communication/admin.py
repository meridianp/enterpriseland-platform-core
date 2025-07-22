"""Communication module admin configuration."""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone

from .models import (
    Channel, ChannelMember, Message, MessageReaction, MessageAttachment,
    Thread, Notification, NotificationPreference, NotificationTemplate,
    Meeting, MeetingParticipant, VideoCall
)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    """Admin for channels."""
    
    list_display = [
        "name", "channel_type", "member_count", "message_count",
        "is_archived", "last_activity", "created_at"
    ]
    list_filter = ["channel_type", "is_archived", "created_at"]
    search_fields = ["name", "description", "slug"]
    readonly_fields = [
        "id", "slug", "member_count", "message_count",
        "last_activity", "created_at", "updated_at"
    ]
    
    fieldsets = [
        ("Basic Information", {
            "fields": ["id", "name", "slug", "description", "channel_type"]
        }),
        ("Settings", {
            "fields": [
                "is_archived", "is_read_only", "allow_guests",
                "allow_threading", "auto_join_new_members"
            ]
        }),
        ("Metadata", {
            "fields": [
                "created_by", "avatar_url", "topic", "pinned_message",
                "external_id", "webhook_url"
            ]
        }),
        ("Statistics", {
            "fields": [
                "member_count", "message_count", "last_activity",
                "created_at", "updated_at"
            ]
        }),
    ]
    
    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related(
            "created_by", "group"
        )


@admin.register(ChannelMember)
class ChannelMemberAdmin(admin.ModelAdmin):
    """Admin for channel members."""
    
    list_display = [
        "user", "channel", "role", "is_muted",
        "notification_level", "joined_at", "last_read_at"
    ]
    list_filter = ["role", "is_muted", "notification_level"]
    search_fields = ["user__username", "user__email", "channel__name"]
    raw_id_fields = ["user", "channel"]
    
    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related(
            "user", "channel"
        )


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Admin for messages."""
    
    list_display = [
        "id", "channel", "sender", "message_type",
        "content_preview", "is_edited", "is_deleted", "created_at"
    ]
    list_filter = [
        "message_type", "is_edited", "is_deleted",
        "content_encrypted", "created_at"
    ]
    search_fields = ["content", "sender__username", "channel__name"]
    raw_id_fields = ["channel", "sender", "thread", "reply_to"]
    readonly_fields = [
        "id", "content_encrypted", "is_edited", "edited_at",
        "is_deleted", "deleted_at", "created_at", "updated_at"
    ]
    
    fieldsets = [
        ("Basic Information", {
            "fields": [
                "id", "channel", "sender", "message_type",
                "content", "content_encrypted"
            ]
        }),
        ("Threading", {
            "fields": ["thread", "reply_to"]
        }),
        ("Metadata", {
            "fields": ["metadata", "mentions", "external_id"]
        }),
        ("Status", {
            "fields": [
                "is_edited", "edited_at", "is_deleted", "deleted_at",
                "created_at", "updated_at"
            ]
        }),
    ]
    
    def content_preview(self, obj):
        """Show content preview."""
        content = obj.get_content() if obj.content_encrypted else obj.content
        return content[:50] + "..." if len(content) > 50 else content
    content_preview.short_description = "Content"
    
    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related(
            "sender", "channel", "group"
        )


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
    """Admin for message attachments."""
    
    list_display = [
        "filename", "message", "file_size_display",
        "mime_type", "is_scanned", "is_safe", "created_at"
    ]
    list_filter = ["mime_type", "is_scanned", "is_safe", "created_at"]
    search_fields = ["filename", "message__content"]
    raw_id_fields = ["message"]
    readonly_fields = ["id", "file_size", "is_scanned", "scan_results"]
    
    def file_size_display(self, obj):
        """Display file size in human-readable format."""
        size = obj.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    file_size_display.short_description = "File Size"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Admin for notifications."""
    
    list_display = [
        "title", "recipient", "notification_type", "priority",
        "is_read", "scheduled_for", "created_at"
    ]
    list_filter = [
        "notification_type", "priority", "is_read",
        "is_archived", "created_at"
    ]
    search_fields = ["title", "content", "recipient__username"]
    raw_id_fields = ["recipient"]
    readonly_fields = [
        "id", "delivery_status", "read_at",
        "created_at", "updated_at"
    ]
    
    fieldsets = [
        ("Basic Information", {
            "fields": [
                "id", "recipient", "notification_type",
                "title", "content", "priority"
            ]
        }),
        ("Related Object", {
            "fields": [
                "related_object_type", "related_object_id", "action_url"
            ]
        }),
        ("Status", {
            "fields": [
                "is_read", "read_at", "is_archived",
                "channels", "delivery_status"
            ]
        }),
        ("Scheduling", {
            "fields": ["scheduled_for", "expires_at"]
        }),
        ("Metadata", {
            "fields": ["metadata", "template_id"]
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"]
        }),
    ]
    
    actions = ["mark_as_read", "mark_as_unread", "archive_notifications"]
    
    def mark_as_read(self, request, queryset):
        """Mark notifications as read."""
        count = queryset.update(is_read=True, read_at=timezone.now())
        self.message_user(request, f"{count} notifications marked as read.")
    mark_as_read.short_description = "Mark selected as read"
    
    def mark_as_unread(self, request, queryset):
        """Mark notifications as unread."""
        count = queryset.update(is_read=False, read_at=None)
        self.message_user(request, f"{count} notifications marked as unread.")
    mark_as_unread.short_description = "Mark selected as unread"
    
    def archive_notifications(self, request, queryset):
        """Archive notifications."""
        count = queryset.update(is_archived=True)
        self.message_user(request, f"{count} notifications archived.")
    archive_notifications.short_description = "Archive selected"


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    """Admin for notification preferences."""
    
    list_display = [
        "user", "email_enabled", "sms_enabled",
        "push_enabled", "in_app_enabled", "quiet_hours_enabled"
    ]
    list_filter = [
        "email_enabled", "sms_enabled", "push_enabled",
        "in_app_enabled", "quiet_hours_enabled"
    ]
    search_fields = ["user__username", "user__email"]
    raw_id_fields = ["user"]


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    """Admin for notification templates."""
    
    list_display = [
        "name", "template_id", "category", "is_active", "created_at"
    ]
    list_filter = ["category", "is_active", "created_at"]
    search_fields = ["name", "template_id", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    
    fieldsets = [
        ("Basic Information", {
            "fields": [
                "id", "template_id", "name", "description",
                "category", "is_active"
            ]
        }),
        ("General Templates", {
            "fields": ["subject_template", "body_template", "html_template"]
        }),
        ("Channel-Specific Templates", {
            "fields": [
                "email_subject", "email_body",
                "sms_template", "push_template"
            ],
            "classes": ["collapse"]
        }),
        ("Variables", {
            "fields": ["required_variables"]
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"]
        }),
    ]


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    """Admin for meetings."""
    
    list_display = [
        "title", "organizer", "status", "scheduled_start",
        "participant_count", "enable_recording", "created_at"
    ]
    list_filter = ["status", "enable_recording", "is_recurring", "created_at"]
    search_fields = ["title", "description", "organizer__username"]
    raw_id_fields = ["organizer", "channel"]
    readonly_fields = [
        "id", "meeting_url", "meeting_id", "passcode",
        "actual_start", "actual_end", "recording_url",
        "recording_duration", "created_at", "updated_at"
    ]
    
    def participant_count(self, obj):
        """Get participant count."""
        return obj.meeting_participants.count()
    participant_count.short_description = "Participants"
    
    actions = ["cancel_meetings", "start_meetings"]
    
    def cancel_meetings(self, request, queryset):
        """Cancel selected meetings."""
        count = queryset.filter(
            status__in=["SCHEDULED", "IN_PROGRESS"]
        ).update(status="CANCELLED")
        self.message_user(request, f"{count} meetings cancelled.")
    cancel_meetings.short_description = "Cancel selected meetings"
    
    def start_meetings(self, request, queryset):
        """Start selected meetings."""
        count = 0
        for meeting in queryset.filter(status="SCHEDULED"):
            meeting.start_meeting()
            count += 1
        self.message_user(request, f"{count} meetings started.")
    start_meetings.short_description = "Start selected meetings"


@admin.register(VideoCall)
class VideoCallAdmin(admin.ModelAdmin):
    """Admin for video calls."""
    
    list_display = [
        "id", "call_type", "status", "initiator",
        "participant_count", "duration", "created_at"
    ]
    list_filter = ["call_type", "status", "recording_enabled", "created_at"]
    search_fields = ["room_id", "initiator__username"]
    raw_id_fields = ["channel", "initiator"]
    readonly_fields = [
        "id", "room_id", "started_at", "ended_at",
        "duration", "recording_url", "quality_metrics"
    ]
    
    def participant_count(self, obj):
        """Get participant count."""
        return obj.call_participants.count()
    participant_count.short_description = "Participants"


# Register inline admins
class MessageReactionInline(admin.TabularInline):
    """Inline admin for message reactions."""
    model = MessageReaction
    extra = 0
    raw_id_fields = ["user"]


class MessageAttachmentInline(admin.TabularInline):
    """Inline admin for message attachments."""
    model = MessageAttachment
    extra = 0
    readonly_fields = ["file_size", "mime_type"]


# Update MessageAdmin to include inlines
MessageAdmin.inlines = [MessageReactionInline, MessageAttachmentInline]


class MeetingParticipantInline(admin.TabularInline):
    """Inline admin for meeting participants."""
    model = MeetingParticipant
    extra = 0
    raw_id_fields = ["user"]
    readonly_fields = ["joined_at", "left_at", "duration"]


# Update MeetingAdmin to include inlines
MeetingAdmin.inlines = [MeetingParticipantInline]