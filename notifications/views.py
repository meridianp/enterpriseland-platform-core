"""
Views for the notifications app.
"""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Count
from django.utils import timezone

from .models import (
    Notification, EmailNotification, NotificationPreference,
    NotificationTemplate
)
from .serializers import (
    NotificationSerializer, NotificationCreateSerializer,
    BulkNotificationSerializer, NotificationMarkReadSerializer,
    EmailNotificationSerializer, NotificationPreferenceSerializer,
    NotificationTemplateSerializer, NotificationStatsSerializer
)


class NotificationPermission(permissions.BasePermission):
    """Custom permission class for notifications."""
    
    def has_permission(self, request, view):
        # All authenticated users can view their notifications
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # Users can only access their own notifications
        return obj.recipient == request.user


class NotificationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for notification management.
    
    Provides CRUD operations for notifications with user-specific filtering.
    """
    
    serializer_class = NotificationSerializer
    permission_classes = [NotificationPermission]
    
    def get_queryset(self):
        """Get notifications for the current user."""
        user = self.request.user
        queryset = Notification.objects.for_user(user)
        
        # Filter by read status
        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            is_read = is_read.lower() == 'true'
            if is_read:
                queryset = queryset.read()
            else:
                queryset = queryset.unread()
        
        # Filter by type
        notification_type = self.request.query_params.get('type')
        if notification_type:
            queryset = queryset.by_type(notification_type)
        
        # Filter by priority
        priority = self.request.query_params.get('priority')
        if priority:
            queryset = queryset.filter(priority=priority)
        
        # Filter by date range
        days = self.request.query_params.get('days')
        if days:
            try:
                days = int(days)
                queryset = queryset.recent(days=days)
            except ValueError:
                pass
        
        return queryset.select_related('sender', 'content_type')
    
    def get_serializer_class(self):
        """Get appropriate serializer class."""
        if self.action == 'create':
            return NotificationCreateSerializer
        elif self.action == 'bulk_create':
            return BulkNotificationSerializer
        elif self.action == 'mark_read':
            return NotificationMarkReadSerializer
        return NotificationSerializer
    
    def perform_create(self, serializer):
        """Create notification with sender from request."""
        serializer.save(sender=self.request.user)
    
    @action(detail=False, methods=['post'])
    def mark_read(self, request):
        """Mark multiple notifications as read."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        notification_ids = serializer.validated_data['notification_ids']
        
        # Update notifications
        updated = Notification.objects.filter(
            id__in=notification_ids,
            recipient=request.user,
            is_read=False
        ).mark_all_read()
        
        return Response({
            'message': f'{updated} notifications marked as read',
            'updated_count': updated
        })
    
    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        """Mark a single notification as read."""
        notification = self.get_object()
        notification.mark_as_read()
        
        serializer = self.get_serializer(notification)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """Mark all notifications as read for the current user."""
        updated = Notification.objects.for_user(
            request.user
        ).unread().mark_all_read()
        
        return Response({
            'message': f'All notifications marked as read',
            'updated_count': updated
        })
    
    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """Create notifications for multiple recipients."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get recipients
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        recipient_ids = serializer.validated_data.pop('recipient_ids')
        recipients = User.objects.filter(id__in=recipient_ids)
        
        if not recipients.exists():
            return Response(
                {'error': 'No valid recipients found'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create notifications
        send_email = serializer.validated_data.pop('send_email', False)
        notifications = Notification.objects.create_bulk(
            recipients=recipients,
            sender=request.user,
            **serializer.validated_data
        )
        
        # Send emails if requested
        if send_email:
            for notification in notifications:
                notification.send_email()
        
        return Response({
            'message': f'{len(notifications)} notifications created',
            'notification_count': len(notifications)
        }, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get notification statistics for the current user."""
        user = request.user
        notifications = Notification.objects.for_user(user)
        
        # Calculate stats
        total = notifications.count()
        unread = notifications.unread().count()
        read = notifications.read().count()
        
        # By type
        by_type = {}
        type_counts = notifications.values('type').annotate(
            count=Count('id')
        ).order_by('-count')
        
        for item in type_counts:
            by_type[item['type']] = item['count']
        
        # By priority
        by_priority = {}
        priority_counts = notifications.values('priority').annotate(
            count=Count('id')
        ).order_by('priority')
        
        for item in priority_counts:
            by_priority[item['priority']] = item['count']
        
        # Recent notifications
        recent = notifications.order_by('-created_at')[:10]
        
        stats_data = {
            'total_notifications': total,
            'unread_count': unread,
            'read_count': read,
            'by_type': by_type,
            'by_priority': by_priority,
            'recent_notifications': recent
        }
        
        serializer = NotificationStatsSerializer(stats_data)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """Get unread notification count for the current user."""
        count = Notification.objects.for_user(
            request.user
        ).unread().count()
        
        return Response({'unread_count': count})


class NotificationPreferenceViewSet(viewsets.ModelViewSet):
    """ViewSet for managing notification preferences."""
    
    serializer_class = NotificationPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Get preferences for the current user."""
        return NotificationPreference.objects.filter(user=self.request.user)
    
    def get_object(self):
        """Get or create preferences for the current user."""
        obj, created = NotificationPreference.objects.get_or_create(
            user=self.request.user
        )
        return obj
    
    @action(detail=False, methods=['get', 'put', 'patch'])
    def me(self, request):
        """Get or update current user's preferences."""
        preference = self.get_object()
        
        if request.method == 'GET':
            serializer = self.get_serializer(preference)
            return Response(serializer.data)
        
        else:  # PUT or PATCH
            serializer = self.get_serializer(
                preference,
                data=request.data,
                partial=(request.method == 'PATCH')
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def update_type_preference(self, request):
        """Update preference for a specific notification type."""
        notification_type = request.data.get('type')
        email_enabled = request.data.get('email_enabled')
        in_app_enabled = request.data.get('in_app_enabled')
        
        if not notification_type:
            return Response(
                {'error': 'Notification type is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        preference = self.get_object()
        
        # Update type preferences
        if notification_type not in preference.type_preferences:
            preference.type_preferences[notification_type] = {}
        
        if email_enabled is not None:
            preference.type_preferences[notification_type]['email'] = email_enabled
        
        if in_app_enabled is not None:
            preference.type_preferences[notification_type]['in_app'] = in_app_enabled
        
        preference.save()
        
        serializer = self.get_serializer(preference)
        return Response(serializer.data)


class NotificationTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for managing notification templates."""
    
    queryset = NotificationTemplate.objects.filter(is_active=True)
    serializer_class = NotificationTemplateSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        """Filter templates by type if provided."""
        queryset = super().get_queryset()
        
        notification_type = self.request.query_params.get('type')
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        """Preview a template with sample data."""
        template = self.get_object()
        context = request.data.get('context', {})
        
        try:
            rendered = template.render(context)
            return Response({
                'template': {
                    'code': template.code,
                    'name': template.name
                },
                'rendered': rendered,
                'context': context
            })
        except Exception as e:
            return Response(
                {'error': f'Template rendering failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )