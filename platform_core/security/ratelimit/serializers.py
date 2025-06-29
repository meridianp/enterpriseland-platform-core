"""
Rate Limit Serializers
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import (
    RateLimitRule, RateLimitViolation, 
    IPWhitelist, UserRateLimit
)


User = get_user_model()


class RateLimitRuleSerializer(serializers.ModelSerializer):
    """Serializer for rate limit rules"""
    
    limit_string = serializers.CharField(
        source='get_limit_string',
        read_only=True
    )
    violation_count = serializers.SerializerMethodField()
    
    class Meta:
        model = RateLimitRule
        fields = [
            'id', 'name', 'description', 'endpoint_pattern',
            'user_group', 'rate_limit', 'per_seconds', 'burst_limit',
            'is_active', 'priority', 'strategy', 'action',
            'limit_string', 'violation_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_violation_count(self, obj):
        """Get recent violation count"""
        from django.utils import timezone
        from datetime import timedelta
        
        # Count violations in last 24 hours
        since = timezone.now() - timedelta(hours=24)
        return obj.violations.filter(timestamp__gte=since).count()


class RateLimitViolationSerializer(serializers.ModelSerializer):
    """Serializer for rate limit violations"""
    
    user_display = serializers.SerializerMethodField()
    rule_name = serializers.CharField(
        source='rule.name',
        read_only=True
    )
    
    class Meta:
        model = RateLimitViolation
        fields = [
            'id', 'user', 'user_display', 'ip_address', 'endpoint',
            'method', 'rule', 'rule_name', 'timestamp', 'user_agent',
            'request_data', 'limit_exceeded', 'request_count',
            'window_seconds', 'action_taken'
        ]
        read_only_fields = fields
    
    def get_user_display(self, obj):
        """Get user display name"""
        if obj.user:
            return {
                'id': obj.user.id,
                'username': obj.user.username,
                'email': obj.user.email
            }
        return None


class IPWhitelistSerializer(serializers.ModelSerializer):
    """Serializer for IP whitelist"""
    
    added_by_display = serializers.SerializerMethodField()
    is_valid = serializers.BooleanField(
        source='is_valid',
        read_only=True
    )
    
    class Meta:
        model = IPWhitelist
        fields = [
            'id', 'ip_address', 'description', 'is_active',
            'added_by', 'added_by_display', 'expires_at',
            'is_valid', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'added_by', 'created_at', 'updated_at']
    
    def get_added_by_display(self, obj):
        """Get user who added this IP"""
        if obj.added_by:
            return {
                'id': obj.added_by.id,
                'username': obj.added_by.username
            }
        return None
    
    def validate_ip_address(self, value):
        """Validate IP address is not already whitelisted"""
        if self.instance:
            # Updating existing
            existing = IPWhitelist.objects.filter(
                ip_address=value
            ).exclude(id=self.instance.id)
        else:
            # Creating new
            existing = IPWhitelist.objects.filter(ip_address=value)
        
        if existing.exists():
            raise serializers.ValidationError(
                "This IP address is already in the whitelist"
            )
        
        return value


class UserRateLimitSerializer(serializers.ModelSerializer):
    """Serializer for custom user rate limits"""
    
    user_display = serializers.SerializerMethodField()
    is_valid = serializers.BooleanField(
        source='is_valid',
        read_only=True
    )
    
    class Meta:
        model = UserRateLimit
        fields = [
            'id', 'user', 'user_display', 'rate_limit', 'burst_limit',
            'is_active', 'reason', 'expires_at', 'is_valid',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_user_display(self, obj):
        """Get user display info"""
        return {
            'id': obj.user.id,
            'username': obj.user.username,
            'email': obj.user.email
        }
    
    def validate_user(self, value):
        """Validate user doesn't already have custom limit"""
        if self.instance:
            # Updating existing
            existing = UserRateLimit.objects.filter(
                user=value
            ).exclude(id=self.instance.id)
        else:
            # Creating new
            existing = UserRateLimit.objects.filter(user=value)
        
        if existing.exists():
            raise serializers.ValidationError(
                "This user already has a custom rate limit"
            )
        
        return value


class RateLimitStatusSerializer(serializers.Serializer):
    """Serializer for rate limit status"""
    
    rule = serializers.CharField()
    limit = serializers.CharField()
    current_usage = serializers.IntegerField()
    remaining = serializers.IntegerField()
    reset_in = serializers.IntegerField(required=False)


class BulkWhitelistSerializer(serializers.Serializer):
    """Serializer for bulk IP whitelist operations"""
    
    ip_addresses = serializers.ListField(
        child=serializers.IPAddressField(),
        min_length=1,
        max_length=100
    )
    description = serializers.CharField(max_length=200)
    expires_at = serializers.DateTimeField(required=False)
    
    def create(self, validated_data):
        """Create multiple whitelist entries"""
        ip_addresses = validated_data.pop('ip_addresses')
        added_by = self.context['request'].user
        
        created = []
        for ip in ip_addresses:
            # Skip if already exists
            if IPWhitelist.objects.filter(ip_address=ip).exists():
                continue
            
            entry = IPWhitelist.objects.create(
                ip_address=ip,
                added_by=added_by,
                **validated_data
            )
            created.append(entry)
        
        return {'created': len(created), 'entries': created}