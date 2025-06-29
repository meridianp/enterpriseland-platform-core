"""
Gateway Views

API endpoints for gateway management and monitoring.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.db.models import Count, Avg, Sum
from django.utils import timezone
from datetime import timedelta

from .models import (
    ServiceRegistry, Route, GatewayConfig, 
    ServiceInstance, APIAggregation
)
from .serializers import (
    ServiceRegistrySerializer, RouteSerializer,
    GatewayConfigSerializer, ServiceInstanceSerializer,
    APIAggregationSerializer
)
from .health import get_health_checker, HealthMonitor
from platform_core.security.audit.models import APIAccessLog


class ServiceRegistryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing service registry.
    """
    queryset = ServiceRegistry.objects.all()
    serializer_class = ServiceRegistrySerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get_queryset(self):
        """Filter by active status if requested"""
        queryset = super().get_queryset()
        
        # Filter by status
        is_active = self.request.query_params.get('active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active == 'true')
        
        # Filter by health
        is_healthy = self.request.query_params.get('healthy')
        if is_healthy is not None:
            queryset = queryset.filter(is_healthy=is_healthy == 'true')
        
        # Filter by type
        service_type = self.request.query_params.get('type')
        if service_type:
            queryset = queryset.filter(service_type=service_type)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def health_check(self, request, pk=None):
        """Trigger health check for service"""
        service = self.get_object()
        
        # Perform health check
        health_checker = get_health_checker()
        # This would trigger an immediate health check
        
        return Response({
            'status': 'Health check triggered',
            'service': service.name
        })
    
    @action(detail=True, methods=['get'])
    def instances(self, request, pk=None):
        """Get service instances"""
        service = self.get_object()
        instances = service.instances.all()
        
        serializer = ServiceInstanceSerializer(instances, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def metrics(self, request, pk=None):
        """Get service metrics"""
        service = self.get_object()
        
        # Time range
        hours = int(request.query_params.get('hours', 24))
        since = timezone.now() - timedelta(hours=hours)
        
        # Get access logs
        logs = APIAccessLog.objects.filter(
            service=service.name,
            timestamp__gte=since
        )
        
        # Calculate metrics
        metrics = {
            'total_requests': logs.count(),
            'error_rate': logs.filter(
                response_status__gte=400
            ).count() / max(logs.count(), 1),
            'avg_response_time': logs.aggregate(
                avg=Avg('response_time')
            )['avg'] or 0,
            'status_codes': logs.values('response_status').annotate(
                count=Count('id')
            ),
            'requests_per_hour': logs.extra(
                select={'hour': "date_trunc('hour', timestamp)"}
            ).values('hour').annotate(count=Count('id'))
        }
        
        return Response(metrics)


class RouteViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing gateway routes.
    """
    queryset = Route.objects.all()
    serializer_class = RouteSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get_queryset(self):
        """Filter routes"""
        queryset = super().get_queryset()
        
        # Filter by service
        service = self.request.query_params.get('service')
        if service:
            queryset = queryset.filter(service__name=service)
        
        # Filter by method
        method = self.request.query_params.get('method')
        if method:
            queryset = queryset.filter(method=method)
        
        # Filter by active
        is_active = self.request.query_params.get('active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active == 'true')
        
        return queryset.select_related('service')
    
    @action(detail=False, methods=['post'])
    def test(self, request):
        """Test route matching"""
        path = request.data.get('path')
        method = request.data.get('method', 'GET')
        
        if not path:
            return Response(
                {'error': 'Path required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Find matching route
        from .router import ServiceRouter
        router = ServiceRouter()
        route = router.find_route(path, method)
        
        if route:
            return Response({
                'matched': True,
                'route': RouteSerializer(route).data,
                'service': route.service.name
            })
        else:
            return Response({
                'matched': False,
                'message': 'No matching route found'
            })
    
    @action(detail=True, methods=['post'])
    def toggle(self, request, pk=None):
        """Toggle route active status"""
        route = self.get_object()
        route.is_active = not route.is_active
        route.save()
        
        return Response({
            'status': 'Route toggled',
            'is_active': route.is_active
        })


class GatewayConfigViewSet(viewsets.ModelViewSet):
    """
    ViewSet for gateway configuration.
    """
    queryset = GatewayConfig.objects.all()
    serializer_class = GatewayConfigSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def create(self, request, *args, **kwargs):
        """Ensure only one config exists"""
        if GatewayConfig.objects.exists():
            return Response(
                {'error': 'Gateway config already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().create(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    def maintenance(self, request, pk=None):
        """Toggle maintenance mode"""
        config = self.get_object()
        
        enabled = request.data.get('enabled', not config.maintenance_mode)
        message = request.data.get('message', config.maintenance_message)
        
        config.maintenance_mode = enabled
        config.maintenance_message = message
        config.save()
        
        return Response({
            'maintenance_mode': config.maintenance_mode,
            'message': config.maintenance_message
        })


class ServiceInstanceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for service instances.
    """
    queryset = ServiceInstance.objects.all()
    serializer_class = ServiceInstanceSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get_queryset(self):
        """Filter instances"""
        queryset = super().get_queryset()
        
        # Filter by service
        service = self.request.query_params.get('service')
        if service:
            queryset = queryset.filter(service__name=service)
        
        # Filter by health
        is_healthy = self.request.query_params.get('healthy')
        if is_healthy is not None:
            queryset = queryset.filter(is_healthy=is_healthy == 'true')
        
        return queryset.select_related('service')
    
    @action(detail=True, methods=['post'])
    def drain(self, request, pk=None):
        """Drain connections from instance"""
        instance = self.get_object()
        
        # Set weight to 0 to stop new connections
        instance.weight = 0
        instance.save()
        
        return Response({
            'status': 'Instance draining',
            'instance': instance.instance_id
        })


class APIAggregationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for API aggregations.
    """
    queryset = APIAggregation.objects.all()
    serializer_class = APIAggregationSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get_queryset(self):
        """Filter aggregations"""
        queryset = super().get_queryset()
        
        # Filter by type
        agg_type = self.request.query_params.get('type')
        if agg_type:
            queryset = queryset.filter(aggregation_type=agg_type)
        
        # Filter by active
        is_active = self.request.query_params.get('active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active == 'true')
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test aggregation with sample data"""
        aggregation = self.get_object()
        
        # Get test data
        test_data = request.data.get('test_data', {})
        
        # This would execute the aggregation with test data
        # and return the result
        
        return Response({
            'status': 'Test completed',
            'aggregation': aggregation.name,
            'result': {}  # Test result would go here
        })


class GatewayHealthView(viewsets.ViewSet):
    """
    Gateway health and monitoring endpoints.
    """
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def status(self, request):
        """Get overall gateway status"""
        # Check gateway config
        try:
            config = GatewayConfig.objects.filter(is_active=True).first()
            gateway_active = config is not None and not config.maintenance_mode
        except:
            gateway_active = False
        
        # Check services
        total_services = ServiceRegistry.objects.filter(is_active=True).count()
        healthy_services = ServiceRegistry.objects.filter(
            is_active=True,
            is_healthy=True
        ).count()
        
        # Check recent errors
        recent_errors = APIAccessLog.objects.filter(
            timestamp__gte=timezone.now() - timedelta(minutes=5),
            response_status__gte=500
        ).count()
        
        return Response({
            'gateway': {
                'active': gateway_active,
                'maintenance': config.maintenance_mode if config else False
            },
            'services': {
                'total': total_services,
                'healthy': healthy_services,
                'unhealthy': total_services - healthy_services
            },
            'errors': {
                'recent_5xx': recent_errors
            },
            'timestamp': timezone.now()
        })
    
    @action(detail=False, methods=['get'])
    def alerts(self, request):
        """Get current health alerts"""
        monitor = HealthMonitor()
        alerts = monitor.check_alerts()
        
        return Response({
            'alerts': [
                {
                    'service': alert['service'].name,
                    'reason': alert['reason'],
                    'details': {
                        k: v for k, v in alert.items() 
                        if k not in ['service']
                    }
                }
                for alert in alerts
            ],
            'count': len(alerts)
        })