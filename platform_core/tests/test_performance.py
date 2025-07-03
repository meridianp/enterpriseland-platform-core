"""
Performance Module Tests

Tests for profiling, monitoring, and optimization tools.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, RequestFactory, override_settings
from django.http import HttpResponse
from django.db import models, connection
from django.core.cache import cache
from django.contrib.auth import get_user_model

from platform_core.performance import (
    ProfilerMiddleware,
    profile_view,
    profile_method,
    PerformanceProfiler,
    MetricsCollector,
    PerformanceMonitor,
    QueryOptimizer,
    CacheWarmer,
    PerformanceOptimizer
)

User = get_user_model()


class TestModel(models.Model):
    """Test model for query optimization tests."""
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default='active')
    created_date = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    
    class Meta:
        app_label = 'test'


class TestPerformanceProfiler(TestCase):
    """Test performance profiler functionality."""
    
    def setUp(self):
        self.profiler = PerformanceProfiler()
    
    def test_profile_lifecycle(self):
        """Test profile start and end lifecycle."""
        profile_id = 'test_profile_1'
        
        # Start profile
        self.profiler.start_profile(profile_id)
        self.assertIn(profile_id, self.profiler.profiles)
        
        # Simulate some work
        time.sleep(0.1)
        
        # End profile
        metrics = self.profiler.end_profile(profile_id)
        
        # Verify metrics
        self.assertIn('duration', metrics)
        self.assertGreater(metrics['duration'], 100)  # > 100ms
        self.assertEqual(metrics['query_count'], 0)
        self.assertNotIn(profile_id, self.profiler.profiles)
    
    def test_query_logging(self):
        """Test database query logging."""
        profile_id = 'test_query_profile'
        
        self.profiler.start_profile(profile_id)
        
        # Log queries
        self.profiler.log_query(profile_id, 'SELECT * FROM users', 50.0)
        self.profiler.log_query(profile_id, 'UPDATE users SET ...', 150.0)  # Slow
        
        metrics = self.profiler.end_profile(profile_id)
        
        # Verify query metrics
        self.assertEqual(metrics['query_count'], 2)
        self.assertEqual(metrics['total_query_time'], 200.0)
        self.assertEqual(len([q for q in metrics['queries'] if q['slow']]), 1)
    
    def test_cache_operation_logging(self):
        """Test cache operation logging."""
        profile_id = 'test_cache_profile'
        
        self.profiler.start_profile(profile_id)
        
        # Log cache operations
        self.profiler.log_cache_operation(profile_id, 'get', 'key1', True)  # Hit
        self.profiler.log_cache_operation(profile_id, 'get', 'key2', False)  # Miss
        self.profiler.log_cache_operation(profile_id, 'set', 'key3', True)
        
        metrics = self.profiler.end_profile(profile_id)
        
        # Verify cache metrics
        self.assertEqual(len(metrics['cache_operations']), 3)
        self.assertEqual(metrics['cache_hit_rate'], 66.67)  # 2/3 hits


class TestProfilerMiddleware(TestCase):
    """Test profiler middleware."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ProfilerMiddleware(lambda r: HttpResponse('OK'))
    
    @override_settings(ENABLE_PROFILING=True, DEBUG=True)
    def test_request_profiling(self):
        """Test request profiling in middleware."""
        request = self.factory.get('/api/test/')
        
        # Process request
        self.middleware.process_request(request)
        self.assertIsNotNone(request._profile_id)
        
        # Process response
        response = HttpResponse('Test response')
        response = self.middleware.process_response(request, response)
        
        # Check headers added
        self.assertIn('X-Response-Time', response)
        self.assertIn('X-Query-Count', response)
    
    def test_excluded_paths(self):
        """Test that excluded paths are not profiled."""
        request = self.factory.get('/static/test.css')
        
        self.middleware.process_request(request)
        self.assertFalse(hasattr(request, '_profile_id'))


class TestProfileDecorators(TestCase):
    """Test profiling decorators."""
    
    @profile_view
    def sample_view(self, request):
        """Sample view for testing."""
        time.sleep(0.05)  # 50ms
        return HttpResponse('OK')
    
    def test_profile_view_decorator(self):
        """Test view profiling decorator."""
        request = RequestFactory().get('/test/')
        
        with patch('platform_core.performance.profiling.cache') as mock_cache:
            response = self.sample_view(request)
            
            # Verify response
            self.assertEqual(response.content, b'OK')
            
            # Verify profiling occurred
            mock_cache.set.assert_called()
    
    def test_profile_method_decorator(self):
        """Test method profiling decorator."""
        
        class TestService:
            @profile_method("test_process")
            def process(self):
                time.sleep(0.05)
                return "processed"
        
        service = TestService()
        
        with patch('platform_core.performance.profiling.logger') as mock_logger:
            result = service.process()
            
            self.assertEqual(result, "processed")
            # Should not log warning for fast method (< 500ms)
            mock_logger.warning.assert_not_called()


class TestMetricsCollector(TestCase):
    """Test metrics collection."""
    
    def setUp(self):
        self.collector = MetricsCollector()
    
    def test_request_metrics_collection(self):
        """Test HTTP request metrics collection."""
        with patch('platform_core.performance.monitoring.request_count') as mock_counter:
            with patch('platform_core.performance.monitoring.request_latency') as mock_histogram:
                self.collector.collect_request_metrics(
                    'GET', '/api/users/', 200, 0.150
                )
                
                # Verify Prometheus metrics updated
                mock_counter.labels.assert_called_with(
                    method='GET',
                    endpoint='/api/users/',
                    status='200'
                )
                mock_histogram.labels.assert_called_with(
                    method='GET',
                    endpoint='/api/users/'
                )
    
    def test_query_metrics_collection(self):
        """Test database query metrics collection."""
        with patch('platform_core.performance.monitoring.db_query_count') as mock_counter:
            self.collector.collect_query_metrics('SELECT * FROM users', 25.0)
            
            mock_counter.labels.assert_called_with(operation='select')
    
    def test_system_metrics_collection(self):
        """Test system-level metrics collection."""
        metrics = self.collector.collect_system_metrics()
        
        # Verify system metrics collected
        self.assertIn('memory_used', metrics)
        self.assertIn('cpu_percent', metrics)
        self.assertIn('disk_used', metrics)
        self.assertIn('db_connections', metrics)


class TestPerformanceMonitor(TestCase):
    """Test performance monitoring."""
    
    def setUp(self):
        self.monitor = PerformanceMonitor()
    
    @patch('platform_core.performance.monitoring.MetricsCollector.get_aggregated_metrics')
    def test_health_check(self, mock_metrics):
        """Test system health check."""
        # Mock metrics
        mock_metrics.return_value = {
            'requests': {
                'total': 1000,
                'avg_duration': 150,
                'by_status': {'2xx': 950, '5xx': 50}
            },
            'system': {
                'cpu_percent': 45,
                'memory_percent': 60
            }
        }
        
        health = self.monitor.check_health()
        
        # Verify health status
        self.assertEqual(health['status'], 'healthy')
        self.assertIn('response_time', health['checks'])
        self.assertIn('error_rate', health['checks'])
        self.assertIn('cpu_usage', health['checks'])
        self.assertIn('memory_usage', health['checks'])
    
    @patch('platform_core.performance.monitoring.MetricsCollector.get_aggregated_metrics')
    def test_performance_report(self, mock_metrics):
        """Test performance report generation."""
        # Mock metrics
        mock_metrics.return_value = {
            'requests': {
                'total': 1000,
                'avg_duration': 600,  # High response time
                'by_status': {}
            },
            'database': {
                'total_queries': 15000  # High query count
            },
            'cache': {
                'hit_rate': 50  # Low hit rate
            }
        }
        
        report = self.monitor.get_performance_report()
        
        # Verify recommendations generated
        self.assertGreater(len(report['recommendations']), 0)
        self.assertTrue(
            any('response time' in r for r in report['recommendations'])
        )


class TestQueryOptimizer(TestCase):
    """Test query optimization."""
    
    def setUp(self):
        self.optimizer = QueryOptimizer()
    
    @patch('django.db.models.QuerySet')
    def test_queryset_optimization(self, mock_queryset):
        """Test queryset optimization with relationships."""
        # Create mock queryset
        mock_queryset.model = TestModel
        mock_queryset.select_related.return_value = mock_queryset
        mock_queryset.prefetch_related.return_value = mock_queryset
        
        # Optimize
        optimized = self.optimizer.optimize_queryset(mock_queryset)
        
        # Verify optimization methods called
        mock_queryset.select_related.assert_called()
    
    def test_index_suggestions(self):
        """Test database index suggestions."""
        suggestions = self.optimizer.suggest_indexes(TestModel)
        
        # Should suggest indexes for foreign keys without indexes
        self.assertTrue(
            any(s['field'] == 'user' for s in suggestions)
        )
        
        # Should suggest indexes for commonly filtered fields
        self.assertTrue(
            any(s['field'] == 'status' for s in suggestions)
        )
    
    def test_query_analysis(self):
        """Test query analysis for patterns."""
        queries = [
            {'sql': 'SELECT * FROM users WHERE id = 1', 'duration': 10},
            {'sql': 'SELECT * FROM users WHERE id = 2', 'duration': 10},
            {'sql': 'SELECT * FROM users WHERE id = 3', 'duration': 10},
            {'sql': 'SELECT * FROM users WHERE id = 4', 'duration': 10},
        ]
        
        # Detect N+1 pattern
        n_plus_one = self.optimizer._detect_n_plus_one(queries)
        self.assertTrue(n_plus_one)
        
        # Find duplicates
        queries.append({'sql': 'SELECT * FROM users WHERE id = 1', 'duration': 10})
        duplicates = self.optimizer._find_duplicates(queries)
        self.assertGreater(len(duplicates), 0)


class TestCacheWarmer(TestCase):
    """Test cache warming functionality."""
    
    def setUp(self):
        self.warmer = CacheWarmer()
        cache.clear()
    
    def test_warming_strategy_registration(self):
        """Test registering cache warming strategies."""
        def test_strategy():
            cache.set('test_key', 'test_value', 300)
            return ['test_key']
        
        self.warmer.register_warming_strategy('test_pattern', test_strategy)
        
        # Warm cache
        results = self.warmer.warm_cache('test_pattern')
        
        # Verify results
        self.assertEqual(results['warmed_keys'], 1)
        self.assertEqual(results['failed_keys'], 0)
        
        # Verify cache warmed
        self.assertEqual(cache.get('test_key'), 'test_value')
    
    @patch('platform_core.performance.optimization.QueryOptimizer')
    def test_queryset_cache_warming(self, mock_optimizer):
        """Test warming cache for querysets."""
        # Mock optimizer
        mock_optimizer.return_value.optimize_queryset.return_value = User.objects.none()
        
        # Warm cache
        warmed_keys = self.warmer.warm_queryset_cache(User)
        
        # Verify keys warmed
        self.assertGreater(len(warmed_keys), 0)


class TestPerformanceOptimizer(TestCase):
    """Test performance optimization coordinator."""
    
    def setUp(self):
        self.optimizer = PerformanceOptimizer()
    
    @patch('platform_core.performance.optimization.QueryOptimizer.analyze_slow_queries')
    @patch('platform_core.performance.optimization.CacheWarmer.warm_cache')
    def test_optimization_suite(self, mock_warm_cache, mock_analyze):
        """Test running full optimization suite."""
        # Mock responses
        mock_analyze.return_value = []
        mock_warm_cache.return_value = {
            'warmed_keys': 10,
            'failed_keys': 0
        }
        
        # Run optimization
        results = self.optimizer.run_optimization_suite()
        
        # Verify results structure
        self.assertIn('timestamp', results)
        self.assertIn('optimizations', results)
        self.assertIn('recommendations', results)
        
        # Verify methods called
        mock_analyze.assert_called()
        mock_warm_cache.assert_called()
    
    def test_model_query_optimization(self):
        """Test optimizing queries for a specific model."""
        # Create test data
        User.objects.create_user('test1', 'test1@example.com')
        User.objects.create_user('test2', 'test2@example.com')
        
        # Optimize
        results = self.optimizer.optimize_model_queries(User)
        
        # Verify results
        self.assertEqual(results['model'], 'auth.User')
        self.assertIn('optimizations', results)
        
        # Each optimization should show timing
        for opt in results['optimizations']:
            self.assertIn('original_time', opt)
            self.assertIn('optimized_time', opt)
            self.assertIn('improvement_percent', opt)


class TestManagementCommand(TestCase):
    """Test performance analysis management command."""
    
    def test_command_execution(self):
        """Test analyze_performance command."""
        from django.core.management import call_command
        from io import StringIO
        
        out = StringIO()
        
        # Test health check
        call_command('analyze_performance', '--type=health', stdout=out)
        output = out.getvalue()
        
        self.assertIn('Status:', output)
        self.assertIn('Health Checks:', output)