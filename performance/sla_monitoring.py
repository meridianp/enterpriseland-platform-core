"""
SLA Monitoring Service

Real-time monitoring of performance SLAs with alerting and reporting.
"""
import time
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from decimal import Decimal
import asyncio
import aioredis
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Avg, Count, Max, Min, Q, F
from prometheus_client import Counter, Histogram, Gauge
import logging

logger = logging.getLogger(__name__)


# Prometheus metrics
response_time_histogram = Histogram(
    'api_response_time_seconds',
    'API response time in seconds',
    ['endpoint', 'method', 'status']
)

sla_breach_counter = Counter(
    'sla_breaches_total',
    'Total number of SLA breaches',
    ['metric', 'severity']
)

current_availability_gauge = Gauge(
    'service_availability_percentage',
    'Current service availability percentage',
    ['service']
)

concurrent_users_gauge = Gauge(
    'concurrent_users_total',
    'Current number of concurrent users',
    ['service']
)


@dataclass
class SLATarget:
    """Defines an SLA target."""
    metric: str
    target: float
    measurement_window: timedelta
    breach_threshold: int = 1  # Number of violations before breach
    severity: str = 'warning'  # warning, critical
    
    
@dataclass
class PerformanceMetric:
    """Performance metric data point."""
    timestamp: datetime
    endpoint: str
    method: str
    response_time: float
    status_code: int
    user_id: Optional[str] = None
    request_size: Optional[int] = None
    response_size: Optional[int] = None
    error: Optional[str] = None
    

@dataclass
class SLAStatus:
    """Current SLA status."""
    metric: str
    current_value: float
    target_value: float
    is_breached: bool
    breach_count: int
    last_breach: Optional[datetime] = None
    trend: str = 'stable'  # improving, stable, degrading
    

class SLAMonitoringService:
    """
    Service for monitoring performance SLAs in real-time.
    
    Tracks:
    - Response time (p50, p95, p99)
    - Availability (uptime percentage)
    - Throughput (requests per second)
    - Error rate
    - Concurrent users
    """
    
    # Default SLA targets
    DEFAULT_SLAS = [
        SLATarget('response_time_p95', 2.0, timedelta(minutes=5), severity='warning'),
        SLATarget('response_time_p99', 5.0, timedelta(minutes=5), severity='critical'),
        SLATarget('availability', 99.9, timedelta(hours=1), severity='critical'),
        SLATarget('error_rate', 1.0, timedelta(minutes=15), severity='warning'),
        SLATarget('throughput', 100.0, timedelta(minutes=1), severity='warning'),
    ]
    
    def __init__(self):
        self.sla_targets = self._load_sla_configuration()
        self.redis_client = None
        self._initialize_redis()
    
    def _initialize_redis(self):
        """Initialize Redis connection for real-time metrics."""
        try:
            import redis
            self.redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
    
    def _load_sla_configuration(self) -> List[SLATarget]:
        """Load SLA configuration from settings or database."""
        # In production, this would load from database
        # For now, use defaults with settings overrides
        slas = self.DEFAULT_SLAS.copy()
        
        # Override from settings if available
        custom_slas = getattr(settings, 'PERFORMANCE_SLAS', {})
        for sla in slas:
            if sla.metric in custom_slas:
                sla.target = custom_slas[sla.metric]
        
        return slas
    
    def record_metric(self, metric: PerformanceMetric) -> None:
        """
        Record a performance metric.
        
        Args:
            metric: Performance metric to record
        """
        # Record in Prometheus
        response_time_histogram.labels(
            endpoint=metric.endpoint,
            method=metric.method,
            status=str(metric.status_code)
        ).observe(metric.response_time)
        
        # Store in Redis for real-time analysis
        if self.redis_client:
            key = f"perf:{metric.endpoint}:{metric.method}"
            timestamp = int(metric.timestamp.timestamp())
            
            # Store in sorted set for time-series queries
            self.redis_client.zadd(
                f"{key}:timeline",
                {f"{timestamp}:{metric.response_time}": timestamp}
            )
            
            # Update rolling window stats
            self._update_rolling_stats(key, metric)
            
            # Store in time-bucketed keys for efficient querying
            bucket = timestamp // 60  # 1-minute buckets
            self.redis_client.rpush(
                f"{key}:bucket:{bucket}",
                metric.response_time
            )
            self.redis_client.expire(f"{key}:bucket:{bucket}", 3600)  # 1 hour TTL
    
    def _update_rolling_stats(self, key: str, metric: PerformanceMetric) -> None:
        """Update rolling window statistics."""
        # Increment counters
        self.redis_client.hincrby(f"{key}:stats", "total_requests", 1)
        
        if metric.status_code >= 400:
            self.redis_client.hincrby(f"{key}:stats", "error_count", 1)
        
        # Update response time stats
        pipe = self.redis_client.pipeline()
        pipe.lpush(f"{key}:recent", metric.response_time)
        pipe.ltrim(f"{key}:recent", 0, 999)  # Keep last 1000
        pipe.expire(f"{key}:recent", 300)  # 5 min TTL
        pipe.execute()
    
    def get_current_metrics(self, endpoint: Optional[str] = None) -> Dict[str, Any]:
        """
        Get current performance metrics.
        
        Args:
            endpoint: Specific endpoint to get metrics for (all if None)
            
        Returns:
            Dictionary of current metrics
        """
        metrics = {
            'timestamp': timezone.now(),
            'endpoints': {}
        }
        
        if not self.redis_client:
            return metrics
        
        # Get all endpoint keys
        pattern = f"perf:{endpoint}:*:stats" if endpoint else "perf:*:stats"
        keys = self.redis_client.keys(pattern)
        
        for key in keys:
            # Parse endpoint and method from key
            parts = key.split(':')
            endpoint_name = parts[1]
            method = parts[2]
            
            # Get stats
            stats = self.redis_client.hgetall(key)
            recent_times = self.redis_client.lrange(
                f"perf:{endpoint_name}:{method}:recent", 0, -1
            )
            
            if recent_times:
                recent_floats = [float(t) for t in recent_times]
                percentiles = self._calculate_percentiles(recent_floats)
                
                endpoint_key = f"{endpoint_name}:{method}"
                metrics['endpoints'][endpoint_key] = {
                    'total_requests': int(stats.get('total_requests', 0)),
                    'error_count': int(stats.get('error_count', 0)),
                    'error_rate': self._calculate_error_rate(stats),
                    'response_times': {
                        'p50': percentiles[50],
                        'p95': percentiles[95],
                        'p99': percentiles[99],
                        'avg': statistics.mean(recent_floats),
                        'min': min(recent_floats),
                        'max': max(recent_floats)
                    }
                }
        
        # Calculate overall metrics
        metrics['overall'] = self._calculate_overall_metrics(metrics['endpoints'])
        
        return metrics
    
    def _calculate_percentiles(self, values: List[float]) -> Dict[int, float]:
        """Calculate percentiles for a list of values."""
        if not values:
            return {50: 0, 95: 0, 99: 0}
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        return {
            50: sorted_values[int(n * 0.5)],
            95: sorted_values[int(n * 0.95)],
            99: sorted_values[int(n * 0.99)]
        }
    
    def _calculate_error_rate(self, stats: Dict[str, str]) -> float:
        """Calculate error rate percentage."""
        total = int(stats.get('total_requests', 0))
        errors = int(stats.get('error_count', 0))
        
        if total == 0:
            return 0.0
        
        return (errors / total) * 100
    
    def _calculate_overall_metrics(self, endpoints: Dict[str, Dict]) -> Dict[str, Any]:
        """Calculate overall metrics across all endpoints."""
        if not endpoints:
            return {}
        
        total_requests = sum(ep['total_requests'] for ep in endpoints.values())
        total_errors = sum(ep['error_count'] for ep in endpoints.values())
        
        all_p95s = [ep['response_times']['p95'] for ep in endpoints.values()]
        all_p99s = [ep['response_times']['p99'] for ep in endpoints.values()]
        
        return {
            'total_requests': total_requests,
            'total_errors': total_errors,
            'error_rate': (total_errors / total_requests * 100) if total_requests > 0 else 0,
            'avg_p95': statistics.mean(all_p95s) if all_p95s else 0,
            'avg_p99': statistics.mean(all_p99s) if all_p99s else 0,
            'availability': self._calculate_availability()
        }
    
    def _calculate_availability(self) -> float:
        """Calculate current availability percentage."""
        # In production, this would check actual service health
        # For now, calculate based on error rate
        metrics = self.get_current_metrics()
        error_rate = metrics.get('overall', {}).get('error_rate', 0)
        
        # Simple availability calculation
        availability = 100 - error_rate
        
        # Update Prometheus gauge
        current_availability_gauge.labels(service='api').set(availability)
        
        return availability
    
    def check_sla_compliance(self) -> List[SLAStatus]:
        """
        Check current SLA compliance status.
        
        Returns:
            List of SLA status objects
        """
        statuses = []
        current_metrics = self.get_current_metrics()
        
        for sla_target in self.sla_targets:
            status = self._check_single_sla(sla_target, current_metrics)
            statuses.append(status)
            
            # Record breach if detected
            if status.is_breached:
                sla_breach_counter.labels(
                    metric=sla_target.metric,
                    severity=sla_target.severity
                ).inc()
                
                # Trigger alert
                self._trigger_sla_alert(sla_target, status)
        
        return statuses
    
    def _check_single_sla(
        self,
        target: SLATarget,
        metrics: Dict[str, Any]
    ) -> SLAStatus:
        """Check a single SLA target."""
        current_value = 0.0
        
        # Extract current value based on metric type
        if target.metric == 'response_time_p95':
            current_value = metrics.get('overall', {}).get('avg_p95', 0)
        elif target.metric == 'response_time_p99':
            current_value = metrics.get('overall', {}).get('avg_p99', 0)
        elif target.metric == 'availability':
            current_value = metrics.get('overall', {}).get('availability', 100)
        elif target.metric == 'error_rate':
            current_value = metrics.get('overall', {}).get('error_rate', 0)
        
        # Check if breached
        is_breached = False
        if target.metric in ['response_time_p95', 'response_time_p99', 'error_rate']:
            is_breached = current_value > target.target
        elif target.metric == 'availability':
            is_breached = current_value < target.target
        
        # Get breach history
        breach_count = self._get_breach_count(target.metric)
        last_breach = self._get_last_breach_time(target.metric)
        
        # Determine trend
        trend = self._calculate_trend(target.metric, current_value)
        
        return SLAStatus(
            metric=target.metric,
            current_value=current_value,
            target_value=target.target,
            is_breached=is_breached,
            breach_count=breach_count,
            last_breach=last_breach,
            trend=trend
        )
    
    def _get_breach_count(self, metric: str) -> int:
        """Get breach count for a metric."""
        if self.redis_client:
            return int(self.redis_client.get(f"sla:breach_count:{metric}") or 0)
        return 0
    
    def _get_last_breach_time(self, metric: str) -> Optional[datetime]:
        """Get last breach time for a metric."""
        if self.redis_client:
            timestamp = self.redis_client.get(f"sla:last_breach:{metric}")
            if timestamp:
                return datetime.fromtimestamp(float(timestamp))
        return None
    
    def _calculate_trend(self, metric: str, current_value: float) -> str:
        """Calculate trend for a metric."""
        if not self.redis_client:
            return 'stable'
        
        # Get historical values
        history_key = f"sla:history:{metric}"
        history = self.redis_client.lrange(history_key, -10, -1)
        
        if len(history) < 3:
            return 'stable'
        
        # Calculate trend
        values = [float(v) for v in history]
        avg_old = statistics.mean(values[:5])
        avg_new = statistics.mean(values[5:])
        
        change_pct = ((avg_new - avg_old) / avg_old) * 100 if avg_old > 0 else 0
        
        if abs(change_pct) < 5:
            return 'stable'
        elif change_pct > 0:
            return 'degrading' if metric != 'availability' else 'improving'
        else:
            return 'improving' if metric != 'availability' else 'degrading'
    
    def _trigger_sla_alert(self, target: SLATarget, status: SLAStatus) -> None:
        """Trigger an alert for SLA breach."""
        alert_data = {
            'type': 'sla_breach',
            'severity': target.severity,
            'metric': target.metric,
            'current_value': status.current_value,
            'target_value': status.target_value,
            'breach_count': status.breach_count,
            'timestamp': timezone.now()
        }
        
        # Log the breach
        logger.warning(f"SLA breach detected: {alert_data}")
        
        # In production, this would send to alerting system
        # For now, store in cache for dashboard
        cache.set(
            f"sla_alert:{target.metric}",
            alert_data,
            timeout=3600
        )
        
        # Update breach tracking
        if self.redis_client:
            self.redis_client.incr(f"sla:breach_count:{target.metric}")
            self.redis_client.set(
                f"sla:last_breach:{target.metric}",
                timezone.now().timestamp()
            )
    
    def generate_sla_report(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Generate SLA compliance report for a time period.
        
        Args:
            start_date: Report start date
            end_date: Report end date
            
        Returns:
            SLA compliance report
        """
        report = {
            'period': {
                'start': start_date,
                'end': end_date
            },
            'overall_compliance': 0.0,
            'metrics': {},
            'incidents': []
        }
        
        # Calculate compliance for each metric
        for target in self.sla_targets:
            metric_report = self._generate_metric_report(
                target, start_date, end_date
            )
            report['metrics'][target.metric] = metric_report
        
        # Calculate overall compliance
        compliances = [m['compliance_percentage'] for m in report['metrics'].values()]
        report['overall_compliance'] = statistics.mean(compliances) if compliances else 0
        
        # Get incidents
        report['incidents'] = self._get_sla_incidents(start_date, end_date)
        
        return report
    
    def _generate_metric_report(
        self,
        target: SLATarget,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Generate report for a single metric."""
        # This would query historical data
        # For now, return sample data
        return {
            'target': target.target,
            'achieved': 1.8 if target.metric == 'response_time_p95' else 99.95,
            'compliance_percentage': 98.5,
            'breach_count': 3,
            'total_measurements': 8640,
            'worst_value': 5.2 if 'response_time' in target.metric else 99.1,
            'best_value': 0.5 if 'response_time' in target.metric else 100.0
        }
    
    def _get_sla_incidents(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Get SLA incidents for a time period."""
        # This would query incident history
        # For now, return sample data
        return [
            {
                'timestamp': timezone.now() - timedelta(days=2),
                'metric': 'response_time_p99',
                'duration_minutes': 15,
                'severity': 'critical',
                'root_cause': 'Database connection pool exhaustion',
                'resolution': 'Increased connection pool size'
            }
        ]


class PerformanceMonitoringMiddleware:
    """
    Django middleware for automatic performance monitoring.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.monitoring_service = SLAMonitoringService()
    
    def __call__(self, request):
        # Record start time
        start_time = time.time()
        
        # Process request
        response = self.get_response(request)
        
        # Calculate response time
        response_time = time.time() - start_time
        
        # Create metric
        metric = PerformanceMetric(
            timestamp=timezone.now(),
            endpoint=request.path,
            method=request.method,
            response_time=response_time,
            status_code=response.status_code,
            user_id=str(request.user.id) if request.user.is_authenticated else None,
            request_size=len(request.body) if request.body else 0,
            response_size=len(response.content) if hasattr(response, 'content') else 0
        )
        
        # Record metric
        self.monitoring_service.record_metric(metric)
        
        # Add performance headers
        response['X-Response-Time'] = f"{response_time:.3f}"
        
        return response