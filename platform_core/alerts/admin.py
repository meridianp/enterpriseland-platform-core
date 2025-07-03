"""
Alert Admin Configuration
"""
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from .models import AlertRule, AlertChannel, Alert, AlertNotification, AlertSilence


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'metric_name', 'condition_display', 'severity', 'enabled', 'created_at']
    list_filter = ['enabled', 'severity', 'created_at']
    search_fields = ['name', 'description', 'metric_name']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'enabled')
        }),
        ('Rule Configuration', {
            'fields': ('metric_name', 'condition', 'threshold', 'severity')
        }),
        ('Timing', {
            'fields': ('evaluation_interval', 'for_duration', 'cooldown_period', 'max_alerts_per_day')
        }),
        ('Additional Data', {
            'fields': ('labels', 'annotations'),
            'classes': ('collapse',)
        })
    )
    
    def condition_display(self, obj):
        return f"{obj.metric_name} {obj.condition} {obj.threshold}"
    condition_display.short_description = 'Condition'


@admin.register(AlertChannel)
class AlertChannelAdmin(admin.ModelAdmin):
    list_display = ['name', 'type', 'enabled', 'rate_limit', 'created_at']
    list_filter = ['type', 'enabled', 'created_at']
    search_fields = ['name']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'type', 'enabled')
        }),
        ('Configuration', {
            'fields': ('configuration',),
            'description': 'Channel-specific configuration in JSON format'
        }),
        ('Routing', {
            'fields': ('severities', 'labels', 'rate_limit')
        })
    )


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['id', 'rule_link', 'severity_badge', 'status_badge', 'value', 'fired_at', 'resolved_at']
    list_filter = ['status', 'severity', 'fired_at', 'rule']
    search_fields = ['message', 'rule__name']
    ordering = ['-fired_at']
    readonly_fields = ['rule', 'fired_at', 'fingerprint']
    
    fieldsets = (
        ('Alert Information', {
            'fields': ('rule', 'severity', 'status', 'message')
        }),
        ('Data', {
            'fields': ('value', 'labels', 'annotations')
        }),
        ('Timeline', {
            'fields': ('fired_at', 'resolved_at', 'acknowledged_at', 'acknowledged_by')
        }),
        ('Notifications', {
            'fields': ('notified_channels', 'notification_count', 'last_notification_at'),
            'classes': ('collapse',)
        }),
        ('Technical', {
            'fields': ('fingerprint',),
            'classes': ('collapse',)
        })
    )
    
    actions = ['acknowledge_alerts', 'resolve_alerts']
    
    def rule_link(self, obj):
        return format_html(
            '<a href="/admin/alerts/alertrule/{}/change/">{}</a>',
            obj.rule.id,
            obj.rule.name
        )
    rule_link.short_description = 'Rule'
    
    def severity_badge(self, obj):
        colors = {
            'info': '#17a2b8',
            'warning': '#ffc107',
            'error': '#dc3545',
            'critical': '#721c24'
        }
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 3px; color: white; background-color: {};">{}</span>',
            colors.get(obj.severity, '#6c757d'),
            obj.severity.upper()
        )
    severity_badge.short_description = 'Severity'
    
    def status_badge(self, obj):
        colors = {
            'pending': '#6c757d',
            'firing': '#dc3545',
            'resolved': '#28a745',
            'acknowledged': '#17a2b8',
            'silenced': '#ffc107'
        }
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 3px; color: white; background-color: {};">{}</span>',
            colors.get(obj.status, '#6c757d'),
            obj.status.upper()
        )
    status_badge.short_description = 'Status'
    
    def acknowledge_alerts(self, request, queryset):
        count = 0
        for alert in queryset:
            if alert.status in ['pending', 'firing']:
                alert.acknowledge(request.user)
                count += 1
        self.message_user(request, f'{count} alerts acknowledged.')
    acknowledge_alerts.short_description = 'Acknowledge selected alerts'
    
    def resolve_alerts(self, request, queryset):
        count = 0
        for alert in queryset:
            if alert.status != 'resolved':
                alert.resolve()
                count += 1
        self.message_user(request, f'{count} alerts resolved.')
    resolve_alerts.short_description = 'Resolve selected alerts'


@admin.register(AlertNotification)
class AlertNotificationAdmin(admin.ModelAdmin):
    list_display = ['alert', 'channel', 'sent_at', 'success', 'error_message']
    list_filter = ['success', 'sent_at', 'channel']
    search_fields = ['alert__message', 'error_message']
    ordering = ['-sent_at']
    readonly_fields = ['alert', 'channel', 'sent_at']


@admin.register(AlertSilence)
class AlertSilenceAdmin(admin.ModelAdmin):
    list_display = ['name', 'active_badge', 'created_by', 'starts_at', 'ends_at']
    list_filter = ['active', 'starts_at', 'ends_at']
    search_fields = ['name', 'description']
    ordering = ['-created_at']
    readonly_fields = ['created_by', 'created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'active')
        }),
        ('Silence Criteria', {
            'fields': ('matchers',),
            'description': 'Label matchers in JSON format'
        }),
        ('Time Range', {
            'fields': ('starts_at', 'ends_at')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',)
        })
    )
    
    def active_badge(self, obj):
        if not obj.active:
            return format_html('<span style="color: #6c757d;">Inactive</span>')
        
        now = timezone.now()
        if now < obj.starts_at:
            return format_html('<span style="color: #ffc107;">Scheduled</span>')
        elif now > obj.ends_at:
            return format_html('<span style="color: #dc3545;">Expired</span>')
        else:
            return format_html('<span style="color: #28a745;">Active</span>')
    active_badge.short_description = 'Status'
    
    def save_model(self, request, obj, form, change):
        if not change:  # Creating new object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)