"""
Monitoring Decorators

Decorators for easy performance monitoring integration.
"""

import time
import functools
import logging
from typing import Any, Callable, Optional, Dict
from django.conf import settings

from .metrics import metrics_registry

logger = logging.getLogger(__name__)


def monitor_performance(
    name: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
    track_args: bool = False
):
    """
    Decorator to monitor function performance.
    
    Args:
        name: Metric name (defaults to function name)
        labels: Additional labels for the metric
        track_args: Whether to include function arguments as labels
    
    Example:
        @monitor_performance(name="api_call", labels={"service": "users"})
        def get_user(user_id):
            return User.objects.get(id=user_id)
    """
    def decorator(func: Callable) -> Callable:
        metric_name = name or f"{func.__module__}.{func.__name__}"
        
        # Create metrics
        timer = metrics_registry.timer(
            f"{metric_name}_duration_seconds",
            f"Execution time for {metric_name}",
            labels=labels
        )
        counter = metrics_registry.counter(
            f"{metric_name}_calls_total",
            f"Total calls to {metric_name}",
            labels=labels
        )
        error_counter = metrics_registry.counter(
            f"{metric_name}_errors_total",
            f"Errors in {metric_name}",
            labels=labels
        )
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Track call
            counter.inc()
            
            # Add argument labels if requested
            call_labels = labels.copy() if labels else {}
            if track_args and args:
                call_labels['arg0'] = str(args[0])[:50]  # Limit label size
            
            # Time execution
            start_time = time.time()
            error_occurred = False
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                error_occurred = True
                error_counter.inc()
                raise
            finally:
                duration = time.time() - start_time
                timer.observe(duration)
                
                # Log slow operations
                if duration > 1.0:  # 1 second threshold
                    logger.warning(
                        f"Slow operation: {metric_name} took {duration:.2f}s"
                    )
        
        return wrapper
    return decorator


def track_metrics(
    timer_name: Optional[str] = None,
    counter_name: Optional[str] = None,
    gauge_name: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None
):
    """
    Generic decorator to track multiple metric types.
    
    Example:
        @track_metrics(
            timer_name="process_order_time",
            counter_name="orders_processed",
            gauge_name="order_value"
        )
        def process_order(order):
            # Process order
            return order.total_value
    """
    def decorator(func: Callable) -> Callable:
        # Initialize metrics
        timer = None
        counter = None
        gauge = None
        
        if timer_name:
            timer = metrics_registry.timer(timer_name, labels=labels)
        if counter_name:
            counter = metrics_registry.counter(counter_name, labels=labels)
        if gauge_name:
            gauge = metrics_registry.gauge(gauge_name, labels=labels)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Start timing
            start_time = time.time() if timer else None
            
            # Execute function
            result = func(*args, **kwargs)
            
            # Update metrics
            if timer:
                timer.observe(time.time() - start_time)
            if counter:
                counter.inc()
            if gauge and isinstance(result, (int, float)):
                gauge.set(result)
            
            return result
        
        return wrapper
    return decorator


def measure_time(metric_name: Optional[str] = None):
    """
    Simple decorator to measure execution time.
    
    Example:
        @measure_time("database_query")
        def complex_query():
            return Model.objects.filter(...).aggregate(...)
    """
    def decorator(func: Callable) -> Callable:
        name = metric_name or f"{func.__module__}.{func.__name__}"
        timer = metrics_registry.timer(f"{name}_duration_seconds")
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with timer.time():
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def count_calls(metric_name: Optional[str] = None, labels: Optional[Dict[str, str]] = None):
    """
    Decorator to count function calls.
    
    Example:
        @count_calls("cache_misses")
        def fetch_from_database(key):
            return db.get(key)
    """
    def decorator(func: Callable) -> Callable:
        name = metric_name or f"{func.__module__}.{func.__name__}_calls"
        counter = metrics_registry.counter(name, labels=labels)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            counter.inc()
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def track_errors(
    metric_name: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
    reraise: bool = True,
    default_return: Any = None
):
    """
    Decorator to track function errors.
    
    Args:
        metric_name: Name for the error metric
        labels: Additional labels
        reraise: Whether to re-raise exceptions
        default_return: Value to return if exception occurs and reraise=False
    
    Example:
        @track_errors("api_errors", labels={"endpoint": "users"})
        def api_call():
            return external_service.call()
    """
    def decorator(func: Callable) -> Callable:
        name = metric_name or f"{func.__module__}.{func.__name__}_errors"
        error_counter = metrics_registry.counter(name, labels=labels)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Track error
                error_labels = labels.copy() if labels else {}
                error_labels['error_type'] = type(e).__name__
                
                error_counter.labels = error_labels
                error_counter.inc()
                
                # Log error
                logger.error(
                    f"Error in {func.__name__}: {e}",
                    exc_info=True
                )
                
                if reraise:
                    raise
                return default_return
        
        return wrapper
    return decorator


class MetricsContext:
    """
    Context manager for tracking metrics.
    
    Example:
        with MetricsContext("batch_processing") as ctx:
            for item in items:
                process_item(item)
                ctx.increment("items_processed")
    """
    
    def __init__(self, name: str, labels: Optional[Dict[str, str]] = None):
        self.name = name
        self.labels = labels or {}
        self.start_time = None
        self.metrics = {}
    
    def __enter__(self):
        self.start_time = time.time()
        
        # Create timer
        self.timer = metrics_registry.timer(
            f"{self.name}_duration_seconds",
            labels=self.labels
        )
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Record duration
        if self.start_time:
            duration = time.time() - self.start_time
            self.timer.observe(duration)
        
        # Handle errors
        if exc_type:
            error_counter = metrics_registry.counter(
                f"{self.name}_errors_total",
                labels={**self.labels, 'error_type': exc_type.__name__}
            )
            error_counter.inc()
    
    def increment(self, metric_name: str, value: float = 1):
        """Increment a counter within the context."""
        if metric_name not in self.metrics:
            self.metrics[metric_name] = metrics_registry.counter(
                f"{self.name}_{metric_name}",
                labels=self.labels
            )
        self.metrics[metric_name].inc(value)
    
    def gauge(self, metric_name: str, value: float):
        """Set a gauge value within the context."""
        if metric_name not in self.metrics:
            self.metrics[metric_name] = metrics_registry.gauge(
                f"{self.name}_{metric_name}",
                labels=self.labels
            )
        self.metrics[metric_name].set(value)
    
    def observe(self, metric_name: str, value: float):
        """Observe a value in a histogram."""
        if metric_name not in self.metrics:
            self.metrics[metric_name] = metrics_registry.histogram(
                f"{self.name}_{metric_name}",
                labels=self.labels
            )
        self.metrics[metric_name].observe(value)


def monitor_model_operation(operation: str = "save"):
    """
    Decorator for Django model methods.
    
    Example:
        class MyModel(models.Model):
            @monitor_model_operation("save")
            def save(self, *args, **kwargs):
                super().save(*args, **kwargs)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            model_name = self.__class__.__name__
            
            # Create metrics
            timer = metrics_registry.timer(
                f"model_{operation}_duration_seconds",
                labels={'model': model_name}
            )
            counter = metrics_registry.counter(
                f"model_{operation}_total",
                labels={'model': model_name}
            )
            
            # Track operation
            counter.inc()
            
            with timer.time():
                return func(self, *args, **kwargs)
        
        return wrapper
    return decorator


def cache_metrics(cache_name: str = "default"):
    """
    Decorator to track cache operations.
    
    Example:
        @cache_metrics("user_cache")
        def get_user(user_id):
            cached = cache.get(f"user_{user_id}")
            if cached:
                return cached
            
            user = User.objects.get(id=user_id)
            cache.set(f"user_{user_id}", user)
            return user
    """
    def decorator(func: Callable) -> Callable:
        # Create metrics
        hit_counter = metrics_registry.counter(
            f"cache_{cache_name}_hits_total"
        )
        miss_counter = metrics_registry.counter(
            f"cache_{cache_name}_misses_total"
        )
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Intercept cache operations
            from django.core.cache import cache
            
            original_get = cache.get
            cache_hit = False
            
            def tracked_get(key, default=None, version=None):
                result = original_get(key, default, version)
                if result is not default:
                    nonlocal cache_hit
                    cache_hit = True
                    hit_counter.inc()
                else:
                    miss_counter.inc()
                return result
            
            # Temporarily replace cache.get
            cache.get = tracked_get
            
            try:
                return func(*args, **kwargs)
            finally:
                # Restore original
                cache.get = original_get
        
        return wrapper
    return decorator