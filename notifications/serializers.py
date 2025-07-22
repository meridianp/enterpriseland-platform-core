"""
Serializers for the notifications app.
"""
from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from .models import (
    Notification, EmailNotification, NotificationPreference,
    NotificationTemplate
)


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for Notification model."""
    
    sender_name = serializers.CharField(source='sender.get_full_name', read_only=True)
    sender_email = serializers.EmailField(source='sender.email', read_only=True)
    recipient_name = serializers.CharField(source='recipient.get_full_name', read_only=True)
    content_object_type = serializers.SerializerMethodField()
    content_object_display = serializers.SerializerMethodField()
    time_since = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            'id', 'type', 'title', 'message', 'priority',
            'sender', 'sender_name', 'sender_email',
            'recipient', 'recipient_name',
            'is_read', 'read_at', 'created_at',
            'action_url', 'action_label',
            'content_object_type', 'content_object_display',
            'time_since', 'metadata'
        ]
        read_only_fields = [
            'id', 'sender', 'recipient', 'created_at', 'read_at'
        ]
    
    def get_content_object_type(self, obj):
        """Get the type of the related object."""
        if obj.content_object:
            return f"{obj.content_type.app_label}.{obj.content_type.model}"
        return None
    
    def get_content_object_display(self, obj):
        """Get display representation of the related object."""
        if obj.content_object:
            return str(obj.content_object)
        return None
    
    def get_time_since(self, obj):
        """Get human-readable time since creation."""
        from django.utils import timezone
        from django.utils.timesince import timesince
        return timesince(obj.created_at, timezone.now())


class NotificationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating notifications."""
    
    recipient_id = serializers.UUIDField(write_only=True)
    content_type_name = serializers.CharField(write_only=True, required=False)
    object_id = serializers.UUIDField(write_only=True, required=False)
    send_email = serializers.BooleanField(write_only=True, default=False)
    
    class Meta:
        model = Notification
        fields = [
            'recipient_id', 'type', 'title', 'message', 'priority',
            'action_url', 'action_label', 'metadata',
            'content_type_name', 'object_id', 'send_email'
        ]
    
    def validate(self, attrs):
        """Validate notification data."""
        # Get recipient
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            recipient = User.objects.get(pk=attrs.pop('recipient_id'))
            attrs['recipient'] = recipient
        except User.DoesNotExist:
            raise serializers.ValidationError("Recipient not found")
        
        # Handle content object
        content_type_name = attrs.pop('content_type_name', None)
        object_id = attrs.get('object_id')
        
        if content_type_name and object_id:
            try:
                app_label, model = content_type_name.split('.')
                content_type = ContentType.objects.get(
                    app_label=app_label,
                    model=model
                )
                attrs['content_type'] = content_type
                
                # Verify object exists
                model_class = content_type.model_class()
                if not model_class.objects.filter(pk=object_id).exists():
                    raise serializers.ValidationError(
                        f"Object with id {object_id} not found"
                    )
            except (ValueError, ContentType.DoesNotExist):
                raise serializers.ValidationError(
                    f"Invalid content type: {content_type_name}"
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create notification with optional email."""
        send_email = validated_data.pop('send_email', False)
        
        # Set sender from context
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['sender'] = request.user
        
        notification = super().create(validated_data)
        
        # Send email if requested
        if send_email:
            notification.send_email()
        
        return notification


class BulkNotificationSerializer(serializers.Serializer):
    """Serializer for bulk notification creation."""
    
    recipient_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False
    )
    type = serializers.CharField(max_length=100)
    title = serializers.CharField(max_length=255)
    message = serializers.CharField()
    priority = serializers.ChoiceField(
        choices=Notification.Priority.choices,
        default=Notification.Priority.NORMAL
    )
    send_email = serializers.BooleanField(default=False)
    metadata = serializers.JSONField(required=False, default=dict)


class NotificationMarkReadSerializer(serializers.Serializer):
    """Serializer for marking notifications as read."""
    
    notification_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False
    )


class EmailNotificationSerializer(serializers.ModelSerializer):
    """Serializer for EmailNotification model."""
    
    notification_title = serializers.CharField(
        source='notification.title',
        read_only=True
    )
    
    class Meta:
        model = EmailNotification
        fields = [
            'id', 'notification', 'notification_title',
            'recipient_email', 'subject', 'status',
            'sent_at', 'error_message', 'provider',
            'opened_at', 'clicked_at', 'open_count', 'click_count',
            'created_at'
        ]
        read_only_fields = [
            'id', 'sent_at', 'error_message', 'provider',
            'opened_at', 'clicked_at', 'open_count', 'click_count',
            'created_at'
        ]


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for NotificationPreference model."""
    
    user_email = serializers.EmailField(source='user.email', read_only=True)
    
    class Meta:
        model = NotificationPreference
        fields = [
            'id', 'user', 'user_email',
            'email_enabled', 'in_app_enabled',
            'type_preferences',
            'quiet_hours_enabled', 'quiet_hours_start', 'quiet_hours_end',
            'digest_enabled', 'digest_frequency',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']


class NotificationTemplateSerializer(serializers.ModelSerializer):
    """Serializer for NotificationTemplate model."""
    
    class Meta:
        model = NotificationTemplate
        fields = [
            'id', 'code', 'name', 'description',
            'title_template', 'message_template',
            'email_subject_template', 'email_body_template',
            'email_html_template',
            'notification_type', 'priority',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class NotificationStatsSerializer(serializers.Serializer):
    """Serializer for notification statistics."""
    
    total_notifications = serializers.IntegerField()
    unread_count = serializers.IntegerField()
    read_count = serializers.IntegerField()
    by_type = serializers.DictField()
    by_priority = serializers.DictField()
    recent_notifications = NotificationSerializer(many=True)