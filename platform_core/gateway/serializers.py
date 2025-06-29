"""
Gateway Serializers

Serializers for gateway models.
"""

from rest_framework import serializers
from .models import (
    ServiceRegistry, Route, GatewayConfig,
    ServiceInstance, APIAggregation
)


class ServiceRegistrySerializer(serializers.ModelSerializer):
    """Serializer for ServiceRegistry"""
    
    instance_count = serializers.SerializerMethodField()
    healthy_instances = serializers.SerializerMethodField()
    
    class Meta:
        model = ServiceRegistry
        fields = [
            'id', 'name', 'display_name', 'description',
            'service_type', 'base_url', 'timeout',
            'weight', 'max_retries',
            'health_check_enabled', 'health_check_type',
            'health_check_path', 'health_check_interval',
            'circuit_breaker_enabled', 'circuit_breaker_threshold',
            'circuit_breaker_timeout',
            'auth_required', 'api_key',
            'is_active', 'is_healthy', 'last_health_check',
            'metadata', 'instance_count', 'healthy_instances',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['is_healthy', 'last_health_check']
        extra_kwargs = {
            'api_key': {'write_only': True}
        }
    
    def get_instance_count(self, obj):
        """Get total instance count"""
        return obj.instances.count()
    
    def get_healthy_instances(self, obj):
        """Get healthy instance count"""
        return obj.instances.filter(is_healthy=True).count()


class RouteSerializer(serializers.ModelSerializer):
    """Serializer for Route"""
    
    service_name = serializers.CharField(source='service.name', read_only=True)
    
    class Meta:
        model = Route
        fields = [
            'id', 'path', 'method', 'description',
            'service', 'service_name', 'service_path',
            'strip_prefix', 'append_slash',
            'transform_request', 'transform_response', 'transform_config',
            'add_request_headers', 'add_response_headers',
            'remove_request_headers', 'remove_response_headers',
            'auth_required', 'allowed_origins', 'rate_limit',
            'cache_enabled', 'cache_ttl', 'cache_key_params',
            'priority', 'is_active', 'metadata',
            'created_at', 'updated_at'
        ]
    
    def validate_path(self, value):
        """Validate route path"""
        # Check for valid placeholders
        import re
        placeholders = re.findall(r'\{(\w+)\}', value)
        
        # Check for duplicate placeholders
        if len(placeholders) != len(set(placeholders)):
            raise serializers.ValidationError(
                "Route path contains duplicate placeholders"
            )
        
        return value


class GatewayConfigSerializer(serializers.ModelSerializer):
    """Serializer for GatewayConfig"""
    
    class Meta:
        model = GatewayConfig
        fields = [
            'id', 'global_timeout', 'max_request_size',
            'require_auth_default', 'allowed_origins',
            'global_rate_limit',
            'log_requests', 'log_request_body', 'log_response_body',
            'enable_compression', 'compression_level',
            'is_active', 'maintenance_mode', 'maintenance_message',
            'created_at', 'updated_at'
        ]


class ServiceInstanceSerializer(serializers.ModelSerializer):
    """Serializer for ServiceInstance"""
    
    service_name = serializers.CharField(source='service.name', read_only=True)
    url = serializers.SerializerMethodField()
    
    class Meta:
        model = ServiceInstance
        fields = [
            'id', 'service', 'service_name',
            'instance_id', 'host', 'port',
            'is_healthy', 'last_health_check', 'health_check_failures',
            'weight', 'current_connections',
            'metadata', 'url',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'is_healthy', 'last_health_check', 
            'health_check_failures', 'current_connections'
        ]
    
    def get_url(self, obj):
        """Get instance URL"""
        return obj.get_url()


class APIAggregationSerializer(serializers.ModelSerializer):
    """Serializer for APIAggregation"""
    
    class Meta:
        model = APIAggregation
        fields = [
            'id', 'name', 'description',
            'aggregation_type',
            'request_path', 'request_method',
            'service_calls',
            'merge_responses', 'response_template',
            'fail_fast', 'partial_response_allowed',
            'cache_enabled', 'cache_ttl', 'timeout',
            'is_active',
            'created_at', 'updated_at'
        ]
    
    def validate_service_calls(self, value):
        """Validate service calls configuration"""
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "service_calls must be a dictionary"
            )
        
        # Validate required fields
        if 'calls' not in value:
            raise serializers.ValidationError(
                "service_calls must contain 'calls' array"
            )
        
        calls = value['calls']
        if not isinstance(calls, list):
            raise serializers.ValidationError(
                "calls must be an array"
            )
        
        # Validate each call
        for call in calls:
            if not isinstance(call, dict):
                raise serializers.ValidationError(
                    "Each call must be a dictionary"
                )
            
            # Required fields
            if 'name' not in call or 'service' not in call:
                raise serializers.ValidationError(
                    "Each call must have 'name' and 'service'"
                )
        
        return value


class RouteTestSerializer(serializers.Serializer):
    """Serializer for route testing"""
    
    path = serializers.CharField(required=True)
    method = serializers.ChoiceField(
        choices=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
        default='GET'
    )


class MaintenanceModeSerializer(serializers.Serializer):
    """Serializer for maintenance mode"""
    
    enabled = serializers.BooleanField(required=True)
    message = serializers.CharField(required=False, allow_blank=True)