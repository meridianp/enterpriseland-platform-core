"""
Core Metrics Classes

Provides metric types and registry for performance monitoring.
"""

import time
import threading
from typing import Dict, List, Any, Optional, Callable, Union
from collections import defaultdict, deque
from datetime import datetime, timedelta
import logging
import statistics

logger = logging.getLogger(__name__)


class Metric:
    """Base metric class."""
    
    def __init__(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None):
        self.name = name
        self.description = description
        self.labels = labels or {}
        self._lock = threading.Lock()
        self.created_at = datetime.now()
    
    def get_value(self) -> Any:
        """Get current metric value."""
        raise NotImplementedError
    
    def reset(self):
        """Reset metric to initial state."""
        raise NotImplementedError
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary."""
        return {
            'name': self.name,
            'description': self.description,
            'labels': self.labels,
            'value': self.get_value(),
            'type': self.__class__.__name__,
            'created_at': self.created_at.isoformat()
        }


class Counter(Metric):
    """Counter metric that can only increase."""
    
    def __init__(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None):
        super().__init__(name, description, labels)
        self._value = 0
    
    def inc(self, value: float = 1):
        """Increment counter."""
        if value < 0:
            raise ValueError("Counter can only be incremented with positive values")
        
        with self._lock:
            self._value += value
    
    def get_value(self) -> float:
        """Get current counter value."""
        with self._lock:
            return self._value
    
    def reset(self):
        """Reset counter to zero."""
        with self._lock:
            self._value = 0


class Gauge(Metric):
    """Gauge metric that can go up or down."""
    
    def __init__(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None):
        super().__init__(name, description, labels)
        self._value = 0
    
    def set(self, value: float):
        """Set gauge value."""
        with self._lock:
            self._value = value
    
    def inc(self, value: float = 1):
        """Increment gauge."""
        with self._lock:
            self._value += value
    
    def dec(self, value: float = 1):
        """Decrement gauge."""
        with self._lock:
            self._value -= value
    
    def get_value(self) -> float:
        """Get current gauge value."""
        with self._lock:
            return self._value
    
    def reset(self):
        """Reset gauge to zero."""
        with self._lock:
            self._value = 0


class Histogram(Metric):
    """Histogram metric for tracking value distributions."""
    
    def __init__(
        self,
        name: str,
        description: str = "",
        labels: Optional[Dict[str, str]] = None,
        buckets: Optional[List[float]] = None
    ):
        super().__init__(name, description, labels)
        self.buckets = buckets or [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
        self._values = []
        self._sum = 0
        self._count = 0
    
    def observe(self, value: float):
        """Record a value in the histogram."""
        with self._lock:
            self._values.append(value)
            self._sum += value
            self._count += 1
            
            # Keep only last 10000 values to prevent memory issues
            if len(self._values) > 10000:
                old_value = self._values.pop(0)
                self._sum -= old_value
    
    def get_value(self) -> Dict[str, Any]:
        """Get histogram statistics."""
        with self._lock:
            if not self._values:
                return {
                    'count': 0,
                    'sum': 0,
                    'mean': 0,
                    'min': 0,
                    'max': 0,
                    'percentiles': {},
                    'buckets': {}
                }
            
            sorted_values = sorted(self._values)
            
            # Calculate percentiles
            percentiles = {}
            for p in [50, 75, 90, 95, 99]:
                idx = int(len(sorted_values) * p / 100)
                if idx < len(sorted_values):
                    percentiles[f'p{p}'] = sorted_values[idx]
            
            # Calculate bucket counts
            bucket_counts = {}
            for bucket in self.buckets:
                bucket_counts[f'le_{bucket}'] = sum(1 for v in self._values if v <= bucket)
            
            return {
                'count': self._count,
                'sum': self._sum,
                'mean': self._sum / self._count if self._count > 0 else 0,
                'min': min(self._values),
                'max': max(self._values),
                'percentiles': percentiles,
                'buckets': bucket_counts
            }
    
    def reset(self):
        """Reset histogram."""
        with self._lock:
            self._values = []
            self._sum = 0
            self._count = 0


class Timer(Histogram):
    """Timer metric for measuring durations."""
    
    def time(self):
        """Context manager for timing code execution."""
        return TimerContext(self)
    
    def time_func(self, func: Callable) -> Callable:
        """Decorator for timing function execution."""
        def wrapper(*args, **kwargs):
            with self.time():
                return func(*args, **kwargs)
        return wrapper


class TimerContext:
    """Context manager for Timer metric."""
    
    def __init__(self, timer: Timer):
        self.timer = timer
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            self.timer.observe(duration)


class MetricsRegistry:
    """Central registry for all metrics."""
    
    def __init__(self):
        self._metrics: Dict[str, Metric] = {}
        self._lock = threading.Lock()
        self._collectors: List[Callable] = []
    
    def register(self, metric: Metric) -> Metric:
        """Register a new metric."""
        with self._lock:
            key = self._generate_key(metric.name, metric.labels)
            if key in self._metrics:
                raise ValueError(f"Metric {key} already registered")
            self._metrics[key] = metric
            return metric
    
    def unregister(self, name: str, labels: Optional[Dict[str, str]] = None):
        """Unregister a metric."""
        with self._lock:
            key = self._generate_key(name, labels)
            if key in self._metrics:
                del self._metrics[key]
    
    def get_metric(self, name: str, labels: Optional[Dict[str, str]] = None) -> Optional[Metric]:
        """Get a registered metric."""
        with self._lock:
            key = self._generate_key(name, labels)
            return self._metrics.get(key)
    
    def counter(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None) -> Counter:
        """Create or get a counter metric."""
        metric = self.get_metric(name, labels)
        if metric:
            if not isinstance(metric, Counter):
                raise TypeError(f"Metric {name} is not a Counter")
            return metric
        
        counter = Counter(name, description, labels)
        return self.register(counter)
    
    def gauge(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None) -> Gauge:
        """Create or get a gauge metric."""
        metric = self.get_metric(name, labels)
        if metric:
            if not isinstance(metric, Gauge):
                raise TypeError(f"Metric {name} is not a Gauge")
            return metric
        
        gauge = Gauge(name, description, labels)
        return self.register(gauge)
    
    def histogram(
        self,
        name: str,
        description: str = "",
        labels: Optional[Dict[str, str]] = None,
        buckets: Optional[List[float]] = None
    ) -> Histogram:
        """Create or get a histogram metric."""
        metric = self.get_metric(name, labels)
        if metric:
            if not isinstance(metric, Histogram):
                raise TypeError(f"Metric {name} is not a Histogram")
            return metric
        
        histogram = Histogram(name, description, labels, buckets)
        return self.register(histogram)
    
    def timer(
        self,
        name: str,
        description: str = "",
        labels: Optional[Dict[str, str]] = None,
        buckets: Optional[List[float]] = None
    ) -> Timer:
        """Create or get a timer metric."""
        metric = self.get_metric(name, labels)
        if metric:
            if not isinstance(metric, Timer):
                raise TypeError(f"Metric {name} is not a Timer")
            return metric
        
        timer = Timer(name, description, labels, buckets)
        return self.register(timer)
    
    def get_all_metrics(self) -> Dict[str, Metric]:
        """Get all registered metrics."""
        with self._lock:
            return self._metrics.copy()
    
    def collect(self) -> List[Dict[str, Any]]:
        """Collect all metric values."""
        metrics = []
        
        # Collect from registered metrics
        for metric in self.get_all_metrics().values():
            metrics.append(metric.to_dict())
        
        # Collect from registered collectors
        for collector in self._collectors:
            try:
                collected = collector()
                if isinstance(collected, list):
                    metrics.extend(collected)
                elif isinstance(collected, dict):
                    metrics.append(collected)
            except Exception as e:
                logger.error(f"Error collecting metrics: {e}")
        
        return metrics
    
    def register_collector(self, collector: Callable):
        """Register a metrics collector function."""
        self._collectors.append(collector)
    
    def reset_all(self):
        """Reset all metrics."""
        with self._lock:
            for metric in self._metrics.values():
                metric.reset()
    
    def _generate_key(self, name: str, labels: Optional[Dict[str, str]] = None) -> str:
        """Generate unique key for metric."""
        if not labels:
            return name
        
        label_str = ','.join(f'{k}={v}' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


class MetricsCollector:
    """Base class for metrics collectors."""
    
    def __init__(self, registry: MetricsRegistry):
        self.registry = registry
        self._enabled = True
    
    def enable(self):
        """Enable metrics collection."""
        self._enabled = True
    
    def disable(self):
        """Disable metrics collection."""
        self._enabled = False
    
    def is_enabled(self) -> bool:
        """Check if collection is enabled."""
        return self._enabled
    
    def collect(self) -> List[Dict[str, Any]]:
        """Collect metrics. Override in subclasses."""
        raise NotImplementedError


# Global metrics registry
metrics_registry = MetricsRegistry()