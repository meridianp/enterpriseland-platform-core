"""
Comprehensive Caching Tests

Tests for all caching strategies, invalidation, warmup, and monitoring.
"""

import pytest
import time
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from django.test import TestCase, RequestFactory, override_settings
from django.core.cache import cache, caches
from django.http import HttpResponse
from django.contrib.auth import get_user_model
from django.db import models
from django.core.management import call_command
from io import StringIO

from platform_core.caching import (
    # Strategies
    TTLCacheStrategy, LRUCacheStrategy, TagBasedCacheStrategy,
    TieredCacheStrategy, AdaptiveCacheStrategy,
    
    # Invalidation
    TagInvalidator, PatternInvalidator, DependencyInvalidator,
    SmartInvalidator,
    
    # Warmup
    QueryCacheWarmer, ViewCacheWarmer, APIEndpointCacheWarmer,
    SmartCacheWarmer,
    
    # Monitoring
    CacheMonitor, CacheMetrics, cache_monitor,
    
    # Decorators
    cached_view, cached_method, cached_api, smart_cache,
    
    # Manager
    CacheManager, cache_manager
)

User = get_user_model()


class TestModel(models.Model):
    """Test model for caching tests."""
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default='active')
    created_date = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        app_label = 'test'


class TestCacheStrategies(TestCase):
    """Test various caching strategies."""
    
    def setUp(self):
        cache.clear()
    
    def test_ttl_cache_strategy(self):
        """Test TTL-based caching strategy."""
        strategy = TTLCacheStrategy(default_timeout=2)
        
        # Test set and get
        strategy.set('test_key', 'test_value', timeout=1)
        self.assertEqual(strategy.get('test_key'), 'test_value')
        
        # Test expiration
        time.sleep(1.1)
        self.assertIsNone(strategy.get('test_key'))
        
        # Test touch
        strategy.set('touch_key', 'value', timeout=1)
        time.sleep(0.5)
        strategy.touch('touch_key', timeout=2)
        time.sleep(1)
        self.assertEqual(strategy.get('touch_key'), 'value')  # Should still exist
    
    def test_lru_cache_strategy(self):
        """Test LRU caching strategy."""
        strategy = LRUCacheStrategy(max_entries=3)
        
        # Fill cache
        strategy.set('key1', 'value1')
        strategy.set('key2', 'value2')
        strategy.set('key3', 'value3')
        
        # Access key1 to make it recently used
        strategy.get('key1')
        
        # Add new key - should evict key2 (least recently used)
        strategy.set('key4', 'value4')
        
        self.assertEqual(strategy.get('key1'), 'value1')
        self.assertIsNone(strategy.get('key2'))  # Evicted
        self.assertEqual(strategy.get('key3'), 'value3')
        self.assertEqual(strategy.get('key4'), 'value4')
    
    def test_tag_based_cache_strategy(self):
        """Test tag-based caching strategy."""
        strategy = TagBasedCacheStrategy()
        
        # Set values with tags
        strategy.set('user:1', {'name': 'John'}, tags=['user', 'profile'])
        strategy.set('user:2', {'name': 'Jane'}, tags=['user', 'profile'])
        strategy.set('post:1', {'title': 'Test'}, tags=['post', 'content'])
        
        # Get values
        self.assertEqual(strategy.get('user:1')['name'], 'John')
        
        # Delete by tag
        deleted = strategy.delete_by_tag('user')
        self.assertEqual(deleted, 2)
        
        # Verify deletion
        self.assertIsNone(strategy.get('user:1'))
        self.assertIsNone(strategy.get('user:2'))
        self.assertEqual(strategy.get('post:1')['title'], 'Test')  # Not deleted
    
    def test_tiered_cache_strategy(self):
        """Test multi-tier caching strategy."""
        strategy = TieredCacheStrategy()
        
        # Set value
        strategy.set('tiered_key', 'tiered_value', timeout=300)
        
        # Should retrieve from L1 (hot)
        value = strategy.get('tiered_key')
        self.assertEqual(value, 'tiered_value')
        
        # Test tier promotion
        # Clear L1 to simulate miss
        strategy.tier_caches[0]['cache'].delete('tiered_key')
        
        # Should retrieve from L2 and promote to L1
        value = strategy.get('tiered_key')
        self.assertEqual(value, 'tiered_value')
        
        # Should now be in L1
        l1_value = strategy.tier_caches[0]['cache'].get('tiered_key')
        self.assertEqual(l1_value, 'tiered_value')
    
    def test_adaptive_cache_strategy(self):
        """Test adaptive caching strategy."""
        strategy = AdaptiveCacheStrategy(base_timeout=60, min_timeout=30, max_timeout=300)
        
        # Initial set
        strategy.set('adaptive_key', 'value1')
        
        # Simulate frequent access
        for _ in range(15):
            strategy.get('adaptive_key')
            time.sleep(0.1)  # Small delay to simulate time passing
        
        # Get stats
        stats = strategy.get_stats('adaptive_key')
        self.assertGreater(stats['count'], 10)
        self.assertGreater(stats['frequency'], 0)
        
        # Set again - should use longer timeout due to high frequency
        strategy.set('adaptive_key', 'value2')
        
        # Verify adaptive timeout calculation
        timeout = strategy._calculate_timeout('adaptive_key')
        self.assertGreater(timeout, strategy.base_timeout)


class TestCacheInvalidation(TestCase):
    """Test cache invalidation mechanisms."""
    
    def setUp(self):
        cache.clear()
    
    def test_tag_invalidator(self):
        """Test tag-based invalidation."""
        invalidator = TagInvalidator()
        
        # Set up cache entries with tags
        cache.set('item:1', 'value1')
        cache.set('item:2', 'value2')
        cache.set('item:3', 'value3')
        
        # Register dependencies
        invalidator.register_dependency('item:1', ['product', 'electronics'])
        invalidator.register_dependency('item:2', ['product', 'clothing'])
        invalidator.register_dependency('item:3', ['service'])
        
        # Invalidate by tag
        count = invalidator.invalidate(['product'])
        self.assertEqual(count, 2)
        
        # Verify invalidation
        self.assertIsNone(cache.get('item:1'))
        self.assertIsNone(cache.get('item:2'))
        self.assertEqual(cache.get('item:3'), 'value3')  # Not invalidated
    
    def test_pattern_invalidator(self):
        """Test pattern-based invalidation."""
        invalidator = PatternInvalidator()
        
        # Set up cache entries
        cache.set('user:1:profile', 'profile1')
        cache.set('user:1:settings', 'settings1')
        cache.set('user:2:profile', 'profile2')
        cache.set('post:1:content', 'content1')
        
        # Register keys
        for key in ['user:1:profile', 'user:1:settings', 'user:2:profile', 'post:1:content']:
            invalidator.register_dependency(key)
        
        # Invalidate by pattern
        count = invalidator.invalidate('^user:1:.*')
        self.assertEqual(count, 2)
        
        # Verify invalidation
        self.assertIsNone(cache.get('user:1:profile'))
        self.assertIsNone(cache.get('user:1:settings'))
        self.assertEqual(cache.get('user:2:profile'), 'profile2')
        self.assertEqual(cache.get('post:1:content'), 'content1')
    
    def test_dependency_invalidator(self):
        """Test model dependency invalidation."""
        invalidator = DependencyInvalidator()
        
        # Set up cache entries
        cache.set('model:user:1', 'user1_data')
        cache.set('model:user:2', 'user2_data')
        cache.set('model:user:all', 'all_users')
        
        # Register dependencies
        invalidator.register_dependency('model:user:1', 'auth.User', 1)
        invalidator.register_dependency('model:user:2', 'auth.User', 2)
        invalidator.register_dependency('model:user:all', 'auth.User')
        
        # Invalidate specific instance
        count = invalidator.invalidate('auth.User', 1)
        self.assertEqual(count, 1)
        self.assertIsNone(cache.get('model:user:1'))
        self.assertEqual(cache.get('model:user:2'), 'user2_data')
        
        # Invalidate all model instances
        count = invalidator.invalidate('auth.User')
        self.assertIsNone(cache.get('model:user:all'))
    
    def test_smart_invalidator(self):
        """Test smart invalidation with multiple strategies."""
        invalidator = SmartInvalidator()
        
        # Set up various cache entries
        cache.set('tagged:1', 'value1')
        cache.set('pattern:test:1', 'value2')
        cache.set('model:1', 'value3')
        
        # Register with different invalidators
        invalidator.tag_invalidator.register_dependency('tagged:1', ['tag1'])
        invalidator.pattern_invalidator.register_dependency('pattern:test:1')
        invalidator.dependency_invalidator.register_dependency('model:1', 'test.Model', 1)
        
        # Invalidate with context
        results = invalidator.invalidate_smart({
            'tags': ['tag1'],
            'pattern': '^pattern:.*',
            'model': 'test.Model',
            'instance_id': 1
        })
        
        self.assertGreater(results['total'], 0)
        self.assertIn('tags', results['by_strategy'])
        self.assertIn('pattern', results['by_strategy'])
        self.assertIn('dependency', results['by_strategy'])


class TestCacheWarmup(TestCase):
    """Test cache warming functionality."""
    
    def setUp(self):
        cache.clear()
        # Create test data
        self.users = [
            User.objects.create_user(f'user{i}', f'user{i}@example.com')
            for i in range(5)
        ]
    
    def test_query_cache_warmer(self):
        """Test query cache warming."""
        warmer = QueryCacheWarmer(cache_timeout=60)
        
        # Warm cache for User model
        results = warmer.warm(
            User,
            filters={'is_active': True},
            select_related=[],
            prefetch_related=[]
        )
        
        self.assertIn('warmed_count', results)
        self.assertGreater(results['warmed_count'], 0)
        
        # Verify cache entries
        keys = warmer.get_keys_to_warm(User, {'is_active': True})
        for key in keys[:5]:  # Check first few keys
            self.assertIsNotNone(cache.get(key))
    
    def test_view_cache_warmer(self):
        """Test view cache warming."""
        warmer = ViewCacheWarmer()
        
        # Mock view function
        def test_view(request):
            return HttpResponse('Test response')
        
        # Warm cache
        view_configs = [{
            'view_name': 'test_view',
            'view_func': test_view,
            'url': '/test/',
            'method': 'GET'
        }]
        
        results = warmer.warm(view_configs)
        
        self.assertEqual(results['success_count'], 1)
        self.assertEqual(results['error_count'], 0)
    
    def test_api_endpoint_cache_warmer(self):
        """Test API endpoint cache warming."""
        warmer = APIEndpointCacheWarmer()
        
        # Mock data function
        def get_user_data(**kwargs):
            return {'users': [{'id': 1, 'name': 'Test'}]}
        
        # Warm cache
        endpoint_configs = [{
            'endpoint': 'users',
            'data_func': get_user_data,
            'params': {'active': True},
            'timeout': 300
        }]
        
        results = warmer.warm(endpoint_configs)
        
        self.assertEqual(results['success_count'], 1)
        self.assertGreater(results['total_size_bytes'], 0)
        
        # Verify cache
        cache_key = warmer._build_cache_key(endpoint_configs[0])
        self.assertIsNotNone(cache.get(cache_key))
    
    def test_smart_cache_warmer(self):
        """Test smart cache warming coordinator."""
        warmer = SmartCacheWarmer()
        
        # Register warming strategy
        warmer.register_strategy(
            'test_strategy',
            QueryCacheWarmer(),
            {
                'model': User,
                'filters': {'is_active': True},
                'interval': 3600
            }
        )
        
        # Run warming
        results = warmer.warm_all()
        
        self.assertIn('test_strategy', results['strategies'])
        self.assertGreater(results['total_warmed'], 0)
        
        # Check schedule
        schedule = warmer.get_warming_schedule()
        self.assertEqual(len(schedule), 1)
        self.assertEqual(schedule[0]['name'], 'test_strategy')


class TestCacheMonitoring(TestCase):
    """Test cache monitoring functionality."""
    
    def setUp(self):
        cache.clear()
        self.monitor = CacheMonitor()
    
    def test_cache_metrics(self):
        """Test cache metrics collection."""
        metrics = CacheMetrics()
        
        # Record operations
        metrics.record_hit('test:key', 5.0)
        metrics.record_miss('test:key2', 10.0)
        metrics.record_set('test:key', 1024, 3.0)
        metrics.record_delete('test:key')
        
        # Check hit rate
        hit_rate = metrics.get_hit_rate()
        self.assertEqual(hit_rate, 0.5)  # 1 hit, 1 miss
        
        # Check response time
        avg_response = metrics.get_average_response_time()
        self.assertGreater(avg_response, 0)
        
        # Check key statistics
        key_stats = metrics.get_key_statistics()
        self.assertIn('test:*', key_stats)
    
    def test_cache_monitor_wrapping(self):
        """Test cache method monitoring."""
        # Perform cache operations
        cache.set('monitor_test', 'value')
        value = cache.get('monitor_test')
        cache.delete('monitor_test')
        
        # Get performance report
        report = self.monitor.get_performance_report()
        
        self.assertIn('hit_rate', report)
        self.assertIn('avg_response_time_ms', report)
        self.assertIn('key_statistics', report)
    
    def test_memory_usage_analysis(self):
        """Test memory usage analysis."""
        # Add some cache entries
        for i in range(10):
            cache.set(f'large:key{i}', 'x' * 1000)  # 1KB values
            cache.set(f'small:key{i}', 'x' * 10)    # 10B values
        
        # Analyze memory
        analysis = self.monitor.analyze_memory_usage()
        
        self.assertIn('total_tracked_bytes', analysis)
        self.assertIn('by_pattern', analysis)
        self.assertGreater(len(analysis['recommendations']), 0)


class TestCacheDecorators(TestCase):
    """Test cache decorators."""
    
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
    
    def test_cached_view_decorator(self):
        """Test cached view decorator."""
        call_count = 0
        
        @cached_view(timeout=60, key_prefix='test', tags=['view'])
        def test_view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(f'Response {call_count}')
        
        # First call - miss
        request = self.factory.get('/test/')
        request.user = Mock(is_authenticated=False)
        response1 = test_view(request)
        self.assertEqual(response1['X-Cache'], 'MISS')
        self.assertEqual(call_count, 1)
        
        # Second call - hit
        response2 = test_view(request)
        self.assertEqual(response2['X-Cache'], 'HIT')
        self.assertEqual(call_count, 1)  # Not incremented
    
    def test_cached_method_decorator(self):
        """Test cached method decorator."""
        class TestService:
            call_count = 0
            
            @cached_method(timeout=60)
            def get_data(self, param):
                self.call_count += 1
                return f'data_{param}_{self.call_count}'
        
        service = TestService()
        
        # First call - miss
        result1 = service.get_data('test')
        self.assertEqual(result1, 'data_test_1')
        
        # Second call - hit
        result2 = service.get_data('test')
        self.assertEqual(result2, 'data_test_1')  # Same result
        self.assertEqual(service.call_count, 1)  # Not incremented
        
        # Different param - miss
        result3 = service.get_data('other')
        self.assertEqual(result3, 'data_other_2')
        self.assertEqual(service.call_count, 2)
    
    def test_smart_cache_decorator(self):
        """Test smart cache decorator with adaptive timeout."""
        call_count = 0
        
        @smart_cache(base_timeout=60, min_timeout=30, max_timeout=300)
        def expensive_function(param):
            nonlocal call_count
            call_count += 1
            return f'result_{param}_{call_count}'
        
        # Multiple calls to build access pattern
        for i in range(5):
            result = expensive_function('test')
            self.assertEqual(result, 'result_test_1')
        
        self.assertEqual(call_count, 1)  # Only called once


class TestCacheManager(TestCase):
    """Test cache manager functionality."""
    
    def setUp(self):
        cache.clear()
        self.manager = CacheManager()
    
    def test_cache_status(self):
        """Test getting cache status."""
        status = self.manager.get_cache_status()
        
        self.assertIn('timestamp', status)
        self.assertIn('health', status)
        self.assertIn('performance', status)
        self.assertIn('configuration', status)
        self.assertIn('backends', status)
    
    def test_optimization_recommendations(self):
        """Test cache optimization analysis."""
        # Simulate poor performance
        with patch.object(cache_monitor, 'get_performance_report') as mock_report:
            mock_report.return_value = {
                'hit_rate': 0.4,  # Low hit rate
                'avg_response_time_ms': 15.0,  # High response time
                'key_statistics': {
                    'pattern1': {'hit_rate': 0.3, 'sets': 20}
                }
            }
            
            analysis = self.manager.optimize_cache_configuration()
            
            self.assertGreater(len(analysis['recommendations']), 0)
            self.assertIn('suggested_config', analysis)
    
    def test_clear_all_caches(self):
        """Test clearing all cache backends."""
        # Add test data
        cache.set('test_key', 'test_value')
        
        # Clear all
        results = self.manager.clear_all_caches()
        
        self.assertTrue(results.get('default', False))
        self.assertIsNone(cache.get('test_key'))


class TestManagementCommand(TestCase):
    """Test cache management command."""
    
    def test_warm_command(self):
        """Test cache warm command."""
        out = StringIO()
        
        # Create test users
        User.objects.create_user('test', 'test@example.com')
        
        # Run warm command
        call_command('manage_cache', 'warm', '--model=auth.User', stdout=out)
        output = out.getvalue()
        
        self.assertIn('Warmed', output)
        self.assertIn('entries', output)
    
    def test_status_command(self):
        """Test cache status command."""
        out = StringIO()
        
        call_command('manage_cache', 'status', stdout=out)
        output = out.getvalue()
        
        self.assertIn('CACHE STATUS', output)
        self.assertIn('Cache Health:', output)
        self.assertIn('Performance Metrics:', output)
    
    def test_optimize_command(self):
        """Test cache optimize command."""
        out = StringIO()
        
        call_command('manage_cache', 'optimize', stdout=out)
        output = out.getvalue()
        
        self.assertIn('CACHE OPTIMIZATION ANALYSIS', output)
        self.assertIn('Current Performance:', output)