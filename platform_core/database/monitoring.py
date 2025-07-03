"""
Database Performance Monitoring

Real-time monitoring of database performance, queries, and connections.
"""

import logging
import time
import threading
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from collections import defaultdict, deque
from django.db import connection, connections
from django.db.backends.signals import connection_created
from django.db.backends.utils import CursorWrapper
from django.dispatch import receiver
from django.conf import settings
from django.core.cache import cache
import json

logger = logging.getLogger(__name__)


class SlowQueryLogger:
    """
    Log and analyze slow database queries.
    """
    
    def __init__(self, threshold_ms: float = 100):
        self.threshold_ms = threshold_ms
        self.slow_queries = deque(maxlen=1000)  # Keep last 1000 slow queries
        self.query_patterns = defaultdict(lambda: {'count': 0, 'total_time': 0})
        self._lock = threading.Lock()
        
        # Set up query logging
        self._setup_query_logging()
    
    def _setup_query_logging(self):
        """Set up automatic query logging."""
        # Monkey patch cursor execute to log queries
        original_execute = CursorWrapper.execute
        original_executemany = CursorWrapper.executemany
        
        def logged_execute(cursor_self, sql, params=None):
            start_time = time.time()
            try:
                return original_execute(cursor_self, sql, params)
            finally:
                duration = (time.time() - start_time) * 1000  # ms
                self.log_query(sql, duration, params)
        
        def logged_executemany(cursor_self, sql, params_list):
            start_time = time.time()
            try:
                return original_executemany(cursor_self, sql, params_list)
            finally:
                duration = (time.time() - start_time) * 1000  # ms
                self.log_query(sql, duration, params_list, is_many=True)
        
        CursorWrapper.execute = logged_execute
        CursorWrapper.executemany = logged_executemany
    
    def log_query(self, sql: str, duration_ms: float, 
                  params: Optional[Any] = None, is_many: bool = False):
        """Log a query execution."""
        if duration_ms >= self.threshold_ms:
            with self._lock:
                query_info = {
                    'sql': sql,
                    'duration_ms': duration_ms,
                    'timestamp': datetime.now().isoformat(),
                    'params_count': len(params) if params and is_many else 1,
                    'is_slow': True
                }
                
                self.slow_queries.append(query_info)
                
                # Update pattern statistics
                pattern = self._extract_pattern(sql)
                self.query_patterns[pattern]['count'] += 1
                self.query_patterns[pattern]['total_time'] += duration_ms
                
                # Log to file/console
                logger.warning(
                    f"Slow query detected ({duration_ms:.2f}ms): {sql[:100]}..."
                )
                
                # Trigger alert if query is extremely slow
                if duration_ms > self.threshold_ms * 10:  # 10x threshold
                    self._trigger_slow_query_alert(query_info)
    
    def _extract_pattern(self, sql: str) -> str:
        """Extract query pattern for grouping similar queries."""
        # Normalize SQL for pattern matching
        pattern = sql.strip().upper()
        
        # Replace values with placeholders
        import re
        # Replace numbers
        pattern = re.sub(r'\b\d+\b', 'N', pattern)
        # Replace quoted strings
        pattern = re.sub(r"'[^']*'", "'S'", pattern)
        pattern = re.sub(r'"[^"]*"', '"S"', pattern)
        
        # Extract just the main operation and table
        if pattern.startswith('SELECT'):
            match = re.search(r'FROM\s+(\w+)', pattern)
            if match:
                return f"SELECT FROM {match.group(1)}"
        elif pattern.startswith('UPDATE'):
            match = re.search(r'UPDATE\s+(\w+)', pattern)
            if match:
                return f"UPDATE {match.group(1)}"
        elif pattern.startswith('INSERT'):
            match = re.search(r'INTO\s+(\w+)', pattern)
            if match:
                return f"INSERT INTO {match.group(1)}"
        elif pattern.startswith('DELETE'):
            match = re.search(r'FROM\s+(\w+)', pattern)
            if match:
                return f"DELETE FROM {match.group(1)}"
        
        return pattern[:50]  # Fallback to first 50 chars
    
    def _trigger_slow_query_alert(self, query_info: Dict[str, Any]):
        """Trigger alert for extremely slow queries."""
        # In production, this would send to monitoring system
        logger.error(
            f"CRITICAL: Extremely slow query ({query_info['duration_ms']:.2f}ms): "
            f"{query_info['sql'][:200]}..."
        )
        
        # Store in cache for dashboard
        alerts = cache.get('db:slow_query_alerts', [])
        alerts.append(query_info)
        # Keep last 100 alerts
        cache.set('db:slow_query_alerts', alerts[-100:], 3600)
    
    def get_slow_queries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent slow queries."""
        with self._lock:
            return list(self.slow_queries)[-limit:]
    
    def get_query_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Get query pattern statistics."""
        with self._lock:
            patterns = []
            for pattern, stats in self.query_patterns.items():
                patterns.append({
                    'pattern': pattern,
                    'count': stats['count'],
                    'total_time': stats['total_time'],
                    'avg_time': stats['total_time'] / stats['count'] if stats['count'] > 0 else 0
                })
            
            # Sort by total time descending
            patterns.sort(key=lambda x: x['total_time'], reverse=True)
            return patterns
    
    def analyze_trends(self, window_minutes: int = 60) -> Dict[str, Any]:
        """Analyze slow query trends over time window."""
        cutoff_time = datetime.now() - timedelta(minutes=window_minutes)
        
        with self._lock:
            recent_queries = [
                q for q in self.slow_queries
                if datetime.fromisoformat(q['timestamp']) > cutoff_time
            ]
        
        if not recent_queries:
            return {'status': 'no_data'}
        
        # Calculate trends
        total_slow = len(recent_queries)
        avg_duration = sum(q['duration_ms'] for q in recent_queries) / total_slow
        
        # Group by time buckets
        bucket_size = max(1, window_minutes // 10)  # 10 buckets
        buckets = defaultdict(list)
        
        for query in recent_queries:
            timestamp = datetime.fromisoformat(query['timestamp'])
            bucket = int((timestamp - cutoff_time).total_seconds() / 60 / bucket_size)
            buckets[bucket].append(query['duration_ms'])
        
        # Calculate trend
        bucket_avgs = []
        for i in range(10):
            if i in buckets:
                bucket_avgs.append(sum(buckets[i]) / len(buckets[i]))
            else:
                bucket_avgs.append(0)
        
        # Simple trend detection
        first_half = sum(bucket_avgs[:5]) / 5
        second_half = sum(bucket_avgs[5:]) / 5
        
        if second_half > first_half * 1.2:
            trend = 'increasing'
        elif second_half < first_half * 0.8:
            trend = 'decreasing'
        else:
            trend = 'stable'
        
        return {
            'total_slow_queries': total_slow,
            'average_duration_ms': avg_duration,
            'trend': trend,
            'buckets': bucket_avgs,
            'window_minutes': window_minutes
        }


class ConnectionMonitor:
    """
    Monitor database connection pool and usage.
    """
    
    def __init__(self):
        self.connection_stats = defaultdict(lambda: {
            'active': 0,
            'idle': 0,
            'total': 0,
            'max_seen': 0
        })
        self.connection_history = deque(maxlen=1000)
        self._lock = threading.Lock()
        
        # Start monitoring thread
        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_connections)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()
    
    def _monitor_connections(self):
        """Background thread to monitor connections."""
        while self._monitoring:
            try:
                for alias in connections:
                    stats = self._get_connection_stats(alias)
                    
                    with self._lock:
                        self.connection_stats[alias].update(stats)
                        
                        # Update max seen
                        if stats['total'] > self.connection_stats[alias]['max_seen']:
                            self.connection_stats[alias]['max_seen'] = stats['total']
                        
                        # Add to history
                        self.connection_history.append({
                            'timestamp': datetime.now().isoformat(),
                            'alias': alias,
                            'stats': stats.copy()
                        })
                
                # Check for connection pool issues
                self._check_connection_health()
                
            except Exception as e:
                logger.error(f"Error monitoring connections: {e}")
            
            time.sleep(30)  # Check every 30 seconds
    
    def _get_connection_stats(self, alias: str) -> Dict[str, int]:
        """Get current connection statistics."""
        stats = {
            'active': 0,
            'idle': 0,
            'idle_in_transaction': 0,
            'total': 0
        }
        
        try:
            with connections[alias].cursor() as cursor:
                cursor.execute("""
                    SELECT state, COUNT(*)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                    GROUP BY state
                """)
                
                for state, count in cursor.fetchall():
                    if state == 'active':
                        stats['active'] = count
                    elif state == 'idle':
                        stats['idle'] = count
                    elif state == 'idle in transaction':
                        stats['idle_in_transaction'] = count
                    
                    stats['total'] += count
                
        except Exception as e:
            logger.error(f"Error getting connection stats for {alias}: {e}")
        
        return stats
    
    def _check_connection_health(self):
        """Check for connection pool health issues."""
        for alias, stats in self.connection_stats.items():
            # Check for connection leaks
            if stats['idle_in_transaction'] > 5:
                logger.warning(
                    f"Potential connection leak on {alias}: "
                    f"{stats['idle_in_transaction']} idle in transaction"
                )
                self._trigger_connection_alert(alias, 'leak', stats)
            
            # Check for connection exhaustion
            max_conn = getattr(settings, 'DATABASES', {}).get(alias, {}).get('OPTIONS', {}).get('MAX_CONNS', 100)
            if stats['total'] > max_conn * 0.9:
                logger.warning(
                    f"Connection pool near exhaustion on {alias}: "
                    f"{stats['total']}/{max_conn}"
                )
                self._trigger_connection_alert(alias, 'exhaustion', stats)
    
    def _trigger_connection_alert(self, alias: str, alert_type: str, stats: Dict[str, Any]):
        """Trigger connection alert."""
        alert = {
            'timestamp': datetime.now().isoformat(),
            'alias': alias,
            'type': alert_type,
            'stats': stats,
            'message': f"Database connection {alert_type} detected"
        }
        
        # Store in cache for dashboard
        alerts = cache.get('db:connection_alerts', [])
        alerts.append(alert)
        cache.set('db:connection_alerts', alerts[-100:], 3600)
    
    def get_current_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get current connection statistics."""
        with self._lock:
            return dict(self.connection_stats)
    
    def get_connection_history(self, alias: Optional[str] = None, 
                             minutes: int = 60) -> List[Dict[str, Any]]:
        """Get connection history."""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        
        with self._lock:
            history = [
                h for h in self.connection_history
                if datetime.fromisoformat(h['timestamp']) > cutoff_time
            ]
            
            if alias:
                history = [h for h in history if h['alias'] == alias]
        
        return history
    
    def stop(self):
        """Stop monitoring thread."""
        self._monitoring = False
        if self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)


class DatabaseMonitor:
    """
    Comprehensive database monitoring coordinator.
    """
    
    def __init__(self):
        self.slow_query_logger = SlowQueryLogger(
            threshold_ms=getattr(settings, 'SLOW_QUERY_THRESHOLD', 100)
        )
        self.connection_monitor = ConnectionMonitor()
        self.metrics = defaultdict(lambda: defaultdict(int))
        self._callbacks = []
    
    def add_metric_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Add callback for metric events."""
        self._callbacks.append(callback)
    
    def _emit_metric(self, metric_type: str, data: Dict[str, Any]):
        """Emit metric to callbacks."""
        for callback in self._callbacks:
            try:
                callback(metric_type, data)
            except Exception as e:
                logger.error(f"Error in metric callback: {e}")
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive monitoring data for dashboard."""
        return {
            'timestamp': datetime.now().isoformat(),
            'slow_queries': {
                'recent': self.slow_query_logger.get_slow_queries(50),
                'patterns': self.slow_query_logger.get_query_patterns(),
                'trends': self.slow_query_logger.analyze_trends()
            },
            'connections': {
                'current': self.connection_monitor.get_current_stats(),
                'history': self.connection_monitor.get_connection_history(minutes=30)
            },
            'alerts': {
                'slow_queries': cache.get('db:slow_query_alerts', [])[-10:],
                'connections': cache.get('db:connection_alerts', [])[-10:]
            },
            'health_score': self._calculate_health_score()
        }
    
    def _calculate_health_score(self) -> Dict[str, Any]:
        """Calculate overall database health score."""
        score = 100
        issues = []
        
        # Check slow query trends
        trends = self.slow_query_logger.analyze_trends(60)
        if trends.get('trend') == 'increasing':
            score -= 20
            issues.append("Increasing slow query trend")
        
        # Check connection health
        conn_stats = self.connection_monitor.get_current_stats()
        for alias, stats in conn_stats.items():
            if stats['idle_in_transaction'] > 5:
                score -= 15
                issues.append(f"Connection leaks on {alias}")
            
            if stats['max_seen'] > 80:  # Assuming 100 max connections
                score -= 10
                issues.append(f"High connection usage on {alias}")
        
        # Check for recent alerts
        slow_alerts = len(cache.get('db:slow_query_alerts', []))
        conn_alerts = len(cache.get('db:connection_alerts', []))
        
        if slow_alerts > 10:
            score -= 10
            issues.append("Multiple slow query alerts")
        
        if conn_alerts > 5:
            score -= 10
            issues.append("Multiple connection alerts")
        
        return {
            'score': max(0, score),
            'status': 'healthy' if score >= 70 else 'degraded' if score >= 40 else 'critical',
            'issues': issues
        }
    
    def create_monitoring_report(self) -> Dict[str, Any]:
        """Create detailed monitoring report."""
        report = {
            'generated_at': datetime.now().isoformat(),
            'period': '24 hours',
            'summary': self.get_dashboard_data(),
            'recommendations': []
        }
        
        # Add recommendations based on data
        health = report['summary']['health_score']
        
        if health['score'] < 70:
            report['recommendations'].extend([
                "Database health is degraded. Immediate attention required.",
                "Review slow query patterns and add appropriate indexes.",
                "Check application code for connection leaks."
            ])
        
        # Specific recommendations
        patterns = report['summary']['slow_queries']['patterns']
        if patterns:
            top_pattern = patterns[0]
            report['recommendations'].append(
                f"Optimize queries matching pattern: {top_pattern['pattern']} "
                f"(avg {top_pattern['avg_time']:.2f}ms)"
            )
        
        return report
    
    def export_metrics(self, format: str = 'prometheus') -> str:
        """Export metrics in specified format."""
        if format == 'prometheus':
            return self._export_prometheus()
        elif format == 'json':
            return json.dumps(self.get_dashboard_data(), indent=2)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        
        # Slow query metrics
        slow_queries = self.slow_query_logger.get_slow_queries()
        lines.append(f"# HELP db_slow_queries_total Total slow queries")
        lines.append(f"# TYPE db_slow_queries_total counter")
        lines.append(f"db_slow_queries_total {len(slow_queries)}")
        
        # Connection metrics
        for alias, stats in self.connection_monitor.get_current_stats().items():
            lines.append(f"# HELP db_connections_active Active database connections")
            lines.append(f"# TYPE db_connections_active gauge")
            lines.append(f'db_connections_active{{alias="{alias}"}} {stats["active"]}')
            
            lines.append(f"# HELP db_connections_idle Idle database connections")
            lines.append(f"# TYPE db_connections_idle gauge")
            lines.append(f'db_connections_idle{{alias="{alias}"}} {stats["idle"]}')
        
        # Health score
        health = self._calculate_health_score()
        lines.append(f"# HELP db_health_score Database health score (0-100)")
        lines.append(f"# TYPE db_health_score gauge")
        lines.append(f"db_health_score {health['score']}")
        
        return "\n".join(lines)


# Global monitor instance
database_monitor = DatabaseMonitor()


# Signal receiver for connection creation
@receiver(connection_created)
def log_connection_created(sender, connection, **kwargs):
    """Log when new database connection is created."""
    logger.info(f"Database connection created: {connection.alias}")
    database_monitor._emit_metric('connection_created', {
        'alias': connection.alias,
        'timestamp': datetime.now().isoformat()
    })