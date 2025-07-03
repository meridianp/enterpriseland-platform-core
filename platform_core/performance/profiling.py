"""
Performance Profiling Tools

Comprehensive profiling for views, methods, and database queries.
"""

import time
import cProfile
import pstats
import io
import functools
import logging
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin
import json

logger = logging.getLogger(__name__)


class PerformanceProfiler:
    """
    Central performance profiler for tracking metrics.
    """
    
    def __init__(self):
        self.profiles = {}
        self.query_log = []
        self.cache_hits = 0
        self.cache_misses = 0
        self.slow_query_threshold = getattr(settings, 'SLOW_QUERY_THRESHOLD', 100)  # ms
        
    def start_profile(self, profile_id: str) -> None:
        """Start profiling for a specific ID."""
        self.profiles[profile_id] = {
            'start_time': time.time(),
            'queries': [],
            'cache_operations': [],
            'memory_start': self._get_memory_usage()
        }
    
    def end_profile(self, profile_id: str) -> Dict[str, Any]:
        """End profiling and return metrics."""
        if profile_id not in self.profiles:
            return {}
        
        profile = self.profiles[profile_id]
        end_time = time.time()
        
        metrics = {
            'profile_id': profile_id,
            'duration': (end_time - profile['start_time']) * 1000,  # ms
            'queries': profile['queries'],
            'query_count': len(profile['queries']),
            'total_query_time': sum(q['duration'] for q in profile['queries']),
            'cache_operations': profile['cache_operations'],
            'cache_hit_rate': self._calculate_cache_hit_rate(profile),
            'memory_used': self._get_memory_usage() - profile['memory_start'],
            'timestamp': datetime.now().isoformat()
        }
        
        # Log slow operations
        if metrics['duration'] > 1000:  # > 1 second
            logger.warning(f"Slow operation detected: {profile_id} took {metrics['duration']:.2f}ms")
        
        # Store in cache for analysis
        self._store_profile(profile_id, metrics)
        
        # Clean up
        del self.profiles[profile_id]
        
        return metrics
    
    def log_query(self, profile_id: str, query: str, duration: float) -> None:
        """Log a database query."""
        if profile_id not in self.profiles:
            return
        
        query_info = {
            'sql': query,
            'duration': duration,
            'slow': duration > self.slow_query_threshold
        }
        
        self.profiles[profile_id]['queries'].append(query_info)
        
        if query_info['slow']:
            logger.warning(f"Slow query ({duration:.2f}ms): {query[:100]}...")
    
    def log_cache_operation(self, profile_id: str, operation: str, 
                          key: str, hit: bool) -> None:
        """Log a cache operation."""
        if profile_id not in self.profiles:
            return
        
        self.profiles[profile_id]['cache_operations'].append({
            'operation': operation,
            'key': key,
            'hit': hit,
            'timestamp': time.time()
        })
        
        if hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
    
    def _get_memory_usage(self) -> int:
        """Get current memory usage in bytes."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss
        except ImportError:
            return 0
    
    def _calculate_cache_hit_rate(self, profile: Dict[str, Any]) -> float:
        """Calculate cache hit rate for profile."""
        operations = profile['cache_operations']
        if not operations:
            return 0.0
        
        hits = sum(1 for op in operations if op['hit'])
        return (hits / len(operations)) * 100
    
    def _store_profile(self, profile_id: str, metrics: Dict[str, Any]) -> None:
        """Store profile metrics for analysis."""
        # Store recent profiles
        cache_key = f'performance:profiles:{datetime.now().strftime("%Y%m%d")}'
        profiles = cache.get(cache_key, [])
        profiles.append(metrics)
        
        # Keep only last 1000 profiles
        if len(profiles) > 1000:
            profiles = profiles[-1000:]
        
        cache.set(cache_key, profiles, timeout=86400)  # 24 hours
        
        # Update aggregate metrics
        self._update_aggregate_metrics(metrics)
    
    def _update_aggregate_metrics(self, metrics: Dict[str, Any]) -> None:
        """Update aggregate performance metrics."""
        hour_key = f'performance:hourly:{datetime.now().strftime("%Y%m%d%H")}'
        
        aggregates = cache.get(hour_key, {
            'count': 0,
            'total_duration': 0,
            'total_queries': 0,
            'slow_queries': 0,
            'cache_hits': 0,
            'cache_misses': 0
        })
        
        aggregates['count'] += 1
        aggregates['total_duration'] += metrics['duration']
        aggregates['total_queries'] += metrics['query_count']
        aggregates['slow_queries'] += sum(
            1 for q in metrics['queries'] if q['slow']
        )
        
        cache.set(hour_key, aggregates, timeout=7200)  # 2 hours


# Global profiler instance
profiler = PerformanceProfiler()


class ProfilerMiddleware(MiddlewareMixin):
    """
    Django middleware for automatic request profiling.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        super().__init__(get_response)
        self.excluded_paths = getattr(
            settings, 
            'PROFILER_EXCLUDED_PATHS', 
            ['/static/', '/media/', '/health/']
        )
    
    def process_request(self, request: HttpRequest) -> None:
        """Start profiling for request."""
        # Skip excluded paths
        if any(request.path.startswith(path) for path in self.excluded_paths):
            return
        
        # Skip if profiling disabled
        if not getattr(settings, 'ENABLE_PROFILING', True):
            return
        
        profile_id = f"{request.method}:{request.path}:{id(request)}"
        request._profile_id = profile_id
        
        profiler.start_profile(profile_id)
        
        # Track initial query count
        request._queries_start = len(connection.queries)
    
    def process_response(self, request: HttpRequest, 
                        response: HttpResponse) -> HttpResponse:
        """End profiling and add metrics to response."""
        if not hasattr(request, '_profile_id'):
            return response
        
        profile_id = request._profile_id
        
        # Log database queries
        if hasattr(request, '_queries_start'):
            queries = connection.queries[request._queries_start:]
            for query in queries:
                profiler.log_query(
                    profile_id,
                    query['sql'],
                    float(query['time']) * 1000  # Convert to ms
                )
        
        # Get profile metrics
        metrics = profiler.end_profile(profile_id)
        
        # Add metrics to response headers in development
        if settings.DEBUG:
            response['X-Response-Time'] = f"{metrics.get('duration', 0):.2f}ms"
            response['X-Query-Count'] = str(metrics.get('query_count', 0))
            response['X-Query-Time'] = f"{metrics.get('total_query_time', 0):.2f}ms"
        
        # Log slow requests
        duration = metrics.get('duration', 0)
        if duration > 1000:  # > 1 second
            logger.warning(
                f"Slow request: {request.method} {request.path} "
                f"took {duration:.2f}ms with {metrics.get('query_count', 0)} queries"
            )
        
        return response


def profile_view(func: Callable) -> Callable:
    """
    Decorator for profiling Django views.
    
    Usage:
        @profile_view
        def my_view(request):
            # View logic
    """
    @functools.wraps(func)
    def wrapper(request, *args, **kwargs):
        profile_id = f"view:{func.__name__}:{id(request)}"
        
        # Use cProfile for detailed profiling
        pr = cProfile.Profile()
        pr.enable()
        
        profiler.start_profile(profile_id)
        
        try:
            result = func(request, *args, **kwargs)
            return result
        finally:
            pr.disable()
            
            # Get profile metrics
            metrics = profiler.end_profile(profile_id)
            
            # Store cProfile stats if in debug mode
            if settings.DEBUG:
                s = io.StringIO()
                ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
                ps.print_stats(20)  # Top 20 functions
                
                cache.set(
                    f"profile:detailed:{profile_id}",
                    {
                        'metrics': metrics,
                        'stats': s.getvalue()
                    },
                    timeout=3600
                )
                
                logger.debug(f"View {func.__name__} profile:\n{s.getvalue()}")
    
    return wrapper


def profile_method(name: Optional[str] = None) -> Callable:
    """
    Decorator for profiling class methods.
    
    Usage:
        class MyService:
            @profile_method("process_data")
            def process(self):
                # Method logic
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            method_name = name or f"{self.__class__.__name__}.{func.__name__}"
            profile_id = f"method:{method_name}:{id(self)}"
            
            profiler.start_profile(profile_id)
            
            try:
                result = func(self, *args, **kwargs)
                return result
            finally:
                metrics = profiler.end_profile(profile_id)
                
                # Log if slow
                if metrics.get('duration', 0) > 500:  # > 500ms
                    logger.warning(
                        f"Slow method: {method_name} took "
                        f"{metrics['duration']:.2f}ms"
                    )
        
        return wrapper
    return decorator


class QueryAnalyzer:
    """
    Analyze database queries for optimization opportunities.
    """
    
    def __init__(self):
        self.analysis_cache = {}
    
    def analyze_queries(self, queries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze a list of queries for patterns and issues."""
        analysis = {
            'total_queries': len(queries),
            'total_time': sum(q['duration'] for q in queries),
            'slow_queries': [q for q in queries if q.get('slow', False)],
            'duplicate_queries': self._find_duplicates(queries),
            'n_plus_one': self._detect_n_plus_one(queries),
            'missing_indexes': self._suggest_indexes(queries),
            'recommendations': []
        }
        
        # Generate recommendations
        if analysis['duplicate_queries']:
            analysis['recommendations'].append(
                f"Found {len(analysis['duplicate_queries'])} duplicate queries. "
                "Consider using select_related() or prefetch_related()."
            )
        
        if analysis['n_plus_one']:
            analysis['recommendations'].append(
                "N+1 query pattern detected. Use select_related() for "
                "foreign keys or prefetch_related() for reverse foreign keys."
            )
        
        if analysis['slow_queries']:
            analysis['recommendations'].append(
                f"Found {len(analysis['slow_queries'])} slow queries. "
                "Consider adding indexes or optimizing query structure."
            )
        
        return analysis
    
    def _find_duplicates(self, queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find duplicate queries."""
        query_counts = {}
        
        for query in queries:
            sql = query['sql']
            # Normalize query for comparison
            normalized = self._normalize_query(sql)
            
            if normalized not in query_counts:
                query_counts[normalized] = {
                    'sql': sql,
                    'count': 0,
                    'total_time': 0
                }
            
            query_counts[normalized]['count'] += 1
            query_counts[normalized]['total_time'] += query['duration']
        
        # Return queries executed more than once
        return [
            info for info in query_counts.values()
            if info['count'] > 1
        ]
    
    def _detect_n_plus_one(self, queries: List[Dict[str, Any]]) -> bool:
        """Detect N+1 query patterns."""
        # Look for patterns like:
        # SELECT * FROM table WHERE id = 1
        # SELECT * FROM table WHERE id = 2
        # SELECT * FROM table WHERE id = 3
        
        similar_queries = {}
        
        for query in queries:
            sql = query['sql']
            # Extract table and remove specific values
            pattern = self._extract_query_pattern(sql)
            
            if pattern not in similar_queries:
                similar_queries[pattern] = 0
            similar_queries[pattern] += 1
        
        # If we see the same pattern more than 3 times, likely N+1
        return any(count > 3 for count in similar_queries.values())
    
    def _suggest_indexes(self, queries: List[Dict[str, Any]]) -> List[str]:
        """Suggest potential indexes based on slow queries."""
        suggestions = []
        
        for query in queries:
            if not query.get('slow'):
                continue
            
            sql = query['sql'].lower()
            
            # Look for WHERE clauses without indexes
            if 'where' in sql and 'index' not in sql:
                # Extract column names from WHERE clause
                # This is a simplified analysis
                where_start = sql.find('where')
                where_clause = sql[where_start:where_start + 100]
                
                # Look for common patterns
                if '=' in where_clause or 'in' in where_clause:
                    suggestions.append(
                        f"Consider adding index on columns used in: {where_clause[:50]}..."
                    )
        
        return suggestions
    
    def _normalize_query(self, sql: str) -> str:
        """Normalize SQL query for comparison."""
        # Remove specific values to find similar queries
        import re
        
        # Replace numbers
        sql = re.sub(r'\b\d+\b', '?', sql)
        # Replace quoted strings
        sql = re.sub(r"'[^']*'", '?', sql)
        sql = re.sub(r'"[^"]*"', '?', sql)
        
        return sql.strip().lower()
    
    def _extract_query_pattern(self, sql: str) -> str:
        """Extract query pattern for N+1 detection."""
        # Simplified pattern extraction
        sql_lower = sql.lower()
        
        # Extract table name
        from_idx = sql_lower.find('from')
        where_idx = sql_lower.find('where')
        
        if from_idx > -1 and where_idx > -1:
            table_part = sql_lower[from_idx:where_idx].strip()
            # Remove specific IDs and values
            pattern = self._normalize_query(table_part)
            return pattern
        
        return sql_lower[:50]  # Fallback


# Create global query analyzer
query_analyzer = QueryAnalyzer()