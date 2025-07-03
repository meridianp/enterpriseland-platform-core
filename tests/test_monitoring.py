"""
Tests for Performance Monitoring
"""

import time
import json
from unittest.mock import Mock, patch
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth.models import User
from django.http import HttpResponse

from platform_core.monitoring import (
    MetricsRegistry,
    Counter,
    Gauge,
    Histogram,
    Timer,
    MetricsCollector,
    SystemMetricsCollector,
    DatabaseMetricsCollector,
    CacheMetricsCollector,
    APIMetricsCollector,
    PrometheusExporter,
    JSONExporter,
    MetricsMiddleware,
    PerformanceMonitor,
    HealthMonitor,
    monitor_performance,
    track_metrics,
    measure_time,
    count_calls,
    track_errors,
    MetricsContext
)
from platform_core.monitoring.views import (
    MetricsView,
    HealthView,
    ReadinessView,
    LivenessView
)


class TestMetrics(TestCase):
    """Test core metrics functionality."""
    
    def setUp(self):
        self.registry = MetricsRegistry()
    
    def test_counter_metric(self):
        """Test counter metric operations."""
        counter = Counter('test_counter', 'Test counter')
        
        # Initial value
        self.assertEqual(counter.get_value(), 0)
        
        # Increment
        counter.inc()
        self.assertEqual(counter.get_value(), 1)
        
        # Increment by value
        counter.inc(5)
        self.assertEqual(counter.get_value(), 6)
        
        # Cannot decrement
        with self.assertRaises(ValueError):
            counter.inc(-1)
        
        # Reset
        counter.reset()
        self.assertEqual(counter.get_value(), 0)
    
    def test_gauge_metric(self):
        """Test gauge metric operations."""
        gauge = Gauge('test_gauge', 'Test gauge')
        
        # Set value
        gauge.set(10)
        self.assertEqual(gauge.get_value(), 10)
        
        # Increment
        gauge.inc(5)
        self.assertEqual(gauge.get_value(), 15)
        
        # Decrement
        gauge.dec(3)
        self.assertEqual(gauge.get_value(), 12)
        
        # Reset
        gauge.reset()
        self.assertEqual(gauge.get_value(), 0)
    
    def test_histogram_metric(self):
        """Test histogram metric operations."""
        histogram = Histogram('test_histogram', 'Test histogram')
        
        # Observe values
        values = [0.1, 0.5, 1.0, 2.0, 5.0]
        for v in values:
            histogram.observe(v)
        
        stats = histogram.get_value()
        
        self.assertEqual(stats['count'], 5)
        self.assertEqual(stats['sum'], sum(values))
        self.assertAlmostEqual(stats['mean'], sum(values) / len(values))
        self.assertEqual(stats['min'], 0.1)
        self.assertEqual(stats['max'], 5.0)
        
        # Check percentiles
        self.assertIn('p50', stats['percentiles'])
        self.assertIn('p95', stats['percentiles'])
        
        # Check buckets
        self.assertIn('le_0.5', stats['buckets'])
        self.assertEqual(stats['buckets']['le_0.5'], 2)  # 0.1 and 0.5
    
    def test_timer_metric(self):
        """Test timer metric operations."""
        timer = Timer('test_timer', 'Test timer')
        
        # Time with context manager
        with timer.time():
            time.sleep(0.01)
        
        stats = timer.get_value()
        self.assertEqual(stats['count'], 1)
        self.assertGreater(stats['sum'], 0.01)
        
        # Time with decorator
        @timer.time_func
        def slow_function():
            time.sleep(0.01)
            return "done"
        
        result = slow_function()
        self.assertEqual(result, "done")
        
        stats = timer.get_value()
        self.assertEqual(stats['count'], 2)
    
    def test_metrics_registry(self):
        """Test metrics registry operations."""
        # Register metrics
        counter = self.registry.counter('requests_total', 'Total requests')
        gauge = self.registry.gauge('active_users', 'Active users')
        
        # Get registered metrics
        self.assertIsNotNone(self.registry.get_metric('requests_total'))
        self.assertIsNotNone(self.registry.get_metric('active_users'))
        
        # Cannot register duplicate
        with self.assertRaises(ValueError):
            self.registry.counter('requests_total')
        
        # Get existing metric
        same_counter = self.registry.counter('requests_total')
        self.assertEqual(same_counter, counter)
        
        # Collect all metrics
        counter.inc(5)
        gauge.set(10)
        
        collected = self.registry.collect()
        self.assertEqual(len(collected), 2)
        
        # Reset all
        self.registry.reset_all()
        self.assertEqual(counter.get_value(), 0)
        self.assertEqual(gauge.get_value(), 0)
    
    def test_labeled_metrics(self):
        """Test metrics with labels."""
        counter = self.registry.counter(
            'http_requests',
            'HTTP requests',
            labels={'method': 'GET', 'status': '200'}
        )
        
        counter.inc()
        
        # Different labels create different metrics
        post_counter = self.registry.counter(
            'http_requests',
            'HTTP requests',
            labels={'method': 'POST', 'status': '200'}
        )
        
        post_counter.inc(2)
        
        # Original counter unchanged
        self.assertEqual(counter.get_value(), 1)
        self.assertEqual(post_counter.get_value(), 2)


class TestCollectors(TestCase):
    """Test metrics collectors."""
    
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    def test_system_metrics_collector(self, mock_memory, mock_cpu):
        """Test system metrics collection."""
        # Mock system stats
        mock_cpu.return_value = 50.0
        mock_memory.return_value = Mock(
            used=1024 * 1024 * 1024,  # 1GB
            percent=25.0
        )
        
        collector = SystemMetricsCollector()
        collector.collect()
        
        # Check metrics were recorded
        cpu_metric = collector.registry.get_metric('system_cpu_usage_percent')
        self.assertEqual(cpu_metric.get_value(), 50.0)
        
        memory_metric = collector.registry.get_metric('system_memory_usage_percent')
        self.assertEqual(memory_metric.get_value(), 25.0)
    
    def test_api_metrics_collector(self):
        """Test API metrics collection."""
        collector = APIMetricsCollector()
        
        # Record some requests
        collector.record_request('GET', '/api/users/', 200, 0.1)
        collector.record_request('GET', '/api/users/', 200, 0.2)
        collector.record_request('POST', '/api/users/', 201, 0.3)
        collector.record_request('GET', '/api/users/', 500, 0.1)
        
        # Check metrics
        total_requests = collector.registry.get_metric(
            'api_requests_total',
            {'method': 'GET', 'endpoint': '/api/users/', 'status': '200'}
        )
        self.assertEqual(total_requests.get_value(), 2)
        
        errors = collector.registry.get_metric(
            'api_errors_total',
            {'method': 'GET', 'endpoint': '/api/users/', 'error_type': '5xx'}
        )
        self.assertEqual(errors.get_value(), 1)
    
    def test_cache_metrics_collector(self):
        """Test cache metrics collection."""
        collector = CacheMetricsCollector()
        
        # Simulate cache operations
        collector.hit_counter.inc(80)
        collector.miss_counter.inc(20)
        
        collector.collect()
        
        # Check hit rate calculation
        hit_rate = collector.registry.get_metric('cache_hit_rate_percent')
        self.assertEqual(hit_rate.get_value(), 80.0)


class TestExporters(TestCase):
    """Test metrics exporters."""
    
    def setUp(self):
        self.registry = MetricsRegistry()
        
        # Create some metrics
        self.counter = self.registry.counter('test_counter', 'Test counter')
        self.counter.inc(42)
        
        self.gauge = self.registry.gauge('test_gauge', 'Test gauge')
        self.gauge.set(3.14)
        
        self.histogram = self.registry.histogram('test_histogram', 'Test histogram')
        for i in range(10):
            self.histogram.observe(i * 0.1)
    
    def test_prometheus_exporter(self):
        """Test Prometheus format export."""
        exporter = PrometheusExporter(self.registry)
        
        metrics = self.registry.collect()
        exporter.export(metrics)
        
        output = exporter.generate_text()
        
        # Check format
        self.assertIn('# HELP test_counter Test counter', output)
        self.assertIn('# TYPE test_counter counter', output)
        self.assertIn('test_counter 42', output)
        
        self.assertIn('# TYPE test_gauge gauge', output)
        self.assertIn('test_gauge 3.14', output)
        
        self.assertIn('# TYPE test_histogram histogram', output)
        self.assertIn('test_histogram_bucket', output)
        self.assertIn('test_histogram_sum', output)
        self.assertIn('test_histogram_count', output)
    
    def test_json_exporter(self):
        """Test JSON format export."""
        exporter = JSONExporter(self.registry)
        
        # Capture output
        with patch('builtins.print') as mock_print:
            metrics = self.registry.collect()
            exporter.export(metrics)
        
        # Check print was called with JSON
        mock_print.assert_called_once()
        output = mock_print.call_args[0][0]
        
        data = json.loads(output)
        self.assertIn('timestamp', data)
        self.assertIn('metrics', data)
        self.assertEqual(len(data['metrics']), 3)


class TestMiddleware(TestCase):
    """Test monitoring middleware."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = MetricsMiddleware(Mock())
    
    def test_request_tracking(self):
        """Test request metrics tracking."""
        request = self.factory.get('/api/test/')
        request._metrics_start_time = time.time()
        
        response = HttpResponse('OK')
        response.status_code = 200
        
        # Process response
        processed = self.middleware.process_response(request, response)
        
        # Check metrics were recorded
        self.assertEqual(self.middleware.request_counter.get_value(), 1)
        self.assertGreater(self.middleware.request_timer.get_value()['count'], 0)
        
        # Check response header
        self.assertIn('X-Response-Time', processed)
    
    def test_error_tracking(self):
        """Test error metrics tracking."""
        request = self.factory.get('/api/test/')
        exception = ValueError("Test error")
        
        self.middleware.process_exception(request, exception)
        
        # Check error was tracked
        error_counter = self.middleware.registry.get_metric(
            'http_errors_total',
            {'type': 'ValueError'}
        )
        self.assertEqual(error_counter.get_value(), 1)
    
    def test_path_normalization(self):
        """Test path normalization for metrics."""
        # UUID normalization
        path1 = self.middleware._normalize_path('/api/users/123e4567-e89b-12d3-a456-426614174000/')
        self.assertEqual(path1, '/api/users/{id}')
        
        # Numeric ID normalization
        path2 = self.middleware._normalize_path('/api/posts/123/')
        self.assertEqual(path2, '/api/posts/{id}')


class TestMonitors(TestCase):
    """Test monitoring components."""
    
    def test_health_monitor(self):
        """Test health monitoring."""
        monitor = HealthMonitor()
        
        # Run health checks
        results = monitor.run_health_checks()
        
        self.assertIn('timestamp', results)
        self.assertIn('checks', results)
        self.assertIn('overall_status', results)
        
        # Should have basic checks
        self.assertIn('database', results['checks'])
        self.assertIn('cache', results['checks'])
        self.assertIn('disk', results['checks'])
    
    @patch('platform_core.monitoring.monitors.metrics_registry')
    def test_performance_monitor(self, mock_registry):
        """Test performance monitoring."""
        # Mock metrics
        mock_registry.get_metric.side_effect = lambda name: Mock(
            get_value=Mock(return_value=50.0)
        )
        
        monitor = PerformanceMonitor()
        
        # Check thresholds
        metrics = {
            'cpu_percent': 90,  # Over threshold
            'memory_percent': 50,  # Under threshold
        }
        
        alerts = monitor._check_thresholds(metrics)
        
        # Should have CPU alert
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['metric'], 'cpu_percent')
        self.assertIn('exceeds threshold', alerts[0]['message'])


class TestDecorators(TestCase):
    """Test monitoring decorators."""
    
    def test_monitor_performance_decorator(self):
        """Test performance monitoring decorator."""
        @monitor_performance(name="test_function")
        def slow_function(x):
            time.sleep(0.01)
            return x * 2
        
        result = slow_function(5)
        self.assertEqual(result, 10)
        
        # Check metrics were recorded
        from platform_core.monitoring.metrics import metrics_registry
        
        counter = metrics_registry.get_metric('test_function_calls_total')
        self.assertEqual(counter.get_value(), 1)
        
        timer = metrics_registry.get_metric('test_function_duration_seconds')
        stats = timer.get_value()
        self.assertEqual(stats['count'], 1)
        self.assertGreater(stats['sum'], 0.01)
    
    def test_track_errors_decorator(self):
        """Test error tracking decorator."""
        @track_errors("test_errors", reraise=False, default_return="error")
        def failing_function():
            raise ValueError("Test error")
        
        result = failing_function()
        self.assertEqual(result, "error")
        
        # Check error was tracked
        from platform_core.monitoring.metrics import metrics_registry
        
        error_counter = metrics_registry.get_metric(
            'test_errors',
            {'error_type': 'ValueError'}
        )
        self.assertEqual(error_counter.get_value(), 1)
    
    def test_metrics_context(self):
        """Test metrics context manager."""
        from platform_core.monitoring.metrics import metrics_registry
        
        with MetricsContext("batch_job") as ctx:
            for i in range(10):
                ctx.increment("items_processed")
                ctx.observe("item_size", i * 100)
            
            ctx.gauge("final_count", 10)
        
        # Check metrics
        counter = metrics_registry.get_metric('batch_job_items_processed')
        self.assertEqual(counter.get_value(), 10)
        
        gauge = metrics_registry.get_metric('batch_job_final_count')
        self.assertEqual(gauge.get_value(), 10)


class TestViews(TestCase):
    """Test monitoring views."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='test',
            password='test',
            is_staff=True
        )
    
    def test_metrics_view(self):
        """Test metrics endpoint."""
        view = MetricsView()
        request = self.factory.get('/metrics/')
        request.user = self.user
        
        response = view.get(request)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain; version=0.0.4; charset=utf-8')
        
        # Should contain Prometheus format
        content = response.content.decode()
        self.assertIn('# TYPE', content)
        self.assertIn('# HELP', content)
    
    def test_health_view(self):
        """Test health endpoint."""
        view = HealthView()
        request = self.factory.get('/health/')
        
        response = view.get(request)
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertIn('status', data)
        self.assertIn('timestamp', data)
        self.assertIn('checks', data)
    
    def test_readiness_view(self):
        """Test readiness endpoint."""
        view = ReadinessView()
        request = self.factory.get('/ready/')
        
        response = view.get(request)
        
        # Should be ready in test environment
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'ready')
    
    def test_liveness_view(self):
        """Test liveness endpoint."""
        view = LivenessView()
        request = self.factory.get('/alive/')
        
        response = view.get(request)
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'alive')