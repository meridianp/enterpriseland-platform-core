"""
Alert API Views
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters import rest_framework as filters

from .models import Alert, AlertRule, AlertChannel, AlertNotification, AlertSilence
from .serializers import (
    AlertSerializer, AlertRuleSerializer, AlertChannelSerializer,
    AlertNotificationSerializer, AlertSilenceSerializer, AlertStatsSerializer,
    AcknowledgeAlertSerializer, TestAlertSerializer
)
from .services import AlertManager, AlertProcessor


class AlertRuleFilter(filters.FilterSet):
    """Alert rule filters"""
    severity = filters.ChoiceFilter(choices=['info', 'warning', 'error', 'critical'])
    enabled = filters.BooleanFilter()
    metric_name = filters.CharFilter(lookup_expr='icontains')
    
    class Meta:
        model = AlertRule
        fields = ['severity', 'enabled', 'metric_name']


class AlertRuleViewSet(viewsets.ModelViewSet):
    """Alert rule management"""
    queryset = AlertRule.objects.all()
    serializer_class = AlertRuleSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = AlertRuleFilter
    search_fields = ['name', 'description', 'metric_name']
    ordering_fields = ['name', 'severity', 'created_at']
    ordering = ['name']
    
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test alert rule with custom value"""
        rule = self.get_object()
        serializer = TestAlertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        value = serializer.validated_data['value']
        message = serializer.validated_data.get('message', '')
        
        # Create test alert
        processor = AlertProcessor()
        alert = Alert.objects.create(
            rule=rule,
            severity=rule.severity,
            status='firing',
            value=value,
            message=message or processor._format_message(rule, value),
            labels={**rule.labels, 'test': True},
            annotations=rule.annotations,
            fingerprint=f"test_{rule.id}_{timezone.now().timestamp()}"
        )
        
        return Response(
            AlertSerializer(alert).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """Duplicate alert rule"""
        rule = self.get_object()
        
        # Create new rule
        new_rule = AlertRule.objects.create(
            name=f"{rule.name} (Copy)",
            description=rule.description,
            metric_name=rule.metric_name,
            condition=rule.condition,
            threshold=rule.threshold,
            evaluation_interval=rule.evaluation_interval,
            for_duration=rule.for_duration,
            severity=rule.severity,
            labels=rule.labels,
            annotations=rule.annotations,
            enabled=False,  # Start disabled
            cooldown_period=rule.cooldown_period,
            max_alerts_per_day=rule.max_alerts_per_day
        )
        
        return Response(
            AlertRuleSerializer(new_rule).data,
            status=status.HTTP_201_CREATED
        )


class AlertChannelViewSet(viewsets.ModelViewSet):
    """Alert channel management"""
    queryset = AlertChannel.objects.all()
    serializer_class = AlertChannelSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['type', 'enabled']
    search_fields = ['name']
    ordering_fields = ['name', 'type', 'created_at']
    ordering = ['name']
    
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test channel with sample alert"""
        channel = self.get_object()
        
        # Create test alert
        test_alert = Alert(
            rule=AlertRule.objects.first(),  # Use any rule
            severity='info',
            status='firing',
            value=42.0,
            message='This is a test alert from EnterpriseLand',
            labels={'test': True},
            annotations={'description': 'Testing notification channel'},
            fired_at=timezone.now(),
            fingerprint='test_channel'
        )
        
        # Send notification
        manager = AlertManager()
        success = manager._send_to_channel(test_alert, channel)
        
        return Response({
            'success': success,
            'channel': channel.name,
            'message': 'Test notification sent' if success else 'Test notification failed'
        })


class AlertFilter(filters.FilterSet):
    """Alert filters"""
    severity = filters.ChoiceFilter(choices=['info', 'warning', 'error', 'critical'])
    status = filters.ChoiceFilter(choices=['pending', 'firing', 'resolved', 'acknowledged', 'silenced'])
    rule = filters.ModelChoiceFilter(queryset=AlertRule.objects.all())
    fired_after = filters.DateTimeFilter(field_name='fired_at', lookup_expr='gte')
    fired_before = filters.DateTimeFilter(field_name='fired_at', lookup_expr='lte')
    
    class Meta:
        model = Alert
        fields = ['severity', 'status', 'rule', 'fired_after', 'fired_before']


class AlertViewSet(viewsets.ModelViewSet):
    """Alert management"""
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = AlertFilter
    search_fields = ['message', 'rule__name']
    ordering_fields = ['fired_at', 'severity', 'status']
    ordering = ['-fired_at']
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    
    @action(detail=False, methods=['post'])
    def acknowledge(self, request):
        """Acknowledge multiple alerts"""
        serializer = AcknowledgeAlertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        alert_ids = serializer.validated_data['alert_ids']
        manager = AlertManager()
        
        acknowledged = []
        for alert_id in alert_ids:
            if manager.acknowledge_alert(alert_id, request.user):
                acknowledged.append(alert_id)
        
        return Response({
            'acknowledged': acknowledged,
            'count': len(acknowledged)
        })
    
    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Resolve alert"""
        alert = self.get_object()
        manager = AlertManager()
        
        if manager.resolve_alert(alert.id):
            return Response({'status': 'resolved'})
        
        return Response(
            {'error': 'Failed to resolve alert'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    @action(detail=True, methods=['post'])
    def silence(self, request, pk=None):
        """Silence alert"""
        alert = self.get_object()
        duration = request.data.get('duration', 14400)  # 4 hours default
        
        alert.silence(duration)
        
        return Response({
            'status': 'silenced',
            'duration': duration
        })
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get alert statistics"""
        manager = AlertManager()
        stats = manager.get_alert_stats()
        
        serializer = AlertStatsSerializer(stats)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def notifications(self, request, pk=None):
        """Get alert notifications"""
        alert = self.get_object()
        notifications = alert.notifications.all()
        
        serializer = AlertNotificationSerializer(notifications, many=True)
        return Response(serializer.data)


class AlertSilenceViewSet(viewsets.ModelViewSet):
    """Alert silence management"""
    queryset = AlertSilence.objects.all()
    serializer_class = AlertSilenceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['active']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'starts_at', 'ends_at']
    ordering = ['-created_at']
    
    def perform_create(self, serializer):
        """Set created_by to current user"""
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def expire(self, request, pk=None):
        """Expire silence immediately"""
        silence = self.get_object()
        silence.active = False
        silence.ends_at = timezone.now()
        silence.save()
        
        return Response({'status': 'expired'})
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get active silences"""
        now = timezone.now()
        active_silences = self.get_queryset().filter(
            active=True,
            starts_at__lte=now,
            ends_at__gte=now
        )
        
        serializer = self.get_serializer(active_silences, many=True)
        return Response(serializer.data)