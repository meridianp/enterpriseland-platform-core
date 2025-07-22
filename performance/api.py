"""
Performance Monitoring API

REST API endpoints for performance monitoring and SLA tracking.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.utils import timezone
from datetime import datetime, timedelta
import asyncio

from .sla_monitoring import SLAMonitoringService, PerformanceMetric
from .load_testing import LoadTestFramework, LoadTestScenario
from .auto_scaling import AutoScalingManager


class PerformanceMonitoringViewSet(viewsets.ViewSet):
    """
    ViewSet for performance monitoring and SLA tracking.
    
    Endpoints:
    - /api/performance/metrics/ - Current performance metrics
    - /api/performance/sla-status/ - SLA compliance status
    - /api/performance/sla-report/ - Generate SLA report
    - /api/performance/load-test/ - Run load test
    - /api/performance/scaling-status/ - Auto-scaling status
    """
    permission_classes = [IsAuthenticated]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sla_service = SLAMonitoringService()
        self.scaling_manager = AutoScalingManager()
    
    @action(detail=False, methods=['get'])
    def metrics(self, request):
        """
        Get current performance metrics.
        
        Query params:
        - endpoint: Specific endpoint to filter by
        - period: Time period (5m, 15m, 1h, 24h)
        """
        endpoint = request.query_params.get('endpoint')
        period = request.query_params.get('period', '15m')
        
        # Get current metrics
        metrics = self.sla_service.get_current_metrics(endpoint)
        
        # Add period-specific calculations
        metrics['period'] = period
        metrics['summary'] = self._calculate_period_summary(period)
        
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def sla_status(self, request):
        """
        Get current SLA compliance status.
        
        Returns real-time SLA compliance for all metrics.
        """
        statuses = self.sla_service.check_sla_compliance()
        
        # Format response
        response_data = {
            'timestamp': timezone.now(),
            'overall_compliance': all(not s.is_breached for s in statuses),
            'metrics': []
        }
        
        for status in statuses:
            response_data['metrics'].append({
                'metric': status.metric,
                'current_value': float(status.current_value),
                'target_value': float(status.target_value),
                'is_breached': status.is_breached,
                'breach_count': status.breach_count,
                'last_breach': status.last_breach,
                'trend': status.trend,
                'status': 'BREACH' if status.is_breached else 'OK'
            })
        
        return Response(response_data)
    
    @action(detail=False, methods=['post'])
    def sla_report(self, request):
        """
        Generate SLA compliance report.
        
        Request body:
        - start_date: Report start date (ISO format)
        - end_date: Report end date (ISO format)
        - format: Report format (json, pdf, excel)
        """
        # Validate dates
        try:
            start_date = datetime.fromisoformat(
                request.data.get('start_date', '')
            )
            end_date = datetime.fromisoformat(
                request.data.get('end_date', '')
            )
        except (ValueError, TypeError):
            return Response(
                {'error': 'Invalid date format. Use ISO format.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate report
        report = self.sla_service.generate_sla_report(start_date, end_date)
        
        # Format based on requested format
        report_format = request.data.get('format', 'json')
        
        if report_format == 'json':
            return Response(report)
        elif report_format in ['pdf', 'excel']:
            # In production, would generate actual file
            return Response({
                'message': f'{report_format.upper()} report generation not implemented',
                'report_data': report
            })
        else:
            return Response(
                {'error': f'Unsupported format: {report_format}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'], permission_classes=[IsAdminUser])
    def load_test(self, request):
        """
        Run a load test scenario.
        
        Request body:
        - scenario: Scenario name (baseline, peak_load, stress_test, endurance_test)
        - custom_config: Optional custom configuration
        """
        scenario_name = request.data.get('scenario', 'baseline')
        custom_config = request.data.get('custom_config', {})
        
        # Initialize load test framework
        base_url = request.build_absolute_uri('/api/')
        auth_token = request.auth.token if hasattr(request, 'auth') else None
        
        framework = LoadTestFramework(base_url, auth_token)
        
        # Get or create scenario
        if scenario_name in framework.SCENARIOS:
            scenario = framework.SCENARIOS[scenario_name]
            
            # Apply custom config if provided
            if custom_config:
                for key, value in custom_config.items():
                    if hasattr(scenario, key):
                        setattr(scenario, key, value)
        else:
            return Response(
                {'error': f'Unknown scenario: {scenario_name}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Run load test asynchronously
        try:
            # For API response, we'll validate SLAs instead of full test
            passed, results = framework.run_sla_validation(scenario_name)
            
            return Response({
                'scenario': scenario_name,
                'sla_validation': results,
                'passed': passed,
                'message': 'Load test completed successfully' if passed else 'SLA violations detected'
            })
            
        except Exception as e:
            return Response(
                {'error': f'Load test failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def scaling_status(self, request):
        """
        Get current auto-scaling status and recommendations.
        
        Returns scaling recommendations for all services.
        """
        recommendations = self.scaling_manager.get_scaling_recommendations()
        
        # Add overall summary
        response_data = {
            'timestamp': timezone.now(),
            'services': recommendations,
            'summary': {
                'total_services': len(recommendations),
                'scaling_needed': sum(
                    1 for r in recommendations.values()
                    if r['direction'] != 'none'
                ),
                'total_replicas': sum(
                    r['current_replicas'] for r in recommendations.values()
                ),
                'recommended_replicas': sum(
                    r['recommended_replicas'] for r in recommendations.values()
                )
            }
        }
        
        return Response(response_data)
    
    @action(detail=False, methods=['post'], permission_classes=[IsAdminUser])
    def execute_scaling(self, request):
        """
        Execute scaling recommendation for a service.
        
        Request body:
        - service: Service name
        - target_replicas: Target replica count
        """
        service_name = request.data.get('service')
        target_replicas = request.data.get('target_replicas')
        
        if not service_name or target_replicas is None:
            return Response(
                {'error': 'service and target_replicas are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get current metrics for the service
        from .auto_scaling import ScalingMetrics, ScalingDecision, ScalingDirection
        
        # This would get real metrics in production
        current_metrics = ScalingMetrics(
            timestamp=timezone.now(),
            cpu_usage=50.0,
            memory_usage=60.0,
            response_time_p95=1.5,
            request_rate=150.0,
            current_replicas=3
        )
        
        # Create scaling decision
        direction = ScalingDirection.UP if target_replicas > current_metrics.current_replicas else ScalingDirection.DOWN
        decision = ScalingDecision(
            direction=direction,
            current_replicas=current_metrics.current_replicas,
            target_replicas=int(target_replicas),
            reason="Manual scaling via API",
            metrics=current_metrics,
            confidence=100.0
        )
        
        # Execute scaling
        success = self.scaling_manager.execute_scaling(service_name, decision)
        
        if success:
            return Response({
                'status': 'success',
                'service': service_name,
                'previous_replicas': current_metrics.current_replicas,
                'new_replicas': target_replicas,
                'message': f'Successfully scaled {service_name}'
            })
        else:
            return Response(
                {'error': 'Failed to execute scaling'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def record_metric(self, request):
        """
        Record a custom performance metric.
        
        Request body:
        - endpoint: API endpoint
        - method: HTTP method
        - response_time: Response time in seconds
        - status_code: HTTP status code
        """
        # Create metric from request data
        try:
            metric = PerformanceMetric(
                timestamp=timezone.now(),
                endpoint=request.data.get('endpoint', '/unknown'),
                method=request.data.get('method', 'GET'),
                response_time=float(request.data.get('response_time', 0)),
                status_code=int(request.data.get('status_code', 200)),
                user_id=str(request.user.id) if request.user.is_authenticated else None
            )
            
            # Record the metric
            self.sla_service.record_metric(metric)
            
            return Response({
                'status': 'success',
                'message': 'Metric recorded successfully'
            })
            
        except (ValueError, TypeError) as e:
            return Response(
                {'error': f'Invalid metric data: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def _calculate_period_summary(self, period: str) -> dict:
        """Calculate summary statistics for a time period."""
        # Convert period to timedelta
        period_map = {
            '5m': timedelta(minutes=5),
            '15m': timedelta(minutes=15),
            '1h': timedelta(hours=1),
            '24h': timedelta(hours=24)
        }
        
        delta = period_map.get(period, timedelta(minutes=15))
        
        # This would calculate real statistics in production
        return {
            'period': period,
            'total_requests': 15000,
            'average_response_time': 0.85,
            'peak_response_time': 2.3,
            'error_rate': 0.05,
            'availability': 99.95
        }


class PerformanceDashboardViewSet(viewsets.ViewSet):
    """
    ViewSet for performance dashboard data.
    
    Provides aggregated data for dashboard visualization.
    """
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """
        Get dashboard overview data.
        
        Returns key metrics and trends for dashboard display.
        """
        # Initialize services
        sla_service = SLAMonitoringService()
        scaling_manager = AutoScalingManager()
        
        # Get current metrics
        current_metrics = sla_service.get_current_metrics()
        sla_status = sla_service.check_sla_compliance()
        scaling_recommendations = scaling_manager.get_scaling_recommendations()
        
        # Calculate trends (last 24 hours)
        trends = self._calculate_trends()
        
        # Build response
        response_data = {
            'timestamp': timezone.now(),
            'health_score': self._calculate_health_score(sla_status),
            'current_metrics': {
                'requests_per_second': current_metrics.get('overall', {}).get('total_requests', 0) / 300,  # Last 5 min
                'average_response_time': current_metrics.get('overall', {}).get('avg_p95', 0),
                'error_rate': current_metrics.get('overall', {}).get('error_rate', 0),
                'availability': current_metrics.get('overall', {}).get('availability', 100)
            },
            'sla_compliance': {
                'compliant_metrics': sum(1 for s in sla_status if not s.is_breached),
                'total_metrics': len(sla_status),
                'compliance_percentage': (
                    sum(1 for s in sla_status if not s.is_breached) / len(sla_status) * 100
                    if sla_status else 100
                )
            },
            'scaling': {
                'total_replicas': sum(
                    r['current_replicas'] for r in scaling_recommendations.values()
                ),
                'services_needing_scaling': sum(
                    1 for r in scaling_recommendations.values()
                    if r['direction'] != 'none'
                )
            },
            'trends': trends,
            'alerts': self._get_active_alerts(sla_status)
        }
        
        return Response(response_data)
    
    @action(detail=False, methods=['get'])
    def time_series(self, request):
        """
        Get time series data for charts.
        
        Query params:
        - metric: Metric name (response_time, error_rate, throughput)
        - period: Time period (1h, 6h, 24h, 7d)
        - resolution: Data point resolution (1m, 5m, 1h)
        """
        metric = request.query_params.get('metric', 'response_time')
        period = request.query_params.get('period', '24h')
        resolution = request.query_params.get('resolution', '5m')
        
        # Generate time series data
        # In production, this would query time-series database
        data_points = self._generate_time_series_data(metric, period, resolution)
        
        return Response({
            'metric': metric,
            'period': period,
            'resolution': resolution,
            'data_points': data_points
        })
    
    def _calculate_health_score(self, sla_status: list) -> float:
        """Calculate overall system health score (0-100)."""
        if not sla_status:
            return 100.0
        
        # Base score on SLA compliance
        compliant = sum(1 for s in sla_status if not s.is_breached)
        base_score = (compliant / len(sla_status)) * 100
        
        # Apply penalties for critical breaches
        critical_breaches = sum(
            1 for s in sla_status
            if s.is_breached and 'critical' in str(s.metric).lower()
        )
        
        penalty = critical_breaches * 10
        return max(0, base_score - penalty)
    
    def _calculate_trends(self) -> dict:
        """Calculate 24-hour trends for key metrics."""
        # In production, would calculate from historical data
        return {
            'response_time': {
                'direction': 'improving',
                'change_percent': -5.2
            },
            'error_rate': {
                'direction': 'stable',
                'change_percent': 0.1
            },
            'throughput': {
                'direction': 'increasing',
                'change_percent': 12.5
            },
            'availability': {
                'direction': 'stable',
                'change_percent': 0.0
            }
        }
    
    def _get_active_alerts(self, sla_status: list) -> list:
        """Get list of active alerts from SLA breaches."""
        alerts = []
        
        for status in sla_status:
            if status.is_breached:
                alerts.append({
                    'id': f"sla_{status.metric}_{timezone.now().timestamp()}",
                    'type': 'sla_breach',
                    'severity': 'high' if 'critical' in str(status.metric) else 'medium',
                    'metric': status.metric,
                    'message': f"{status.metric} SLA breach: {status.current_value:.2f} (target: {status.target_value:.2f})",
                    'timestamp': timezone.now(),
                    'breach_count': status.breach_count
                })
        
        return alerts
    
    def _generate_time_series_data(
        self,
        metric: str,
        period: str,
        resolution: str
    ) -> list:
        """Generate sample time series data."""
        import random
        from datetime import datetime, timedelta
        
        # Parse period and resolution
        period_hours = {
            '1h': 1, '6h': 6, '24h': 24, '7d': 168
        }.get(period, 24)
        
        resolution_minutes = {
            '1m': 1, '5m': 5, '1h': 60
        }.get(resolution, 5)
        
        # Generate data points
        data_points = []
        current_time = timezone.now()
        
        for i in range(0, period_hours * 60, resolution_minutes):
            timestamp = current_time - timedelta(minutes=i)
            
            # Generate realistic values based on metric
            if metric == 'response_time':
                value = random.uniform(0.5, 2.0) + (random.random() * 0.5 if i % 60 == 0 else 0)
            elif metric == 'error_rate':
                value = random.uniform(0, 1.0) + (random.random() * 2 if i % 180 == 0 else 0)
            elif metric == 'throughput':
                value = random.uniform(80, 150) + (random.random() * 50 if i % 120 == 0 else 0)
            else:
                value = random.uniform(0, 100)
            
            data_points.append({
                'timestamp': timestamp.isoformat(),
                'value': round(value, 2)
            })
        
        # Reverse to have oldest first
        data_points.reverse()
        
        return data_points