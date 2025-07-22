"""Communication module models."""

import uuid
from datetime import timedelta
from typing import Optional, List, Dict, Any

from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.validators import FileExtensionValidator, MaxLengthValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from platform_core.models import BaseModel, GroupFilteredModel
from .encryption import MessageEncryption

User = get_user_model()


class Channel(GroupFilteredModel):
    """Communication channel for group messaging."""
    
    class ChannelType(models.TextChoices):
        """Types of channels."""
        PUBLIC = "PUBLIC", _("Public Channel")
        PRIVATE = "PRIVATE", _("Private Channel")
        DIRECT = "DIRECT", _("Direct Message")
        ANNOUNCEMENT = "ANNOUNCEMENT", _("Announcement Channel")
        EXTERNAL = "EXTERNAL", _("External Channel")
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, db_index=True)
    slug = models.SlugField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(blank=True)
    channel_type = models.CharField(
        max_length=20,
        choices=ChannelType.choices,
        default=ChannelType.PUBLIC,
        db_index=True
    )
    
    # Channel settings
    is_archived = models.BooleanField(default=False, db_index=True)
    is_read_only = models.BooleanField(default=False)
    allow_guests = models.BooleanField(default=False)
    allow_threading = models.BooleanField(default=True)
    auto_join_new_members = models.BooleanField(default=False)
    
    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_channels"
    )
    avatar_url = models.URLField(blank=True)
    topic = models.CharField(max_length=250, blank=True)
    pinned_message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pinned_in_channels"
    )
    
    # Statistics
    member_count = models.PositiveIntegerField(default=0)
    message_count = models.PositiveIntegerField(default=0)
    last_activity = models.DateTimeField(null=True, blank=True, db_index=True)
    
    # Integration
    external_id = models.CharField(max_length=100, blank=True, db_index=True)
    webhook_url = models.URLField(blank=True)
    
    class Meta:
        ordering = ["-last_activity", "name"]
        indexes = [
            models.Index(fields=["channel_type", "is_archived"]),
            models.Index(fields=["group", "channel_type", "-last_activity"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "slug"],
                name="unique_channel_slug_per_group"
            ),
        ]
    
    def __str__(self):
        return self.name
    
    def add_member(self, user: User, role: str = "MEMBER") -> "ChannelMember":
        """Add a member to the channel."""
        member, created = ChannelMember.objects.get_or_create(
            channel=self,
            user=user,
            defaults={"role": role}
        )
        if created:
            self.member_count = self.members.count()
            self.save(update_fields=["member_count"])
        return member
    
    def remove_member(self, user: User) -> bool:
        """Remove a member from the channel."""
        deleted = ChannelMember.objects.filter(
            channel=self,
            user=user
        ).delete()[0]
        if deleted:
            self.member_count = self.members.count()
            self.save(update_fields=["member_count"])
        return bool(deleted)
    
    def is_member(self, user: User) -> bool:
        """Check if user is a member of the channel."""
        return self.members.filter(user=user).exists()
    
    def get_unread_count(self, user: User) -> int:
        """Get unread message count for a user."""
        try:
            member = self.members.get(user=user)
            return self.messages.filter(
                created_at__gt=member.last_read_at
            ).count()
        except ChannelMember.DoesNotExist:
            return 0


class ChannelMember(BaseModel):
    """Membership in a channel."""
    
    class MemberRole(models.TextChoices):
        """Roles within a channel."""
        OWNER = "OWNER", _("Owner")
        ADMIN = "ADMIN", _("Admin")
        MODERATOR = "MODERATOR", _("Moderator")
        MEMBER = "MEMBER", _("Member")
        GUEST = "GUEST", _("Guest")
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="members"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="channel_memberships"
    )
    role = models.CharField(
        max_length=20,
        choices=MemberRole.choices,
        default=MemberRole.MEMBER
    )
    
    # Membership settings
    is_muted = models.BooleanField(default=False)
    notification_level = models.CharField(
        max_length=20,
        choices=[
            ("ALL", "All Messages"),
            ("MENTIONS", "Mentions Only"),
            ("NONE", "No Notifications"),
        ],
        default="ALL"
    )
    
    # Activity tracking
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(default=timezone.now)
    last_typed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = [("channel", "user")]
        indexes = [
            models.Index(fields=["channel", "user"]),
            models.Index(fields=["user", "is_muted"]),
        ]
    
    def __str__(self):
        return f"{self.user} in {self.channel}"
    
    def mark_as_read(self):
        """Mark channel as read up to current time."""
        self.last_read_at = timezone.now()
        self.save(update_fields=["last_read_at"])


class Thread(GroupFilteredModel):
    """Message thread for organized discussions."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="threads"
    )
    parent_message = models.ForeignKey(
        "Message",
        on_delete=models.CASCADE,
        related_name="thread"
    )
    
    # Statistics
    reply_count = models.PositiveIntegerField(default=0)
    participant_count = models.PositiveIntegerField(default=0)
    last_reply_at = models.DateTimeField(null=True, blank=True)
    
    # Participants tracking
    participants = models.ManyToManyField(
        User,
        through="ThreadParticipant",
        related_name="threads"
    )
    
    class Meta:
        ordering = ["-last_reply_at"]
        indexes = [
            models.Index(fields=["channel", "-last_reply_at"]),
        ]
    
    def add_participant(self, user: User):
        """Add a participant to the thread."""
        ThreadParticipant.objects.get_or_create(
            thread=self,
            user=user
        )
        self.participant_count = self.participants.count()
        self.save(update_fields=["participant_count"])


class ThreadParticipant(BaseModel):
    """Participation in a thread."""
    
    thread = models.ForeignKey(
        Thread,
        on_delete=models.CASCADE,
        related_name="thread_participants"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="thread_participations"
    )
    last_read_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        unique_together = [("thread", "user")]


class Message(GroupFilteredModel):
    """A message in a channel or thread."""
    
    class MessageType(models.TextChoices):
        """Types of messages."""
        TEXT = "TEXT", _("Text Message")
        SYSTEM = "SYSTEM", _("System Message")
        FILE = "FILE", _("File Upload")
        IMAGE = "IMAGE", _("Image")
        VIDEO = "VIDEO", _("Video")
        AUDIO = "AUDIO", _("Audio")
        POLL = "POLL", _("Poll")
        ANNOUNCEMENT = "ANNOUNCEMENT", _("Announcement")
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="messages"
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_messages"
    )
    
    # Message content
    content = models.TextField(
        validators=[MaxLengthValidator(5000)],
        blank=True
    )
    content_encrypted = models.BooleanField(default=False)
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT
    )
    
    # Threading
    thread = models.ForeignKey(
        Thread,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies"
    )
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies_to_message"
    )
    
    # Rich content
    metadata = models.JSONField(default=dict, blank=True)
    mentions = ArrayField(
        models.CharField(max_length=150),
        default=list,
        blank=True
    )
    
    # Status
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    # Search
    search_vector = SearchVectorField(null=True)
    
    # Integration
    external_id = models.CharField(max_length=100, blank=True, db_index=True)
    
    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["channel", "created_at"]),
            models.Index(fields=["sender", "-created_at"]),
            models.Index(fields=["channel", "is_deleted", "-created_at"]),
            GinIndex(fields=["search_vector"]),
            GinIndex(fields=["mentions"]),
        ]
    
    def __str__(self):
        return f"Message from {self.sender} in {self.channel}"
    
    def save(self, *args, **kwargs):
        """Save the message with encryption if enabled."""
        # Encrypt content if required
        if self.content and self.channel.group.settings.get("encrypt_messages", False):
            self.content = MessageEncryption.encrypt(self.content)
            self.content_encrypted = True
        
        # Update edited timestamp
        if self.pk and self.content != self.__class__.objects.get(pk=self.pk).content:
            self.is_edited = True
            self.edited_at = timezone.now()
        
        super().save(*args, **kwargs)
        
        # Update channel activity
        self.channel.last_activity = timezone.now()
        self.channel.message_count = self.channel.messages.filter(
            is_deleted=False
        ).count()
        self.channel.save(update_fields=["last_activity", "message_count"])
    
    def get_content(self) -> str:
        """Get decrypted content if encrypted."""
        if self.content_encrypted:
            return MessageEncryption.decrypt(self.content)
        return self.content
    
    def soft_delete(self):
        """Soft delete the message."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])
    
    def add_reaction(self, user: User, emoji: str) -> "MessageReaction":
        """Add a reaction to the message."""
        reaction, created = MessageReaction.objects.get_or_create(
            message=self,
            user=user,
            emoji=emoji
        )
        return reaction


class MessageReaction(BaseModel):
    """Reaction to a message."""
    
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="reactions"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="message_reactions"
    )
    emoji = models.CharField(max_length=10)
    
    class Meta:
        unique_together = [("message", "user", "emoji")]
        indexes = [
            models.Index(fields=["message", "emoji"]),
        ]


class MessageAttachment(GroupFilteredModel):
    """File attachment for a message."""
    
    ALLOWED_EXTENSIONS = [
        'jpg', 'jpeg', 'png', 'gif', 'pdf', 'doc', 'docx',
        'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'mp4',
        'mp3', 'wav', 'zip', 'rar'
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="attachments"
    )
    
    # File information
    file = models.FileField(
        upload_to="communication/attachments/%Y/%m/%d/",
        validators=[FileExtensionValidator(allowed_extensions=ALLOWED_EXTENSIONS)]
    )
    filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()  # in bytes
    mime_type = models.CharField(max_length=100)
    
    # Metadata
    thumbnail_url = models.URLField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Security
    is_scanned = models.BooleanField(default=False)
    is_safe = models.BooleanField(default=True)
    scan_results = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["message", "created_at"]),
        ]
    
    def __str__(self):
        return f"Attachment: {self.filename}"


class Notification(GroupFilteredModel):
    """System notification for users."""
    
    class NotificationType(models.TextChoices):
        """Types of notifications."""
        MESSAGE = "MESSAGE", _("New Message")
        MENTION = "MENTION", _("Mentioned")
        CHANNEL_INVITE = "CHANNEL_INVITE", _("Channel Invitation")
        TASK_ASSIGNED = "TASK_ASSIGNED", _("Task Assigned")
        MEETING_REMINDER = "MEETING_REMINDER", _("Meeting Reminder")
        SYSTEM = "SYSTEM", _("System Notification")
        CUSTOM = "CUSTOM", _("Custom Notification")
    
    class NotificationPriority(models.TextChoices):
        """Priority levels for notifications."""
        LOW = "LOW", _("Low")
        MEDIUM = "MEDIUM", _("Medium")
        HIGH = "HIGH", _("High")
        URGENT = "URGENT", _("Urgent")
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications"
    )
    
    # Notification content
    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        db_index=True
    )
    title = models.CharField(max_length=200)
    content = models.TextField()
    priority = models.CharField(
        max_length=10,
        choices=NotificationPriority.choices,
        default=NotificationPriority.MEDIUM
    )
    
    # Related objects
    related_object_type = models.CharField(max_length=50, blank=True)
    related_object_id = models.CharField(max_length=100, blank=True)
    action_url = models.CharField(max_length=500, blank=True)
    
    # Status
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    
    # Delivery channels
    channels = ArrayField(
        models.CharField(max_length=20),
        default=list,
        help_text="Channels through which this notification was sent"
    )
    delivery_status = models.JSONField(default=dict)
    
    # Scheduling
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    template_id = models.CharField(max_length=100, blank=True)
    
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
            models.Index(fields=["recipient", "notification_type", "-created_at"]),
            models.Index(fields=["scheduled_for", "is_read"]),
            GinIndex(fields=["channels"]),
        ]
    
    def __str__(self):
        return f"{self.notification_type}: {self.title}"
    
    def mark_as_read(self):
        """Mark notification as read."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])
    
    def is_expired(self) -> bool:
        """Check if notification has expired."""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False


class NotificationPreference(GroupFilteredModel):
    """User preferences for notifications."""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="notification_preferences"
    )
    
    # Channel preferences
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    push_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)
    
    # Type preferences
    message_notifications = models.BooleanField(default=True)
    mention_notifications = models.BooleanField(default=True)
    task_notifications = models.BooleanField(default=True)
    meeting_notifications = models.BooleanField(default=True)
    system_notifications = models.BooleanField(default=True)
    
    # Scheduling preferences
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    timezone = models.CharField(max_length=50, default="UTC")
    
    # Batching preferences
    batch_email_notifications = models.BooleanField(default=True)
    batch_interval_minutes = models.PositiveIntegerField(default=30)
    
    # Advanced settings
    notification_sound = models.CharField(max_length=50, default="default")
    desktop_notifications = models.BooleanField(default=True)
    mobile_vibrate = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Notification Preference"
        verbose_name_plural = "Notification Preferences"
    
    def __str__(self):
        return f"Notification preferences for {self.user}"
    
    def should_send_notification(
        self,
        notification_type: str,
        channel: str,
        check_quiet_hours: bool = True
    ) -> bool:
        """Check if a notification should be sent based on preferences."""
        # Check channel preference
        channel_enabled = getattr(self, f"{channel}_enabled", False)
        if not channel_enabled:
            return False
        
        # Check type preference
        type_field = f"{notification_type}_notifications"
        if hasattr(self, type_field):
            if not getattr(self, type_field):
                return False
        
        # Check quiet hours
        if check_quiet_hours and self.quiet_hours_enabled:
            current_time = timezone.now().time()
            if self.quiet_hours_start <= current_time <= self.quiet_hours_end:
                return False
        
        return True


class NotificationTemplate(BaseModel):
    """Template for notifications."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Template content
    subject_template = models.CharField(max_length=500)
    body_template = models.TextField()
    html_template = models.TextField(blank=True)
    
    # Channel-specific templates
    email_subject = models.CharField(max_length=500, blank=True)
    email_body = models.TextField(blank=True)
    sms_template = models.CharField(max_length=500, blank=True)
    push_template = models.CharField(max_length=500, blank=True)
    
    # Variables
    required_variables = ArrayField(
        models.CharField(max_length=50),
        default=list,
        help_text="Required template variables"
    )
    
    # Settings
    is_active = models.BooleanField(default=True)
    category = models.CharField(max_length=50, db_index=True)
    
    class Meta:
        ordering = ["category", "name"]
        indexes = [
            models.Index(fields=["template_id", "is_active"]),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.template_id})"


class Meeting(GroupFilteredModel):
    """Scheduled meeting with video conferencing."""
    
    class MeetingStatus(models.TextChoices):
        """Meeting status options."""
        SCHEDULED = "SCHEDULED", _("Scheduled")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Scheduling
    scheduled_start = models.DateTimeField(db_index=True)
    scheduled_end = models.DateTimeField()
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    
    # Participants
    organizer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="organized_meetings"
    )
    participants = models.ManyToManyField(
        User,
        through="MeetingParticipant",
        related_name="meetings"
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meetings"
    )
    
    # Meeting details
    status = models.CharField(
        max_length=20,
        choices=MeetingStatus.choices,
        default=MeetingStatus.SCHEDULED
    )
    meeting_url = models.URLField(blank=True)
    meeting_id = models.CharField(max_length=100, blank=True)
    passcode = models.CharField(max_length=50, blank=True)
    
    # Settings
    is_recurring = models.BooleanField(default=False)
    recurrence_rule = models.CharField(max_length=500, blank=True)
    enable_recording = models.BooleanField(default=False)
    enable_waiting_room = models.BooleanField(default=True)
    max_participants = models.PositiveIntegerField(default=50)
    
    # Integration
    calendar_event_id = models.CharField(max_length=200, blank=True)
    video_provider = models.CharField(max_length=50, default="agora")
    
    # Recording
    recording_url = models.URLField(blank=True)
    recording_duration = models.DurationField(null=True, blank=True)
    
    class Meta:
        ordering = ["scheduled_start"]
        indexes = [
            models.Index(fields=["status", "scheduled_start"]),
            models.Index(fields=["organizer", "-scheduled_start"]),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.scheduled_start}"
    
    def start_meeting(self):
        """Start the meeting."""
        self.status = self.MeetingStatus.IN_PROGRESS
        self.actual_start = timezone.now()
        self.save(update_fields=["status", "actual_start"])
    
    def end_meeting(self):
        """End the meeting."""
        self.status = self.MeetingStatus.COMPLETED
        self.actual_end = timezone.now()
        self.save(update_fields=["status", "actual_end"])


class MeetingParticipant(BaseModel):
    """Participant in a meeting."""
    
    class ParticipantRole(models.TextChoices):
        """Roles in a meeting."""
        HOST = "HOST", _("Host")
        CO_HOST = "CO_HOST", _("Co-Host")
        PRESENTER = "PRESENTER", _("Presenter")
        PARTICIPANT = "PARTICIPANT", _("Participant")
    
    class ResponseStatus(models.TextChoices):
        """Meeting invitation response."""
        PENDING = "PENDING", _("Pending")
        ACCEPTED = "ACCEPTED", _("Accepted")
        DECLINED = "DECLINED", _("Declined")
        TENTATIVE = "TENTATIVE", _("Tentative")
    
    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="meeting_participants"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="meeting_participations"
    )
    
    # Participation details
    role = models.CharField(
        max_length=20,
        choices=ParticipantRole.choices,
        default=ParticipantRole.PARTICIPANT
    )
    response_status = models.CharField(
        max_length=20,
        choices=ResponseStatus.choices,
        default=ResponseStatus.PENDING
    )
    response_message = models.TextField(blank=True)
    
    # Attendance
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    
    class Meta:
        unique_together = [("meeting", "user")]
        indexes = [
            models.Index(fields=["meeting", "response_status"]),
        ]
    
    def __str__(self):
        return f"{self.user} in {self.meeting}"


class VideoCall(GroupFilteredModel):
    """Video/audio call session."""
    
    class CallType(models.TextChoices):
        """Types of calls."""
        VIDEO = "VIDEO", _("Video Call")
        AUDIO = "AUDIO", _("Audio Call")
        SCREEN_SHARE = "SCREEN_SHARE", _("Screen Share")
    
    class CallStatus(models.TextChoices):
        """Status of the call."""
        INITIATING = "INITIATING", _("Initiating")
        RINGING = "RINGING", _("Ringing")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")
        FAILED = "FAILED", _("Failed")
        MISSED = "MISSED", _("Missed")
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="video_calls"
    )
    
    # Call details
    call_type = models.CharField(
        max_length=20,
        choices=CallType.choices,
        default=CallType.VIDEO
    )
    status = models.CharField(
        max_length=20,
        choices=CallStatus.choices,
        default=CallStatus.INITIATING
    )
    
    # Participants
    initiator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="initiated_calls"
    )
    participants = models.ManyToManyField(
        User,
        through="CallParticipant",
        related_name="video_calls"
    )
    
    # Timing
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    
    # Technical details
    room_id = models.CharField(max_length=100, unique=True)
    recording_enabled = models.BooleanField(default=False)
    recording_url = models.URLField(blank=True)
    max_participants = models.PositiveIntegerField(default=10)
    
    # Quality metrics
    quality_metrics = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["channel", "-created_at"]),
        ]
    
    def __str__(self):
        return f"{self.call_type} call - {self.created_at}"
    
    def start_call(self):
        """Start the call."""
        self.status = self.CallStatus.IN_PROGRESS
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])
    
    def end_call(self):
        """End the call."""
        self.status = self.CallStatus.COMPLETED
        self.ended_at = timezone.now()
        if self.started_at:
            self.duration = self.ended_at - self.started_at
        self.save(update_fields=["status", "ended_at", "duration"])


class CallParticipant(BaseModel):
    """Participant in a video/audio call."""
    
    call = models.ForeignKey(
        VideoCall,
        on_delete=models.CASCADE,
        related_name="call_participants"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="call_participations"
    )
    
    # Participation details
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    
    # Call settings
    is_muted = models.BooleanField(default=False)
    is_video_enabled = models.BooleanField(default=True)
    is_screen_sharing = models.BooleanField(default=False)
    
    # Quality
    connection_quality = models.CharField(
        max_length=20,
        choices=[
            ("EXCELLENT", "Excellent"),
            ("GOOD", "Good"),
            ("FAIR", "Fair"),
            ("POOR", "Poor"),
        ],
        default="GOOD"
    )
    
    class Meta:
        unique_together = [("call", "user")]
    
    def leave_call(self):
        """Mark participant as left the call."""
        self.left_at = timezone.now()
        self.duration = self.left_at - self.joined_at
        self.save(update_fields=["left_at", "duration"])