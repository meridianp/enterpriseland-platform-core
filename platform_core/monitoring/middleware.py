"""
Monitoring Middleware

Django middleware for performance monitoring.
"""

import time
import logging
from typing import Optional, Callable
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

from .metrics import metrics_registry
from .collectors import APIMetricsCollector

logger = logging.getLogger(__name__)


class MetricsMiddleware(MiddlewareMixin):
    """Base middleware for metrics collection."""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, 'METRICS_ENABLED', True)
        
        # Initialize collectors
        self.api_collector = APIMetricsCollector(metrics_registry)
        
        # Register general metrics
        self.active_requests = metrics_registry.gauge(
            'http_requests_active',
            'Currently active HTTP requests'
        )
        self.request_counter = metrics_registry.counter(
            'http_requests_total',
            'Total HTTP requests'
        )
        self.request_timer = metrics_registry.timer(
            'http_request_duration_seconds',
            'HTTP request duration'
        )
        self.response_size_histogram = metrics_registry.histogram(
            'http_response_size_bytes',
            'HTTP response size in bytes',
            buckets=[100, 1000, 10000, 100000, 1000000]
        )
    
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Process incoming request."""
        if not self.enabled:
            return None
        
        # Track active requests
        self.active_requests.inc()
        
        # Start timing
        request._metrics_start_time = time.time()
        
        return None
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Process outgoing response."""
        if not self.enabled:
            return response
        
        try:
            # Calculate duration
            duration = time.time() - getattr(request, '_metrics_start_time', time.time())
            
            # Get endpoint info
            method = request.method
            path = request.path
            status = response.status_code
            
            # Normalize path for metrics (remove IDs, etc.)
            endpoint = self._normalize_path(path)
            
            # Track request metrics
            self.request_counter.inc()
            self.request_timer.observe(duration)
            self.active_requests.dec()
            
            # Track response size
            if hasattr(response, 'content'):
                self.response_size_histogram.observe(len(response.content))
            
            # Track API-specific metrics
            self.api_collector.record_request(method, endpoint, status, duration)
            
            # Add timing header
            response['X-Response-Time'] = f"{duration * 1000:.2f}ms"
            
        except Exception as e:
            logger.error(f"Error recording metrics: {e}")
        
        return response
    
    def process_exception(self, request: HttpRequest, exception: Exception) -> Optional[HttpResponse]:
        """Process exceptions."""
        if not self.enabled:
            return None
        
        # Decrement active requests
        self.active_requests.dec()
        
        # Track errors
        error_counter = metrics_registry.counter(
            'http_errors_total',
            'Total HTTP errors',
            labels={'type': type(exception).__name__}
        )
        error_counter.inc()
        
        return None
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path for metrics grouping."""
        # Remove trailing slash
        path = path.rstrip('/')
        
        # Replace IDs with placeholders
        import re
        
        # UUID pattern
        path = re.sub(
            r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '/{id}',
            path
        )
        
        # Numeric ID pattern
        path = re.sub(r'/\d+', '/{id}', path)
        
        return path or '/'


class RequestMetricsMiddleware(MetricsMiddleware):
    """Detailed request metrics middleware."""
    
    def __init__(self, get_response):
        super().__init__(get_response)
        
        # Additional metrics
        self.request_by_method = {}
        self.request_by_status = {}
        
        for method in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
            self.request_by_method[method] = metrics_registry.counter(
                f'http_requests_{method.lower()}_total',
                f'Total {method} requests'
            )
        
        for status_range in ['2xx', '3xx', '4xx', '5xx']:
            self.request_by_status[status_range] = metrics_registry.counter(
                f'http_responses_{status_range}_total',
                f'Total {status_range} responses'
            )
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Process response with detailed metrics."""
        response = super().process_response(request, response)
        
        if not self.enabled:
            return response
        
        try:
            # Track by method
            method = request.method
            if method in self.request_by_method:
                self.request_by_method[method].inc()
            
            # Track by status code range
            status = response.status_code
            if 200 <= status < 300:
                self.request_by_status['2xx'].inc()
            elif 300 <= status < 400:
                self.request_by_status['3xx'].inc()
            elif 400 <= status < 500:
                self.request_by_status['4xx'].inc()
            elif 500 <= status < 600:
                self.request_by_status['5xx'].inc()
            
            # Track user agent
            user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
            browser = self._parse_browser(user_agent)
            
            browser_counter = metrics_registry.counter(
                'http_requests_by_browser_total',
                'Requests by browser',
                labels={'browser': browser}
            )
            browser_counter.inc()
            
        except Exception as e:
            logger.error(f"Error recording detailed metrics: {e}")
        
        return response
    
    def _parse_browser(self, user_agent: str) -> str:
        """Parse browser from user agent."""
        user_agent_lower = user_agent.lower()
        
        if 'chrome' in user_agent_lower:
            return 'chrome'
        elif 'firefox' in user_agent_lower:
            return 'firefox'
        elif 'safari' in user_agent_lower:
            return 'safari'
        elif 'edge' in user_agent_lower:
            return 'edge'
        elif 'bot' in user_agent_lower or 'crawler' in user_agent_lower:
            return 'bot'
        else:
            return 'other'


class ResponseTimeMiddleware(MiddlewareMixin):
    """Middleware focused on response time monitoring."""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.slow_request_threshold = getattr(settings, 'SLOW_REQUEST_THRESHOLD', 1.0)  # 1 second
        
        # Metrics
        self.slow_requests = metrics_registry.counter(
            'http_slow_requests_total',
            'Requests slower than threshold'
        )
        self.response_time_by_view = {}
    
    def process_view(self, request: HttpRequest, view_func: Callable, view_args: tuple, view_kwargs: dict) -> Optional[HttpResponse]:
        """Track view processing time."""
        request._view_start_time = time.time()
        request._view_name = f"{view_func.__module__}.{view_func.__name__}"
        return None
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Track response times."""
        if hasattr(request, '_view_start_time'):
            duration = time.time() - request._view_start_time
            view_name = getattr(request, '_view_name', 'unknown')
            
            # Track slow requests
            if duration > self.slow_request_threshold:
                self.slow_requests.inc()
                logger.warning(
                    f"Slow request detected: {view_name} took {duration:.2f}s "
                    f"(threshold: {self.slow_request_threshold}s)"
                )
            
            # Track per-view metrics
            if view_name not in self.response_time_by_view:
                self.response_time_by_view[view_name] = metrics_registry.timer(
                    'http_view_duration_seconds',
                    'View processing duration',
                    labels={'view': view_name}
                )
            
            self.response_time_by_view[view_name].observe(duration)
        
        return response


class ErrorTrackingMiddleware(MiddlewareMixin):
    """Middleware for detailed error tracking."""
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Error metrics
        self.error_by_type = {}
        self.error_by_view = {}
        self.unhandled_errors = metrics_registry.counter(
            'errors_unhandled_total',
            'Unhandled exceptions'
        )
    
    def process_exception(self, request: HttpRequest, exception: Exception) -> Optional[HttpResponse]:
        """Track exceptions."""
        error_type = type(exception).__name__
        view_name = getattr(request, '_view_name', 'unknown')
        
        # Track by error type
        if error_type not in self.error_by_type:
            self.error_by_type[error_type] = metrics_registry.counter(
                'errors_by_type_total',
                'Errors by type',
                labels={'error_type': error_type}
            )
        self.error_by_type[error_type].inc()
        
        # Track by view
        if view_name not in self.error_by_view:
            self.error_by_view[view_name] = metrics_registry.counter(
                'errors_by_view_total',
                'Errors by view',
                labels={'view': view_name}
            )
        self.error_by_view[view_name].inc()
        
        # Track unhandled
        self.unhandled_errors.inc()
        
        # Log error details
        logger.error(
            f"Unhandled exception in {view_name}: {error_type}",
            exc_info=exception
        )
        
        return None