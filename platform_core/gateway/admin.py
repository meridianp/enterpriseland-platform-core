"""
Gateway Admin Configuration

Django admin interface for gateway management.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import (
    ServiceRegistry, Route, GatewayConfig,
    ServiceInstance, APIAggregation
)


@admin.register(ServiceRegistry)
class ServiceRegistryAdmin(admin.ModelAdmin):
    """Admin for ServiceRegistry"""
    
    list_display = [
        'name', 'display_name', 'service_type', 'base_url',
        'health_status', 'circuit_status', 'is_active'
    ]
    list_filter = [
        'service_type', 'is_active', 'is_healthy',
        'health_check_enabled', 'circuit_breaker_enabled'
    ]
    search_fields = ['name', 'display_name', 'base_url']
    readonly_fields = ['is_healthy', 'last_health_check']
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'name', 'display_name', 'description',
                'service_type', 'base_url', 'is_active'
            )
        }),
        ('Configuration', {
            'fields': (
                'timeout', 'weight', 'max_retries',
                'auth_required', 'api_key'
            )
        }),
        ('Health Check', {
            'fields': (
                'health_check_enabled', 'health_check_type',
                'health_check_path', 'health_check_interval',
                'is_healthy', 'last_health_check'
            )
        }),
        ('Circuit Breaker', {
            'fields': (
                'circuit_breaker_enabled', 'circuit_breaker_threshold',
                'circuit_breaker_timeout'
            )
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        })
    )
    
    def health_status(self, obj):
        """Display health status"""
        if obj.is_healthy:
            color = 'green'
            status = 'Healthy'
        else:
            color = 'red'
            status = 'Unhealthy'
        
        return format_html(
            '<span style="color: {};">⬤ {}</span>',
            color, status
        )
    health_status.short_description = 'Health'
    
    def circuit_status(self, obj):
        """Display circuit breaker status"""
        if not obj.circuit_breaker_enabled:
            return 'Disabled'
        
        # This would check actual circuit status
        return 'Closed'
    circuit_status.short_description = 'Circuit'


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    """Admin for Route"""
    
    list_display = [
        'path', 'method', 'service_link', 'priority',
        'cache_status', 'is_active'
    ]
    list_filter = [
        'method', 'service', 'is_active',
        'auth_required', 'cache_enabled',
        'transform_request', 'transform_response'
    ]
    search_fields = ['path', 'description', 'service__name']
    list_editable = ['priority', 'is_active']
    
    fieldsets = (
        ('Route Configuration', {
            'fields': (
                'path', 'method', 'description',
                'service', 'service_path',
                'strip_prefix', 'append_slash',
                'priority', 'is_active'
            )
        }),
        ('Transformation', {
            'fields': (
                'transform_request', 'transform_response',
                'transform_config'
            ),
            'classes': ('collapse',)
        }),
        ('Headers', {
            'fields': (
                'add_request_headers', 'add_response_headers',
                'remove_request_headers', 'remove_response_headers'
            ),
            'classes': ('collapse',)
        }),
        ('Security', {
            'fields': (
                'auth_required', 'allowed_origins', 'rate_limit'
            )
        }),
        ('Caching', {
            'fields': (
                'cache_enabled', 'cache_ttl', 'cache_key_params'
            )
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        })
    )
    
    def service_link(self, obj):
        """Link to service"""
        url = reverse('admin:gateway_serviceregistry_change', args=[obj.service.id])
        return format_html('<a href="{}">{}</a>', url, obj.service.name)
    service_link.short_description = 'Service'
    
    def cache_status(self, obj):
        """Display cache status"""
        if obj.cache_enabled:
            return f"✓ {obj.cache_ttl}s"
        return "✗"
    cache_status.short_description = 'Cache'


@admin.register(GatewayConfig)
class GatewayConfigAdmin(admin.ModelAdmin):
    """Admin for GatewayConfig"""
    
    list_display = ['id', 'status_display', 'global_timeout', 'global_rate_limit']
    
    fieldsets = (
        ('Request Handling', {
            'fields': (
                'global_timeout', 'max_request_size',
                'enable_compression', 'compression_level'
            )
        }),
        ('Security', {
            'fields': (
                'require_auth_default', 'allowed_origins',
                'global_rate_limit'
            )
        }),
        ('Logging', {
            'fields': (
                'log_requests', 'log_request_body', 'log_response_body'
            )
        }),
        ('Status', {
            'fields': (
                'is_active', 'maintenance_mode', 'maintenance_message'
            )
        })
    )
    
    def status_display(self, obj):
        """Display gateway status"""
        if obj.maintenance_mode:
            return format_html(
                '<span style="color: orange;">⚠️ Maintenance</span>'
            )
        elif obj.is_active:
            return format_html(
                '<span style="color: green;">✓ Active</span>'
            )
        else:
            return format_html(
                '<span style="color: red;">✗ Inactive</span>'
            )
    status_display.short_description = 'Status'
    
    def has_add_permission(self, request):
        """Only allow one config"""
        return not GatewayConfig.objects.exists()


@admin.register(ServiceInstance)
class ServiceInstanceAdmin(admin.ModelAdmin):
    """Admin for ServiceInstance"""
    
    list_display = [
        'instance_id', 'service', 'host', 'port',
        'health_display', 'weight', 'connections'
    ]
    list_filter = ['service', 'is_healthy']
    search_fields = ['instance_id', 'host']
    readonly_fields = [
        'is_healthy', 'last_health_check',
        'health_check_failures', 'current_connections'
    ]
    
    fieldsets = (
        ('Instance Information', {
            'fields': (
                'service', 'instance_id', 'host', 'port'
            )
        }),
        ('Health Status', {
            'fields': (
                'is_healthy', 'last_health_check',
                'health_check_failures'
            )
        }),
        ('Load Balancing', {
            'fields': (
                'weight', 'current_connections'
            )
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        })
    )
    
    def health_display(self, obj):
        """Display health with failures"""
        if obj.is_healthy:
            return format_html(
                '<span style="color: green;">✓ Healthy</span>'
            )
        else:
            return format_html(
                '<span style="color: red;">✗ Failed ({})</span>',
                obj.health_check_failures
            )
    health_display.short_description = 'Health'
    
    def connections(self, obj):
        """Display connections"""
        return obj.current_connections
    connections.short_description = 'Connections'


@admin.register(APIAggregation)
class APIAggregationAdmin(admin.ModelAdmin):
    """Admin for APIAggregation"""
    
    list_display = [
        'name', 'aggregation_type', 'request_path',
        'request_method', 'is_active'
    ]
    list_filter = ['aggregation_type', 'request_method', 'is_active']
    search_fields = ['name', 'description', 'request_path']
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'name', 'description', 'aggregation_type',
                'is_active'
            )
        }),
        ('Request Configuration', {
            'fields': (
                'request_path', 'request_method'
            )
        }),
        ('Service Calls', {
            'fields': (
                'service_calls',
            )
        }),
        ('Response Handling', {
            'fields': (
                'merge_responses', 'response_template',
                'fail_fast', 'partial_response_allowed'
            )
        }),
        ('Performance', {
            'fields': (
                'cache_enabled', 'cache_ttl', 'timeout'
            )
        })
    )
    
    def get_readonly_fields(self, request, obj=None):
        """Make service_calls read-only in admin"""
        if obj:  # Editing existing object
            return ['service_calls']
        return []