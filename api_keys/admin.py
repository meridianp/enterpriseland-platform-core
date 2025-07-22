"""
Django admin interface for API Key management.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from .models import APIKey, APIKeyUsage


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    """Admin interface for API keys."""
    
    list_display = [
        'name', 'masked_key', 'owner_display', 'key_type', 
        'status_display', 'expires_at', 'usage_count', 'created_at'
    ]
    list_filter = [
        'is_active', 'created_at', 'expires_at', 'scopes'
    ]
    search_fields = [
        'name', 'user__email', 'application_name', 'key_prefix'
    ]
    readonly_fields = [
        'id', 'key_hash', 'key_prefix', 'created_at', 'updated_at',
        'last_used_at', 'usage_count', 'masked_key_display'
    ]
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'masked_key_display', 'key_prefix')
        }),
        ('Ownership', {
            'fields': ('user', 'application_name', 'group')
        }),
        ('Permissions', {
            'fields': ('scopes', 'allowed_ips', 'rate_limit_per_hour')
        }),
        ('Security', {
            'fields': ('is_active', 'expires_at')
        }),
        ('Usage Tracking', {
            'fields': ('last_used_at', 'usage_count'),
            'classes': ('collapse',)
        }),
        ('Rotation', {
            'fields': ('replaced_by', 'rotation_reminder_sent'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('System Fields', {
            'fields': ('id', 'key_hash', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def owner_display(self, obj):
        """Display the owner of the API key."""
        if obj.user:
            return obj.user.email
        return obj.application_name or "Unknown"
    owner_display.short_description = "Owner"
    
    def masked_key(self, obj):
        """Display a masked version of the key."""
        return f"{obj.key_prefix}...{obj.id.hex[-4:]}"
    masked_key.short_description = "Key"
    
    def masked_key_display(self, obj):
        """Display masked key for readonly field."""
        return self.masked_key(obj)
    masked_key_display.short_description = "Masked Key"
    
    def status_display(self, obj):
        """Display colored status."""
        if obj.is_expired:
            return format_html(
                '<span style="color: red; font-weight: bold;">Expired</span>'
            )
        elif not obj.is_active:
            return format_html(
                '<span style="color: orange; font-weight: bold;">Revoked</span>'
            )
        else:
            return format_html(
                '<span style="color: green; font-weight: bold;">Active</span>'
            )
    status_display.short_description = "Status"
    
    def key_type(self, obj):
        """Display the type of key."""
        return "Application" if obj.application_name else "User"
    key_type.short_description = "Type"
    
    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related('user', 'group', 'replaced_by')
    
    def has_add_permission(self, request):
        """Disable adding keys through admin (use management commands instead)."""
        return False


@admin.register(APIKeyUsage)
class APIKeyUsageAdmin(admin.ModelAdmin):
    """Admin interface for API key usage logs."""
    
    list_display = [
        'api_key_display', 'timestamp', 'method', 'endpoint', 
        'status_code', 'ip_address', 'response_time_ms'
    ]
    list_filter = [
        'timestamp', 'method', 'status_code', 'api_key__name'
    ]
    search_fields = [
        'api_key__name', 'endpoint', 'ip_address', 'api_key__key_prefix'
    ]
    readonly_fields = [
        'id', 'timestamp', 'api_key', 'endpoint', 'method', 
        'status_code', 'ip_address', 'user_agent', 
        'response_time_ms', 'error_message'
    ]
    date_hierarchy = 'timestamp'
    
    def api_key_display(self, obj):
        """Display API key information."""
        return f"{obj.api_key.name} ({obj.api_key.key_prefix}...)"
    api_key_display.short_description = "API Key"
    
    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related('api_key', 'api_key__user')
    
    def has_add_permission(self, request):
        """Disable manual creation of usage logs."""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Make usage logs read-only."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Disable deletion of usage logs."""
        return False
