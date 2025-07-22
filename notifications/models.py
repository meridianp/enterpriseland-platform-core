"""
Generic notification models for platform-wide notification management.
"""
import uuid
from typing import Optional, Dict, Any, List
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.utils import timezone
from platform_core.core.models import TimestampedModel


class NotificationQuerySet(models.QuerySet):
    """Custom QuerySet for Notification with specialized filtering."""
    
    def unread(self):
        """Get unread notifications."""
        return self.filter(is_read=False)
    
    def read(self):
        """Get read notifications."""
        return self.filter(is_read=True)
    
    def for_user(self, user):
        """Get notifications for a specific user."""
        return self.filter(recipient=user)
    
    def recent(self, days: int = 7):
        """Get recent notifications."""
        cutoff = timezone.now() - timezone.timedelta(days=days)
        return self.filter(created_at__gte=cutoff)
    
    def by_type(self, notification_type: str):
        """Filter by notification type."""
        return self.filter(type=notification_type)
    
    def mark_all_read(self):
        """Mark all notifications in queryset as read."""
        return self.update(is_read=True, read_at=timezone.now())


class NotificationManager(models.Manager):
    """Custom manager for Notification model."""
    
    def get_queryset(self):
        return NotificationQuerySet(self.model, using=self._db)
    
    def create_for_user(
        self,
        recipient,
        type: str,
        title: str,
        message: str,
        sender=None,
        related_object=None,
        metadata: Dict[str, Any] = None,
        priority: str = 'normal'
    ):
        """Create a notification for a user."""
        notification = self.create(
            recipient=recipient,
            sender=sender,
            type=type,
            title=title,
            message=message,
            priority=priority,
            metadata=metadata or {}
        )
        
        if related_object:
            notification.content_type = ContentType.objects.get_for_model(related_object)
            notification.object_id = related_object.pk
            notification.save()
        
        return notification
    
    def create_bulk(self, recipients: List, **kwargs):
        """Create notifications for multiple recipients."""
        notifications = []
        for recipient in recipients:
            notification = self.create_for_user(recipient=recipient, **kwargs)
            notifications.append(notification)
        return notifications


class Notification(TimestampedModel):
    """
    Generic notification model that can be associated with any content.
    """
    
    class Priority(models.TextChoices):
        """Notification priority levels."""
        LOW = 'low', 'Low'
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'
        URGENT = 'urgent', 'Urgent'
    
    # Primary fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Users
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        help_text="User who receives the notification"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_notifications',
        help_text="User who triggered the notification"
    )
    
    # Content
    type = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Type identifier for the notification"
    )
    title = models.CharField(
        max_length=255,
        help_text="Notification title"
    )
    message = models.TextField(
        help_text="Notification message content"
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL,
        help_text="Notification priority"
    )
    
    # Generic relation to any model
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.UUIDField(
        null=True,
        blank=True
    )
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Status
    is_read = models.BooleanField(
        default=False,
        help_text="Whether the notification has been read"
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the notification was read"
    )
    
    # Actions
    action_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="URL for the primary action"
    )
    action_label = models.CharField(
        max_length=100,
        blank=True,
        help_text="Label for the primary action button"
    )
    
    # Additional data
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata as JSON"
    )
    
    # Email tracking
    email_sent = models.BooleanField(
        default=False,
        help_text="Whether an email was sent for this notification"
    )
    email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the email was sent"
    )
    
    objects = NotificationManager()
    
    class Meta:
        db_table = 'platform_notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['type', '-created_at']),
            models.Index(fields=['content_type', 'object_id']),
        ]
    
    def __str__(self):
        return f"{self.title} for {self.recipient}"
    
    def mark_as_read(self):
        """Mark notification as read."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    def send_email(self, force: bool = False):
        """Send email notification."""
        if self.email_sent and not force:
            return False
        
        # Create email notification record
        EmailNotification.objects.create(
            notification=self,
            recipient_email=self.recipient.email,
            subject=self.title,
            body=self.message
        )
        
        self.email_sent = True
        self.email_sent_at = timezone.now()
        self.save(update_fields=['email_sent', 'email_sent_at'])
        
        return True


class EmailNotification(TimestampedModel):
    """Track email notifications sent."""
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
        BOUNCED = 'bounced', 'Bounced'
        OPENED = 'opened', 'Opened'
        CLICKED = 'clicked', 'Clicked'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Related notification
    notification = models.OneToOneField(
        Notification,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='email_notification'
    )
    
    # Email details
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()
    html_body = models.TextField(blank=True)
    
    # Template used
    template_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="ID of the email template used"
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    
    # Provider tracking
    provider = models.CharField(
        max_length=50,
        blank=True,
        help_text="Email provider used"
    )
    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Message ID from email provider"
    )
    
    # Engagement tracking
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    open_count = models.IntegerField(default=0)
    click_count = models.IntegerField(default=0)
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'platform_email_notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['recipient_email', '-created_at']),
        ]
    
    def __str__(self):
        return f"Email to {self.recipient_email}: {self.subject}"


class NotificationPreference(models.Model):
    """User notification preferences."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    
    # Global preferences
    email_enabled = models.BooleanField(
        default=True,
        help_text="Receive email notifications"
    )
    in_app_enabled = models.BooleanField(
        default=True,
        help_text="Receive in-app notifications"
    )
    
    # Type-specific preferences (JSON for flexibility)
    type_preferences = models.JSONField(
        default=dict,
        help_text="Preferences by notification type"
    )
    
    # Quiet hours
    quiet_hours_enabled = models.BooleanField(
        default=False,
        help_text="Enable quiet hours"
    )
    quiet_hours_start = models.TimeField(
        null=True,
        blank=True,
        help_text="Quiet hours start time"
    )
    quiet_hours_end = models.TimeField(
        null=True,
        blank=True,
        help_text="Quiet hours end time"
    )
    
    # Digest preferences
    digest_enabled = models.BooleanField(
        default=False,
        help_text="Receive digest emails"
    )
    digest_frequency = models.CharField(
        max_length=20,
        choices=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
        ],
        default='daily'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'platform_notification_preferences'
    
    def __str__(self):
        return f"Preferences for {self.user}"
    
    def should_send_email(self, notification_type: str) -> bool:
        """Check if email should be sent for a notification type."""
        if not self.email_enabled:
            return False
        
        type_pref = self.type_preferences.get(notification_type, {})
        return type_pref.get('email', True)
    
    def should_send_in_app(self, notification_type: str) -> bool:
        """Check if in-app notification should be created."""
        if not self.in_app_enabled:
            return False
        
        type_pref = self.type_preferences.get(notification_type, {})
        return type_pref.get('in_app', True)
    
    def is_in_quiet_hours(self) -> bool:
        """Check if current time is in quiet hours."""
        if not self.quiet_hours_enabled:
            return False
        
        now = timezone.now().time()
        
        if self.quiet_hours_start <= self.quiet_hours_end:
            # Normal case: quiet hours don't cross midnight
            return self.quiet_hours_start <= now <= self.quiet_hours_end
        else:
            # Quiet hours cross midnight
            return now >= self.quiet_hours_start or now <= self.quiet_hours_end


class NotificationTemplate(models.Model):
    """Templates for notification content."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Identification
    code = models.CharField(
        max_length=100,
        unique=True,
        help_text="Unique code for the template"
    )
    name = models.CharField(
        max_length=255,
        help_text="Human-readable name"
    )
    description = models.TextField(
        blank=True,
        help_text="Description of when this template is used"
    )
    
    # Content templates
    title_template = models.CharField(
        max_length=500,
        help_text="Title template with variables like {user_name}"
    )
    message_template = models.TextField(
        help_text="Message template with variables"
    )
    
    # Email templates
    email_subject_template = models.CharField(
        max_length=500,
        blank=True,
        help_text="Email subject template"
    )
    email_body_template = models.TextField(
        blank=True,
        help_text="Email body template (plain text)"
    )
    email_html_template = models.TextField(
        blank=True,
        help_text="Email body template (HTML)"
    )
    
    # Configuration
    notification_type = models.CharField(
        max_length=100,
        help_text="Associated notification type"
    )
    priority = models.CharField(
        max_length=20,
        choices=Notification.Priority.choices,
        default=Notification.Priority.NORMAL
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'platform_notification_templates'
        ordering = ['notification_type', 'code']
    
    def __str__(self):
        return f"{self.name} ({self.code})"
    
    def render(self, context: Dict[str, Any]) -> Dict[str, str]:
        """Render the template with context."""
        from django.template import Template, Context
        
        result = {}
        
        # Render each template field
        for field in ['title_template', 'message_template', 'email_subject_template',
                      'email_body_template', 'email_html_template']:
            template_str = getattr(self, field)
            if template_str:
                template = Template(template_str)
                rendered = template.render(Context(context))
                result[field.replace('_template', '')] = rendered
        
        return result