"""
Event System Serializers
"""

from rest_framework import serializers
from .models import (
    EventSchema,
    EventSubscription,
    Event,
    EventProcessor,
    SagaInstance
)


class EventSchemaSerializer(serializers.ModelSerializer):
    """Serializer for EventSchema."""
    
    class Meta:
        model = EventSchema
        fields = [
            'id',
            'event_type',
            'version',
            'name',
            'description',
            'schema',
            'routing_key',
            'exchange',
            'ttl',
            'priority',
            'persistent',
            'is_active',
            'metadata',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_schema(self, value):
        """Validate JSON schema format."""
        if value and not isinstance(value, dict):
            raise serializers.ValidationError("Schema must be a valid JSON object")
        
        # Basic JSON Schema validation
        if value and 'type' not in value:
            raise serializers.ValidationError("Schema must have a 'type' field")
        
        return value


class EventSubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for EventSubscription."""
    
    status_display = serializers.SerializerMethodField()
    
    class Meta:
        model = EventSubscription
        fields = [
            'id',
            'name',
            'description',
            'event_types',
            'filter_expression',
            'subscription_type',
            'endpoint',
            'handler',
            'max_retries',
            'retry_policy',
            'retry_delay',
            'dead_letter_queue',
            'max_receive_count',
            'batch_size',
            'visibility_timeout',
            'concurrent_workers',
            'is_active',
            'is_paused',
            'last_error',
            'last_error_at',
            'status_display',
            'metadata',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'last_error',
            'last_error_at',
            'status_display',
            'created_at',
            'updated_at'
        ]
    
    def get_status_display(self, obj):
        """Get human-readable status."""
        if not obj.is_active:
            return 'inactive'
        elif obj.is_paused:
            return 'paused'
        elif obj.last_error:
            return 'error'
        else:
            return 'active'
    
    def validate_event_types(self, value):
        """Validate event types list."""
        if not value:
            raise serializers.ValidationError("At least one event type is required")
        
        if not isinstance(value, list):
            raise serializers.ValidationError("Event types must be a list")
        
        return value
    
    def validate_filter_expression(self, value):
        """Validate JMESPath expression."""
        if value:
            try:
                import jmespath
                jmespath.compile(value)
            except Exception as e:
                raise serializers.ValidationError(f"Invalid filter expression: {e}")
        
        return value


class EventSerializer(serializers.ModelSerializer):
    """Serializer for Event."""
    
    user_username = serializers.CharField(source='user.username', read_only=True)
    processing_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id',
            'event_id',
            'event_type',
            'version',
            'data',
            'metadata',
            'source',
            'correlation_id',
            'causation_id',
            'user',
            'user_username',
            'occurred_at',
            'published_at',
            'expires_at',
            'status',
            'publish_attempts',
            'error_message',
            'processing_status',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'event_id',
            'user_username',
            'published_at',
            'processing_status',
            'created_at',
            'updated_at'
        ]
    
    def get_processing_status(self, obj):
        """Get processing status summary."""
        processors = obj.processors.all()
        
        if not processors:
            return None
        
        return {
            'total': processors.count(),
            'completed': processors.filter(status='completed').count(),
            'failed': processors.filter(status='failed').count(),
            'pending': processors.filter(status='pending').count()
        }


class EventProcessorSerializer(serializers.ModelSerializer):
    """Serializer for EventProcessor."""
    
    event_type = serializers.CharField(source='event.event_type', read_only=True)
    subscription_name = serializers.CharField(source='subscription.name', read_only=True)
    
    class Meta:
        model = EventProcessor
        fields = [
            'id',
            'event',
            'event_type',
            'subscription',
            'subscription_name',
            'status',
            'attempts',
            'started_at',
            'completed_at',
            'next_retry_at',
            'result',
            'error_message',
            'error_details',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'event_type',
            'subscription_name',
            'created_at',
            'updated_at'
        ]


class SagaInstanceSerializer(serializers.ModelSerializer):
    """Serializer for SagaInstance."""
    
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = SagaInstance
        fields = [
            'id',
            'saga_id',
            'saga_type',
            'status',
            'current_step',
            'state_data',
            'correlation_id',
            'initiating_event_id',
            'completed_steps',
            'compensated_steps',
            'started_at',
            'completed_at',
            'expires_at',
            'duration',
            'error_message',
            'retry_count',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'saga_id',
            'duration',
            'created_at',
            'updated_at'
        ]
    
    def get_duration(self, obj):
        """Get saga duration."""
        if obj.completed_at and obj.started_at:
            delta = obj.completed_at - obj.started_at
            return delta.total_seconds()
        return None


class EventPublishSerializer(serializers.Serializer):
    """Serializer for publishing events."""
    
    event_type = serializers.CharField(max_length=100)
    data = serializers.JSONField()
    correlation_id = serializers.CharField(max_length=100, required=False)
    metadata = serializers.JSONField(required=False)
    version = serializers.CharField(max_length=10, default='1.0')
    source = serializers.CharField(max_length=200, required=False)
    
    def validate_event_type(self, value):
        """Validate event type format."""
        import re
        
        if not re.match(r'^[a-zA-Z0-9._-]+$', value):
            raise serializers.ValidationError(
                "Event type must contain only letters, numbers, dots, underscores, and hyphens"
            )
        
        return value