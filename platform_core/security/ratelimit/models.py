"""
Rate Limiting Models

Models for tracking rate limit violations and configurations.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from platform_core.core.models import BaseModel, TenantFilteredModel


User = get_user_model()


class RateLimitRule(TenantFilteredModel):
    """
    Configurable rate limit rules per endpoint or user group.
    """
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Rule identifier")
    )
    description = models.TextField(
        blank=True
    )
    endpoint_pattern = models.CharField(
        max_length=200,
        help_text=_("Regex pattern for matching endpoints"),
        blank=True
    )
    user_group = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Apply to specific user group/role")
    )
    rate_limit = models.IntegerField(
        help_text=_("Number of requests allowed")
    )
    per_seconds = models.IntegerField(
        help_text=_("Time window in seconds")
    )
    burst_limit = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Allow temporary burst above rate limit")
    )
    is_active = models.BooleanField(
        default=True
    )
    priority = models.IntegerField(
        default=0,
        help_text=_("Higher priority rules are checked first")
    )
    
    # Rate limit strategy
    strategy = models.CharField(
        max_length=20,
        choices=[
            ('user', _('Per User')),
            ('ip', _('Per IP')),
            ('user_ip', _('Per User+IP')),
            ('global', _('Global')),
        ],
        default='user'
    )
    
    # Actions when limit exceeded
    action = models.CharField(
        max_length=20,
        choices=[
            ('throttle', _('Throttle (429)')),
            ('block', _('Block (403)')),
            ('captcha', _('Require CAPTCHA')),
            ('log_only', _('Log Only')),
        ],
        default='throttle'
    )
    
    class Meta:
        db_table = 'security_rate_limit_rules'
        ordering = ['-priority', 'name']
        indexes = [
            models.Index(fields=['is_active', 'priority']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.rate_limit}/{self.per_seconds}s)"
    
    def get_cache_key(self, identifier):
        """Get cache key for this rule"""
        return f"ratelimit:{self.name}:{identifier}"
    
    def get_limit_string(self):
        """Get limit as string format"""
        return f"{self.rate_limit}/{self.per_seconds}s"


class RateLimitViolation(BaseModel):
    """
    Log of rate limit violations for monitoring and analysis.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rate_limit_violations'
    )
    ip_address = models.GenericIPAddressField()
    endpoint = models.CharField(
        max_length=200
    )
    method = models.CharField(
        max_length=10
    )
    rule = models.ForeignKey(
        RateLimitRule,
        on_delete=models.SET_NULL,
        null=True,
        related_name='violations'
    )
    timestamp = models.DateTimeField(
        auto_now_add=True
    )
    user_agent = models.TextField(
        blank=True
    )
    request_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Sanitized request data")
    )
    
    # Violation details
    limit_exceeded = models.IntegerField(
        help_text=_("The limit that was exceeded")
    )
    request_count = models.IntegerField(
        help_text=_("Number of requests made")
    )
    window_seconds = models.IntegerField(
        help_text=_("Time window for the limit")
    )
    
    # Response
    action_taken = models.CharField(
        max_length=20,
        choices=[
            ('throttled', _('Throttled')),
            ('blocked', _('Blocked')),
            ('captcha', _('CAPTCHA Required')),
            ('logged', _('Logged Only')),
        ]
    )
    
    class Meta:
        db_table = 'security_rate_limit_violations'
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['ip_address', 'timestamp']),
        ]
    
    def __str__(self):
        identifier = self.user.username if self.user else self.ip_address
        return f"Rate limit violation: {identifier} on {self.endpoint}"


class IPWhitelist(BaseModel):
    """
    IP addresses exempt from rate limiting.
    """
    
    ip_address = models.GenericIPAddressField(
        unique=True
    )
    description = models.CharField(
        max_length=200,
        help_text=_("Why this IP is whitelisted")
    )
    is_active = models.BooleanField(
        default=True
    )
    added_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When this whitelist entry expires")
    )
    
    class Meta:
        db_table = 'security_ip_whitelist'
        indexes = [
            models.Index(fields=['ip_address', 'is_active']),
        ]
    
    def __str__(self):
        return f"Whitelist: {self.ip_address}"
    
    def is_valid(self):
        """Check if whitelist entry is still valid"""
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True


class UserRateLimit(TenantFilteredModel):
    """
    Custom rate limits for specific users.
    """
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='custom_rate_limit'
    )
    rate_limit = models.IntegerField(
        help_text=_("Requests allowed per minute")
    )
    burst_limit = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("Burst allowance")
    )
    is_active = models.BooleanField(
        default=True
    )
    reason = models.TextField(
        blank=True,
        help_text=_("Why this custom limit was set")
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When to revert to default limits")
    )
    
    class Meta:
        db_table = 'security_user_rate_limits'
    
    def __str__(self):
        return f"Custom limit for {self.user}: {self.rate_limit}/min"
    
    def is_valid(self):
        """Check if custom limit is still valid"""
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True