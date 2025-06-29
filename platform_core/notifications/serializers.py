
from rest_framework import serializers
from platform_core.core.serializers import PlatformSerializer
from .models import Notification, EmailNotification, WebhookEndpoint, WebhookDelivery

class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for notifications"""
    sender_name = serializers.CharField(source='sender.get_full_name', read_only=True)
    assessment_title = serializers.CharField(source='assessment.__str__', read_only=True)
    
    class Meta:
        model = Notification
        fields = [
            'id', 'type', 'title', 'message', 'assessment', 'assessment_title',
            'sender', 'sender_name', 'is_read', 'read_at', 'created_at'
        ]
        read_only_fields = ['id', 'sender', 'read_at', 'created_at']

class EmailNotificationSerializer(serializers.ModelSerializer):
    """Serializer for email notifications"""
    
    class Meta:
        model = EmailNotification
        fields = [
            'id', 'recipient_email', 'subject', 'body', 'html_body',
            'status', 'sent_at', 'error_message', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'sent_at', 'created_at', 'updated_at']

class WebhookEndpointSerializer(serializers.ModelSerializer):
    """Serializer for webhook endpoints"""
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        model = WebhookEndpoint
        fields = [
            'id', 'name', 'url', 'secret_key', 'events', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

class WebhookDeliverySerializer(serializers.ModelSerializer):
    """Serializer for webhook deliveries"""
    endpoint_name = serializers.CharField(source='endpoint.name', read_only=True)
    
    class Meta:
        model = WebhookDelivery
        fields = [
            'id', 'endpoint', 'endpoint_name', 'event_type', 'payload',
            'status', 'response_status_code', 'response_body', 'error_message',
            'attempt_count', 'max_attempts', 'next_retry_at',
            'created_at', 'delivered_at'
        ]
        read_only_fields = [
            'id', 'response_status_code', 'response_body', 'error_message',
            'attempt_count', 'next_retry_at', 'created_at', 'delivered_at'
        ]
