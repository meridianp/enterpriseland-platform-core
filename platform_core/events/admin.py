"""
Event System Admin Configuration
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
import json

from .models import (
    EventSchema,
    EventSubscription,
    Event,
    EventProcessor,
    SagaInstance
)


@admin.register(EventSchema)
class EventSchemaAdmin(admin.ModelAdmin):
    list_display = [
        'event_type',
        'version',
        'name',
        'exchange',
        'routing_key',
        'is_active',
        'created_at'
    ]
    list_filter = [
        'is_active',
        'version',
        'exchange',
        'created_at'
    ]
    search_fields = [
        'event_type',
        'name',
        'description'
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'formatted_schema'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'event_type',
                'version',
                'name',
                'description',
                'is_active'
            )
        }),
        ('Routing Configuration', {
            'fields': (
                'exchange',
                'routing_key',
                'ttl',
                'priority',
                'persistent'
            )
        }),
        ('Schema Definition', {
            'fields': (
                'schema',
                'formatted_schema'
            )
        }),
        ('Metadata', {
            'fields': (
                'metadata',
                'created_at',
                'updated_at'
            ),
            'classes': ['collapse']
        })
    )
    
    def formatted_schema(self, obj):
        """Display formatted JSON schema."""
        if obj.schema:
            formatted = json.dumps(obj.schema, indent=2)
            return format_html(
                '<pre style="margin: 0;">{}</pre>',
                formatted
            )
        return '-'
    formatted_schema.short_description = 'Schema (Formatted)'


@admin.register(EventSubscription)
class EventSubscriptionAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'subscription_type',
        'endpoint',
        'event_types_display',
        'is_active',
        'is_paused',
        'status_indicator'
    ]
    list_filter = [
        'is_active',
        'is_paused',
        'subscription_type',
        'retry_policy',
        'created_at'
    ]
    search_fields = [
        'name',
        'description',
        'endpoint',
        'handler'
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'last_error_at',
        'status_indicator'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'name',
                'description',
                'is_active',
                'is_paused'
            )
        }),
        ('Event Configuration', {
            'fields': (
                'event_types',
                'filter_expression'
            )
        }),
        ('Delivery Configuration', {
            'fields': (
                'subscription_type',
                'endpoint',
                'handler'
            )
        }),
        ('Processing Configuration', {
            'fields': (
                'batch_size',
                'visibility_timeout',
                'concurrent_workers'
            )
        }),
        ('Retry Configuration', {
            'fields': (
                'max_retries',
                'retry_policy',
                'retry_delay',
                'dead_letter_queue',
                'max_receive_count'
            )
        }),
        ('Status', {
            'fields': (
                'last_error',
                'last_error_at',
                'status_indicator'
            ),
            'classes': ['collapse']
        }),
        ('Metadata', {
            'fields': (
                'metadata',
                'created_at',
                'updated_at'
            ),
            'classes': ['collapse']
        })
    )
    
    actions = [
        'pause_subscriptions',
        'resume_subscriptions',
        'reset_errors'
    ]
    
    def event_types_display(self, obj):
        """Display event types as tags."""
        types = obj.event_types[:3]
        if len(obj.event_types) > 3:
            types.append(f"... +{len(obj.event_types) - 3} more")
        
        return ', '.join(types)
    event_types_display.short_description = 'Event Types'
    
    def status_indicator(self, obj):
        """Display status indicator."""
        if not obj.is_active:
            return format_html(
                '<span style="color: #999;">⚫ Inactive</span>'
            )
        elif obj.is_paused:
            return format_html(
                '<span style="color: #f39c12;">⏸ Paused</span>'
            )
        elif obj.last_error:
            return format_html(
                '<span style="color: #e74c3c;">⚠️ Error</span>'
            )
        else:
            return format_html(
                '<span style="color: #27ae60;">✅ Active</span>'
            )
    status_indicator.short_description = 'Status'
    
    def pause_subscriptions(self, request, queryset):
        """Pause selected subscriptions."""
        count = queryset.update(is_paused=True)
        self.message_user(
            request,
            f"{count} subscription(s) paused."
        )
    pause_subscriptions.short_description = 'Pause selected subscriptions'
    
    def resume_subscriptions(self, request, queryset):
        """Resume selected subscriptions."""
        count = queryset.update(is_paused=False)
        self.message_user(
            request,
            f"{count} subscription(s) resumed."
        )
    resume_subscriptions.short_description = 'Resume selected subscriptions'
    
    def reset_errors(self, request, queryset):
        """Reset errors for selected subscriptions."""
        count = queryset.update(
            last_error='',
            last_error_at=None
        )
        self.message_user(
            request,
            f"Errors reset for {count} subscription(s)."
        )
    reset_errors.short_description = 'Reset errors'


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = [
        'event_id',
        'event_type',
        'version',
        'status',
        'source',
        'user_link',
        'occurred_at'
    ]
    list_filter = [
        'status',
        'event_type',
        'version',
        'source',
        'occurred_at',
        'published_at'
    ]
    search_fields = [
        'event_id',
        'event_type',
        'correlation_id',
        'causation_id'
    ]
    readonly_fields = [
        'event_id',
        'occurred_at',
        'published_at',
        'created_at',
        'updated_at',
        'formatted_data',
        'formatted_metadata'
    ]
    date_hierarchy = 'occurred_at'
    
    fieldsets = (
        ('Event Information', {
            'fields': (
                'event_id',
                'event_type',
                'version',
                'status'
            )
        }),
        ('Event Data', {
            'fields': (
                'data',
                'formatted_data',
                'metadata',
                'formatted_metadata'
            )
        }),
        ('Context', {
            'fields': (
                'source',
                'correlation_id',
                'causation_id',
                'user'
            )
        }),
        ('Timing', {
            'fields': (
                'occurred_at',
                'published_at',
                'expires_at'
            )
        }),
        ('Publishing', {
            'fields': (
                'publish_attempts',
                'error_message'
            ),
            'classes': ['collapse']
        })
    )
    
    actions = [
        'republish_events',
        'mark_as_processed'
    ]
    
    def user_link(self, obj):
        """Link to user."""
        if obj.user:
            url = reverse('admin:auth_user_change', args=[obj.user.pk])
            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.user.username
            )
        return '-'
    user_link.short_description = 'User'
    
    def formatted_data(self, obj):
        """Display formatted event data."""
        formatted = json.dumps(obj.data, indent=2)
        return format_html(
            '<pre style="margin: 0;">{}</pre>',
            formatted
        )
    formatted_data.short_description = 'Data (Formatted)'
    
    def formatted_metadata(self, obj):
        """Display formatted metadata."""
        if obj.metadata:
            formatted = json.dumps(obj.metadata, indent=2)
            return format_html(
                '<pre style="margin: 0;">{}</pre>',
                formatted
            )
        return '-'
    formatted_metadata.short_description = 'Metadata (Formatted)'
    
    def republish_events(self, request, queryset):
        """Republish selected events."""
        from .publishers import event_publisher
        
        success_count = 0
        for event in queryset.filter(status__in=['failed', 'pending']):
            try:
                # Create message and republish
                # This is simplified - in production would use proper republishing
                event.status = 'pending'
                event.save()
                success_count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error republishing event {event.event_id}: {e}",
                    level='ERROR'
                )
        
        self.message_user(
            request,
            f"{success_count} event(s) queued for republishing."
        )
    republish_events.short_description = 'Republish selected events'
    
    def mark_as_processed(self, request, queryset):
        """Mark events as processed."""
        count = queryset.update(status='processed')
        self.message_user(
            request,
            f"{count} event(s) marked as processed."
        )
    mark_as_processed.short_description = 'Mark as processed'


@admin.register(EventProcessor)
class EventProcessorAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'event_link',
        'subscription_link',
        'status',
        'attempts',
        'started_at',
        'completed_at'
    ]
    list_filter = [
        'status',
        'subscription',
        'created_at',
        'started_at',
        'completed_at'
    ]
    search_fields = [
        'event__event_id',
        'event__event_type',
        'subscription__name'
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'formatted_result',
        'formatted_error_details'
    ]
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Processing Information', {
            'fields': (
                'event',
                'subscription',
                'status',
                'attempts'
            )
        }),
        ('Timing', {
            'fields': (
                'started_at',
                'completed_at',
                'next_retry_at'
            )
        }),
        ('Results', {
            'fields': (
                'result',
                'formatted_result'
            ),
            'classes': ['collapse']
        }),
        ('Errors', {
            'fields': (
                'error_message',
                'error_details',
                'formatted_error_details'
            ),
            'classes': ['collapse']
        })
    )
    
    def event_link(self, obj):
        """Link to event."""
        url = reverse('admin:events_event_change', args=[obj.event.pk])
        return format_html(
            '<a href="{}">{}</a>',
            url,
            obj.event.event_type
        )
    event_link.short_description = 'Event'
    
    def subscription_link(self, obj):
        """Link to subscription."""
        url = reverse('admin:events_eventsubscription_change', args=[obj.subscription.pk])
        return format_html(
            '<a href="{}">{}</a>',
            url,
            obj.subscription.name
        )
    subscription_link.short_description = 'Subscription'
    
    def formatted_result(self, obj):
        """Display formatted result."""
        if obj.result:
            formatted = json.dumps(obj.result, indent=2)
            return format_html(
                '<pre style="margin: 0;">{}</pre>',
                formatted
            )
        return '-'
    formatted_result.short_description = 'Result (Formatted)'
    
    def formatted_error_details(self, obj):
        """Display formatted error details."""
        if obj.error_details:
            formatted = json.dumps(obj.error_details, indent=2)
            return format_html(
                '<pre style="margin: 0;">{}</pre>',
                formatted
            )
        return '-'
    formatted_error_details.short_description = 'Error Details (Formatted)'


@admin.register(SagaInstance)
class SagaInstanceAdmin(admin.ModelAdmin):
    list_display = [
        'saga_id',
        'saga_type',
        'status',
        'current_step',
        'started_at',
        'completed_at'
    ]
    list_filter = [
        'status',
        'saga_type',
        'started_at',
        'completed_at'
    ]
    search_fields = [
        'saga_id',
        'saga_type',
        'correlation_id'
    ]
    readonly_fields = [
        'saga_id',
        'started_at',
        'completed_at',
        'created_at',
        'updated_at',
        'formatted_state_data'
    ]
    date_hierarchy = 'started_at'
    
    fieldsets = (
        ('Saga Information', {
            'fields': (
                'saga_id',
                'saga_type',
                'status',
                'current_step'
            )
        }),
        ('Context', {
            'fields': (
                'correlation_id',
                'initiating_event_id'
            )
        }),
        ('State', {
            'fields': (
                'state_data',
                'formatted_state_data'
            )
        }),
        ('History', {
            'fields': (
                'completed_steps',
                'compensated_steps'
            )
        }),
        ('Timing', {
            'fields': (
                'started_at',
                'completed_at',
                'expires_at'
            )
        }),
        ('Error Handling', {
            'fields': (
                'error_message',
                'retry_count'
            ),
            'classes': ['collapse']
        })
    )
    
    def formatted_state_data(self, obj):
        """Display formatted state data."""
        if obj.state_data:
            formatted = json.dumps(obj.state_data, indent=2)
            return format_html(
                '<pre style="margin: 0;">{}</pre>',
                formatted
            )
        return '-'
    formatted_state_data.short_description = 'State Data (Formatted)'