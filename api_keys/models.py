"""
API Key models for secure authentication and authorization.

Provides comprehensive API key management with:
- Multiple keys per user/application
- Scoped permissions and rate limiting
- Secure key generation and storage
- Usage tracking and analytics
- Key rotation support
"""

import hashlib
import secrets
import string
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.contrib.postgres.fields import ArrayField

from accounts.models import Group
# Import AuditLog directly from core.models to avoid circular import
from core.models import AuditLog

User = get_user_model()


class APIKeyQuerySet(models.QuerySet):
    """Custom QuerySet for APIKey with specialized filtering."""
    
    def active(self) -> 'APIKeyQuerySet':
        """Filter for active, non-expired keys."""
        now = timezone.now()
        return self.filter(
            is_active=True,
            expires_at__gt=now
        )
    
    def for_user(self, user: User) -> 'APIKeyQuerySet':
        """Filter keys for a specific user."""
        return self.filter(user=user)
    
    def for_application(self, app_name: str) -> 'APIKeyQuerySet':
        """Filter keys for a specific application."""
        return self.filter(application_name=app_name)
    
    def expiring_soon(self, days: int = 7) -> 'APIKeyQuerySet':
        """Filter keys expiring within specified days."""
        future_date = timezone.now() + timedelta(days=days)
        return self.filter(
            expires_at__lte=future_date,
            expires_at__gt=timezone.now(),
            is_active=True
        )
    
    def with_scope(self, scope: str) -> 'APIKeyQuerySet':
        """Filter keys that have a specific scope."""
        return self.filter(scopes__contains=[scope])
    
    def recently_used(self, hours: int = 24) -> 'APIKeyQuerySet':
        """Filter keys used within specified hours."""
        cutoff_time = timezone.now() - timedelta(hours=hours)
        return self.filter(last_used_at__gte=cutoff_time)


class APIKeyManager(models.Manager):
    """Custom manager for APIKey with business logic."""
    
    def get_queryset(self) -> APIKeyQuerySet:
        """Return custom queryset."""
        return APIKeyQuerySet(self.model, using=self._db)
    
    def active(self) -> APIKeyQuerySet:
        """Get active API keys."""
        return self.get_queryset().active()
    
    def create_key(
        self,
        user: Optional[User] = None,
        name: str = "",
        scopes: List[str] = None,
        expires_in_days: int = 365,
        rate_limit: int = 1000,
        application_name: str = "",
        allowed_ips: List[str] = None,
        group: Optional[Group] = None,
        metadata: Dict[str, Any] = None
    ) -> Tuple['APIKey', str]:
        """
        Create a new API key with secure generation.
        
        Returns:
            Tuple of (APIKey instance, raw key string)
        """
        # Generate secure key
        raw_key = self._generate_key()
        key_hash = self._hash_key(raw_key)
        
        # Determine prefix based on type
        prefix = "sk_live_" if not application_name else "ak_live_"
        display_key = f"{prefix}{raw_key}"
        
        # Set expiration
        expires_at = timezone.now() + timedelta(days=expires_in_days)
        
        # Create key instance
        api_key = self.create(
            user=user,
            name=name or f"API Key created on {timezone.now().date()}",
            key_hash=key_hash,
            key_prefix=raw_key[:8],  # Store prefix for identification
            scopes=scopes or ['read'],
            expires_at=expires_at,
            rate_limit_per_hour=rate_limit,
            application_name=application_name,
            allowed_ips=allowed_ips or [],
            group=group,
            metadata=metadata or {}
        )
        
        # Log creation
        AuditLog.objects.create_log(
            action=AuditLog.Action.CREATE,
            user=user,
            content_object=api_key,
            changes={'action': 'api_key_created', 'name': api_key.name},
            metadata={'key_type': 'application' if application_name else 'user'}
        )
        
        return api_key, display_key
    
    def _generate_key(self, length: int = 32) -> str:
        """Generate a cryptographically secure API key."""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def _hash_key(self, raw_key: str) -> str:
        """Hash the API key using SHA-256."""
        return hashlib.sha256(raw_key.encode()).hexdigest()
    
    def verify_key(self, raw_key: str) -> Optional['APIKey']:
        """
        Verify an API key and return the instance if valid.
        
        Args:
            raw_key: The raw API key string (with or without prefix)
            
        Returns:
            APIKey instance if valid, None otherwise
        """
        # Remove prefix if present
        for prefix in ['sk_live_', 'ak_live_', 'sk_test_', 'ak_test_']:
            if raw_key.startswith(prefix):
                raw_key = raw_key[len(prefix):]
                break
        
        # Hash the key
        key_hash = self._hash_key(raw_key)
        
        # Look up the key
        try:
            api_key = self.get(
                key_hash=key_hash,
                is_active=True,
                expires_at__gt=timezone.now()
            )
            
            # Update last used timestamp
            api_key.last_used_at = timezone.now()
            api_key.usage_count += 1
            api_key.save(update_fields=['last_used_at', 'usage_count'])
            
            return api_key
            
        except self.model.DoesNotExist:
            return None


class APIKey(models.Model):
    """
    API Key for authentication and authorization.
    
    Features:
    - Secure key generation and hashed storage
    - Scoped permissions
    - Rate limiting
    - IP restrictions
    - Usage tracking
    - Automatic expiration
    """
    
    class Scope(models.TextChoices):
        """Available API scopes."""
        READ = 'read', 'Read Access'
        WRITE = 'write', 'Write Access'
        DELETE = 'delete', 'Delete Access'
        ADMIN = 'admin', 'Admin Access'
        
        # Platform resource scopes
        FILES_READ = 'files:read', 'Read Files'
        FILES_WRITE = 'files:write', 'Write Files'
        FILES_DELETE = 'files:delete', 'Delete Files'
        
        # Module-specific scopes will be registered dynamically
        # Legacy investment module scopes (deprecated - modules should register these)
        ASSESSMENTS_READ = 'assessments:read', 'Read Assessments'
        ASSESSMENTS_WRITE = 'assessments:write', 'Write Assessments'
        LEADS_READ = 'leads:read', 'Read Leads'
        LEADS_WRITE = 'leads:write', 'Write Leads'
        MARKET_INTEL_READ = 'market_intel:read', 'Read Market Intelligence'
        MARKET_INTEL_WRITE = 'market_intel:write', 'Write Market Intelligence'
        DEALS_READ = 'deals:read', 'Read Deals'
        DEALS_WRITE = 'deals:write', 'Write Deals'
        CONTACTS_READ = 'contacts:read', 'Read Contacts'
        CONTACTS_WRITE = 'contacts:write', 'Write Contacts'
    
    # Primary fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Key identification
    name = models.CharField(
        max_length=255,
        help_text="Descriptive name for the API key"
    )
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 hash of the API key"
    )
    key_prefix = models.CharField(
        max_length=8,
        help_text="First 8 characters for identification"
    )
    
    # Ownership
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='api_keys',
        help_text="User who owns this key"
    )
    application_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Application using this key (for app-level keys)"
    )
    
    # Permissions
    scopes = ArrayField(
        models.CharField(max_length=50, choices=Scope.choices),
        default=list,
        help_text="List of permitted scopes"
    )
    
    # Security
    expires_at = models.DateTimeField(
        help_text="When this key expires"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this key is currently active"
    )
    allowed_ips = ArrayField(
        models.GenericIPAddressField(),
        default=list,
        blank=True,
        help_text="List of allowed IP addresses (empty = all allowed)"
    )
    
    # Rate limiting
    rate_limit_per_hour = models.IntegerField(
        default=1000,
        validators=[MinValueValidator(0)],
        help_text="Maximum requests per hour"
    )
    
    # Usage tracking
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this key was used"
    )
    usage_count = models.BigIntegerField(
        default=0,
        help_text="Total number of times used"
    )
    
    # Multi-tenancy
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='api_keys',
        help_text="Group this key belongs to"
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata"
    )
    
    # Rotation support
    replaced_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replaces',
        help_text="New key that replaces this one"
    )
    rotation_reminder_sent = models.BooleanField(
        default=False,
        help_text="Whether rotation reminder was sent"
    )
    
    objects = APIKeyManager()
    
    class Meta:
        db_table = 'api_keys'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['key_hash', 'is_active']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['expires_at', 'is_active']),
            models.Index(fields=['application_name', 'is_active']),
            models.Index(fields=['group', 'is_active']),
            models.Index(fields=['last_used_at']),
        ]
        verbose_name = 'API Key'
        verbose_name_plural = 'API Keys'
    
    def __str__(self) -> str:
        owner = self.user.email if self.user else self.application_name
        return f"{self.name} ({self.key_prefix}...) - {owner}"
    
    def clean(self) -> None:
        """Validate the model."""
        super().clean()
        
        # Ensure either user or application is set
        if not self.user and not self.application_name:
            raise ValidationError("Either user or application_name must be set")
        
        # Validate scopes
        if not self.scopes:
            raise ValidationError("At least one scope must be assigned")
    
    @property
    def is_expired(self) -> bool:
        """Check if the key has expired."""
        return timezone.now() > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        """Check if the key is valid for use."""
        return self.is_active and not self.is_expired
    
    @property
    def days_until_expiry(self) -> int:
        """Get days until expiration."""
        if self.is_expired:
            return 0
        delta = self.expires_at - timezone.now()
        return delta.days
    
    @property
    def key_type(self) -> str:
        """Get the type of key (user or application)."""
        return 'application' if self.application_name else 'user'
    
    def has_scope(self, scope: str) -> bool:
        """Check if the key has a specific scope."""
        return scope in self.scopes or 'admin' in self.scopes
    
    def has_any_scope(self, scopes: List[str]) -> bool:
        """Check if the key has any of the specified scopes."""
        return any(self.has_scope(scope) for scope in scopes)
    
    def check_rate_limit(self, window_minutes: int = 60) -> Tuple[bool, int]:
        """
        Check if the key has exceeded its rate limit.
        
        Returns:
            Tuple of (is_within_limit, requests_in_window)
        """
        # This is a simplified check - in production, use Redis
        window_start = timezone.now() - timedelta(minutes=window_minutes)
        requests = APIKeyUsage.objects.filter(
            api_key=self,
            timestamp__gte=window_start
        ).count()
        
        limit = self.rate_limit_per_hour * (window_minutes / 60)
        return requests < limit, requests
    
    def revoke(self, user: Optional[User] = None, reason: str = "") -> None:
        """Revoke this API key."""
        self.is_active = False
        self.save(update_fields=['is_active'])
        
        # Log revocation
        AuditLog.objects.create_log(
            action=AuditLog.Action.UPDATE,
            user=user,
            content_object=self,
            changes={'is_active': {'old': True, 'new': False}},
            metadata={'reason': reason}
        )
    
    def rotate(self, user: Optional[User] = None) -> Tuple['APIKey', str]:
        """
        Rotate this API key by creating a new one and marking this as replaced.
        
        Returns:
            Tuple of (new APIKey instance, raw key string)
        """
        # Create new key with same settings
        new_key, raw_key = APIKey.objects.create_key(
            user=self.user,
            name=f"{self.name} (Rotated)",
            scopes=self.scopes,
            expires_in_days=self.days_until_expiry or 365,
            rate_limit=self.rate_limit_per_hour,
            application_name=self.application_name,
            allowed_ips=self.allowed_ips,
            group=self.group,
            metadata={**self.metadata, 'rotated_from': str(self.id)}
        )
        
        # Mark this key as replaced
        self.replaced_by = new_key
        self.save(update_fields=['replaced_by'])
        
        # Log rotation
        AuditLog.objects.create_log(
            action=AuditLog.Action.UPDATE,
            user=user,
            content_object=self,
            changes={'action': 'key_rotated', 'new_key_id': str(new_key.id)},
            metadata={'rotation_reason': 'manual_rotation'}
        )
        
        return new_key, raw_key


class APIKeyUsage(models.Model):
    """
    Track API key usage for analytics and rate limiting.
    
    Records each use of an API key with request details.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Key reference
    api_key = models.ForeignKey(
        APIKey,
        on_delete=models.CASCADE,
        related_name='usage_logs'
    )
    
    # Request details
    endpoint = models.CharField(
        max_length=255,
        help_text="API endpoint accessed"
    )
    method = models.CharField(
        max_length=10,
        help_text="HTTP method used"
    )
    status_code = models.IntegerField(
        help_text="Response status code"
    )
    
    # Request metadata
    ip_address = models.GenericIPAddressField(
        help_text="IP address of the request"
    )
    user_agent = models.TextField(
        blank=True,
        help_text="User agent string"
    )
    
    # Performance
    response_time_ms = models.IntegerField(
        help_text="Response time in milliseconds"
    )
    
    # Additional context
    error_message = models.TextField(
        blank=True,
        help_text="Error message if request failed"
    )
    
    class Meta:
        db_table = 'api_key_usage'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['api_key', 'timestamp']),
            models.Index(fields=['timestamp', 'status_code']),
            models.Index(fields=['endpoint', 'timestamp']),
        ]
        verbose_name = 'API Key Usage'
        verbose_name_plural = 'API Key Usage Logs'
    
    def __str__(self) -> str:
        return f"{self.api_key.key_prefix}... - {self.method} {self.endpoint} at {self.timestamp}"
