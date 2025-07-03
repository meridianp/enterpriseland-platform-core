# Performance Monitoring

## Overview

The EnterpriseLand platform includes a comprehensive performance monitoring system that provides real-time metrics collection, health monitoring, and integration with popular monitoring tools like Prometheus and Grafana. The system tracks application performance, resource usage, business metrics, and system health.

## Architecture

### Components

1. **Metrics Core** - Base metric types (Counter, Gauge, Histogram, Timer)
2. **Collectors** - Specialized collectors for different subsystems
3. **Exporters** - Export metrics to monitoring systems
4. **Middleware** - Automatic request/response tracking
5. **Monitors** - Active monitoring with alerting
6. **Decorators** - Easy integration into existing code

### Metric Types

#### Counter
A cumulative metric that only increases:
```python
from platform_core.monitoring import metrics_registry

request_counter = metrics_registry.counter(
    'http_requests_total',
    'Total HTTP requests',
    labels={'method': 'GET', 'endpoint': '/api/users/'}
)
request_counter.inc()
```

#### Gauge
A metric that can go up or down:
```python
active_users = metrics_registry.gauge(
    'active_users_count',
    'Number of active users'
)
active_users.set(42)
active_users.inc(5)  # Now 47
active_users.dec(3)  # Now 44
```

#### Histogram
Track distributions of values:
```python
response_time = metrics_registry.histogram(
    'response_time_seconds',
    'Response time distribution',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0]
)
response_time.observe(0.234)
```

#### Timer
Specialized histogram for timing operations:
```python
query_timer = metrics_registry.timer(
    'db_query_duration_seconds',
    'Database query execution time'
)

# Using context manager
with query_timer.time():
    perform_database_query()

# Using decorator
@query_timer.time_func
def slow_operation():
    # ... operation code ...
```

## Configuration

### Django Settings

```python
# settings.py

# Enable/disable metrics
METRICS_ENABLED = True

# Require authentication for metrics endpoint
METRICS_REQUIRE_AUTH = False

# Slow request threshold (seconds)
SLOW_REQUEST_THRESHOLD = 1.0

# Add monitoring middleware
MIDDLEWARE = [
    # ... other middleware ...
    'platform_core.monitoring.middleware.MetricsMiddleware',
    'platform_core.monitoring.middleware.ResponseTimeMiddleware',
    'platform_core.monitoring.middleware.ErrorTrackingMiddleware',
]

# Performance thresholds
MONITORING_THRESHOLDS = {
    'cpu_percent': 80,
    'memory_percent': 85,
    'disk_percent': 90,
    'response_time_ms': 1000,
    'error_rate_percent': 5,
    'cache_hit_rate_percent': 80
}
```

### URL Configuration

```python
# urls.py
from platform_core.monitoring.views import (
    MetricsView, HealthView, ReadinessView, 
    LivenessView, MetricsDashboardView
)

urlpatterns = [
    # Prometheus metrics endpoint
    path('metrics/', MetricsView.as_view(), name='metrics'),
    
    # Health check endpoints
    path('health/', HealthView.as_view(), name='health'),
    path('ready/', ReadinessView.as_view(), name='readiness'),
    path('alive/', LivenessView.as_view(), name='liveness'),
    
    # Development dashboard
    path('metrics-dashboard/', MetricsDashboardView.as_view(), name='metrics-dashboard'),
]
```

## Usage

### Using Decorators

#### Monitor Performance
```python
from platform_core.monitoring import monitor_performance

@monitor_performance(
    name="process_order",
    labels={"queue": "high_priority"}
)
def process_order(order_id):
    # Function automatically tracked for:
    # - Execution time
    # - Call count
    # - Errors
    order = Order.objects.get(id=order_id)
    order.process()
    return order
```

#### Track Specific Metrics
```python
from platform_core.monitoring import track_metrics

@track_metrics(
    timer_name="payment_processing_time",
    counter_name="payments_processed",
    gauge_name="payment_amount"
)
def process_payment(amount):
    # Process payment
    charge_credit_card(amount)
    return amount  # Gauge will be set to this value
```

#### Error Tracking
```python
from platform_core.monitoring import track_errors

@track_errors(
    metric_name="external_api_errors",
    labels={"service": "payment_gateway"},
    reraise=True
)
def call_payment_api():
    # Errors are automatically tracked
    return payment_gateway.charge()
```

### Using Context Managers

```python
from platform_core.monitoring import MetricsContext

def batch_process_orders(orders):
    with MetricsContext("batch_processing") as ctx:
        for order in orders:
            try:
                process_order(order)
                ctx.increment("orders_processed")
                ctx.observe("order_value", order.total)
            except Exception as e:
                ctx.increment("orders_failed")
        
        ctx.gauge("batch_size", len(orders))
```

### Direct Metric Access

```python
from platform_core.monitoring import metrics_registry

# Get or create metrics
cpu_gauge = metrics_registry.gauge('custom_cpu_usage')
error_counter = metrics_registry.counter(
    'custom_errors',
    labels={'component': 'payment'}
)

# Update metrics
cpu_gauge.set(get_cpu_usage())
if error_occurred:
    error_counter.inc()
```

### Model Performance Tracking

```python
from platform_core.monitoring import monitor_model_operation

class Order(models.Model):
    @monitor_model_operation("save")
    def save(self, *args, **kwargs):
        # Save operations are automatically tracked
        super().save(*args, **kwargs)
    
    @monitor_model_operation("process")
    def process(self):
        # Custom model methods can be tracked
        self.status = 'processed'
        self.save()
```

## Collectors

### System Metrics Collector
Automatically collects:
- CPU usage percentage
- Memory usage (bytes and percentage)
- Disk usage percentage
- Network I/O (bytes sent/received per second)
- Disk I/O (read/write bytes per second)
- Process and thread counts

### Database Metrics Collector
Tracks:
- Query count and execution time
- Active database connections
- Transaction count
- Table-level statistics (inserts, updates, deletes)
- Database size

### Cache Metrics Collector
Monitors:
- Cache hits and misses
- Cache hit rate percentage
- Set and delete operations
- Eviction count

### API Metrics Collector
Records:
- Request count by method, endpoint, and status
- Request duration (with percentiles)
- Active request count
- Error rates by endpoint

### Business Metrics Collector
Tracks application-specific metrics:
- Total and active users
- Business entity counts (deals, leads, assessments)
- Revenue metrics
- Custom business KPIs

## Exporters

### Prometheus Exporter
Exports metrics in Prometheus text format:
```python
from platform_core.monitoring import PrometheusExporter

exporter = PrometheusExporter()
prometheus_text = exporter.generate_text()
```

### JSON Exporter
Exports metrics as JSON:
```python
from platform_core.monitoring import JSONExporter

exporter = JSONExporter(output_file='metrics.json')
exporter.export_all()
```

### CloudWatch Exporter
Sends metrics to AWS CloudWatch:
```python
from platform_core.monitoring import CloudWatchExporter

exporter = CloudWatchExporter(
    namespace='EnterpriseLand',
    region='us-east-1'
)
exporter.export_all()
```

### Datadog Exporter
Sends metrics to Datadog:
```python
from platform_core.monitoring import DatadogExporter

exporter = DatadogExporter(
    api_key='your-api-key',
    app_key='your-app-key'
)
exporter.export_all()
```

## Health Monitoring

### Health Checks
The system performs comprehensive health checks:

```python
from platform_core.monitoring import HealthMonitor

monitor = HealthMonitor()
health_status = monitor.run_health_checks()

# Returns:
{
    'status': 'healthy',  # or 'degraded', 'unhealthy', 'critical'
    'timestamp': '2024-01-20T10:30:00',
    'checks': {
        'database': {
            'status': 'healthy',
            'message': 'Database connection successful'
        },
        'cache': {
            'status': 'healthy',
            'message': 'Cache operations successful'
        },
        'disk': {
            'status': 'degraded',
            'message': 'High disk usage: 82%',
            'details': {'free_gb': 18.5}
        }
    }
}
```

### Kubernetes Integration

#### Readiness Probe
```yaml
readinessProbe:
  httpGet:
    path: /ready/
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
```

#### Liveness Probe
```yaml
livenessProbe:
  httpGet:
    path: /alive/
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
```

## Performance Monitoring

### Automatic Monitoring
Start the performance monitor to track system metrics:

```python
from platform_core.monitoring import PerformanceMonitor

monitor = PerformanceMonitor()
monitor.start()

# Get current status
status = monitor.get_status()
# {
#     'monitoring': True,
#     'metrics': {
#         'cpu_percent': 45.2,
#         'memory_percent': 62.8,
#         'response_time_ms': 234
#     },
#     'alerts': [
#         {
#             'metric': 'memory_percent',
#             'value': 62.8,
#             'threshold': 60,
#             'severity': 'warning'
#         }
#     ]
# }
```

### Custom Thresholds
```python
monitor.thresholds = {
    'cpu_percent': 90,  # Alert when CPU > 90%
    'memory_percent': 80,  # Alert when memory > 80%
    'response_time_ms': 500,  # Alert when response > 500ms
}
```

## Alerting

### Configure Alert Rules
```python
from platform_core.monitoring import AlertingMonitor

alerting = AlertingMonitor()

# Add alert rule
alerting.add_alert_rule({
    'name': 'high_error_rate',
    'condition': {
        'metric': 'error_rate_percent',
        'operator': '>',
        'threshold': 5
    },
    'severity': 'critical',
    'message': 'Error rate exceeds 5%'
})

# Add alert handler
def send_alert_email(alert):
    send_email(
        to='ops@example.com',
        subject=f"Alert: {alert['rule']}",
        body=alert['message']
    )

alerting.add_alert_handler(send_alert_email)
```

## Prometheus & Grafana Setup

### Prometheus Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'enterpriseland'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics/'
```

### Grafana Dashboard

Import the provided dashboard JSON or create custom dashboards:

1. **System Overview**
   - CPU, Memory, Disk usage
   - Network and Disk I/O
   - Process and thread counts

2. **Application Performance**
   - Request rate and duration
   - Error rates by endpoint
   - Response time percentiles
   - Active requests

3. **Business Metrics**
   - User activity
   - Entity counts and growth
   - Revenue tracking
   - Custom KPIs

## Best Practices

### 1. Metric Naming
Follow Prometheus naming conventions:
- Use lowercase with underscores
- Include unit suffix: `_seconds`, `_bytes`, `_total`
- Be descriptive: `http_request_duration_seconds`

### 2. Label Usage
- Keep cardinality low (< 100 unique values)
- Use consistent label names
- Avoid high-cardinality labels like user IDs

### 3. Performance Impact
- Metrics collection is lightweight (< 1% overhead)
- Use sampling for high-frequency operations
- Batch metric updates when possible

### 4. Monitoring Strategy
- Monitor user-facing metrics (response time, errors)
- Track resource usage (CPU, memory, disk)
- Include business KPIs
- Set realistic alerting thresholds

## Troubleshooting

### High Memory Usage
```python
# Check metric count
from platform_core.monitoring import metrics_registry
metric_count = len(metrics_registry.get_all_metrics())

# Reset if needed
metrics_registry.reset_all()
```

### Missing Metrics
1. Verify `METRICS_ENABLED = True`
2. Check middleware is installed
3. Ensure collectors are running
4. Verify no exceptions in metric collection

### Performance Impact
1. Reduce metric collection frequency
2. Disable unnecessary collectors
3. Use sampling for high-volume metrics
4. Optimize histogram bucket sizes

## Integration Examples

### Celery Task Monitoring
```python
from celery import Task
from platform_core.monitoring import monitor_performance

class MonitoredTask(Task):
    @monitor_performance(name="celery_task")
    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)

@app.task(base=MonitoredTask)
def process_data(data_id):
    # Task execution is automatically monitored
    return process(data_id)
```

### API View Monitoring
```python
from rest_framework.views import APIView
from platform_core.monitoring import monitor_performance

class UserAPIView(APIView):
    @monitor_performance(
        name="api_users_list",
        labels={"version": "v1"}
    )
    def get(self, request):
        users = User.objects.all()
        return Response(UserSerializer(users, many=True).data)
```

### Background Job Monitoring
```python
from platform_core.monitoring import MetricsContext

def nightly_batch_job():
    with MetricsContext("nightly_job") as ctx:
        users = User.objects.filter(active=True)
        ctx.gauge("total_users", users.count())
        
        for user in users:
            try:
                process_user(user)
                ctx.increment("users_processed")
            except Exception as e:
                ctx.increment("users_failed")
                logger.error(f"Failed to process user {user.id}: {e}")
```

---

*The performance monitoring system provides comprehensive observability for the EnterpriseLand platform, enabling proactive identification of issues and optimization opportunities through real-time metrics and intelligent alerting.*