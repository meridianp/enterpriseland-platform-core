
from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid

class User(AbstractUser):
    """Custom user model with role-based access control"""
    
    class Role(models.TextChoices):
        BUSINESS_ANALYST = 'business_analyst', 'Business Analyst'
        PORTFOLIO_MANAGER = 'portfolio_manager', 'Portfolio Manager'
        EXTERNAL_PARTNER = 'external_partner', 'External Partner'
        AUDITOR = 'auditor', 'Auditor'
        ADMIN = 'admin', 'Admin'
        READ_ONLY = 'read_only', 'Read Only'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.READ_ONLY)
    auth0_sub = models.CharField(max_length=255, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    
    # Group membership for multi-tenancy
    groups = models.ManyToManyField('Group', through='GroupMembership', related_name='members')
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']
    
    class Meta:
        db_table = 'users'
        
    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"
    
    @property
    def can_create_assessments(self):
        return self.role in [self.Role.BUSINESS_ANALYST, self.Role.PORTFOLIO_MANAGER, self.Role.ADMIN]
    
    @property
    def can_approve_assessments(self):
        return self.role in [self.Role.PORTFOLIO_MANAGER, self.Role.ADMIN]
    
    @property
    def can_export_data(self):
        return self.role in [self.Role.BUSINESS_ANALYST, self.Role.PORTFOLIO_MANAGER, self.Role.AUDITOR, self.Role.ADMIN]


class Group(models.Model):
    """Groups for multi-tenant access control"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'groups'
        
    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    """Through model for user-group relationships"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)
    is_admin = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'group_memberships'
        unique_together = ['user', 'group']
        
    def __str__(self):
        return f"{self.user.email} in {self.group.name}"


class GuestAccess(models.Model):
    """Guest access tokens for third-party viewing"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token = models.CharField(max_length=255, unique=True)
    assessment = models.ForeignKey('assessments.Assessment', on_delete=models.CASCADE, related_name='guest_accesses')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    accessed_count = models.IntegerField(default=0)
    last_accessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'guest_accesses'
        
    def __str__(self):
        return f"Guest access for {self.assessment}"
    
    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at
    
    @property
    def is_valid(self):
        return self.is_active and not self.is_expired


# Import security models
from .security_models import (
    UserDevice, LoginAttempt, MFAMethod, 
    MFABackupCode, SecurityEvent
)
