"""
Health Check Implementation
"""
import time
import logging
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    UNHEALTHY = 'unhealthy'
    CRITICAL = 'critical'


@dataclass
class HealthCheckResult:
    """Result of a health check"""
    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any]
    duration_ms: float
    timestamp: str


class HealthCheck:
    """Base health check class"""
    
    def __init__(self, name: str, critical: bool = False):
        self.name = name
        self.critical = critical
    
    def check(self) -> HealthCheckResult:
        """Run the health check"""
        start_time = time.time()
        
        try:
            status, message, details = self._perform_check()
            duration_ms = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                name=self.name,
                status=status,
                message=message,
                details=details,
                duration_ms=duration_ms,
                timestamp=timezone.now().isoformat()
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Health check {self.name} failed: {e}")
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.CRITICAL if self.critical else HealthStatus.UNHEALTHY,
                message=f"Check failed: {str(e)}",
                details={'error': str(e)},
                duration_ms=duration_ms,
                timestamp=timezone.now().isoformat()
            )
    
    def _perform_check(self) -> tuple[HealthStatus, str, Dict[str, Any]]:
        """Perform the actual health check - override in subclasses"""
        raise NotImplementedError


class DatabaseHealthCheck(HealthCheck):
    """Database connectivity and performance check"""
    
    def __init__(self):
        super().__init__('database', critical=True)
    
    def _perform_check(self) -> tuple[HealthStatus, str, Dict[str, Any]]:
        """Check database health"""
        details = {}
        
        # Check basic connectivity
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result[0] != 1:
                    return HealthStatus.CRITICAL, "Database query failed", details
        except Exception as e:
            return HealthStatus.CRITICAL, f"Database connection failed: {e}", details
        
        # Check connection pool
        connection_count = len(connection.queries)
        details['connection_count'] = connection_count
        
        # Check query performance
        start = time.time()
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM django_migrations")
            count = cursor.fetchone()[0]
        
        query_time = (time.time() - start) * 1000
        details['query_time_ms'] = query_time
        details['migration_count'] = count
        
        # Determine status
        if query_time > 100:  # Over 100ms is concerning
            return HealthStatus.DEGRADED, f"Slow database queries ({query_time:.1f}ms)", details
        
        return HealthStatus.HEALTHY, "Database is healthy", details


class CacheHealthCheck(HealthCheck):
    """Redis cache connectivity and performance check"""
    
    def __init__(self):
        super().__init__('cache', critical=False)
    
    def _perform_check(self) -> tuple[HealthStatus, str, Dict[str, Any]]:
        """Check cache health"""
        details = {}
        test_key = '_health_check_test'
        test_value = 'healthy'
        
        try:
            # Test write
            start = time.time()
            cache.set(test_key, test_value, 10)
            write_time = (time.time() - start) * 1000
            details['write_time_ms'] = write_time
            
            # Test read
            start = time.time()
            value = cache.get(test_key)
            read_time = (time.time() - start) * 1000
            details['read_time_ms'] = read_time
            
            if value != test_value:
                return HealthStatus.UNHEALTHY, "Cache read/write mismatch", details
            
            # Test delete
            cache.delete(test_key)
            
            # Check performance
            if write_time > 50 or read_time > 50:
                return HealthStatus.DEGRADED, f"Slow cache operations", details
            
            return HealthStatus.HEALTHY, "Cache is healthy", details
            
        except Exception as e:
            return HealthStatus.UNHEALTHY, f"Cache error: {e}", details


class CeleryHealthCheck(HealthCheck):
    """Celery worker and broker connectivity check"""
    
    def __init__(self):
        super().__init__('celery', critical=False)
    
    def _perform_check(self) -> tuple[HealthStatus, str, Dict[str, Any]]:
        """Check Celery health"""
        from celery import current_app
        details = {}
        
        try:
            # Check broker connection
            conn = current_app.connection()
            conn.ensure_connection(max_retries=1)
            conn.close()
            details['broker_connected'] = True
            
            # Check active workers
            inspect = current_app.control.inspect()
            stats = inspect.stats()
            
            if not stats:
                return HealthStatus.UNHEALTHY, "No active Celery workers", details
            
            worker_count = len(stats)
            details['worker_count'] = worker_count
            details['workers'] = list(stats.keys())
            
            # Check task queue sizes
            active = inspect.active()
            if active:
                total_active = sum(len(tasks) for tasks in active.values())
                details['active_tasks'] = total_active
                
                if total_active > 1000:
                    return HealthStatus.DEGRADED, f"High task queue ({total_active} tasks)", details
            
            return HealthStatus.HEALTHY, f"{worker_count} workers active", details
            
        except Exception as e:
            return HealthStatus.UNHEALTHY, f"Celery check failed: {e}", details


class FileStorageHealthCheck(HealthCheck):
    """File storage (S3/local) health check"""
    
    def __init__(self):
        super().__init__('file_storage', critical=False)
    
    def _perform_check(self) -> tuple[HealthStatus, str, Dict[str, Any]]:
        """Check file storage health"""
        from django.core.files.storage import default_storage
        details = {}
        
        try:
            # Test file operations
            test_file = 'health_check/test.txt'
            test_content = b'health check'
            
            # Write
            start = time.time()
            default_storage.save(test_file, test_content)
            write_time = (time.time() - start) * 1000
            details['write_time_ms'] = write_time
            
            # Read
            start = time.time()
            exists = default_storage.exists(test_file)
            read_time = (time.time() - start) * 1000
            details['read_time_ms'] = read_time
            
            if not exists:
                return HealthStatus.UNHEALTHY, "File storage write/read failed", details
            
            # Delete
            default_storage.delete(test_file)
            
            # Check performance
            if write_time > 1000 or read_time > 500:
                return HealthStatus.DEGRADED, "Slow file storage operations", details
            
            return HealthStatus.HEALTHY, "File storage is healthy", details
            
        except Exception as e:
            return HealthStatus.UNHEALTHY, f"File storage error: {e}", details


class ExternalServicesHealthCheck(HealthCheck):
    """Check connectivity to external services"""
    
    def __init__(self):
        super().__init__('external_services', critical=False)
    
    def _perform_check(self) -> tuple[HealthStatus, str, Dict[str, Any]]:
        """Check external service connectivity"""
        import requests
        details = {}
        unhealthy_services = []
        
        # Define services to check
        services = {
            'dns': 'https://1.1.1.1',
            'google': 'https://www.google.com',
        }
        
        # Add configured services
        if hasattr(settings, 'HEALTH_CHECK_EXTERNAL_SERVICES'):
            services.update(settings.HEALTH_CHECK_EXTERNAL_SERVICES)
        
        for name, url in services.items():
            try:
                start = time.time()
                response = requests.head(url, timeout=5)
                response_time = (time.time() - start) * 1000
                
                details[f'{name}_status'] = response.status_code
                details[f'{name}_time_ms'] = response_time
                
                if response.status_code >= 500:
                    unhealthy_services.append(name)
                
            except Exception as e:
                details[f'{name}_error'] = str(e)
                unhealthy_services.append(name)
        
        if unhealthy_services:
            if len(unhealthy_services) == len(services):
                return HealthStatus.CRITICAL, "All external services unreachable", details
            else:
                return HealthStatus.DEGRADED, f"Some services unreachable: {', '.join(unhealthy_services)}", details
        
        return HealthStatus.HEALTHY, "All external services reachable", details


class DiskSpaceHealthCheck(HealthCheck):
    """Check available disk space"""
    
    def __init__(self):
        super().__init__('disk_space', critical=True)
    
    def _perform_check(self) -> tuple[HealthStatus, str, Dict[str, Any]]:
        """Check disk space"""
        import shutil
        details = {}
        
        try:
            # Check main disk
            stat = shutil.disk_usage('/')
            
            total_gb = stat.total / (1024 ** 3)
            used_gb = stat.used / (1024 ** 3)
            free_gb = stat.free / (1024 ** 3)
            percent_used = (stat.used / stat.total) * 100
            
            details['total_gb'] = round(total_gb, 2)
            details['used_gb'] = round(used_gb, 2)
            details['free_gb'] = round(free_gb, 2)
            details['percent_used'] = round(percent_used, 2)
            
            # Determine status
            if percent_used > 95:
                return HealthStatus.CRITICAL, f"Disk space critical ({percent_used:.1f}% used)", details
            elif percent_used > 85:
                return HealthStatus.UNHEALTHY, f"Low disk space ({percent_used:.1f}% used)", details
            elif percent_used > 75:
                return HealthStatus.DEGRADED, f"Disk space warning ({percent_used:.1f}% used)", details
            
            return HealthStatus.HEALTHY, f"Adequate disk space ({percent_used:.1f}% used)", details
            
        except Exception as e:
            return HealthStatus.UNHEALTHY, f"Disk check failed: {e}", details


class HealthCheckRegistry:
    """Registry for health checks"""
    
    def __init__(self):
        self._checks: Dict[str, HealthCheck] = {}
        self._initialize_default_checks()
    
    def _initialize_default_checks(self):
        """Register default health checks"""
        self.register(DatabaseHealthCheck())
        self.register(CacheHealthCheck())
        self.register(CeleryHealthCheck())
        self.register(FileStorageHealthCheck())
        self.register(ExternalServicesHealthCheck())
        self.register(DiskSpaceHealthCheck())
    
    def register(self, check: HealthCheck) -> None:
        """Register a health check"""
        self._checks[check.name] = check
    
    def unregister(self, name: str) -> None:
        """Unregister a health check"""
        self._checks.pop(name, None)
    
    def run_all_checks(self) -> Dict[str, Any]:
        """Run all registered health checks"""
        results = {}
        overall_status = HealthStatus.HEALTHY
        critical_failed = False
        
        for name, check in self._checks.items():
            result = check.check()
            results[name] = result
            
            # Update overall status
            if check.critical and result.status in [HealthStatus.CRITICAL, HealthStatus.UNHEALTHY]:
                critical_failed = True
                overall_status = HealthStatus.CRITICAL
            elif result.status == HealthStatus.CRITICAL:
                if overall_status != HealthStatus.CRITICAL:
                    overall_status = HealthStatus.CRITICAL
            elif result.status == HealthStatus.UNHEALTHY:
                if overall_status not in [HealthStatus.CRITICAL]:
                    overall_status = HealthStatus.UNHEALTHY
            elif result.status == HealthStatus.DEGRADED:
                if overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.DEGRADED
        
        return {
            'status': overall_status,
            'timestamp': timezone.now().isoformat(),
            'checks': results,
            'critical_failure': critical_failed
        }
    
    def run_check(self, name: str) -> Optional[HealthCheckResult]:
        """Run a specific health check"""
        check = self._checks.get(name)
        if check:
            return check.check()
        return None


# Global registry instance
health_check_registry = HealthCheckRegistry()