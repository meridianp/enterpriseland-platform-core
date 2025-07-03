"""
Kubernetes-style Readiness and Liveness Probes
"""
import time
import logging
from typing import Dict, Any, Optional
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from .checks import health_check_registry, HealthStatus

logger = logging.getLogger(__name__)


class ReadinessProbe:
    """
    Readiness probe to determine if the service is ready to accept traffic.
    
    Checks:
    - Database connectivity
    - Cache connectivity
    - Required services are running
    - Migrations are up to date
    """
    
    def __init__(self):
        self.timeout = getattr(settings, 'READINESS_PROBE_TIMEOUT', 10)
        self.required_checks = getattr(
            settings, 
            'READINESS_REQUIRED_CHECKS', 
            ['database', 'cache']
        )
    
    def is_ready(self) -> tuple[bool, Dict[str, Any]]:
        """
        Check if service is ready to accept traffic
        
        Returns:
            tuple: (is_ready, details)
        """
        start_time = time.time()
        details = {
            'timestamp': timezone.now().isoformat(),
            'checks': {}
        }
        
        try:
            # Check database
            if 'database' in self.required_checks:
                db_ready, db_details = self._check_database()
                details['checks']['database'] = {
                    'ready': db_ready,
                    'details': db_details
                }
                if not db_ready:
                    details['ready'] = False
                    details['reason'] = 'Database not ready'
                    return False, details
            
            # Check cache
            if 'cache' in self.required_checks:
                cache_ready, cache_details = self._check_cache()
                details['checks']['cache'] = {
                    'ready': cache_ready,
                    'details': cache_details
                }
                if not cache_ready:
                    details['ready'] = False
                    details['reason'] = 'Cache not ready'
                    return False, details
            
            # Check migrations
            if 'migrations' in self.required_checks:
                migrations_ready, migration_details = self._check_migrations()
                details['checks']['migrations'] = {
                    'ready': migrations_ready,
                    'details': migration_details
                }
                if not migrations_ready:
                    details['ready'] = False
                    details['reason'] = 'Migrations not up to date'
                    return False, details
            
            # Run custom health checks
            health_results = health_check_registry.run_all_checks()
            for check_name in self.required_checks:
                if check_name in health_results['checks']:
                    check_result = health_results['checks'][check_name]
                    is_healthy = check_result.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
                    details['checks'][check_name] = {
                        'ready': is_healthy,
                        'status': check_result.status.value,
                        'message': check_result.message
                    }
                    if not is_healthy:
                        details['ready'] = False
                        details['reason'] = f'{check_name} check failed'
                        return False, details
            
            # All checks passed
            duration = (time.time() - start_time) * 1000
            details['ready'] = True
            details['duration_ms'] = duration
            
            return True, details
            
        except Exception as e:
            logger.error(f"Readiness probe failed: {e}")
            details['ready'] = False
            details['error'] = str(e)
            details['duration_ms'] = (time.time() - start_time) * 1000
            return False, details
    
    def _check_database(self) -> tuple[bool, Dict[str, Any]]:
        """Check database connectivity"""
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                return result[0] == 1, {'connected': True}
        except Exception as e:
            return False, {'connected': False, 'error': str(e)}
    
    def _check_cache(self) -> tuple[bool, Dict[str, Any]]:
        """Check cache connectivity"""
        try:
            test_key = '_readiness_probe'
            cache.set(test_key, 'ready', 5)
            value = cache.get(test_key)
            cache.delete(test_key)
            return value == 'ready', {'connected': True}
        except Exception as e:
            return False, {'connected': False, 'error': str(e)}
    
    def _check_migrations(self) -> tuple[bool, Dict[str, Any]]:
        """Check if migrations are up to date"""
        try:
            from django.core.management import call_command
            from io import StringIO
            
            out = StringIO()
            call_command('showmigrations', '--plan', stdout=out)
            output = out.getvalue()
            
            # Check if any migrations are not applied
            unapplied = []
            for line in output.split('\n'):
                if '[ ]' in line:  # Unapplied migration
                    unapplied.append(line.strip())
            
            if unapplied:
                return False, {
                    'up_to_date': False,
                    'unapplied_count': len(unapplied),
                    'unapplied': unapplied[:5]  # Show first 5
                }
            
            return True, {'up_to_date': True}
            
        except Exception as e:
            # If we can't check, assume they're okay
            logger.warning(f"Could not check migrations: {e}")
            return True, {'check_skipped': True, 'reason': str(e)}


class LivenessProbe:
    """
    Liveness probe to determine if the service is alive and should not be restarted.
    
    This is a simpler check than readiness - just verifies the process is responsive.
    """
    
    def __init__(self):
        self.timeout = getattr(settings, 'LIVENESS_PROBE_TIMEOUT', 5)
        self.failure_threshold = getattr(settings, 'LIVENESS_FAILURE_THRESHOLD', 3)
        self._failure_count = 0
    
    def is_alive(self) -> tuple[bool, Dict[str, Any]]:
        """
        Check if service is alive
        
        Returns:
            tuple: (is_alive, details)
        """
        start_time = time.time()
        details = {
            'timestamp': timezone.now().isoformat(),
            'pid': os.getpid()
        }
        
        try:
            # Simple check - can we allocate memory and respond?
            test_data = list(range(1000))
            details['memory_test'] = len(test_data) == 1000
            
            # Check if we can perform basic operations
            current_time = timezone.now()
            details['time_check'] = True
            
            # Check deadlock detection
            if hasattr(self, '_check_deadlocks'):
                deadlocks = self._check_deadlocks()
                if deadlocks:
                    details['deadlocks'] = deadlocks
                    self._failure_count += 1
                    if self._failure_count >= self.failure_threshold:
                        details['alive'] = False
                        details['reason'] = 'Deadlock detected'
                        return False, details
            
            # Reset failure count on success
            self._failure_count = 0
            
            duration = (time.time() - start_time) * 1000
            details['alive'] = True
            details['duration_ms'] = duration
            
            return True, details
            
        except Exception as e:
            logger.error(f"Liveness probe failed: {e}")
            self._failure_count += 1
            
            details['alive'] = self._failure_count < self.failure_threshold
            details['error'] = str(e)
            details['failure_count'] = self._failure_count
            details['duration_ms'] = (time.time() - start_time) * 1000
            
            return details['alive'], details
    
    def _check_deadlocks(self) -> Optional[Dict[str, Any]]:
        """Check for potential deadlocks (optional advanced check)"""
        # This is a placeholder for advanced deadlock detection
        # In production, you might check:
        # - Thread states
        # - Database locks
        # - Long-running transactions
        return None


# Singleton instances
readiness_probe = ReadinessProbe()
liveness_probe = LivenessProbe()


# Helper functions for views
def check_readiness() -> tuple[bool, Dict[str, Any]]:
    """Check service readiness"""
    return readiness_probe.is_ready()


def check_liveness() -> tuple[bool, Dict[str, Any]]:
    """Check service liveness"""
    return liveness_probe.is_alive()


import os  # Import was missing