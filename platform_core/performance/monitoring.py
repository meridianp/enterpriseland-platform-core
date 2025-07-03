"""
Performance Monitoring and Metrics Collection

Real-time performance monitoring with Prometheus integration.
"""

import time
import psutil
import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from prometheus_client import (
    Counter, Histogram, Gauge, Summary,
    generate_latest, CONTENT_TYPE_LATEST
)
from django.http import HttpResponse
import json

logger = logging.getLogger(__name__)


# Prometheus metrics
request_count = Counter(
    'django_request_count',
    'Total request count',
    ['method', 'endpoint', 'status']
)

request_latency = Histogram(
    'django_request_latency_seconds',
    'Request latency',
    ['method', 'endpoint']
)

db_query_count = Counter(
    'django_db_query_count',
    'Total database query count',
    ['operation']
)

db_query_duration = Histogram(
    'django_db_query_duration_seconds',
    'Database query duration',
    ['operation']
)

cache_operations = Counter(
    'django_cache_operations_total',
    'Cache operations',
    ['operation', 'hit']
)

active_connections = Gauge(
    'django_active_connections',
    'Active database connections'
)

memory_usage = Gauge(
    'django_memory_usage_bytes',
    'Memory usage in bytes'
)

cpu_usage = Gauge(
    'django_cpu_usage_percent',
    'CPU usage percentage'
)

websocket_connections = Gauge(
    'django_websocket_connections',
    'Active WebSocket connections'
)

celery_task_count = Counter(
    'celery_task_total',
    'Total Celery tasks',
    ['task_name', 'status']
)

celery_task_duration = Histogram(
    'celery_task_duration_seconds',
    'Celery task duration',
    ['task_name']
)


class MetricsCollector:
    """
    Collects and aggregates performance metrics.
    """
    
    def __init__(self):
        self.enabled = getattr(settings, 'ENABLE_METRICS', True)
        self.collection_interval = 60  # seconds
        self.metrics_buffer = []
        self._start_background_collection()
    
    def collect_request_metrics(self, method: str, path: str, 
                              status_code: int, duration: float) -> None:
        """Collect HTTP request metrics."""
        if not self.enabled:
            return
        
        # Update Prometheus metrics
        request_count.labels(
            method=method,
            endpoint=self._normalize_path(path),
            status=str(status_code)
        ).inc()
        
        request_latency.labels(
            method=method,
            endpoint=self._normalize_path(path)
        ).observe(duration)
        
        # Store for aggregation
        self._buffer_metric({
            'type': 'request',
            'method': method,
            'path': path,
            'status': status_code,
            'duration': duration,
            'timestamp': time.time()
        })
    
    def collect_query_metrics(self, query_type: str, duration: float) -> None:
        """Collect database query metrics."""
        if not self.enabled:
            return
        
        # Determine operation type
        operation = self._get_query_operation(query_type)
        
        # Update Prometheus metrics
        db_query_count.labels(operation=operation).inc()
        db_query_duration.labels(operation=operation).observe(duration / 1000)  # Convert to seconds
        
        # Store for aggregation
        self._buffer_metric({
            'type': 'query',
            'operation': operation,
            'duration': duration,
            'timestamp': time.time()
        })
    
    def collect_cache_metrics(self, operation: str, hit: bool) -> None:
        """Collect cache operation metrics."""
        if not self.enabled:
            return
        
        # Update Prometheus metrics
        cache_operations.labels(
            operation=operation,
            hit='hit' if hit else 'miss'
        ).inc()
        
        # Store for aggregation
        self._buffer_metric({
            'type': 'cache',
            'operation': operation,
            'hit': hit,
            'timestamp': time.time()
        })
    
    def collect_system_metrics(self) -> Dict[str, Any]:
        """Collect system-level metrics."""
        metrics = {}
        
        try:
            # Memory usage
            memory = psutil.virtual_memory()
            metrics['memory_used'] = memory.used
            metrics['memory_percent'] = memory.percent
            memory_usage.set(memory.used)
            
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            metrics['cpu_percent'] = cpu_percent
            cpu_usage.set(cpu_percent)
            
            # Disk usage
            disk = psutil.disk_usage('/')
            metrics['disk_used'] = disk.used
            metrics['disk_percent'] = disk.percent
            
            # Network I/O
            net_io = psutil.net_io_counters()
            metrics['bytes_sent'] = net_io.bytes_sent
            metrics['bytes_recv'] = net_io.bytes_recv
            
            # Database connections
            active_conns = self._get_active_db_connections()
            metrics['db_connections'] = active_conns
            active_connections.set(active_conns)
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
        
        return metrics
    
    def collect_celery_metrics(self, task_name: str, status: str, 
                             duration: Optional[float] = None) -> None:
        """Collect Celery task metrics."""
        if not self.enabled:
            return
        
        # Update Prometheus metrics
        celery_task_count.labels(
            task_name=task_name,
            status=status
        ).inc()
        
        if duration is not None:
            celery_task_duration.labels(task_name=task_name).observe(duration)
        
        # Store for aggregation
        self._buffer_metric({
            'type': 'celery_task',
            'task_name': task_name,
            'status': status,
            'duration': duration,
            'timestamp': time.time()
        })
    
    def get_aggregated_metrics(self, time_range: str = '1h') -> Dict[str, Any]:
        """Get aggregated metrics for time range."""
        # Calculate time boundaries
        now = datetime.now()
        range_map = {
            '1h': timedelta(hours=1),
            '24h': timedelta(days=1),
            '7d': timedelta(days=7),
            '30d': timedelta(days=30)
        }
        
        start_time = now - range_map.get(time_range, timedelta(hours=1))
        
        # Get metrics from cache
        cache_key = f'metrics:aggregated:{time_range}'
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        # Aggregate metrics
        aggregated = self._aggregate_metrics(start_time)
        
        # Cache for 5 minutes
        cache.set(cache_key, aggregated, timeout=300)
        
        return aggregated
    
    def _normalize_path(self, path: str) -> str:
        """Normalize URL path for metrics grouping."""
        # Remove IDs and parameters
        import re
        
        # Replace UUIDs
        path = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '{id}',
            path
        )
        
        # Replace numeric IDs
        path = re.sub(r'/\d+/', '/{id}/', path)
        
        # Remove query parameters
        path = path.split('?')[0]
        
        return path
    
    def _get_query_operation(self, query: str) -> str:
        """Extract operation type from SQL query."""
        query_lower = query.lower().strip()
        
        if query_lower.startswith('select'):
            return 'select'
        elif query_lower.startswith('insert'):
            return 'insert'
        elif query_lower.startswith('update'):
            return 'update'
        elif query_lower.startswith('delete'):
            return 'delete'
        else:
            return 'other'
    
    def _get_active_db_connections(self) -> int:
        """Get number of active database connections."""
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active'"
                )
                return cursor.fetchone()[0]
        except Exception:
            return 0
    
    def _buffer_metric(self, metric: Dict[str, Any]) -> None:
        """Buffer metric for batch processing."""
        self.metrics_buffer.append(metric)
        
        # Flush buffer if too large
        if len(self.metrics_buffer) > 1000:
            self._flush_metrics_buffer()
    
    def _flush_metrics_buffer(self) -> None:
        """Flush metrics buffer to storage."""
        if not self.metrics_buffer:
            return
        
        # Store in time-series cache
        timestamp = datetime.now().strftime('%Y%m%d%H%M')
        cache_key = f'metrics:raw:{timestamp}'
        
        existing = cache.get(cache_key, [])
        existing.extend(self.metrics_buffer)
        
        cache.set(cache_key, existing, timeout=86400)  # 24 hours
        
        # Clear buffer
        self.metrics_buffer = []
    
    def _aggregate_metrics(self, start_time: datetime) -> Dict[str, Any]:
        """Aggregate metrics from raw data."""
        aggregated = {
            'time_range': {
                'start': start_time.isoformat(),
                'end': datetime.now().isoformat()
            },
            'requests': {
                'total': 0,
                'by_method': {},
                'by_status': {},
                'avg_duration': 0,
                'p95_duration': 0,
                'p99_duration': 0
            },
            'database': {
                'total_queries': 0,
                'by_operation': {},
                'avg_duration': 0,
                'slow_queries': 0
            },
            'cache': {
                'total_operations': 0,
                'hits': 0,
                'misses': 0,
                'hit_rate': 0
            },
            'system': self.collect_system_metrics()
        }
        
        # Process raw metrics
        # This is a simplified aggregation
        # In production, use a time-series database
        
        return aggregated
    
    def _start_background_collection(self) -> None:
        """Start background metric collection."""
        # In production, use Celery beat for this
        pass


class PerformanceMonitor:
    """
    High-level performance monitoring interface.
    """
    
    def __init__(self):
        self.collector = MetricsCollector()
        self.alert_thresholds = {
            'response_time': 1000,  # ms
            'error_rate': 0.05,  # 5%
            'cpu_usage': 80,  # %
            'memory_usage': 90,  # %
            'db_connections': 90  # % of max
        }
    
    def check_health(self) -> Dict[str, Any]:
        """Check overall system health."""
        health = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'checks': {}
        }
        
        # Check response times
        metrics = self.collector.get_aggregated_metrics('1h')
        
        # Response time check
        avg_response = metrics['requests'].get('avg_duration', 0)
        health['checks']['response_time'] = {
            'status': 'ok' if avg_response < self.alert_thresholds['response_time'] else 'warning',
            'value': avg_response,
            'threshold': self.alert_thresholds['response_time']
        }
        
        # Error rate check
        total_requests = metrics['requests'].get('total', 1)
        errors = metrics['requests']['by_status'].get('5xx', 0)
        error_rate = errors / total_requests if total_requests > 0 else 0
        
        health['checks']['error_rate'] = {
            'status': 'ok' if error_rate < self.alert_thresholds['error_rate'] else 'critical',
            'value': error_rate,
            'threshold': self.alert_thresholds['error_rate']
        }
        
        # System resource checks
        system_metrics = metrics.get('system', {})
        
        health['checks']['cpu_usage'] = {
            'status': 'ok' if system_metrics.get('cpu_percent', 0) < self.alert_thresholds['cpu_usage'] else 'warning',
            'value': system_metrics.get('cpu_percent', 0),
            'threshold': self.alert_thresholds['cpu_usage']
        }
        
        health['checks']['memory_usage'] = {
            'status': 'ok' if system_metrics.get('memory_percent', 0) < self.alert_thresholds['memory_usage'] else 'critical',
            'value': system_metrics.get('memory_percent', 0),
            'threshold': self.alert_thresholds['memory_usage']
        }
        
        # Overall status
        if any(check['status'] == 'critical' for check in health['checks'].values()):
            health['status'] = 'unhealthy'
        elif any(check['status'] == 'warning' for check in health['checks'].values()):
            health['status'] = 'degraded'
        
        return health
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report."""
        report = {
            'generated_at': datetime.now().isoformat(),
            'summary': {},
            'recommendations': []
        }
        
        # Get metrics for different time ranges
        hourly = self.collector.get_aggregated_metrics('1h')
        daily = self.collector.get_aggregated_metrics('24h')
        
        # Summary statistics
        report['summary'] = {
            'requests_per_second': hourly['requests']['total'] / 3600,
            'average_response_time': hourly['requests']['avg_duration'],
            'error_rate': self._calculate_error_rate(hourly),
            'cache_hit_rate': hourly['cache']['hit_rate'],
            'database_queries_per_request': (
                hourly['database']['total_queries'] / hourly['requests']['total']
                if hourly['requests']['total'] > 0 else 0
            )
        }
        
        # Generate recommendations
        if report['summary']['average_response_time'] > 500:
            report['recommendations'].append(
                "High average response time detected. Consider optimizing slow endpoints."
            )
        
        if report['summary']['database_queries_per_request'] > 10:
            report['recommendations'].append(
                "High number of database queries per request. "
                "Consider using select_related() and prefetch_related()."
            )
        
        if report['summary']['cache_hit_rate'] < 70:
            report['recommendations'].append(
                "Low cache hit rate. Review caching strategy and cache key design."
            )
        
        return report
    
    def _calculate_error_rate(self, metrics: Dict[str, Any]) -> float:
        """Calculate error rate from metrics."""
        total = metrics['requests'].get('total', 1)
        errors = sum(
            count for status, count in metrics['requests']['by_status'].items()
            if status.startswith('5')
        )
        return (errors / total) * 100 if total > 0 else 0


# Create global instances
metrics_collector = MetricsCollector()
performance_monitor = PerformanceMonitor()


def metrics_view(request):
    """
    Prometheus metrics endpoint.
    
    Add to urls.py:
        path('metrics/', metrics_view, name='prometheus-metrics')
    """
    # Generate metrics in Prometheus format
    metrics_output = generate_latest()
    
    return HttpResponse(
        metrics_output,
        content_type=CONTENT_TYPE_LATEST
    )


def health_check_view(request):
    """
    Health check endpoint for monitoring.
    
    Add to urls.py:
        path('health/', health_check_view, name='health-check')
    """
    health = performance_monitor.check_health()
    
    status_code = 200
    if health['status'] == 'unhealthy':
        status_code = 503
    elif health['status'] == 'degraded':
        status_code = 200  # Still return 200 for degraded
    
    return HttpResponse(
        json.dumps(health, indent=2),
        content_type='application/json',
        status=status_code
    )