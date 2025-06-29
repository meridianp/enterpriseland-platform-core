
from django.db import models
import uuid

class Notification(models.Model):
    """In-app notifications for users"""
    
    class Type(models.TextChoices):
        ASSESSMENT_CREATED = 'assessment_created', 'Assessment Created'
        ASSESSMENT_UPDATED = 'assessment_updated', 'Assessment Updated'
        ASSESSMENT_APPROVED = 'assessment_approved', 'Assessment Approved'
        ASSESSMENT_REJECTED = 'assessment_rejected', 'Assessment Rejected'
        ASSESSMENT_NEEDS_INFO = 'assessment_needs_info', 'Assessment Needs Info'
        FILE_UPLOADED = 'file_uploaded', 'File Uploaded'
        COMMENT_ADDED = 'comment_added', 'Comment Added'
        SYSTEM_ALERT = 'system_alert', 'System Alert'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='sent_notifications', null=True, blank=True)
    
    type = models.CharField(max_length=30, choices=Type.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    
    # Related objects
    assessment = models.ForeignKey('assessments.Assessment', on_delete=models.CASCADE, null=True, blank=True)
    
    # Status
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.title} for {self.recipient.email}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            from django.utils import timezone
            self.is_read = True
            self.read_at = timezone.now()
            self.save()


class EmailNotification(models.Model):
    """Email notification tracking"""
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
        BOUNCED = 'bounced', 'Bounced'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()
    html_body = models.TextField(blank=True)
    
    # Related notification
    notification = models.OneToOneField(Notification, on_delete=models.CASCADE, null=True, blank=True)
    
    # Status tracking
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True, help_text="Message ID from email provider")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'email_notifications'
        
    def __str__(self):
        return f"Email to {self.recipient_email}: {self.subject}"


class WebhookEndpoint(models.Model):
    """Webhook endpoints for external integrations"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    url = models.URLField()
    secret_key = models.CharField(max_length=255, blank=True)
    
    # Event subscriptions
    events = models.JSONField(default=list, help_text="List of events to subscribe to")
    
    # Status
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'webhook_endpoints'
        
    def __str__(self):
        return f"{self.name} ({self.url})"


class WebhookDelivery(models.Model):
    """Webhook delivery tracking"""
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        RETRYING = 'retrying', 'Retrying'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name='deliveries')
    
    event_type = models.CharField(max_length=50)
    payload = models.JSONField()
    
    # Delivery tracking
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    response_status_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    
    # Retry tracking
    attempt_count = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'webhook_deliveries'
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.event_type} to {self.endpoint.name} ({self.status})"
