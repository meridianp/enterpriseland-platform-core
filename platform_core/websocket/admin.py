"""
WebSocket Admin Configuration
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone

from .models import (
    WebSocketConnection,
    WebSocketRoom,
    WebSocketMessage,
    WebSocketPresence
)


@admin.register(WebSocketConnection)
class WebSocketConnectionAdmin(admin.ModelAdmin):
    list_display = [
        'connection_id',
        'user_link',
        'state',
        'ip_address',
        'protocol',
        'connected_at',
        'duration_display'
    ]
    list_filter = [
        'state',
        'protocol',
        'connected_at',
        'disconnected_at'
    ]
    search_fields = [
        'connection_id',
        'user__username',
        'ip_address',
        'channel_name'
    ]
    readonly_fields = [
        'connection_id',
        'channel_name',
        'connected_at',
        'last_seen_at',
        'disconnected_at',
        'duration_display'
    ]
    date_hierarchy = 'connected_at'
    
    fieldsets = (
        ('Connection Info', {
            'fields': (
                'connection_id',
                'channel_name',
                'user',
                'session_key',
                'state'
            )
        }),
        ('Client Info', {
            'fields': (
                'ip_address',
                'user_agent',
                'protocol',
                'path',
                'query_params'
            )
        }),
        ('Subscriptions', {
            'fields': (
                'subscribed_rooms',
                'subscribed_channels'
            )
        }),
        ('Timing', {
            'fields': (
                'connected_at',
                'last_seen_at',
                'disconnected_at',
                'duration_display'
            )
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ['collapse']
        })
    )
    
    actions = ['force_disconnect']
    
    def user_link(self, obj):
        """Link to user."""
        if obj.user:
            url = reverse('admin:auth_user_change', args=[obj.user.pk])
            return format_html('<a href="{}">{}</a>', url, obj.user.username)
        return '-'
    user_link.short_description = 'User'
    
    def duration_display(self, obj):
        """Display connection duration."""
        if obj.duration:
            total_seconds = int(obj.duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            
            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return '-'
    duration_display.short_description = 'Duration'
    
    def force_disconnect(self, request, queryset):
        """Force disconnect selected connections."""
        count = 0
        for connection in queryset.filter(state='open'):
            connection.close()
            count += 1
        
        self.message_user(request, f"{count} connection(s) disconnected.")
    force_disconnect.short_description = 'Force disconnect selected connections'


@admin.register(WebSocketRoom)
class WebSocketRoomAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'display_name',
        'room_type',
        'is_active',
        'connection_count_display',
        'owner_link',
        'created_at'
    ]
    list_filter = [
        'room_type',
        'is_active',
        'is_persistent',
        'require_authentication',
        'enable_presence',
        'enable_history'
    ]
    search_fields = [
        'name',
        'display_name',
        'description',
        'owner__username'
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'connection_count_display'
    ]
    filter_horizontal = ['allowed_users']
    
    fieldsets = (
        ('Basic Info', {
            'fields': (
                'name',
                'display_name',
                'room_type',
                'description',
                'is_active',
                'is_persistent'
            )
        }),
        ('Access Control', {
            'fields': (
                'owner',
                'allowed_users',
                'require_authentication',
                'max_connections'
            )
        }),
        ('Features', {
            'fields': (
                'enable_presence',
                'enable_history',
                'enable_typing',
                'message_retention_days'
            )
        }),
        ('Status', {
            'fields': (
                'connection_count_display',
                'created_at',
                'updated_at'
            )
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ['collapse']
        })
    )
    
    def owner_link(self, obj):
        """Link to owner."""
        if obj.owner:
            url = reverse('admin:auth_user_change', args=[obj.owner.pk])
            return format_html('<a href="{}">{}</a>', url, obj.owner.username)
        return '-'
    owner_link.short_description = 'Owner'
    
    def connection_count_display(self, obj):
        """Display active connection count."""
        count = obj.connection_count
        max_connections = obj.max_connections
        
        if max_connections > 0:
            percentage = (count / max_connections) * 100
            color = 'green' if percentage < 80 else 'orange' if percentage < 100 else 'red'
            return format_html(
                '<span style="color: {};">{} / {}</span>',
                color, count, max_connections
            )
        return str(count)
    connection_count_display.short_description = 'Active Connections'


@admin.register(WebSocketMessage)
class WebSocketMessageAdmin(admin.ModelAdmin):
    list_display = [
        'message_id',
        'sender_link',
        'room_link',
        'message_type',
        'delivery_status',
        'content_preview',
        'created_at'
    ]
    list_filter = [
        'message_type',
        'delivery_status',
        'created_at'
    ]
    search_fields = [
        'message_id',
        'sender__username',
        'content'
    ]
    readonly_fields = [
        'message_id',
        'created_at',
        'delivered_at'
    ]
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Message Info', {
            'fields': (
                'message_id',
                'message_type',
                'content',
                'metadata'
            )
        }),
        ('Source/Destination', {
            'fields': (
                'sender',
                'connection',
                'room',
                'recipient'
            )
        }),
        ('Delivery', {
            'fields': (
                'delivery_status',
                'delivered_at',
                'expires_at'
            )
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
                'updated_at'
            )
        })
    )
    
    def sender_link(self, obj):
        """Link to sender."""
        if obj.sender:
            url = reverse('admin:auth_user_change', args=[obj.sender.pk])
            return format_html('<a href="{}">{}</a>', url, obj.sender.username)
        return '-'
    sender_link.short_description = 'Sender'
    
    def room_link(self, obj):
        """Link to room."""
        if obj.room:
            url = reverse('admin:websocket_websocketroom_change', args=[obj.room.pk])
            return format_html('<a href="{}">{}</a>', url, obj.room.name)
        return '-'
    room_link.short_description = 'Room'
    
    def content_preview(self, obj):
        """Preview of message content."""
        max_length = 100
        if len(obj.content) > max_length:
            return obj.content[:max_length] + '...'
        return obj.content
    content_preview.short_description = 'Content'


@admin.register(WebSocketPresence)
class WebSocketPresenceAdmin(admin.ModelAdmin):
    list_display = [
        'user_link',
        'room_link',
        'status',
        'status_message',
        'connection_count',
        'joined_at',
        'last_activity_at'
    ]
    list_filter = [
        'status',
        'joined_at',
        'last_activity_at'
    ]
    search_fields = [
        'user__username',
        'room__name',
        'status_message'
    ]
    readonly_fields = [
        'joined_at',
        'last_activity_at'
    ]
    date_hierarchy = 'last_activity_at'
    
    fieldsets = (
        ('User & Room', {
            'fields': (
                'user',
                'room'
            )
        }),
        ('Status', {
            'fields': (
                'status',
                'status_message',
                'connection_count'
            )
        }),
        ('Timing', {
            'fields': (
                'joined_at',
                'last_activity_at'
            )
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ['collapse']
        })
    )
    
    actions = ['set_online', 'set_away', 'set_offline']
    
    def user_link(self, obj):
        """Link to user."""
        url = reverse('admin:auth_user_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def room_link(self, obj):
        """Link to room."""
        url = reverse('admin:websocket_websocketroom_change', args=[obj.room.pk])
        return format_html('<a href="{}">{}</a>', url, obj.room.name)
    room_link.short_description = 'Room'
    
    def set_online(self, request, queryset):
        """Set users as online."""
        count = queryset.update(status='online', last_activity_at=timezone.now())
        self.message_user(request, f"{count} user(s) set to online.")
    set_online.short_description = 'Set selected users as online'
    
    def set_away(self, request, queryset):
        """Set users as away."""
        count = queryset.update(status='away')
        self.message_user(request, f"{count} user(s) set to away.")
    set_away.short_description = 'Set selected users as away'
    
    def set_offline(self, request, queryset):
        """Set users as offline."""
        count = queryset.update(status='offline', connection_count=0)
        self.message_user(request, f"{count} user(s) set to offline.")
    set_offline.short_description = 'Set selected users as offline'