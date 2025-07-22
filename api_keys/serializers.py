"""
Serializers for API Key management.

Provides serializers for creating, viewing, and managing API keys
with proper security and validation.
"""

from typing import Dict, Any

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from accounts.models import Group
from .models import APIKey, APIKeyUsage

User = get_user_model()


class APIKeyCreateSerializer(serializers.Serializer):
    """Serializer for creating new API keys."""
    
    name = serializers.CharField(
        max_length=255,
        help_text="Descriptive name for the API key"
    )
    scopes = serializers.MultipleChoiceField(
        choices=APIKey.Scope.choices,
        help_text="List of permitted scopes"
    )
    expires_in_days = serializers.IntegerField(
        min_value=1,
        max_value=3650,  # 10 years max
        default=365,
        help_text="Number of days until expiration"
    )
    rate_limit_per_hour = serializers.IntegerField(
        min_value=0,
        default=1000,
        help_text="Maximum requests per hour (0 = unlimited)"
    )
    application_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Application name for app-level keys"
    )
    allowed_ips = serializers.ListField(
        child=serializers.IPAddressField(),
        required=False,
        default=list,
        help_text="List of allowed IP addresses (empty = all allowed)"
    )
    metadata = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Additional metadata"
    )
    
    def validate_scopes(self, value):
        """Ensure at least one scope is provided."""
        if not value:
            raise serializers.ValidationError("At least one scope must be selected")
        return value
    
    def validate(self, attrs):
        """Validate the entire payload."""
        # For application keys, ensure they have limited scopes
        if attrs.get('application_name') and 'admin' in attrs.get('scopes', []):
            raise serializers.ValidationError({
                'scopes': "Application keys cannot have admin scope"
            })
        
        return attrs
    
    def create(self, validated_data):
        """Create the API key."""
        # This will be called from the view with additional context
        raise NotImplementedError("Use APIKey.objects.create_key() directly")


class APIKeySerializer(serializers.ModelSerializer):
    """Serializer for viewing API keys (without sensitive data)."""
    
    is_expired = serializers.BooleanField(read_only=True)
    is_valid = serializers.BooleanField(read_only=True)
    days_until_expiry = serializers.IntegerField(read_only=True)
    key_type = serializers.CharField(read_only=True)
    owner = serializers.SerializerMethodField()
    masked_key = serializers.SerializerMethodField()
    
    class Meta:
        model = APIKey
        fields = [
            'id', 'name', 'masked_key', 'key_prefix', 'owner', 'key_type',
            'scopes', 'expires_at', 'is_active', 'is_expired', 'is_valid',
            'days_until_expiry', 'allowed_ips', 'rate_limit_per_hour',
            'last_used_at', 'usage_count', 'created_at', 'updated_at',
            'replaced_by', 'rotation_reminder_sent', 'metadata'
        ]
        read_only_fields = [
            'id', 'key_hash', 'key_prefix', 'created_at', 'updated_at',
            'last_used_at', 'usage_count', 'replaced_by'
        ]
    
    def get_owner(self, obj):
        """Get the owner display name."""
        if obj.user:
            return obj.user.email
        return obj.application_name or "Unknown"
    
    def get_masked_key(self, obj):
        """Return a masked version of the key for display."""
        return f"{obj.key_prefix}...{obj.id.hex[-4:]}"


class APIKeyListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing API keys."""
    
    is_expired = serializers.BooleanField(read_only=True)
    owner = serializers.SerializerMethodField()
    
    class Meta:
        model = APIKey
        fields = [
            'id', 'name', 'key_prefix', 'owner', 'scopes',
            'expires_at', 'is_active', 'is_expired',
            'last_used_at', 'usage_count', 'created_at'
        ]
    
    def get_owner(self, obj):
        """Get the owner display name."""
        if obj.user:
            return obj.user.email
        return obj.application_name or "Unknown"


class APIKeyUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating API key settings."""
    
    class Meta:
        model = APIKey
        fields = [
            'name', 'scopes', 'allowed_ips', 'rate_limit_per_hour',
            'metadata'
        ]
    
    def validate_scopes(self, value):
        """Ensure at least one scope remains."""
        if not value:
            raise serializers.ValidationError("At least one scope must be selected")
        
        # Check if removing admin from app key
        instance = self.instance
        if instance and instance.application_name and 'admin' in value:
            raise serializers.ValidationError(
                "Application keys cannot have admin scope"
            )
        
        return value


class APIKeyRotateSerializer(serializers.Serializer):
    """Serializer for key rotation requests."""
    
    expires_in_days = serializers.IntegerField(
        min_value=1,
        max_value=3650,
        required=False,
        help_text="Days until new key expires (defaults to remaining time of old key)"
    )
    revoke_old_key = serializers.BooleanField(
        default=False,
        help_text="Whether to immediately revoke the old key"
    )
    overlap_hours = serializers.IntegerField(
        min_value=0,
        max_value=168,  # 1 week max
        default=24,
        help_text="Hours to keep old key active for transition"
    )


class APIKeyUsageSerializer(serializers.ModelSerializer):
    """Serializer for API key usage logs."""
    
    class Meta:
        model = APIKeyUsage
        fields = [
            'id', 'timestamp', 'endpoint', 'method', 'status_code',
            'ip_address', 'user_agent', 'response_time_ms', 'error_message'
        ]


class APIKeyUsageStatsSerializer(serializers.Serializer):
    """Serializer for usage statistics."""
    
    total_requests = serializers.IntegerField()
    successful_requests = serializers.IntegerField()
    failed_requests = serializers.IntegerField()
    average_response_time_ms = serializers.FloatField()
    unique_ips = serializers.IntegerField()
    top_endpoints = serializers.ListField(
        child=serializers.DictField()
    )
    requests_by_hour = serializers.ListField(
        child=serializers.DictField()
    )
    error_rate = serializers.FloatField()


class APIKeyResponseSerializer(serializers.Serializer):
    """Serializer for API key creation response."""
    
    api_key = APIKeySerializer()
    key = serializers.CharField(
        help_text="The actual API key - store this securely, it won't be shown again"
    )
    message = serializers.CharField(
        default="API key created successfully. Please store the key securely."
    )