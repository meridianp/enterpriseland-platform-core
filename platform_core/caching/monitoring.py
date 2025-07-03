"""
Cache Monitoring

Monitor cache performance, hit rates, and efficiency.
"""

import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, deque
import threading
from django.core.cache import cache, caches
from django.conf import settings
import json

logger = logging.getLogger(__name__)


class CacheMetrics:
    """Track cache performance metrics."""
    
    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self.hits = deque(maxlen=window_size)
        self.misses = deque(maxlen=window_size)
        self.sets = deque(maxlen=window_size)
        self.deletes = deque(maxlen=window_size)
        self.response_times = deque(maxlen=window_size)
        self.key_sizes = defaultdict(deque)
        self.value_sizes = defaultdict(deque)
        self._lock = threading.Lock()
    
    def record_hit(self, key: str, response_time: float) -> None:
        """Record a cache hit."""
        with self._lock:
            self.hits.append({
                'key': key,
                'timestamp': time.time(),
                'response_time': response_time
            })
            self.response_times.append(response_time)
    
    def record_miss(self, key: str, response_time: float) -> None:
        """Record a cache miss."""
        with self._lock:
            self.misses.append({
                'key': key,
                'timestamp': time.time(),
                'response_time': response_time
            })
    
    def record_set(self, key: str, value_size: int, response_time: float) -> None:
        """Record a cache set operation."""
        with self._lock:
            self.sets.append({
                'key': key,
                'timestamp': time.time(),
                'value_size': value_size,
                'response_time': response_time
            })
            self.key_sizes[key].append(value_size)
            if len(self.key_sizes[key]) > 100:
                self.key_sizes[key].popleft()
    
    def record_delete(self, key: str) -> None:
        """Record a cache delete operation."""
        with self._lock:
            self.deletes.append({
                'key': key,
                'timestamp': time.time()
            })
    
    def get_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        with self._lock:
            total_requests = len(self.hits) + len(self.misses)
            if total_requests == 0:
                return 0.0
            return len(self.hits) / total_requests
    
    def get_average_response_time(self) -> float:
        """Calculate average response time."""
        with self._lock:
            if not self.response_times:
                return 0.0
            return sum(self.response_times) / len(self.response_times)
    
    def get_key_statistics(self) -> Dict[str, Any]:
        """Get statistics by key pattern."""
        with self._lock:
            key_stats = defaultdict(lambda: {
                'hits': 0, 'misses': 0, 'sets': 0, 'deletes': 0,
                'avg_size': 0, 'total_size': 0
            })
            
            # Process hits
            for hit in self.hits:
                pattern = self._extract_key_pattern(hit['key'])
                key_stats[pattern]['hits'] += 1
            
            # Process misses
            for miss in self.misses:
                pattern = self._extract_key_pattern(miss['key'])
                key_stats[pattern]['misses'] += 1
            
            # Process sets
            for set_op in self.sets:
                pattern = self._extract_key_pattern(set_op['key'])
                key_stats[pattern]['sets'] += 1
                key_stats[pattern]['total_size'] += set_op['value_size']
            
            # Process deletes
            for delete in self.deletes:
                pattern = self._extract_key_pattern(delete['key'])
                key_stats[pattern]['deletes'] += 1
            
            # Calculate averages
            for pattern, stats in key_stats.items():
                if stats['sets'] > 0:
                    stats['avg_size'] = stats['total_size'] / stats['sets']
                
                total = stats['hits'] + stats['misses']
                if total > 0:
                    stats['hit_rate'] = stats['hits'] / total
                else:
                    stats['hit_rate'] = 0.0
            
            return dict(key_stats)
    
    def _extract_key_pattern(self, key: str) -> str:
        """Extract pattern from cache key."""
        # Simple pattern extraction - can be customized
        parts = key.split(':')
        if len(parts) >= 2:
            return f"{parts[0]}:*"
        return key


class CacheMonitor:
    """Monitor cache performance and health."""
    
    def __init__(self, cache_alias: str = 'default'):
        self.cache_alias = cache_alias
        self.cache = caches[cache_alias]
        self.metrics = CacheMetrics()
        self.monitoring_enabled = True
        self._original_methods = {}
        self._setup_monitoring()
    
    def _setup_monitoring(self):
        """Set up cache method monitoring."""
        # Wrap cache methods to track metrics
        self._wrap_method('get', self._monitored_get)
        self._wrap_method('set', self._monitored_set)
        self._wrap_method('delete', self._monitored_delete)
        self._wrap_method('get_many', self._monitored_get_many)
        self._wrap_method('set_many', self._monitored_set_many)
    
    def _wrap_method(self, method_name: str, wrapper: callable):
        """Wrap a cache method with monitoring."""
        if hasattr(self.cache, method_name):
            self._original_methods[method_name] = getattr(self.cache, method_name)
            setattr(self.cache, method_name, wrapper)
    
    def _monitored_get(self, key: str, default=None, version=None):
        """Monitored cache get."""
        start_time = time.time()
        value = self._original_methods['get'](key, default, version)
        response_time = (time.time() - start_time) * 1000  # ms
        
        if value is not default:
            self.metrics.record_hit(key, response_time)
        else:
            self.metrics.record_miss(key, response_time)
        
        return value
    
    def _monitored_set(self, key: str, value: Any, timeout=None, version=None):
        """Monitored cache set."""
        start_time = time.time()
        
        # Estimate value size
        try:
            value_size = len(json.dumps(value, default=str))
        except:
            value_size = len(str(value))
        
        result = self._original_methods['set'](key, value, timeout, version)
        response_time = (time.time() - start_time) * 1000  # ms
        
        self.metrics.record_set(key, value_size, response_time)
        
        return result
    
    def _monitored_delete(self, key: str, version=None):
        """Monitored cache delete."""
        result = self._original_methods['delete'](key, version)
        if result:
            self.metrics.record_delete(key)
        return result
    
    def _monitored_get_many(self, keys: List[str], version=None):
        """Monitored cache get_many."""
        start_time = time.time()
        result = self._original_methods['get_many'](keys, version)
        response_time = (time.time() - start_time) * 1000  # ms
        
        for key in keys:
            if key in result:
                self.metrics.record_hit(key, response_time / len(keys))
            else:
                self.metrics.record_miss(key, response_time / len(keys))
        
        return result
    
    def _monitored_set_many(self, data: Dict[str, Any], timeout=None, version=None):
        """Monitored cache set_many."""
        start_time = time.time()
        
        for key, value in data.items():
            try:
                value_size = len(json.dumps(value, default=str))
            except:
                value_size = len(str(value))
            
            response_time = (time.time() - start_time) * 1000 / len(data)  # ms per key
            self.metrics.record_set(key, value_size, response_time)
        
        return self._original_methods['set_many'](data, timeout, version)
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Get comprehensive performance report."""
        return {
            'cache_alias': self.cache_alias,
            'timestamp': datetime.now().isoformat(),
            'hit_rate': self.metrics.get_hit_rate(),
            'avg_response_time_ms': self.metrics.get_average_response_time(),
            'key_statistics': self.metrics.get_key_statistics(),
            'recommendations': self._generate_recommendations()
        }
    
    def _generate_recommendations(self) -> List[str]:
        """Generate performance recommendations."""
        recommendations = []
        
        # Check hit rate
        hit_rate = self.metrics.get_hit_rate()
        if hit_rate < 0.7:
            recommendations.append(
                f"Low cache hit rate ({hit_rate:.1%}). "
                "Consider adjusting TTL values or warming cache."
            )
        
        # Check response time
        avg_response = self.metrics.get_average_response_time()
        if avg_response > 10:  # 10ms threshold
            recommendations.append(
                f"High average response time ({avg_response:.1f}ms). "
                "Consider using a faster cache backend or reducing value sizes."
            )
        
        # Check key patterns
        key_stats = self.metrics.get_key_statistics()
        for pattern, stats in key_stats.items():
            if stats['hit_rate'] < 0.5 and stats['sets'] > 10:
                recommendations.append(
                    f"Pattern '{pattern}' has low hit rate ({stats['hit_rate']:.1%}). "
                    "Review caching strategy for these keys."
                )
        
        return recommendations
    
    def get_cache_size_estimate(self) -> Dict[str, Any]:
        """Estimate current cache size and usage."""
        # This is backend-specific; example for Redis
        try:
            if hasattr(self.cache._cache, 'get_client'):
                client = self.cache._cache.get_client()
                info = client.info()
                
                return {
                    'used_memory': info.get('used_memory_human', 'N/A'),
                    'used_memory_bytes': info.get('used_memory', 0),
                    'total_keys': client.dbsize(),
                    'evicted_keys': info.get('evicted_keys', 0),
                    'keyspace_hits': info.get('keyspace_hits', 0),
                    'keyspace_misses': info.get('keyspace_misses', 0)
                }
        except:
            pass
        
        return {'error': 'Cache size estimation not available for this backend'}
    
    def analyze_memory_usage(self) -> Dict[str, Any]:
        """Analyze memory usage patterns."""
        key_stats = self.metrics.get_key_statistics()
        
        # Calculate memory usage by pattern
        memory_by_pattern = {}
        total_memory = 0
        
        for pattern, stats in key_stats.items():
            estimated_memory = stats['total_size']
            memory_by_pattern[pattern] = {
                'bytes': estimated_memory,
                'percentage': 0,  # Will calculate after total
                'avg_size': stats['avg_size'],
                'count': stats['sets']
            }
            total_memory += estimated_memory
        
        # Calculate percentages
        if total_memory > 0:
            for pattern in memory_by_pattern:
                memory_by_pattern[pattern]['percentage'] = (
                    memory_by_pattern[pattern]['bytes'] / total_memory * 100
                )
        
        return {
            'total_tracked_bytes': total_memory,
            'by_pattern': memory_by_pattern,
            'recommendations': self._generate_memory_recommendations(memory_by_pattern)
        }
    
    def _generate_memory_recommendations(self, 
                                       memory_by_pattern: Dict[str, Any]) -> List[str]:
        """Generate memory usage recommendations."""
        recommendations = []
        
        for pattern, usage in memory_by_pattern.items():
            # Large average size
            if usage['avg_size'] > 10000:  # 10KB
                recommendations.append(
                    f"Pattern '{pattern}' has large average size "
                    f"({usage['avg_size'] / 1024:.1f}KB). "
                    "Consider compression or storing references."
                )
            
            # High memory percentage
            if usage['percentage'] > 50:
                recommendations.append(
                    f"Pattern '{pattern}' uses {usage['percentage']:.1f}% of cache. "
                    "Consider separate cache or optimization."
                )
        
        return recommendations
    
    def export_metrics(self, format: str = 'prometheus') -> str:
        """Export metrics in specified format."""
        if format == 'prometheus':
            return self._export_prometheus()
        elif format == 'json':
            return json.dumps(self.get_performance_report(), indent=2)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        
        # Hit rate
        hit_rate = self.metrics.get_hit_rate()
        lines.append(f"# HELP cache_hit_rate Cache hit rate (0-1)")
        lines.append(f"# TYPE cache_hit_rate gauge")
        lines.append(f'cache_hit_rate{{cache="{self.cache_alias}"}} {hit_rate}')
        
        # Response time
        avg_response = self.metrics.get_average_response_time()
        lines.append(f"# HELP cache_response_time_ms Average cache response time")
        lines.append(f"# TYPE cache_response_time_ms gauge")
        lines.append(f'cache_response_time_ms{{cache="{self.cache_alias}"}} {avg_response}')
        
        # Operations count
        lines.append(f"# HELP cache_operations_total Total cache operations")
        lines.append(f"# TYPE cache_operations_total counter")
        lines.append(f'cache_operations_total{{cache="{self.cache_alias}",op="hit"}} {len(self.metrics.hits)}')
        lines.append(f'cache_operations_total{{cache="{self.cache_alias}",op="miss"}} {len(self.metrics.misses)}')
        lines.append(f'cache_operations_total{{cache="{self.cache_alias}",op="set"}} {len(self.metrics.sets)}')
        lines.append(f'cache_operations_total{{cache="{self.cache_alias}",op="delete"}} {len(self.metrics.deletes)}')
        
        return "\n".join(lines)


# Global cache monitor instance
cache_monitor = CacheMonitor()


class CacheHealthChecker:
    """Check cache health and availability."""
    
    def __init__(self, timeout: int = 5):
        self.timeout = timeout
    
    def check_all_caches(self) -> Dict[str, Dict[str, Any]]:
        """Check health of all configured caches."""
        results = {}
        
        for cache_alias in settings.CACHES:
            results[cache_alias] = self.check_cache(cache_alias)
        
        return results
    
    def check_cache(self, cache_alias: str) -> Dict[str, Any]:
        """Check health of specific cache."""
        try:
            cache_instance = caches[cache_alias]
            test_key = f"_health_check_{cache_alias}"
            test_value = f"test_{time.time()}"
            
            # Test set
            start_time = time.time()
            set_result = cache_instance.set(test_key, test_value, self.timeout)
            set_time = (time.time() - start_time) * 1000
            
            # Test get
            start_time = time.time()
            get_result = cache_instance.get(test_key)
            get_time = (time.time() - start_time) * 1000
            
            # Test delete
            start_time = time.time()
            delete_result = cache_instance.delete(test_key)
            delete_time = (time.time() - start_time) * 1000
            
            # Verify operations
            healthy = (
                set_result and 
                get_result == test_value and 
                delete_result
            )
            
            return {
                'healthy': healthy,
                'response_times': {
                    'set_ms': set_time,
                    'get_ms': get_time,
                    'delete_ms': delete_time
                },
                'backend': cache_instance.__class__.__name__
            }
            
        except Exception as e:
            return {
                'healthy': False,
                'error': str(e)
            }