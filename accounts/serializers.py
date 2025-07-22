
from rest_framework import serializers
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .models import (
    User, Group, GroupMembership, GuestAccess,
    MFAMethod, SecurityEvent, UserDevice
)

class UserSerializer(serializers.ModelSerializer):
    """Serializer for user data"""
    groups = serializers.StringRelatedField(many=True, read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'role', 'is_active', 'created_at', 'last_login_at', 'groups'
        ]
        read_only_fields = ['id', 'created_at', 'last_login_at']

class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new users"""
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'role', 'password', 'password_confirm'
        ]
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match")
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()
        return user

class GroupSerializer(serializers.ModelSerializer):
    """Serializer for group data"""
    member_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Group
        fields = ['id', 'name', 'description', 'created_at', 'member_count']
        read_only_fields = ['id', 'created_at']
    
    def get_member_count(self, obj):
        return obj.members.count()

class GroupMembershipSerializer(serializers.ModelSerializer):
    """Serializer for group membership"""
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    group_name = serializers.CharField(source='group.name', read_only=True)
    
    class Meta:
        model = GroupMembership
        fields = ['id', 'user', 'group', 'user_email', 'user_name', 'group_name', 'is_admin', 'joined_at']
        read_only_fields = ['id', 'joined_at']

class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""
    email = serializers.EmailField()
    password = serializers.CharField()
    
    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        
        if email and password:
            user = authenticate(username=email, password=password)
            if not user:
                raise serializers.ValidationError('Invalid credentials')
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled')
            attrs['user'] = user
        else:
            raise serializers.ValidationError('Must include email and password')
        
        return attrs

class TokenSerializer(serializers.Serializer):
    """Serializer for JWT tokens"""
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()

class GuestAccessSerializer(serializers.ModelSerializer):
    """Serializer for guest access tokens"""
    assessment_title = serializers.CharField(source='assessment.__str__', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_valid = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = GuestAccess
        fields = [
            'id', 'token', 'assessment', 'assessment_title', 'created_by',
            'created_by_name', 'expires_at', 'is_active', 'accessed_count',
            'last_accessed_at', 'created_at', 'is_expired', 'is_valid'
        ]
        read_only_fields = ['id', 'token', 'accessed_count', 'last_accessed_at', 'created_at']


class MFAMethodSerializer(serializers.ModelSerializer):
    """Serializer for MFA methods"""
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    
    class Meta:
        model = MFAMethod
        fields = [
            'id', 'method', 'method_display', 'is_primary', 'is_active',
            'verified_at', 'last_used_at', 'use_count', 'created_at'
        ]
        read_only_fields = ['id', 'verified_at', 'last_used_at', 'use_count', 'created_at']


class SecurityEventSerializer(serializers.ModelSerializer):
    """Serializer for security events"""
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    
    class Meta:
        model = SecurityEvent
        fields = [
            'id', 'event_type', 'event_type_display', 'description',
            'ip_address', 'device_id', 'metadata', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class UserDeviceSerializer(serializers.ModelSerializer):
    """Serializer for user devices"""
    
    class Meta:
        model = UserDevice
        fields = [
            'id', 'device_id', 'device_name', 'device_type', 'user_agent',
            'ip_address', 'country', 'city', 'first_seen', 'last_seen',
            'login_count', 'is_trusted', 'is_blocked'
        ]
        read_only_fields = ['id', 'device_id', 'first_seen', 'last_seen', 'login_count']
