"""
Authentication Models

Enhanced authentication models for JWT and OAuth2.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from platform_core.core.models import BaseModel, TenantFilteredModel


User = get_user_model()


class BlacklistedToken(BaseModel):
    """
    Stores blacklisted JWT tokens to prevent reuse after logout.
    """
    
    token = models.CharField(
        max_length=500,
        unique=True,
        help_text=_("The JWT token string")
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='blacklisted_tokens',
        null=True,
        blank=True
    )
    blacklisted_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_("When the token was blacklisted")
    )
    expires_at = models.DateTimeField(
        help_text=_("When the token naturally expires")
    )
    reason = models.CharField(
        max_length=100,
        choices=[
            ('logout', _('User Logout')),
            ('revoked', _('Manually Revoked')),
            ('security', _('Security Concern')),
            ('password_change', _('Password Changed')),
            ('user_deactivated', _('User Deactivated')),
        ],
        default='logout'
    )
    
    class Meta:
        db_table = 'security_blacklisted_tokens'
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"Blacklisted token for {self.user} - {self.reason}"
    
    @classmethod
    def cleanup_expired(cls):
        """Remove blacklisted tokens that have naturally expired"""
        return cls.objects.filter(expires_at__lt=timezone.now()).delete()


class RefreshTokenRotation(TenantFilteredModel):
    """
    Tracks refresh token rotation for enhanced security.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='refresh_tokens'
    )
    token_family = models.UUIDField(
        help_text=_("Groups related refresh tokens")
    )
    jti = models.CharField(
        max_length=255,
        unique=True,
        help_text=_("JWT ID of the refresh token")
    )
    issued_at = models.DateTimeField(
        auto_now_add=True
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When this token was used to get a new token")
    )
    replaced_by = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='replaces'
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )
    user_agent = models.TextField(
        blank=True
    )
    
    class Meta:
        db_table = 'security_refresh_token_rotation'
        indexes = [
            models.Index(fields=['jti']),
            models.Index(fields=['token_family']),
            models.Index(fields=['user', 'expires_at']),
        ]
    
    def __str__(self):
        return f"Refresh token for {self.user} - Family: {self.token_family}"
    
    def is_valid(self):
        """Check if token is still valid"""
        return (
            not self.used_at and
            self.expires_at > timezone.now()
        )
    
    def rotate(self, new_jti, ip_address=None, user_agent=None):
        """Rotate this token to a new one"""
        self.used_at = timezone.now()
        self.save()
        
        new_token = RefreshTokenRotation.objects.create(
            user=self.user,
            group=self.group,
            token_family=self.token_family,
            jti=new_jti,
            expires_at=self.expires_at,  # Keep same expiry
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        self.replaced_by = new_token
        self.save()
        
        return new_token


class AuthSession(TenantFilteredModel):
    """
    Enhanced session tracking for security monitoring.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='auth_sessions'
    )
    session_key = models.CharField(
        max_length=255,
        unique=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )
    last_activity = models.DateTimeField(
        auto_now=True
    )
    expires_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    device_info = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Parsed device information")
    )
    location_info = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Geolocation information")
    )
    is_active = models.BooleanField(
        default=True
    )
    terminated_at = models.DateTimeField(
        null=True,
        blank=True
    )
    termination_reason = models.CharField(
        max_length=100,
        blank=True,
        choices=[
            ('logout', _('User Logout')),
            ('timeout', _('Session Timeout')),
            ('security', _('Security Termination')),
            ('concurrent', _('Concurrent Session Limit')),
            ('admin', _('Admin Termination')),
        ]
    )
    
    class Meta:
        db_table = 'security_auth_sessions'
        indexes = [
            models.Index(fields=['session_key']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"Session for {self.user} from {self.ip_address}"
    
    def terminate(self, reason='logout'):
        """Terminate this session"""
        self.is_active = False
        self.terminated_at = timezone.now()
        self.termination_reason = reason
        self.save()
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])
    
    @classmethod
    def cleanup_expired(cls):
        """Clean up expired sessions"""
        return cls.objects.filter(
            expires_at__lt=timezone.now(),
            is_active=True
        ).update(
            is_active=False,
            termination_reason='timeout'
        )


class MFADevice(TenantFilteredModel):
    """
    Multi-factor authentication devices.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='mfa_devices'
    )
    name = models.CharField(
        max_length=100,
        help_text=_("User-friendly device name")
    )
    device_type = models.CharField(
        max_length=20,
        choices=[
            ('totp', _('Time-based OTP')),
            ('sms', _('SMS')),
            ('email', _('Email')),
            ('webauthn', _('WebAuthn/FIDO2')),
            ('backup', _('Backup Codes')),
        ]
    )
    is_primary = models.BooleanField(
        default=False,
        help_text=_("Primary device for MFA")
    )
    is_active = models.BooleanField(
        default=True
    )
    secret_key = models.CharField(
        max_length=255,
        help_text=_("Encrypted secret key")
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text=_("For SMS devices")
    )
    email = models.EmailField(
        blank=True,
        help_text=_("For email devices")
    )
    backup_codes = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Encrypted backup codes")
    )
    last_used = models.DateTimeField(
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )
    
    class Meta:
        db_table = 'security_mfa_devices'
        unique_together = [['user', 'name']]
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.device_type} - {self.name} for {self.user}"
    
    def mark_used(self):
        """Mark device as used"""
        self.last_used = timezone.now()
        self.save(update_fields=['last_used'])
    
    def generate_backup_codes(self, count=10):
        """Generate new backup codes"""
        import secrets
        codes = [secrets.token_hex(4) for _ in range(count)]
        # In production, encrypt these codes
        self.backup_codes = codes
        self.save()
        return codes


class OAuth2Client(TenantFilteredModel):
    """
    OAuth2 client applications.
    """
    
    client_id = models.CharField(
        max_length=100,
        unique=True
    )
    client_secret = models.CharField(
        max_length=255,
        help_text=_("Encrypted client secret")
    )
    name = models.CharField(
        max_length=200
    )
    description = models.TextField(
        blank=True
    )
    client_type = models.CharField(
        max_length=20,
        choices=[
            ('confidential', _('Confidential')),
            ('public', _('Public')),
        ],
        default='confidential'
    )
    redirect_uris = models.JSONField(
        default=list,
        help_text=_("Allowed redirect URIs")
    )
    allowed_scopes = models.JSONField(
        default=list,
        help_text=_("Allowed OAuth2 scopes")
    )
    is_active = models.BooleanField(
        default=True
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_oauth_clients'
    )
    
    class Meta:
        db_table = 'security_oauth2_clients'
        indexes = [
            models.Index(fields=['client_id']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.client_id})"
    
    def is_redirect_uri_allowed(self, uri):
        """Check if redirect URI is allowed"""
        return uri in self.redirect_uris
    
    def has_scope(self, scope):
        """Check if scope is allowed"""
        return scope in self.allowed_scopes