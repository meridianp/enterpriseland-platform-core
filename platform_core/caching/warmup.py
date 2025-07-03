"""
Cache Warmup

Proactive cache warming strategies for optimal performance.
"""

import logging
import time
from typing import List, Dict, Any, Optional, Callable, Type
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from collections import defaultdict
import threading
from django.core.cache import cache
from django.db import models
from django.db.models import QuerySet, Prefetch
from django.urls import reverse
from django.test import RequestFactory
from django.conf import settings

logger = logging.getLogger(__name__)


class CacheWarmer(ABC):
    """Base cache warmer interface."""
    
    @abstractmethod
    def warm(self, **kwargs) -> Dict[str, Any]:
        """Warm cache entries. Returns warming statistics."""
        pass
    
    @abstractmethod
    def get_keys_to_warm(self, **kwargs) -> List[str]:
        """Get list of cache keys to warm."""
        pass


class QueryCacheWarmer(CacheWarmer):
    """Warm cache for database queries."""
    
    def __init__(self, cache_timeout: int = 300):
        self.cache_timeout = cache_timeout
        self.warmed_queries = []
    
    def warm(self, model: Type[models.Model], 
            filters: Optional[Dict[str, Any]] = None,
            select_related: Optional[List[str]] = None,
            prefetch_related: Optional[List[str]] = None) -> Dict[str, Any]:
        """Warm cache for model queries."""
        start_time = time.time()
        warmed_count = 0
        
        # Build queryset
        queryset = model.objects.all()
        
        if filters:
            queryset = queryset.filter(**filters)
        
        if select_related:
            queryset = queryset.select_related(*select_related)
        
        if prefetch_related:
            queryset = queryset.prefetch_related(*prefetch_related)
        
        # Common query patterns
        patterns = [
            ('list', lambda qs: list(qs[:100])),
            ('count', lambda qs: qs.count()),
            ('exists', lambda qs: qs.exists()),
            ('first', lambda qs: qs.first()),
            ('last', lambda qs: qs.last()),
        ]
        
        # Warm each pattern
        for pattern_name, pattern_func in patterns:
            cache_key = self._generate_cache_key(
                model, pattern_name, filters
            )
            
            try:
                result = pattern_func(queryset)
                cache.set(cache_key, result, self.cache_timeout)
                warmed_count += 1
                self.warmed_queries.append(cache_key)
            except Exception as e:
                logger.error(f"Failed to warm {pattern_name} for {model}: {e}")
        
        # Warm individual objects
        for obj in queryset[:20]:  # Limit to prevent memory issues
            cache_key = f"{model._meta.label_lower}:{obj.pk}"
            cache.set(cache_key, obj, self.cache_timeout)
            warmed_count += 1
            self.warmed_queries.append(cache_key)
        
        duration = time.time() - start_time
        
        return {
            'model': model._meta.label,
            'warmed_count': warmed_count,
            'duration': duration,
            'queries_per_second': warmed_count / duration if duration > 0 else 0
        }
    
    def get_keys_to_warm(self, model: Type[models.Model], 
                        filters: Optional[Dict[str, Any]] = None) -> List[str]:
        """Get list of cache keys that would be warmed."""
        keys = []
        
        # Pattern keys
        for pattern_name in ['list', 'count', 'exists', 'first', 'last']:
            keys.append(self._generate_cache_key(model, pattern_name, filters))
        
        # Object keys
        queryset = model.objects.all()
        if filters:
            queryset = queryset.filter(**filters)
        
        for obj in queryset[:20]:
            keys.append(f"{model._meta.label_lower}:{obj.pk}")
        
        return keys
    
    def _generate_cache_key(self, model: Type[models.Model], 
                          pattern: str, 
                          filters: Optional[Dict[str, Any]]) -> str:
        """Generate consistent cache key."""
        key_parts = [model._meta.label_lower, pattern]
        
        if filters:
            # Sort filters for consistent keys
            filter_str = ':'.join(
                f"{k}={v}" for k, v in sorted(filters.items())
            )
            key_parts.append(filter_str)
        
        return ':'.join(key_parts)
    
    def warm_aggregations(self, model: Type[models.Model], 
                         group_by: str,
                         aggregations: Dict[str, models.Aggregate]) -> Dict[str, Any]:
        """Warm cache for aggregation queries."""
        start_time = time.time()
        warmed_count = 0
        
        # Build aggregation query
        queryset = model.objects.values(group_by)
        for name, aggregate in aggregations.items():
            queryset = queryset.annotate(**{name: aggregate})
        
        # Cache results
        results = list(queryset)
        cache_key = f"{model._meta.label_lower}:agg:{group_by}"
        cache.set(cache_key, results, self.cache_timeout)
        warmed_count += 1
        
        return {
            'model': model._meta.label,
            'aggregation': group_by,
            'warmed_count': warmed_count,
            'duration': time.time() - start_time
        }


class ViewCacheWarmer(CacheWarmer):
    """Warm cache for views."""
    
    def __init__(self):
        self.factory = RequestFactory()
        self.warmed_views = []
    
    def warm(self, view_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Warm cache for specified views."""
        start_time = time.time()
        success_count = 0
        error_count = 0
        
        for config in view_configs:
            try:
                # Create request
                url = config.get('url') or reverse(config['view_name'], 
                                                  kwargs=config.get('kwargs', {}))
                method = config.get('method', 'GET')
                
                if method == 'GET':
                    request = self.factory.get(url)
                elif method == 'POST':
                    request = self.factory.post(url, data=config.get('data', {}))
                else:
                    continue
                
                # Add user if specified
                if 'user' in config:
                    request.user = config['user']
                
                # Call view
                view_func = config['view_func']
                response = view_func(request, **config.get('kwargs', {}))
                
                # Cache response if successful
                if response.status_code == 200:
                    cache_key = f"view:{config['view_name']}:{url}"
                    cache.set(cache_key, response.content, 
                            config.get('timeout', 300))
                    success_count += 1
                    self.warmed_views.append(cache_key)
                else:
                    error_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to warm view {config.get('view_name')}: {e}")
                error_count += 1
        
        duration = time.time() - start_time
        
        return {
            'total_views': len(view_configs),
            'success_count': success_count,
            'error_count': error_count,
            'duration': duration,
            'views_per_second': success_count / duration if duration > 0 else 0
        }
    
    def get_keys_to_warm(self, view_configs: List[Dict[str, Any]]) -> List[str]:
        """Get list of cache keys that would be warmed."""
        keys = []
        
        for config in view_configs:
            url = config.get('url') or reverse(config['view_name'], 
                                             kwargs=config.get('kwargs', {}))
            keys.append(f"view:{config['view_name']}:{url}")
        
        return keys


class APIEndpointCacheWarmer(CacheWarmer):
    """Warm cache for API endpoints."""
    
    def __init__(self):
        self.warmed_endpoints = []
    
    def warm(self, endpoint_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Warm cache for API endpoints."""
        start_time = time.time()
        success_count = 0
        error_count = 0
        total_size = 0
        
        for config in endpoint_configs:
            try:
                # Build cache key
                cache_key = self._build_cache_key(config)
                
                # Get data function
                data_func = config['data_func']
                params = config.get('params', {})
                
                # Fetch and cache data
                data = data_func(**params)
                
                # Serialize if needed
                if config.get('serialize'):
                    serializer_class = config['serializer_class']
                    serializer = serializer_class(data, many=config.get('many', False))
                    data = serializer.data
                
                # Cache with appropriate timeout
                timeout = config.get('timeout', 300)
                cache.set(cache_key, data, timeout)
                
                success_count += 1
                total_size += len(str(data))
                self.warmed_endpoints.append(cache_key)
                
            except Exception as e:
                logger.error(f"Failed to warm endpoint {config.get('endpoint')}: {e}")
                error_count += 1
        
        duration = time.time() - start_time
        
        return {
            'total_endpoints': len(endpoint_configs),
            'success_count': success_count,
            'error_count': error_count,
            'total_size_bytes': total_size,
            'duration': duration,
            'endpoints_per_second': success_count / duration if duration > 0 else 0
        }
    
    def get_keys_to_warm(self, endpoint_configs: List[Dict[str, Any]]) -> List[str]:
        """Get list of cache keys that would be warmed."""
        return [self._build_cache_key(config) for config in endpoint_configs]
    
    def _build_cache_key(self, config: Dict[str, Any]) -> str:
        """Build consistent cache key for endpoint."""
        parts = ['api', config['endpoint']]
        
        # Add params to key
        params = config.get('params', {})
        if params:
            param_str = ':'.join(f"{k}={v}" for k, v in sorted(params.items()))
            parts.append(param_str)
        
        return ':'.join(parts)


class SmartCacheWarmer:
    """Intelligent cache warming coordinator."""
    
    def __init__(self):
        self.query_warmer = QueryCacheWarmer()
        self.view_warmer = ViewCacheWarmer()
        self.api_warmer = APIEndpointCacheWarmer()
        self.warming_strategies = []
        self.warming_stats = defaultdict(list)
        self._lock = threading.Lock()
    
    def register_strategy(self, name: str, 
                         warmer: CacheWarmer,
                         config: Dict[str, Any]) -> None:
        """Register a warming strategy."""
        with self._lock:
            self.warming_strategies.append({
                'name': name,
                'warmer': warmer,
                'config': config,
                'last_run': None,
                'next_run': datetime.now()
            })
    
    def warm_all(self) -> Dict[str, Any]:
        """Execute all warming strategies."""
        results = {
            'total_warmed': 0,
            'total_duration': 0,
            'strategies': {}
        }
        
        for strategy in self.warming_strategies:
            if datetime.now() >= strategy['next_run']:
                result = self._execute_strategy(strategy)
                results['strategies'][strategy['name']] = result
                results['total_warmed'] += result.get('warmed_count', 0)
                results['total_duration'] += result.get('duration', 0)
        
        return results
    
    def _execute_strategy(self, strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single warming strategy."""
        start_time = time.time()
        
        try:
            # Run warmer
            result = strategy['warmer'].warm(**strategy['config'])
            
            # Update strategy metadata
            with self._lock:
                strategy['last_run'] = datetime.now()
                strategy['next_run'] = datetime.now() + timedelta(
                    seconds=strategy['config'].get('interval', 3600)
                )
                
                # Track stats
                self.warming_stats[strategy['name']].append({
                    'timestamp': datetime.now(),
                    'result': result
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Warming strategy {strategy['name']} failed: {e}")
            return {
                'error': str(e),
                'duration': time.time() - start_time
            }
    
    def get_warming_schedule(self) -> List[Dict[str, Any]]:
        """Get warming schedule for all strategies."""
        schedule = []
        
        with self._lock:
            for strategy in self.warming_strategies:
                schedule.append({
                    'name': strategy['name'],
                    'last_run': strategy['last_run'],
                    'next_run': strategy['next_run'],
                    'interval': strategy['config'].get('interval', 3600)
                })
        
        return sorted(schedule, key=lambda x: x['next_run'])
    
    def warm_critical_paths(self) -> Dict[str, Any]:
        """Warm cache for critical application paths."""
        critical_configs = [
            # Dashboard data
            {
                'name': 'dashboard_stats',
                'model': 'assessments.Assessment',
                'filters': {'status': 'active'},
                'timeout': 600
            },
            # User profiles
            {
                'name': 'user_profiles',
                'model': 'auth.User',
                'filters': {'is_active': True},
                'select_related': ['profile'],
                'timeout': 1800
            },
            # Recent activity
            {
                'name': 'recent_activity',
                'model': 'core.AuditLog',
                'filters': {
                    'created_at__gte': datetime.now() - timedelta(days=1)
                },
                'timeout': 300
            }
        ]
        
        results = {}
        
        for config in critical_configs:
            model_path = config.pop('model')
            app_label, model_name = model_path.split('.')
            
            from django.apps import apps
            model = apps.get_model(app_label, model_name)
            
            name = config.pop('name')
            results[name] = self.query_warmer.warm(model, **config)
        
        return results


class WarmingScheduler:
    """Schedule cache warming tasks."""
    
    def __init__(self, warmer: SmartCacheWarmer):
        self.warmer = warmer
        self._timer = None
        self._running = False
    
    def start(self, interval: int = 300):
        """Start scheduled warming."""
        self._running = True
        self._schedule_next_run(interval)
    
    def stop(self):
        """Stop scheduled warming."""
        self._running = False
        if self._timer:
            self._timer.cancel()
    
    def _schedule_next_run(self, interval: int):
        """Schedule next warming run."""
        if not self._running:
            return
        
        def run_warming():
            try:
                # Run warming
                results = self.warmer.warm_all()
                logger.info(f"Cache warming completed: {results['total_warmed']} entries")
                
                # Also warm critical paths
                critical_results = self.warmer.warm_critical_paths()
                logger.info(f"Critical path warming completed: {len(critical_results)} paths")
                
            except Exception as e:
                logger.error(f"Scheduled warming failed: {e}")
            
            finally:
                # Schedule next run
                if self._running:
                    self._schedule_next_run(interval)
        
        self._timer = threading.Timer(interval, run_warming)
        self._timer.daemon = True
        self._timer.start()