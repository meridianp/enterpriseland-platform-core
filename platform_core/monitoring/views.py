"""
Monitoring Views

Django views for metrics and health endpoints.
"""

import json
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings

from .metrics import metrics_registry
from .exporters import PrometheusExporter, JSONExporter
from .monitors import HealthMonitor, PerformanceMonitor


@method_decorator(never_cache, name='dispatch')
class MetricsView(View):
    """Expose metrics in Prometheus format."""
    
    def get(self, request):
        """Return metrics in Prometheus text format."""
        # Check if metrics are enabled
        if not getattr(settings, 'METRICS_ENABLED', True):
            return HttpResponse("Metrics disabled", status=503)
        
        # Check authentication if required
        if getattr(settings, 'METRICS_REQUIRE_AUTH', False):
            if not request.user.is_authenticated:
                return HttpResponse("Unauthorized", status=401)
        
        # Export metrics
        exporter = PrometheusExporter(metrics_registry)
        metrics = metrics_registry.collect()
        exporter.export(metrics)
        
        # Generate Prometheus format
        content = exporter.generate_text()
        
        return HttpResponse(
            content,
            content_type='text/plain; version=0.0.4; charset=utf-8'
        )


@method_decorator(never_cache, name='dispatch')
class HealthView(View):
    """Health check endpoint."""
    
    def get(self, request):
        """Return health status."""
        monitor = HealthMonitor()
        health_status = monitor.run_health_checks()
        
        # Determine HTTP status code
        status_code = 200
        if health_status['overall_status'].value in ['critical', 'unhealthy']:
            status_code = 503
        elif health_status['overall_status'].value == 'degraded':
            status_code = 200  # Still return 200 for degraded
        
        # Convert enums to strings for JSON serialization
        response_data = {
            'status': health_status['overall_status'].value,
            'timestamp': health_status['timestamp'],
            'checks': {}
        }
        
        for name, check in health_status['checks'].items():
            response_data['checks'][name] = {
                'status': check.status.value,
                'message': check.message,
                'details': check.details
            }
        
        return JsonResponse(response_data, status=status_code)


@method_decorator(never_cache, name='dispatch')
class ReadinessView(View):
    """Kubernetes readiness probe endpoint."""
    
    def get(self, request):
        """Check if service is ready to accept traffic."""
        try:
            # Check database
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            
            # Check cache
            from django.core.cache import cache
            cache.set('_readiness_check', '1', 1)
            
            return JsonResponse({'status': 'ready'})
            
        except Exception as e:
            return JsonResponse(
                {'status': 'not_ready', 'error': str(e)},
                status=503
            )


@method_decorator(never_cache, name='dispatch')
class LivenessView(View):
    """Kubernetes liveness probe endpoint."""
    
    def get(self, request):
        """Check if service is alive."""
        # Simple check - if we can respond, we're alive
        return JsonResponse({'status': 'alive'})


@method_decorator([never_cache, staff_member_required], name='dispatch')
class MetricsDashboardView(View):
    """Simple metrics dashboard for development."""
    
    def get(self, request):
        """Render metrics dashboard."""
        # Collect all metrics
        metrics = metrics_registry.collect()
        
        # Get performance status
        perf_monitor = PerformanceMonitor()
        perf_status = perf_monitor.get_status()
        
        # Get health status
        health_monitor = HealthMonitor()
        health_status = health_monitor.run_health_checks()
        
        # Create HTML response
        html = self._generate_dashboard_html(metrics, perf_status, health_status)
        
        return HttpResponse(html)
    
    def _generate_dashboard_html(self, metrics, perf_status, health_status):
        """Generate simple HTML dashboard."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Metrics Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .metric { margin: 10px 0; padding: 10px; background: #f0f0f0; }
                .metric-name { font-weight: bold; }
                .metric-value { color: #0066cc; }
                .health-check { margin: 5px 0; }
                .status-healthy { color: green; }
                .status-degraded { color: orange; }
                .status-unhealthy { color: red; }
                .status-critical { color: darkred; font-weight: bold; }
                table { border-collapse: collapse; width: 100%; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
            </style>
            <meta http-equiv="refresh" content="5">
        </head>
        <body>
            <h1>Metrics Dashboard</h1>
            
            <h2>Health Status</h2>
            <div class="status-{status}">{status}</div>
            
            <h3>Health Checks</h3>
            {health_checks}
            
            <h2>Performance Metrics</h2>
            {perf_metrics}
            
            <h2>All Metrics</h2>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Type</th>
                    <th>Value</th>
                    <th>Labels</th>
                </tr>
                {metrics_rows}
            </table>
            
            <p><small>Auto-refreshing every 5 seconds</small></p>
        </body>
        </html>
        """.format(
            status=health_status['overall_status'].value,
            health_checks=self._format_health_checks(health_status['checks']),
            perf_metrics=self._format_perf_metrics(perf_status),
            metrics_rows=self._format_metrics_table(metrics)
        )
        
        return html
    
    def _format_health_checks(self, checks):
        """Format health checks as HTML."""
        html = ""
        for name, check in checks.items():
            html += f"""
            <div class="health-check">
                <span class="status-{check['status']}">{name}: {check['status']}</span>
                - {check['message']}
            </div>
            """
        return html
    
    def _format_perf_metrics(self, perf_status):
        """Format performance metrics as HTML."""
        if not perf_status.get('metrics'):
            return "<p>No performance metrics available</p>"
        
        html = "<ul>"
        for key, value in perf_status['metrics'].items():
            html += f"<li>{key}: {value:.2f}</li>"
        html += "</ul>"
        
        if perf_status.get('alerts'):
            html += "<h3>Active Alerts</h3><ul>"
            for alert in perf_status['alerts']:
                html += f"<li class='status-{alert['severity']}'>{alert['message']}</li>"
            html += "</ul>"
        
        return html
    
    def _format_metrics_table(self, metrics):
        """Format metrics as HTML table rows."""
        rows = ""
        for metric in metrics:
            value = metric.get('value', '')
            if isinstance(value, dict):
                value = json.dumps(value, indent=2)
            
            labels = json.dumps(metric.get('labels', {}))
            
            rows += f"""
            <tr>
                <td>{metric.get('name', '')}</td>
                <td>{metric.get('type', '')}</td>
                <td><pre>{value}</pre></td>
                <td>{labels}</td>
            </tr>
            """
        
        return rows


# URL patterns to include in your urls.py:
"""
from platform_core.monitoring.views import (
    MetricsView, HealthView, ReadinessView, 
    LivenessView, MetricsDashboardView
)

urlpatterns = [
    path('metrics/', MetricsView.as_view(), name='metrics'),
    path('health/', HealthView.as_view(), name='health'),
    path('ready/', ReadinessView.as_view(), name='readiness'),
    path('alive/', LivenessView.as_view(), name='liveness'),
    path('metrics-dashboard/', MetricsDashboardView.as_view(), name='metrics-dashboard'),
]
"""