"""
Module System Admin Configuration
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import ModuleManifest, ModuleInstallation, ModuleDependency, ModuleEvent


@admin.register(ModuleManifest)
class ModuleManifestAdmin(admin.ModelAdmin):
    list_display = [
        'module_id', 'name', 'version', 'author',
        'is_active_badge', 'is_certified_badge', 'pricing_model',
        'created_at'
    ]
    list_filter = [
        'is_active', 'is_certified', 'pricing_model',
        'created_at', 'updated_at'
    ]
    search_fields = [
        'module_id', 'name', 'description', 'author',
        'tags'
    ]
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'module_id', 'name', 'description', 'version',
                'platform_version'
            )
        }),
        ('Author Information', {
            'fields': ('author', 'author_email', 'website')
        }),
        ('Configuration', {
            'fields': (
                'dependencies', 'permissions', 'entities',
                'workflows', 'ui_components', 'api_endpoints'
            )
        }),
        ('Resource Limits', {
            'fields': ('resource_limits',),
            'classes': ('collapse',)
        }),
        ('Schema', {
            'fields': ('configuration_schema',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': (
                'pricing_model', 'tags', 'is_active',
                'is_certified', 'created_at', 'updated_at'
            )
        })
    )
    
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="color: green;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: red;">✗ Inactive</span>'
        )
    is_active_badge.short_description = 'Active'
    
    def is_certified_badge(self, obj):
        if obj.is_certified:
            return format_html(
                '<span style="color: green;">✓ Certified</span>'
            )
        return format_html(
            '<span style="color: gray;">- Not Certified</span>'
        )
    is_certified_badge.short_description = 'Certified'


@admin.register(ModuleInstallation)
class ModuleInstallationAdmin(admin.ModelAdmin):
    list_display = [
        'module_name', 'tenant', 'status_badge',
        'installed_by', 'installed_at'
    ]
    list_filter = [
        'status', 'installed_at', 'enabled_at',
        'tenant'
    ]
    search_fields = [
        'module__module_id', 'module__name',
        'tenant__name'
    ]
    readonly_fields = [
        'installed_at', 'installed_by',
        'enabled_at', 'disabled_at'
    ]
    
    fieldsets = (
        ('Installation', {
            'fields': (
                'tenant', 'module', 'status',
                'installed_by', 'installed_at'
            )
        }),
        ('Configuration', {
            'fields': ('configuration',)
        }),
        ('Status History', {
            'fields': ('enabled_at', 'disabled_at'),
            'classes': ('collapse',)
        })
    )
    
    def module_name(self, obj):
        return f"{obj.module.name} ({obj.module.version})"
    module_name.short_description = 'Module'
    
    def status_badge(self, obj):
        colors = {
            'active': 'green',
            'disabled': 'orange',
            'failed': 'red',
            'installing': 'blue'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {};">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'


@admin.register(ModuleDependency)
class ModuleDependencyAdmin(admin.ModelAdmin):
    list_display = [
        'installation_module', 'required_module',
        'version_constraint', 'is_satisfied_badge'
    ]
    list_filter = ['is_satisfied', 'created_at']
    search_fields = [
        'installation__module__module_id',
        'required_module__module_id'
    ]
    
    def installation_module(self, obj):
        return f"{obj.installation.module.name}"
    installation_module.short_description = 'Module'
    
    def is_satisfied_badge(self, obj):
        if obj.is_satisfied:
            return format_html(
                '<span style="color: green;">✓ Satisfied</span>'
            )
        return format_html(
            '<span style="color: red;">✗ Not Satisfied</span>'
        )
    is_satisfied_badge.short_description = 'Satisfied'


@admin.register(ModuleEvent)
class ModuleEventAdmin(admin.ModelAdmin):
    list_display = [
        'event_type', 'module_name', 'tenant',
        'user', 'occurred_at'
    ]
    list_filter = [
        'event_type', 'occurred_at',
        'module', 'tenant'
    ]
    search_fields = [
        'module__module_id', 'module__name',
        'event_type', 'user__username'
    ]
    readonly_fields = ['occurred_at']
    
    fieldsets = (
        ('Event Information', {
            'fields': (
                'tenant', 'module', 'event_type',
                'user', 'occurred_at'
            )
        }),
        ('Event Data', {
            'fields': ('event_data',)
        })
    )
    
    def module_name(self, obj):
        return obj.module.name
    module_name.short_description = 'Module'
    
    def has_add_permission(self, request):
        # Events should only be created programmatically
        return False
    
    def has_change_permission(self, request, obj=None):
        # Events should not be editable
        return False