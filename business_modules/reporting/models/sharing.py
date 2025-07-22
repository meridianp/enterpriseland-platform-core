"""Sharing models for the reporting module."""

import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

from core.models.base import BaseModel

User = get_user_model()


class SharePermission(models.TextChoices):
    """Permission levels for shared resources."""
    VIEW = 'view', 'View Only'
    COMMENT = 'comment', 'View and Comment'
    EDIT = 'edit', 'Edit'
    ADMIN = 'admin', 'Admin'


class ReportShare(BaseModel):
    """Share reports with users or via public links."""
    
    report = models.ForeignKey('Report', on_delete=models.CASCADE, related_name='shares')
    
    # Share type
    share_type = models.CharField(
        max_length=20,
        choices=[
            ('user', 'User'),
            ('group', 'Group'),
            ('link', 'Public Link'),
            ('email', 'Email'),
        ]
    )
    
    # Recipients
    shared_with_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_reports'
    )
    shared_with_group = models.ForeignKey(
        'accounts.UserGroup',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_reports'
    )
    shared_with_email = models.EmailField(blank=True)
    
    # Permissions
    permission = models.CharField(
        max_length=20,
        choices=SharePermission.choices,
        default=SharePermission.VIEW
    )
    
    # Share settings
    message = models.TextField(blank=True, help_text="Message to include with share")
    allow_export = models.BooleanField(default=False)
    allow_drill_down = models.BooleanField(default=True)
    require_authentication = models.BooleanField(default=True)
    
    # Link sharing
    share_token = models.UUIDField(default=uuid.uuid4, unique=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Access tracking
    access_count = models.IntegerField(default=0)
    last_accessed = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    shared_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_report_shares')
    
    class Meta:
        ordering = ['-created_at']
        unique_together = [
            ['report', 'shared_with_user'],
            ['report', 'shared_with_group'],
        ]
        
    def __str__(self):
        if self.shared_with_user:
            return f"{self.report.name} shared with {self.shared_with_user.username}"
        elif self.shared_with_group:
            return f"{self.report.name} shared with {self.shared_with_group.name}"
        elif self.shared_with_email:
            return f"{self.report.name} shared with {self.shared_with_email}"
        else:
            return f"{self.report.name} - Public Link"
    
    def is_expired(self):
        """Check if the share has expired."""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False
    
    def record_access(self):
        """Record access to the shared resource."""
        self.access_count += 1
        self.last_accessed = timezone.now()
        self.save(update_fields=['access_count', 'last_accessed'])


class DashboardShare(BaseModel):
    """Share dashboards with users or via public links."""
    
    dashboard = models.ForeignKey('Dashboard', on_delete=models.CASCADE, related_name='shares')
    
    # Share type
    share_type = models.CharField(
        max_length=20,
        choices=[
            ('user', 'User'),
            ('group', 'Group'),
            ('link', 'Public Link'),
            ('embed', 'Embed'),
            ('email', 'Email'),
        ]
    )
    
    # Recipients
    shared_with_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_dashboards'
    )
    shared_with_group = models.ForeignKey(
        'accounts.UserGroup',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='shared_dashboards'
    )
    shared_with_email = models.EmailField(blank=True)
    
    # Permissions
    permission = models.CharField(
        max_length=20,
        choices=SharePermission.choices,
        default=SharePermission.VIEW
    )
    
    # Share settings
    message = models.TextField(blank=True)
    allow_export = models.BooleanField(default=False)
    allow_full_screen = models.BooleanField(default=True)
    show_title = models.BooleanField(default=True)
    require_authentication = models.BooleanField(default=True)
    
    # Link/Embed settings
    share_token = models.UUIDField(default=uuid.uuid4, unique=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Embed configuration
    embed_width = models.CharField(max_length=20, default='100%')
    embed_height = models.CharField(max_length=20, default='600px')
    embed_theme = models.CharField(max_length=20, blank=True)
    
    # Access tracking
    access_count = models.IntegerField(default=0)
    last_accessed = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    shared_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_dashboard_shares')
    
    class Meta:
        ordering = ['-created_at']
        unique_together = [
            ['dashboard', 'shared_with_user'],
            ['dashboard', 'shared_with_group'],
        ]
        
    def __str__(self):
        if self.shared_with_user:
            return f"{self.dashboard.name} shared with {self.shared_with_user.username}"
        elif self.shared_with_group:
            return f"{self.dashboard.name} shared with {self.shared_with_group.name}"
        elif self.shared_with_email:
            return f"{self.dashboard.name} shared with {self.shared_with_email}"
        else:
            return f"{self.dashboard.name} - {self.get_share_type_display()}"
    
    def is_expired(self):
        """Check if the share has expired."""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False
    
    def record_access(self):
        """Record access to the shared resource."""
        self.access_count += 1
        self.last_accessed = timezone.now()
        self.save(update_fields=['access_count', 'last_accessed'])
    
    def get_embed_code(self):
        """Generate embed code for the dashboard."""
        if self.share_type != 'embed':
            return None
            
        base_url = "https://your-domain.com"  # This should come from settings
        embed_url = f"{base_url}/embed/dashboard/{self.share_token}/"
        
        return f'''<iframe 
    src="{embed_url}"
    width="{self.embed_width}"
    height="{self.embed_height}"
    frameborder="0"
    style="border: 1px solid #ddd; border-radius: 4px;"
    allowfullscreen>
</iframe>'''