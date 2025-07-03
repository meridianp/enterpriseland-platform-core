"""
Performance Monitors

Active monitoring components for system health and performance.
"""

import time
import threading
import logging
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from .metrics import metrics_registry
from .collectors import (
    SystemMetricsCollector,
    DatabaseMetricsCollector,
    CacheMetricsCollector,
    APIMetricsCollector,
    BusinessMetricsCollector
)

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """System health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    """Health check result."""
    name: str
    status: HealthStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class PerformanceMonitor:
    """Monitors overall system performance."""
    
    def __init__(self):
        self.collectors = {
            'system': SystemMetricsCollector(),
            'database': DatabaseMetricsCollector(),
            'cache': CacheMetricsCollector(),
            'api': APIMetricsCollector(),
            'business': BusinessMetricsCollector()
        }
        
        self.thresholds = {
            'cpu_percent': 80,
            'memory_percent': 85,
            'disk_percent': 90,
            'response_time_ms': 1000,
            'error_rate_percent': 5,
            'cache_hit_rate_percent': 80
        }
        
        self._monitoring = False
        self._monitor_thread = None
        self._alerts = []
    
    def start(self):
        """Start performance monitoring."""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()
        
        logger.info("Performance monitoring started")
    
    def stop(self):
        """Stop performance monitoring."""
        self._monitoring = False
        
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        
        # Stop collectors
        if hasattr(self.collectors['system'], 'stop'):
            self.collectors['system'].stop()
        
        logger.info("Performance monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._monitoring:
            try:
                # Collect metrics
                metrics = self._collect_all_metrics()
                
                # Check thresholds
                alerts = self._check_thresholds(metrics)
                
                # Process alerts
                if alerts:
                    self._process_alerts(alerts)
                
                # Update health status
                self._update_health_status(metrics, alerts)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
            
            time.sleep(30)  # Check every 30 seconds
    
    def _collect_all_metrics(self) -> Dict[str, Any]:
        """Collect metrics from all collectors."""
        all_metrics = {}
        
        for name, collector in self.collectors.items():
            try:
                # Force collection
                collector.collect()
                
                # Get specific metrics
                if name == 'system':
                    all_metrics['cpu_percent'] = metrics_registry.get_metric('system_cpu_usage_percent').get_value()
                    all_metrics['memory_percent'] = metrics_registry.get_metric('system_memory_usage_percent').get_value()
                    all_metrics['disk_percent'] = metrics_registry.get_metric('system_disk_usage_percent').get_value()
                
                elif name == 'api':
                    # Calculate error rate
                    total_requests = metrics_registry.get_metric('api_requests_total').get_value()
                    total_errors = metrics_registry.get_metric('api_errors_total').get_value()
                    
                    if total_requests > 0:
                        all_metrics['error_rate_percent'] = (total_errors / total_requests) * 100
                    
                    # Get response time
                    response_timer = metrics_registry.get_metric('api_request_duration_seconds')
                    if response_timer:
                        stats = response_timer.get_value()
                        all_metrics['response_time_ms'] = stats.get('mean', 0) * 1000
                
                elif name == 'cache':
                    # Calculate cache hit rate
                    cache_hit_rate = metrics_registry.get_metric('cache_hit_rate_percent')
                    if cache_hit_rate:
                        all_metrics['cache_hit_rate_percent'] = cache_hit_rate.get_value()
                
            except Exception as e:
                logger.error(f"Error collecting {name} metrics: {e}")
        
        return all_metrics
    
    def _check_thresholds(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check metrics against thresholds."""
        alerts = []
        
        for metric_name, threshold in self.thresholds.items():
            value = metrics.get(metric_name)
            
            if value is None:
                continue
            
            # Check threshold based on metric type
            if metric_name == 'cache_hit_rate_percent':
                # Lower is bad for cache hit rate
                if value < threshold:
                    alerts.append({
                        'metric': metric_name,
                        'value': value,
                        'threshold': threshold,
                        'severity': 'warning',
                        'message': f"Cache hit rate ({value:.1f}%) below threshold ({threshold}%)"
                    })
            else:
                # Higher is bad for other metrics
                if value > threshold:
                    severity = self._determine_severity(metric_name, value, threshold)
                    alerts.append({
                        'metric': metric_name,
                        'value': value,
                        'threshold': threshold,
                        'severity': severity,
                        'message': f"{metric_name} ({value:.1f}) exceeds threshold ({threshold})"
                    })
        
        return alerts
    
    def _determine_severity(self, metric: str, value: float, threshold: float) -> str:
        """Determine alert severity."""
        ratio = value / threshold
        
        if ratio > 1.5:
            return 'critical'
        elif ratio > 1.2:
            return 'error'
        else:
            return 'warning'
    
    def _process_alerts(self, alerts: List[Dict[str, Any]]):
        """Process and store alerts."""
        for alert in alerts:
            alert['timestamp'] = datetime.now()
            self._alerts.append(alert)
            
            # Log alert
            if alert['severity'] == 'critical':
                logger.critical(alert['message'])
            elif alert['severity'] == 'error':
                logger.error(alert['message'])
            else:
                logger.warning(alert['message'])
            
            # Update alert metric
            alert_counter = metrics_registry.counter(
                'monitoring_alerts_total',
                'Total monitoring alerts',
                labels={'severity': alert['severity'], 'metric': alert['metric']}
            )
            alert_counter.inc()
        
        # Keep only recent alerts (last hour)
        cutoff = datetime.now() - timedelta(hours=1)
        self._alerts = [a for a in self._alerts if a['timestamp'] > cutoff]
    
    def _update_health_status(self, metrics: Dict[str, Any], alerts: List[Dict[str, Any]]):
        """Update overall health status."""
        if not alerts:
            status = HealthStatus.HEALTHY
        else:
            critical_alerts = [a for a in alerts if a['severity'] == 'critical']
            error_alerts = [a for a in alerts if a['severity'] == 'error']
            
            if critical_alerts:
                status = HealthStatus.CRITICAL
            elif error_alerts:
                status = HealthStatus.UNHEALTHY
            else:
                status = HealthStatus.DEGRADED
        
        # Update health metric
        health_gauge = metrics_registry.gauge('system_health_status')
        health_gauge.set(self._health_status_to_value(status))
    
    def _health_status_to_value(self, status: HealthStatus) -> int:
        """Convert health status to numeric value."""
        mapping = {
            HealthStatus.HEALTHY: 4,
            HealthStatus.DEGRADED: 3,
            HealthStatus.UNHEALTHY: 2,
            HealthStatus.CRITICAL: 1
        }
        return mapping.get(status, 0)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current monitoring status."""
        metrics = self._collect_all_metrics()
        
        return {
            'monitoring': self._monitoring,
            'metrics': metrics,
            'alerts': self._alerts,
            'thresholds': self.thresholds
        }


class ResourceMonitor:
    """Monitors resource usage and limits."""
    
    def __init__(self):
        self.limits = {
            'max_connections': 100,
            'max_memory_mb': 4096,
            'max_disk_gb': 100,
            'max_open_files': 10000
        }
        
        self.usage_history = {
            'connections': [],
            'memory': [],
            'disk': [],
            'files': []
        }
    
    def check_resources(self) -> List[HealthCheck]:
        """Check resource usage against limits."""
        checks = []
        
        # Check database connections
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                if connection.vendor == 'postgresql':
                    cursor.execute("SELECT count(*) FROM pg_stat_activity")
                    active_connections = cursor.fetchone()[0]
                    
                    if active_connections > self.limits['max_connections'] * 0.8:
                        checks.append(HealthCheck(
                            name='database_connections',
                            status=HealthStatus.DEGRADED,
                            message=f"High connection count: {active_connections}/{self.limits['max_connections']}",
                            details={'connections': active_connections}
                        ))
                    else:
                        checks.append(HealthCheck(
                            name='database_connections',
                            status=HealthStatus.HEALTHY,
                            message=f"Connection count normal: {active_connections}/{self.limits['max_connections']}"
                        ))
        except Exception as e:
            checks.append(HealthCheck(
                name='database_connections',
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check connections: {e}"
            ))
        
        # Check memory usage
        try:
            import psutil
            memory = psutil.virtual_memory()
            memory_mb = memory.used / (1024 * 1024)
            
            if memory_mb > self.limits['max_memory_mb'] * 0.9:
                checks.append(HealthCheck(
                    name='memory_usage',
                    status=HealthStatus.CRITICAL,
                    message=f"Critical memory usage: {memory_mb:.0f}MB/{self.limits['max_memory_mb']}MB"
                ))
            elif memory_mb > self.limits['max_memory_mb'] * 0.8:
                checks.append(HealthCheck(
                    name='memory_usage',
                    status=HealthStatus.DEGRADED,
                    message=f"High memory usage: {memory_mb:.0f}MB/{self.limits['max_memory_mb']}MB"
                ))
            else:
                checks.append(HealthCheck(
                    name='memory_usage',
                    status=HealthStatus.HEALTHY,
                    message=f"Memory usage normal: {memory_mb:.0f}MB/{self.limits['max_memory_mb']}MB"
                ))
        except Exception as e:
            checks.append(HealthCheck(
                name='memory_usage',
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check memory: {e}"
            ))
        
        return checks


class HealthMonitor:
    """Comprehensive health monitoring."""
    
    def __init__(self):
        self.checks = {
            'database': self._check_database,
            'cache': self._check_cache,
            'api': self._check_api,
            'disk': self._check_disk,
            'services': self._check_services
        }
        
        self.resource_monitor = ResourceMonitor()
    
    def run_health_checks(self) -> Dict[str, Any]:
        """Run all health checks."""
        results = {
            'timestamp': datetime.now().isoformat(),
            'checks': {},
            'overall_status': HealthStatus.HEALTHY
        }
        
        # Run configured checks
        for name, check_func in self.checks.items():
            try:
                check_result = check_func()
                results['checks'][name] = check_result
                
                # Update overall status
                if check_result.status == HealthStatus.CRITICAL:
                    results['overall_status'] = HealthStatus.CRITICAL
                elif check_result.status == HealthStatus.UNHEALTHY and results['overall_status'] != HealthStatus.CRITICAL:
                    results['overall_status'] = HealthStatus.UNHEALTHY
                elif check_result.status == HealthStatus.DEGRADED and results['overall_status'] == HealthStatus.HEALTHY:
                    results['overall_status'] = HealthStatus.DEGRADED
                    
            except Exception as e:
                results['checks'][name] = HealthCheck(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {e}"
                )
        
        # Run resource checks
        resource_checks = self.resource_monitor.check_resources()
        for check in resource_checks:
            results['checks'][check.name] = check
        
        return results
    
    def _check_database(self) -> HealthCheck:
        """Check database health."""
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            
            return HealthCheck(
                name='database',
                status=HealthStatus.HEALTHY,
                message='Database connection successful'
            )
        except Exception as e:
            return HealthCheck(
                name='database',
                status=HealthStatus.UNHEALTHY,
                message=f'Database connection failed: {e}'
            )
    
    def _check_cache(self) -> HealthCheck:
        """Check cache health."""
        try:
            from django.core.cache import cache
            test_key = '_health_check_test'
            test_value = str(time.time())
            
            cache.set(test_key, test_value, 10)
            retrieved = cache.get(test_key)
            cache.delete(test_key)
            
            if retrieved == test_value:
                return HealthCheck(
                    name='cache',
                    status=HealthStatus.HEALTHY,
                    message='Cache operations successful'
                )
            else:
                return HealthCheck(
                    name='cache',
                    status=HealthStatus.DEGRADED,
                    message='Cache read/write mismatch'
                )
                
        except Exception as e:
            return HealthCheck(
                name='cache',
                status=HealthStatus.UNHEALTHY,
                message=f'Cache operations failed: {e}'
            )
    
    def _check_api(self) -> HealthCheck:
        """Check API health."""
        # Check recent error rate
        try:
            error_rate = metrics_registry.get_metric('api_errors_total')
            total_requests = metrics_registry.get_metric('api_requests_total')
            
            if error_rate and total_requests:
                error_count = error_rate.get_value()
                request_count = total_requests.get_value()
                
                if request_count > 0:
                    rate = (error_count / request_count) * 100
                    
                    if rate > 10:
                        return HealthCheck(
                            name='api',
                            status=HealthStatus.UNHEALTHY,
                            message=f'High API error rate: {rate:.1f}%'
                        )
                    elif rate > 5:
                        return HealthCheck(
                            name='api',
                            status=HealthStatus.DEGRADED,
                            message=f'Elevated API error rate: {rate:.1f}%'
                        )
            
            return HealthCheck(
                name='api',
                status=HealthStatus.HEALTHY,
                message='API operating normally'
            )
            
        except Exception as e:
            return HealthCheck(
                name='api',
                status=HealthStatus.UNHEALTHY,
                message=f'Failed to check API health: {e}'
            )
    
    def _check_disk(self) -> HealthCheck:
        """Check disk space."""
        try:
            import psutil
            disk = psutil.disk_usage('/')
            
            if disk.percent > 90:
                return HealthCheck(
                    name='disk',
                    status=HealthStatus.CRITICAL,
                    message=f'Critical disk usage: {disk.percent}%',
                    details={'free_gb': disk.free / (1024**3)}
                )
            elif disk.percent > 80:
                return HealthCheck(
                    name='disk',
                    status=HealthStatus.DEGRADED,
                    message=f'High disk usage: {disk.percent}%',
                    details={'free_gb': disk.free / (1024**3)}
                )
            else:
                return HealthCheck(
                    name='disk',
                    status=HealthStatus.HEALTHY,
                    message=f'Disk usage normal: {disk.percent}%'
                )
                
        except Exception as e:
            return HealthCheck(
                name='disk',
                status=HealthStatus.UNHEALTHY,
                message=f'Failed to check disk: {e}'
            )
    
    def _check_services(self) -> HealthCheck:
        """Check required services."""
        services_healthy = True
        failed_services = []
        
        # Check Redis
        try:
            from django_redis import get_redis_connection
            redis_conn = get_redis_connection("default")
            redis_conn.ping()
        except:
            services_healthy = False
            failed_services.append('Redis')
        
        # Check Celery (if configured)
        try:
            from celery import current_app
            stats = current_app.control.inspect().stats()
            if not stats:
                services_healthy = False
                failed_services.append('Celery')
        except:
            pass  # Celery might not be configured
        
        if services_healthy:
            return HealthCheck(
                name='services',
                status=HealthStatus.HEALTHY,
                message='All services operational'
            )
        else:
            return HealthCheck(
                name='services',
                status=HealthStatus.UNHEALTHY,
                message=f'Services failed: {", ".join(failed_services)}'
            )


class AlertingMonitor:
    """Monitor with alerting capabilities."""
    
    def __init__(self):
        self.alert_handlers = []
        self.alert_rules = []
        self.alert_history = []
        self.performance_monitor = PerformanceMonitor()
        self.health_monitor = HealthMonitor()
    
    def add_alert_handler(self, handler: Callable[[Dict[str, Any]], None]):
        """Add an alert handler."""
        self.alert_handlers.append(handler)
    
    def add_alert_rule(self, rule: Dict[str, Any]):
        """Add an alert rule."""
        self.alert_rules.append(rule)
    
    def check_alerts(self):
        """Check all alert rules."""
        # Get current metrics
        metrics = self.performance_monitor._collect_all_metrics()
        
        # Check each rule
        for rule in self.alert_rules:
            if self._evaluate_rule(rule, metrics):
                alert = {
                    'rule': rule['name'],
                    'condition': rule['condition'],
                    'severity': rule.get('severity', 'warning'),
                    'message': rule['message'],
                    'timestamp': datetime.now(),
                    'metrics': metrics
                }
                
                self._trigger_alert(alert)
    
    def _evaluate_rule(self, rule: Dict[str, Any], metrics: Dict[str, Any]) -> bool:
        """Evaluate an alert rule."""
        condition = rule['condition']
        
        # Simple threshold conditions
        if 'metric' in condition and 'threshold' in condition:
            metric_value = metrics.get(condition['metric'])
            if metric_value is None:
                return False
            
            operator = condition.get('operator', '>')
            threshold = condition['threshold']
            
            if operator == '>':
                return metric_value > threshold
            elif operator == '<':
                return metric_value < threshold
            elif operator == '>=':
                return metric_value >= threshold
            elif operator == '<=':
                return metric_value <= threshold
            elif operator == '==':
                return metric_value == threshold
        
        return False
    
    def _trigger_alert(self, alert: Dict[str, Any]):
        """Trigger an alert."""
        # Add to history
        self.alert_history.append(alert)
        
        # Keep only recent alerts
        cutoff = datetime.now() - timedelta(hours=24)
        self.alert_history = [a for a in self.alert_history if a['timestamp'] > cutoff]
        
        # Call handlers
        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")