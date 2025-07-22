"""
Security-related models for authentication
"""
import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


class UserDevice(models.Model):
    """Track user devices for security monitoring"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='devices')
    device_id = models.CharField(max_length=64, db_index=True)
    device_name = models.CharField(max_length=255, blank=True)
    device_type = models.CharField(max_length=50, blank=True)  # mobile, desktop, tablet
    
    # Device metadata
    user_agent = models.TextField()
    ip_address = models.GenericIPAddressField()
    country = models.CharField(max_length=2, blank=True)
    city = models.CharField(max_length=100, blank=True)
    
    # Security tracking
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    last_activity = models.DateTimeField(auto_now=True)
    login_count = models.PositiveIntegerField(default=0)
    
    # Trust status
    is_trusted = models.BooleanField(default=False)
    trusted_at = models.DateTimeField(null=True, blank=True)
    trusted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='trusted_devices')
    
    # Blocking
    is_blocked = models.BooleanField(default=False)
    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_reason = models.TextField(blank=True)
    
    class Meta:
        unique_together = [('user', 'device_id')]
        ordering = ['-last_seen']
        indexes = [
            models.Index(fields=['user', '-last_seen']),
            models.Index(fields=['device_id']),
        ]
    
    def __str__(self):
        return f"{self.user.email} - {self.device_name or self.device_id[:8]}"
    
    def mark_trusted(self, by_user=None):
        """Mark device as trusted"""
        self.is_trusted = True
        self.trusted_at = timezone.now()
        self.trusted_by = by_user
        self.save(update_fields=['is_trusted', 'trusted_at', 'trusted_by'])
    
    def block(self, reason=''):
        """Block device"""
        self.is_blocked = True
        self.blocked_at = timezone.now()
        self.blocked_reason = reason
        self.save(update_fields=['is_blocked', 'blocked_at', 'blocked_reason'])


class LoginAttempt(models.Model):
    """Track login attempts for security monitoring"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    email = models.EmailField(db_index=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    
    # Attempt details
    success = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=100, blank=True)
    
    # User if successful
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='login_attempts')
    
    # Device tracking
    device_id = models.CharField(max_length=64, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', '-created_at']),
            models.Index(fields=['ip_address', '-created_at']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.email} - {'Success' if self.success else 'Failed'} - {self.created_at}"


class MFAMethod(models.Model):
    """Multi-factor authentication methods for users"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Method(models.TextChoices):
        TOTP = 'totp', 'Time-based OTP'
        SMS = 'sms', 'SMS'
        EMAIL = 'email', 'Email'
        BACKUP_CODES = 'backup_codes', 'Backup Codes'
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mfa_methods')
    method = models.CharField(max_length=20, choices=Method.choices)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    # Method-specific data (encrypted in practice)
    secret = models.CharField(max_length=255, blank=True)  # For TOTP
    phone_number = models.CharField(max_length=20, blank=True)  # For SMS
    email = models.EmailField(blank=True)  # For email (if different from account email)
    
    # Verification
    verified_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = [('user', 'method', 'phone_number'), ('user', 'method', 'email')]
        ordering = ['-is_primary', '-created_at']
    
    def __str__(self):
        return f"{self.user.email} - {self.get_method_display()}"


class MFABackupCode(models.Model):
    """Backup codes for MFA recovery"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mfa_backup_codes')
    code = models.CharField(max_length=12, unique=True)
    used_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.user.email} - {'Used' if self.used_at else 'Available'}"
    
    def use(self):
        """Mark backup code as used"""
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])


class SecurityEvent(models.Model):
    """Log security-related events"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class EventType(models.TextChoices):
        LOGIN_SUCCESS = 'login_success', 'Login Success'
        LOGIN_FAILED = 'login_failed', 'Login Failed'
        LOGOUT = 'logout', 'Logout'
        PASSWORD_CHANGED = 'password_changed', 'Password Changed'
        PASSWORD_RESET = 'password_reset', 'Password Reset'
        MFA_ENABLED = 'mfa_enabled', 'MFA Enabled'
        MFA_DISABLED = 'mfa_disabled', 'MFA Disabled'
        MFA_FAILED = 'mfa_failed', 'MFA Failed'
        SUSPICIOUS_ACTIVITY = 'suspicious', 'Suspicious Activity'
        DEVICE_TRUSTED = 'device_trusted', 'Device Trusted'
        DEVICE_BLOCKED = 'device_blocked', 'Device Blocked'
        TOKEN_REVOKED = 'token_revoked', 'Token Revoked'
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='security_events')
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    
    # Event details
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    device_id = models.CharField(max_length=64, blank=True)
    
    # Additional metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['event_type', '-created_at']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.email} - {self.get_event_type_display()} - {self.created_at}"