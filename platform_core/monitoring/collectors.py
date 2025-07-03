"""
Metrics Collectors

Specialized collectors for different system components.
"""

import os
import time
import psutil
import threading
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from django.db import connection
from django.core.cache import cache
from django.conf import settings
import logging

from .metrics import MetricsCollector, metrics_registry

logger = logging.getLogger(__name__)


class SystemMetricsCollector(MetricsCollector):
    """Collects system-level metrics."""
    
    def __init__(self, registry=None):
        super().__init__(registry or metrics_registry)
        self._last_cpu_time = None
        self._last_disk_io = None
        self._last_net_io = None
        
        # Register metrics
        self.cpu_gauge = self.registry.gauge('system_cpu_usage_percent', 'CPU usage percentage')
        self.memory_gauge = self.registry.gauge('system_memory_usage_bytes', 'Memory usage in bytes')
        self.memory_percent_gauge = self.registry.gauge('system_memory_usage_percent', 'Memory usage percentage')
        self.disk_gauge = self.registry.gauge('system_disk_usage_percent', 'Disk usage percentage')
        self.process_gauge = self.registry.gauge('system_process_count', 'Number of processes')
        self.thread_gauge = self.registry.gauge('system_thread_count', 'Number of threads')
        
        # Start collection thread
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._collect_loop)
        self._thread.daemon = True
        self._thread.start()
    
    def _collect_loop(self):
        """Background collection loop."""
        while not self._stop_event.is_set():
            try:
                self.collect()
            except Exception as e:
                logger.error(f"System metrics collection error: {e}")
            
            self._stop_event.wait(10)  # Collect every 10 seconds
    
    def collect(self) -> List[Dict[str, Any]]:
        """Collect system metrics."""
        if not self.is_enabled():
            return []
        
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            self.cpu_gauge.set(cpu_percent)
            
            # Memory usage
            memory = psutil.virtual_memory()
            self.memory_gauge.set(memory.used)
            self.memory_percent_gauge.set(memory.percent)
            
            # Disk usage
            disk = psutil.disk_usage('/')
            self.disk_gauge.set(disk.percent)
            
            # Process count
            process_count = len(psutil.pids())
            self.process_gauge.set(process_count)
            
            # Thread count for current process
            current_process = psutil.Process()
            thread_count = current_process.num_threads()
            self.thread_gauge.set(thread_count)
            
            # Network I/O
            net_io = psutil.net_io_counters()
            if self._last_net_io:
                bytes_sent_per_sec = (net_io.bytes_sent - self._last_net_io.bytes_sent) / 10
                bytes_recv_per_sec = (net_io.bytes_recv - self._last_net_io.bytes_recv) / 10
                
                self.registry.gauge('system_network_sent_bytes_per_second').set(bytes_sent_per_sec)
                self.registry.gauge('system_network_received_bytes_per_second').set(bytes_recv_per_sec)
            
            self._last_net_io = net_io
            
            # Disk I/O
            disk_io = psutil.disk_io_counters()
            if self._last_disk_io:
                read_per_sec = (disk_io.read_bytes - self._last_disk_io.read_bytes) / 10
                write_per_sec = (disk_io.write_bytes - self._last_disk_io.write_bytes) / 10
                
                self.registry.gauge('system_disk_read_bytes_per_second').set(read_per_sec)
                self.registry.gauge('system_disk_write_bytes_per_second').set(write_per_sec)
            
            self._last_disk_io = disk_io
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
        
        return []
    
    def stop(self):
        """Stop collection thread."""
        self._stop_event.set()
        self._thread.join(timeout=5)


class DatabaseMetricsCollector(MetricsCollector):
    """Collects database performance metrics."""
    
    def __init__(self, registry=None):
        super().__init__(registry or metrics_registry)
        
        # Register metrics
        self.query_counter = self.registry.counter('db_queries_total', 'Total database queries')
        self.query_timer = self.registry.timer('db_query_duration_seconds', 'Query execution time')
        self.connection_gauge = self.registry.gauge('db_connections_active', 'Active database connections')
        self.transaction_counter = self.registry.counter('db_transactions_total', 'Total transactions')
        self.error_counter = self.registry.counter('db_errors_total', 'Database errors')
    
    def collect(self) -> List[Dict[str, Any]]:
        """Collect database metrics."""
        if not self.is_enabled():
            return []
        
        metrics = []
        
        try:
            # Get connection stats
            with connection.cursor() as cursor:
                # PostgreSQL specific queries
                if connection.vendor == 'postgresql':
                    # Active connections
                    cursor.execute("""
                        SELECT count(*) FROM pg_stat_activity
                        WHERE state = 'active'
                    """)
                    active_connections = cursor.fetchone()[0]
                    self.connection_gauge.set(active_connections)
                    
                    # Database size
                    cursor.execute("""
                        SELECT pg_database_size(current_database())
                    """)
                    db_size = cursor.fetchone()[0]
                    self.registry.gauge('db_size_bytes').set(db_size)
                    
                    # Table statistics
                    cursor.execute("""
                        SELECT 
                            schemaname,
                            tablename,
                            n_tup_ins,
                            n_tup_upd,
                            n_tup_del,
                            n_live_tup,
                            n_dead_tup
                        FROM pg_stat_user_tables
                    """)
                    
                    for row in cursor.fetchall():
                        schema, table, inserts, updates, deletes, live, dead = row
                        labels = {'schema': schema, 'table': table}
                        
                        self.registry.counter('db_table_inserts_total', labels=labels).inc(inserts)
                        self.registry.counter('db_table_updates_total', labels=labels).inc(updates)
                        self.registry.counter('db_table_deletes_total', labels=labels).inc(deletes)
                        self.registry.gauge('db_table_rows_live', labels=labels).set(live)
                        self.registry.gauge('db_table_rows_dead', labels=labels).set(dead)
                
        except Exception as e:
            logger.error(f"Error collecting database metrics: {e}")
            self.error_counter.inc()
        
        return metrics


class CacheMetricsCollector(MetricsCollector):
    """Collects cache performance metrics."""
    
    def __init__(self, registry=None):
        super().__init__(registry or metrics_registry)
        
        # Register metrics
        self.hit_counter = self.registry.counter('cache_hits_total', 'Cache hits')
        self.miss_counter = self.registry.counter('cache_misses_total', 'Cache misses')
        self.set_counter = self.registry.counter('cache_sets_total', 'Cache sets')
        self.delete_counter = self.registry.counter('cache_deletes_total', 'Cache deletes')
        self.eviction_counter = self.registry.counter('cache_evictions_total', 'Cache evictions')
        
        self._instrument_cache()
    
    def _instrument_cache(self):
        """Instrument Django cache to collect metrics."""
        # Wrap cache methods to collect metrics
        original_get = cache.get
        original_set = cache.set
        original_delete = cache.delete
        
        def instrumented_get(key, default=None, version=None):
            result = original_get(key, default, version)
            if result is not default:
                self.hit_counter.inc()
            else:
                self.miss_counter.inc()
            return result
        
        def instrumented_set(key, value, timeout=None, version=None):
            self.set_counter.inc()
            return original_set(key, value, timeout, version)
        
        def instrumented_delete(key, version=None):
            self.delete_counter.inc()
            return original_delete(key, version)
        
        # Replace methods
        cache.get = instrumented_get
        cache.set = instrumented_set
        cache.delete = instrumented_delete
    
    def collect(self) -> List[Dict[str, Any]]:
        """Collect cache metrics."""
        if not self.is_enabled():
            return []
        
        # Calculate hit rate
        hits = self.hit_counter.get_value()
        misses = self.miss_counter.get_value()
        total = hits + misses
        
        if total > 0:
            hit_rate = (hits / total) * 100
            self.registry.gauge('cache_hit_rate_percent').set(hit_rate)
        
        return []


class APIMetricsCollector(MetricsCollector):
    """Collects API performance metrics."""
    
    def __init__(self, registry=None):
        super().__init__(registry or metrics_registry)
        
        # Register metrics per endpoint
        self.request_counter = self.registry.counter(
            'api_requests_total',
            'Total API requests',
            labels={'method': '', 'endpoint': '', 'status': ''}
        )
        self.request_timer = self.registry.timer(
            'api_request_duration_seconds',
            'API request duration',
            labels={'method': '', 'endpoint': ''}
        )
        self.active_requests = self.registry.gauge(
            'api_requests_active',
            'Currently active requests'
        )
        self.error_counter = self.registry.counter(
            'api_errors_total',
            'API errors',
            labels={'method': '', 'endpoint': '', 'error_type': ''}
        )
    
    def record_request(self, method: str, endpoint: str, status: int, duration: float):
        """Record API request metrics."""
        labels = {'method': method, 'endpoint': endpoint, 'status': str(status)}
        self.request_counter.labels = labels
        self.request_counter.inc()
        
        timer_labels = {'method': method, 'endpoint': endpoint}
        self.request_timer.labels = timer_labels
        self.request_timer.observe(duration)
        
        # Track errors
        if status >= 400:
            error_type = '4xx' if status < 500 else '5xx'
            error_labels = {'method': method, 'endpoint': endpoint, 'error_type': error_type}
            self.error_counter.labels = error_labels
            self.error_counter.inc()
    
    def collect(self) -> List[Dict[str, Any]]:
        """Collect API metrics."""
        return []


class BusinessMetricsCollector(MetricsCollector):
    """Collects business-specific metrics."""
    
    def __init__(self, registry=None):
        super().__init__(registry or metrics_registry)
        
        # Register business metrics
        self.user_gauge = self.registry.gauge('business_users_total', 'Total users')
        self.active_user_gauge = self.registry.gauge('business_users_active', 'Active users')
        self.assessment_counter = self.registry.counter('business_assessments_created', 'Assessments created')
        self.deal_gauge = self.registry.gauge('business_deals_active', 'Active deals')
        self.lead_gauge = self.registry.gauge('business_leads_total', 'Total leads')
        self.revenue_gauge = self.registry.gauge('business_revenue_total', 'Total revenue')
    
    def collect(self) -> List[Dict[str, Any]]:
        """Collect business metrics."""
        if not self.is_enabled():
            return []
        
        try:
            # Import models dynamically to avoid circular imports
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            # User metrics
            total_users = User.objects.count()
            self.user_gauge.set(total_users)
            
            # Active users (logged in within last 30 days)
            thirty_days_ago = datetime.now() - timedelta(days=30)
            active_users = User.objects.filter(last_login__gte=thirty_days_ago).count()
            self.active_user_gauge.set(active_users)
            
            # Try to import business models
            try:
                from investment_module.models import Deal, Lead, Assessment
                
                # Deal metrics
                active_deals = Deal.objects.filter(status__in=['PIPELINE', 'DUE_DILIGENCE']).count()
                self.deal_gauge.set(active_deals)
                
                # Lead metrics
                total_leads = Lead.objects.count()
                self.lead_gauge.set(total_leads)
                
                # Assessment metrics
                assessment_count = Assessment.objects.count()
                self.assessment_counter._value = assessment_count
                
            except ImportError:
                logger.debug("Business models not available")
            
        except Exception as e:
            logger.error(f"Error collecting business metrics: {e}")
        
        return []