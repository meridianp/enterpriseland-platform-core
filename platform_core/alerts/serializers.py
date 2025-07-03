"""
Alert API Serializers
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import Alert, AlertRule, AlertChannel, AlertNotification, AlertSilence

User = get_user_model()


class AlertRuleSerializer(serializers.ModelSerializer):
    """Alert rule serializer"""
    
    class Meta:
        model = AlertRule
        fields = [
            'id', 'name', 'description', 'metric_name', 'condition',
            'threshold', 'evaluation_interval', 'for_duration',
            'severity', 'labels', 'annotations', 'enabled',
            'cooldown_period', 'max_alerts_per_day',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_metric_name(self, value):
        """Validate metric exists"""
        # TODO: Check if metric exists in registry
        return value


class AlertChannelSerializer(serializers.ModelSerializer):
    """Alert channel serializer"""
    
    class Meta:
        model = AlertChannel
        fields = [
            'id', 'name', 'type', 'configuration',
            'severities', 'labels', 'enabled',
            'rate_limit', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_configuration(self, value):
        """Validate channel configuration"""
        channel_type = self.initial_data.get('type')
        
        # Validate based on channel type
        if channel_type == 'email':
            if not value.get('recipients'):
                raise serializers.ValidationError("Email channel requires recipients")
        elif channel_type == 'slack':
            if not value.get('webhook_url'):
                raise serializers.ValidationError("Slack channel requires webhook_url")
        elif channel_type == 'pagerduty':
            if not value.get('integration_key'):
                raise serializers.ValidationError("PagerDuty channel requires integration_key")
        elif channel_type == 'webhook':
            if not value.get('url'):
                raise serializers.ValidationError("Webhook channel requires url")
        
        return value


class AlertSerializer(serializers.ModelSerializer):
    """Alert serializer"""
    rule_name = serializers.CharField(source='rule.name', read_only=True)
    acknowledged_by_username = serializers.CharField(
        source='acknowledged_by.username',
        read_only=True,
        allow_null=True
    )
    
    class Meta:
        model = Alert
        fields = [
            'id', 'rule', 'rule_name', 'severity', 'status',
            'value', 'message', 'labels', 'annotations',
            'fired_at', 'resolved_at', 'acknowledged_at',
            'acknowledged_by', 'acknowledged_by_username',
            'notified_channels', 'notification_count',
            'last_notification_at', 'fingerprint'
        ]
        read_only_fields = [
            'id', 'rule', 'severity', 'value', 'message',
            'labels', 'annotations', 'fired_at', 'fingerprint'
        ]


class AlertNotificationSerializer(serializers.ModelSerializer):
    """Alert notification serializer"""
    alert_id = serializers.IntegerField(source='alert.id', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    
    class Meta:
        model = AlertNotification
        fields = [
            'id', 'alert_id', 'channel', 'channel_name',
            'sent_at', 'success', 'error_message', 'response_data'
        ]
        read_only_fields = fields


class AlertSilenceSerializer(serializers.ModelSerializer):
    """Alert silence serializer"""
    created_by_username = serializers.CharField(
        source='created_by.username',
        read_only=True
    )
    duration_hours = serializers.IntegerField(write_only=True, required=False, default=4)
    
    class Meta:
        model = AlertSilence
        fields = [
            'id', 'name', 'description', 'matchers',
            'starts_at', 'ends_at', 'created_by', 'created_by_username',
            'created_at', 'active', 'duration_hours'
        ]
        read_only_fields = ['id', 'created_by', 'created_at']
    
    def create(self, validated_data):
        """Create silence with duration"""
        duration_hours = validated_data.pop('duration_hours', 4)
        
        # Set end time based on duration
        if 'ends_at' not in validated_data:
            from datetime import timedelta
            validated_data['ends_at'] = (
                validated_data.get('starts_at', timezone.now()) +
                timedelta(hours=duration_hours)
            )
        
        return super().create(validated_data)


class AlertStatsSerializer(serializers.Serializer):
    """Alert statistics serializer"""
    active = serializers.IntegerField()
    last_24h = serializers.IntegerField()
    last_7d = serializers.IntegerField()
    by_severity = serializers.DictField(child=serializers.IntegerField())
    top_rules = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=True
    )


class AcknowledgeAlertSerializer(serializers.Serializer):
    """Acknowledge alert request serializer"""
    alert_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1
    )


class TestAlertSerializer(serializers.Serializer):
    """Test alert creation serializer"""
    rule_id = serializers.IntegerField()
    value = serializers.FloatField()
    message = serializers.CharField(required=False, allow_blank=True)