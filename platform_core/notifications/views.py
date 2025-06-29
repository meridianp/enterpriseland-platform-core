
from rest_framework import viewsets
from platform_core.core.views import PlatformViewSet, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

from accounts.permissions import RoleBasedPermission, IsAdminOrReadOnly
from .models import Notification, EmailNotification, WebhookEndpoint, WebhookDelivery
from .serializers import (
    NotificationSerializer, EmailNotificationSerializer,
    WebhookEndpointSerializer, WebhookDeliverySerializer
)

class NotificationViewSet(PlatformViewSet):
    """ViewSet for notifications"""
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter notifications for current user"""
        return Notification.objects.filter(recipient=self.request.user)
    
    @action(detail=False, methods=['get'])
    def unread(self, request):
        """Get unread notifications"""
        notifications = self.get_queryset().filter(is_read=False)
        serializer = self.get_serializer(notifications, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Mark notification as read"""
        notification = self.get_object()
        notification.mark_as_read()
        serializer = self.get_serializer(notification)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """Mark all notifications as read"""
        notifications = self.get_queryset().filter(is_read=False)
        for notification in notifications:
            notification.mark_as_read()
        
        return Response({'message': f'Marked {notifications.count()} notifications as read'})
    
    @action(detail=False, methods=['get'])
    def count(self, request):
        """Get notification counts"""
        total = self.get_queryset().count()
        unread = self.get_queryset().filter(is_read=False).count()
        
        return Response({
            'total': total,
            'unread': unread
        })

class EmailNotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for email notifications (read-only)"""
    queryset = EmailNotification.objects.all()
    serializer_class = EmailNotificationSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]
    
    def get_queryset(self):
        """Only admins can view email notifications"""
        user = self.request.user
        if user.role != user.Role.ADMIN:
            return EmailNotification.objects.none()
        
        return EmailNotification.objects.all()

class WebhookEndpointViewSet(PlatformViewSet):
    """ViewSet for webhook endpoints"""
    queryset = WebhookEndpoint.objects.all()
    serializer_class = WebhookEndpointSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
    
    def perform_create(self, serializer):
        """Set created_by when creating webhook"""
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test webhook endpoint"""
        endpoint = self.get_object()
        
        # Create test delivery
        test_payload = {
            'event': 'webhook.test',
            'timestamp': timezone.now().isoformat(),
            'data': {'message': 'This is a test webhook delivery'}
        }
        
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_type='webhook.test',
            payload=test_payload
        )
        
        # Trigger webhook delivery task
        from .tasks import deliver_webhook
        deliver_webhook.delay(delivery.id)
        
        return Response({
            'message': 'Test webhook queued for delivery',
            'delivery_id': delivery.id
        })

class WebhookDeliveryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for webhook deliveries (read-only)"""
    queryset = WebhookDelivery.objects.all()
    serializer_class = WebhookDeliverySerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Retry failed webhook delivery"""
        delivery = self.get_object()
        
        if delivery.status != WebhookDelivery.Status.FAILED:
            return Response(
                {'error': 'Only failed deliveries can be retried'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if delivery.attempt_count >= delivery.max_attempts:
            return Response(
                {'error': 'Maximum retry attempts exceeded'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Reset status and trigger retry
        delivery.status = WebhookDelivery.Status.PENDING
        delivery.save()
        
        from .tasks import deliver_webhook
        deliver_webhook.delay(delivery.id)
        
        return Response({'message': 'Webhook delivery retry queued'})
