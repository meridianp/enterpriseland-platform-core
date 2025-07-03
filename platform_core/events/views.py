"""
Event System Views
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Count, Q, Avg
from datetime import timedelta

from platform_core.common.views import BaseViewSet
from .models import (
    EventSchema,
    EventSubscription,
    Event,
    EventProcessor,
    SagaInstance
)
from .serializers import (
    EventSchemaSerializer,
    EventSubscriptionSerializer,
    EventSerializer,
    EventProcessorSerializer,
    SagaInstanceSerializer,
    EventPublishSerializer
)
from .publishers import event_publisher
from .consumers import consumer_manager


class EventSchemaViewSet(BaseViewSet):
    """ViewSet for event schemas."""
    
    queryset = EventSchema.objects.all()
    serializer_class = EventSchemaSerializer
    filterset_fields = ['event_type', 'version', 'is_active', 'exchange']
    search_fields = ['event_type', 'name', 'description']
    ordering_fields = ['event_type', 'version', 'created_at']
    ordering = ['-created_at']
    
    @action(detail=True, methods=['post'])
    def validate(self, request, pk=None):
        """Validate data against schema."""
        schema = self.get_object()
        data = request.data.get('data', {})
        
        is_valid = schema.validate_event_data(data)
        
        return Response({
            'valid': is_valid,
            'event_type': schema.event_type,
            'version': schema.version
        })
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get all active schemas."""
        schemas = self.filter_queryset(
            self.get_queryset().filter(is_active=True)
        )
        
        serializer = self.get_serializer(schemas, many=True)
        return Response(serializer.data)


class EventSubscriptionViewSet(BaseViewSet):
    """ViewSet for event subscriptions."""
    
    queryset = EventSubscription.objects.all()
    serializer_class = EventSubscriptionSerializer
    filterset_fields = ['is_active', 'is_paused', 'subscription_type']
    search_fields = ['name', 'description', 'endpoint']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    
    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Pause subscription."""
        subscription = self.get_object()
        subscription.is_paused = True
        subscription.save()
        
        # Stop consumer if running
        consumer_manager.stop_consumer(subscription.name)
        
        return Response({
            'status': 'paused',
            'subscription': subscription.name
        })
    
    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """Resume subscription."""
        subscription = self.get_object()
        subscription.is_paused = False
        subscription.last_error = ''
        subscription.last_error_at = None
        subscription.save()
        
        # Start consumer
        consumer_manager.start_consumer(subscription)
        
        return Response({
            'status': 'resumed',
            'subscription': subscription.name
        })
    
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Get subscription statistics."""
        subscription = self.get_object()
        
        # Get processing stats
        stats = EventProcessor.objects.filter(
            subscription=subscription
        ).aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            failed=Count('id', filter=Q(status='failed')),
            pending=Count('id', filter=Q(status='pending')),
            avg_processing_time=Avg(
                'completed_at' - 'started_at',
                filter=Q(status='completed')
            )
        )
        
        # Get recent errors
        recent_errors = EventProcessor.objects.filter(
            subscription=subscription,
            status='failed',
            updated_at__gte=timezone.now() - timedelta(hours=24)
        ).count()
        
        return Response({
            'subscription': subscription.name,
            'is_active': subscription.is_active and not subscription.is_paused,
            'statistics': {
                'total_processed': stats['total'],
                'completed': stats['completed'],
                'failed': stats['failed'],
                'pending': stats['pending'],
                'success_rate': (
                    stats['completed'] / stats['total'] * 100
                    if stats['total'] > 0 else 0
                ),
                'avg_processing_time': stats['avg_processing_time'],
                'recent_errors_24h': recent_errors
            }
        })


class EventViewSet(BaseViewSet):
    """ViewSet for events."""
    
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    filterset_fields = ['event_type', 'status', 'source', 'version']
    search_fields = ['event_id', 'event_type', 'correlation_id']
    ordering_fields = ['occurred_at', 'created_at']
    ordering = ['-occurred_at']
    
    @action(detail=True, methods=['post'])
    def republish(self, request, pk=None):
        """Republish a failed event."""
        event = self.get_object()
        
        if event.status not in ['failed', 'pending']:
            return Response(
                {'error': 'Can only republish failed or pending events'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Reset status and attempt republish
        event.status = 'pending'
        event.publish_attempts += 1
        event.save()
        
        # This would trigger republishing logic
        # In production, this would be handled by a background task
        
        return Response({
            'status': 'queued',
            'event_id': str(event.event_id),
            'attempts': event.publish_attempts
        })
    
    @action(detail=False, methods=['get'])
    def failed(self, request):
        """Get all failed events."""
        events = self.filter_queryset(
            self.get_queryset().filter(status='failed')
        )
        
        page = self.paginate_queryset(events)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_correlation(self, request):
        """Get all events with same correlation ID."""
        correlation_id = request.query_params.get('correlation_id')
        
        if not correlation_id:
            return Response(
                {'error': 'correlation_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        events = self.filter_queryset(
            self.get_queryset().filter(correlation_id=correlation_id)
        ).order_by('occurred_at')
        
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)


class EventProcessorViewSet(BaseViewSet):
    """ViewSet for event processors."""
    
    queryset = EventProcessor.objects.all()
    serializer_class = EventProcessorSerializer
    filterset_fields = ['status', 'subscription']
    ordering_fields = ['created_at', 'started_at', 'completed_at']
    ordering = ['-created_at']
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Retry processing."""
        processor = self.get_object()
        
        if processor.status not in ['failed', 'pending']:
            return Response(
                {'error': 'Can only retry failed or pending processors'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Reset for retry
        processor.status = 'pending'
        processor.next_retry_at = timezone.now()
        processor.save()
        
        return Response({
            'status': 'queued',
            'processor_id': processor.id,
            'attempts': processor.attempts + 1
        })


class SagaInstanceViewSet(BaseViewSet):
    """ViewSet for saga instances."""
    
    queryset = SagaInstance.objects.all()
    serializer_class = SagaInstanceSerializer
    filterset_fields = ['saga_type', 'status']
    search_fields = ['saga_id', 'correlation_id']
    ordering_fields = ['started_at', 'completed_at']
    ordering = ['-started_at']
    
    @action(detail=True, methods=['post'])
    def compensate(self, request, pk=None):
        """Start compensation for saga."""
        saga = self.get_object()
        
        if saga.status == 'completed':
            return Response(
                {'error': 'Cannot compensate completed saga'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        saga.start_compensation()
        
        return Response({
            'status': 'compensating',
            'saga_id': str(saga.saga_id),
            'compensated_steps': saga.compensated_steps
        })


class EventPublishView(APIView):
    """API endpoint for publishing events."""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Publish an event."""
        serializer = EventPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            event = event_publisher.publish(
                event_type=serializer.validated_data['event_type'],
                data=serializer.validated_data['data'],
                user=request.user,
                correlation_id=serializer.validated_data.get('correlation_id'),
                metadata=serializer.validated_data.get('metadata'),
                version=serializer.validated_data.get('version', '1.0'),
                source=serializer.validated_data.get('source', 'api')
            )
            
            return Response({
                'status': 'published',
                'event_id': str(event.event_id),
                'event_type': event.event_type,
                'correlation_id': event.correlation_id
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                'error': str(e),
                'event_type': serializer.validated_data['event_type']
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EventStatusView(APIView):
    """Get event processing status."""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, event_id):
        """Get event status."""
        event = get_object_or_404(Event, event_id=event_id)
        
        # Get processing status
        processors = EventProcessor.objects.filter(event=event)
        
        return Response({
            'event_id': str(event.event_id),
            'event_type': event.event_type,
            'status': event.status,
            'occurred_at': event.occurred_at,
            'published_at': event.published_at,
            'processors': [
                {
                    'subscription': proc.subscription.name,
                    'status': proc.status,
                    'attempts': proc.attempts,
                    'started_at': proc.started_at,
                    'completed_at': proc.completed_at,
                    'error': proc.error_message if proc.status == 'failed' else None
                }
                for proc in processors
            ]
        })


class SubscriptionHealthView(APIView):
    """Get subscription health status."""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, name):
        """Get subscription health."""
        subscription = get_object_or_404(EventSubscription, name=name)
        
        # Check if consumer is running
        consumer_status = consumer_manager.get_status()
        is_running = name in consumer_status['consumers']
        
        # Get recent processing stats
        recent_stats = EventProcessor.objects.filter(
            subscription=subscription,
            updated_at__gte=timezone.now() - timedelta(hours=1)
        ).aggregate(
            total=Count('id'),
            failed=Count('id', filter=Q(status='failed'))
        )
        
        # Calculate health score
        if recent_stats['total'] > 0:
            error_rate = recent_stats['failed'] / recent_stats['total']
            health_score = max(0, 100 - (error_rate * 100))
        else:
            health_score = 100 if is_running else 0
        
        return Response({
            'subscription': subscription.name,
            'health_score': health_score,
            'status': {
                'is_active': subscription.is_active,
                'is_paused': subscription.is_paused,
                'is_running': is_running,
                'has_errors': bool(subscription.last_error)
            },
            'recent_stats': recent_stats,
            'last_error': {
                'message': subscription.last_error,
                'timestamp': subscription.last_error_at
            } if subscription.last_error else None
        })