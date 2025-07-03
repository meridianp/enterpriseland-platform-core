"""
Cache Manager

Central cache management and coordination.
"""

import logging
from typing import Dict, Any, List, Optional, Type
from datetime import datetime, timedelta
from django.core.cache import caches
from django.conf import settings
from django.db import models
from django.apps import apps

from .strategies import (
    CacheStrategy, TTLCacheStrategy, LRUCacheStrategy,
    TagBasedCacheStrategy, TieredCacheStrategy, AdaptiveCacheStrategy
)
from .invalidation import (
    TagInvalidator, PatternInvalidator, DependencyInvalidator,
    SmartInvalidator, InvalidationScheduler
)
from .warmup import (
    QueryCacheWarmer, ViewCacheWarmer, APIEndpointCacheWarmer,
    SmartCacheWarmer, WarmingScheduler
)
from .monitoring import CacheMonitor, CacheHealthChecker, cache_monitor

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Central cache management system coordinating all caching operations.
    """
    
    def __init__(self):
        # Initialize strategies
        self.strategies = {
            'ttl': TTLCacheStrategy(),
            'lru': LRUCacheStrategy(),
            'tag': TagBasedCacheStrategy(),
            'tiered': TieredCacheStrategy(),
            'adaptive': AdaptiveCacheStrategy()
        }
        
        # Initialize invalidators
        self.invalidators = {
            'tag': TagInvalidator(),
            'pattern': PatternInvalidator(),
            'dependency': DependencyInvalidator(),
            'smart': SmartInvalidator()
        }
        
        # Initialize warmers
        self.warmers = {
            'query': QueryCacheWarmer(),
            'view': ViewCacheWarmer(),
            'api': APIEndpointCacheWarmer(),
            'smart': SmartCacheWarmer()
        }
        
        # Initialize schedulers
        self.invalidation_scheduler = InvalidationScheduler()
        self.warming_scheduler = WarmingScheduler(self.warmers['smart'])
        
        # Health checker
        self.health_checker = CacheHealthChecker()
        
        # Cache configuration
        self.config = self._load_configuration()
        
        # Setup model invalidation
        self._setup_model_invalidation()
    
    def _load_configuration(self) -> Dict[str, Any]:
        """Load cache configuration from settings."""
        return {
            'default_timeout': getattr(settings, 'CACHE_DEFAULT_TIMEOUT', 300),
            'warming_enabled': getattr(settings, 'CACHE_WARMING_ENABLED', True),
            'warming_interval': getattr(settings, 'CACHE_WARMING_INTERVAL', 300),
            'invalidation_enabled': getattr(settings, 'CACHE_INVALIDATION_ENABLED', True),
            'monitoring_enabled': getattr(settings, 'CACHE_MONITORING_ENABLED', True),
            'strategies': getattr(settings, 'CACHE_STRATEGIES', {}),
            'warming_configs': getattr(settings, 'CACHE_WARMING_CONFIGS', [])
        }
    
    def _setup_model_invalidation(self):
        """Set up automatic model-based cache invalidation."""
        if not self.config['invalidation_enabled']:
            return
        
        # Register invalidation for configured models
        model_configs = self.config.get('strategies', {}).get('models', [])
        
        for config in model_configs:
            try:
                app_label, model_name = config['model'].split('.')
                model_class = apps.get_model(app_label, model_name)
                
                # Register with dependency invalidator
                self.invalidators['dependency'].register_model_signals(model_class)
                
                logger.info(f"Registered cache invalidation for {config['model']}")
                
            except Exception as e:
                logger.error(f"Failed to register invalidation for {config['model']}: {e}")
    
    def get_strategy(self, strategy_name: str = 'ttl') -> CacheStrategy:
        """Get cache strategy by name."""
        return self.strategies.get(strategy_name, self.strategies['ttl'])
    
    def invalidate(self, invalidation_type: str = 'smart', **kwargs) -> Dict[str, Any]:
        """
        Invalidate cache entries.
        
        Args:
            invalidation_type: Type of invalidation (tag, pattern, dependency, smart)
            **kwargs: Arguments for specific invalidator
        
        Returns:
            Invalidation results
        """
        invalidator = self.invalidators.get(invalidation_type)
        
        if not invalidator:
            raise ValueError(f"Unknown invalidation type: {invalidation_type}")
        
        return invalidator.invalidate(**kwargs)
    
    def warm_cache(self, warming_type: str = 'smart', **kwargs) -> Dict[str, Any]:
        """
        Warm cache entries.
        
        Args:
            warming_type: Type of warming (query, view, api, smart)
            **kwargs: Arguments for specific warmer
        
        Returns:
            Warming results
        """
        warmer = self.warmers.get(warming_type)
        
        if not warmer:
            raise ValueError(f"Unknown warming type: {warming_type}")
        
        return warmer.warm(**kwargs)
    
    def schedule_invalidation(self, delay_seconds: int, 
                            invalidation_type: str = 'smart',
                            **kwargs) -> str:
        """Schedule cache invalidation."""
        invalidator = self.invalidators.get(invalidation_type)
        
        if not invalidator:
            raise ValueError(f"Unknown invalidation type: {invalidation_type}")
        
        return self.invalidation_scheduler.schedule_invalidation(
            delay_seconds, invalidator, **kwargs
        )
    
    def start_warming_schedule(self):
        """Start automatic cache warming."""
        if self.config['warming_enabled']:
            # Register warming strategies from config
            for config in self.config['warming_configs']:
                self._register_warming_strategy(config)
            
            # Start scheduler
            self.warming_scheduler.start(self.config['warming_interval'])
            logger.info("Cache warming scheduler started")
    
    def stop_warming_schedule(self):
        """Stop automatic cache warming."""
        self.warming_scheduler.stop()
        logger.info("Cache warming scheduler stopped")
    
    def _register_warming_strategy(self, config: Dict[str, Any]):
        """Register a warming strategy from configuration."""
        try:
            strategy_type = config['type']
            
            if strategy_type == 'model':
                # Query warming for models
                app_label, model_name = config['model'].split('.')
                model = apps.get_model(app_label, model_name)
                
                self.warmers['smart'].register_strategy(
                    name=f"model_{config['model']}",
                    warmer=self.warmers['query'],
                    config={
                        'model': model,
                        'filters': config.get('filters', {}),
                        'select_related': config.get('select_related', []),
                        'prefetch_related': config.get('prefetch_related', []),
                        'interval': config.get('interval', 3600)
                    }
                )
                
            elif strategy_type == 'view':
                # View warming
                self.warmers['smart'].register_strategy(
                    name=f"view_{config['name']}",
                    warmer=self.warmers['view'],
                    config={
                        'view_configs': config['views'],
                        'interval': config.get('interval', 3600)
                    }
                )
                
            elif strategy_type == 'api':
                # API endpoint warming
                self.warmers['smart'].register_strategy(
                    name=f"api_{config['name']}",
                    warmer=self.warmers['api'],
                    config={
                        'endpoint_configs': config['endpoints'],
                        'interval': config.get('interval', 3600)
                    }
                )
                
            logger.info(f"Registered warming strategy: {config.get('name', strategy_type)}")
            
        except Exception as e:
            logger.error(f"Failed to register warming strategy: {e}")
    
    def get_cache_status(self) -> Dict[str, Any]:
        """Get comprehensive cache status."""
        status = {
            'timestamp': datetime.now().isoformat(),
            'health': self.health_checker.check_all_caches(),
            'performance': cache_monitor.get_performance_report(),
            'warming_schedule': self.warmers['smart'].get_warming_schedule(),
            'configuration': {
                'warming_enabled': self.config['warming_enabled'],
                'invalidation_enabled': self.config['invalidation_enabled'],
                'monitoring_enabled': self.config['monitoring_enabled']
            }
        }
        
        # Add cache backend information
        status['backends'] = {}
        for alias in settings.CACHES:
            cache_backend = caches[alias]
            backend_info = {
                'backend': cache_backend.__class__.__name__,
                'location': getattr(cache_backend, '_cache_location', 'N/A')
            }
            
            # Add size estimate if available
            size_info = cache_monitor.get_cache_size_estimate()
            if 'error' not in size_info:
                backend_info.update(size_info)
            
            status['backends'][alias] = backend_info
        
        return status
    
    def optimize_cache_configuration(self) -> Dict[str, Any]:
        """Analyze and optimize cache configuration."""
        recommendations = []
        
        # Get performance metrics
        perf_report = cache_monitor.get_performance_report()
        
        # Check overall hit rate
        hit_rate = perf_report['hit_rate']
        if hit_rate < 0.7:
            recommendations.append({
                'issue': 'Low cache hit rate',
                'current': f"{hit_rate:.1%}",
                'recommendation': 'Increase cache timeout or implement cache warming',
                'priority': 'high'
            })
        
        # Check key pattern performance
        key_stats = perf_report['key_statistics']
        for pattern, stats in key_stats.items():
            if stats['hit_rate'] < 0.5:
                recommendations.append({
                    'issue': f"Low hit rate for pattern '{pattern}'",
                    'current': f"{stats['hit_rate']:.1%}",
                    'recommendation': f"Review caching strategy for {pattern}",
                    'priority': 'medium'
                })
        
        # Check cache health
        health_status = self.health_checker.check_all_caches()
        for alias, health in health_status.items():
            if not health.get('healthy', False):
                recommendations.append({
                    'issue': f"Cache '{alias}' is unhealthy",
                    'error': health.get('error', 'Unknown'),
                    'recommendation': f"Check {alias} cache backend configuration",
                    'priority': 'critical'
                })
        
        # Memory usage analysis
        memory_analysis = cache_monitor.analyze_memory_usage()
        for pattern, usage in memory_analysis['by_pattern'].items():
            if usage['percentage'] > 30:
                recommendations.append({
                    'issue': f"High memory usage for pattern '{pattern}'",
                    'current': f"{usage['percentage']:.1f}% of cache",
                    'recommendation': 'Consider separate cache or data structure optimization',
                    'priority': 'medium'
                })
        
        return {
            'timestamp': datetime.now().isoformat(),
            'current_performance': {
                'hit_rate': hit_rate,
                'avg_response_time': perf_report['avg_response_time_ms']
            },
            'recommendations': sorted(
                recommendations, 
                key=lambda x: {'critical': 0, 'high': 1, 'medium': 2}.get(x.get('priority', 'medium'))
            ),
            'suggested_config': self._generate_optimized_config(recommendations)
        }
    
    def _generate_optimized_config(self, recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate optimized configuration based on recommendations."""
        config = dict(self.config)
        
        # Adjust based on recommendations
        for rec in recommendations:
            if 'Low cache hit rate' in rec.get('issue', ''):
                # Increase default timeout
                config['default_timeout'] = int(config['default_timeout'] * 1.5)
                
                # Enable warming if not already
                config['warming_enabled'] = True
                config['warming_interval'] = 300  # 5 minutes
        
        return config
    
    def clear_all_caches(self) -> Dict[str, bool]:
        """Clear all cache backends."""
        results = {}
        
        for alias in settings.CACHES:
            try:
                cache_backend = caches[alias]
                cache_backend.clear()
                results[alias] = True
                logger.info(f"Cleared cache: {alias}")
            except Exception as e:
                results[alias] = False
                logger.error(f"Failed to clear cache {alias}: {e}")
        
        return results
    
    def export_metrics(self, format: str = 'prometheus') -> str:
        """Export cache metrics in specified format."""
        return cache_monitor.export_metrics(format)


# Create global cache manager instance
cache_manager = CacheManager()