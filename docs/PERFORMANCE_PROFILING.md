# Performance Profiling and Monitoring

## Overview

The EnterpriseLand platform includes comprehensive performance profiling and monitoring tools to ensure optimal application performance. This module provides real-time insights, automatic optimization suggestions, and proactive performance management.

## Features

### 1. Performance Profiling

#### Automatic Request Profiling
```python
# In settings.py
MIDDLEWARE = [
    # ... other middleware
    'platform_core.performance.ProfilerMiddleware',
]

ENABLE_PROFILING = True  # Enable/disable profiling
PROFILER_EXCLUDED_PATHS = ['/static/', '/media/', '/health/']
SLOW_QUERY_THRESHOLD = 100  # milliseconds
```

The middleware automatically profiles:
- Request duration
- Database queries
- Cache operations
- Memory usage

#### View Profiling
```python
from platform_core.performance import profile_view

@profile_view
def my_view(request):
    # View logic
    return render(request, 'template.html')
```

#### Method Profiling
```python
from platform_core.performance import profile_method

class MyService:
    @profile_method("process_data")
    def process(self, data):
        # Method logic
        return processed_data
```

### 2. Metrics Collection

#### Prometheus Integration
```python
# urls.py
from platform_core.performance.monitoring import metrics_view, health_check_view

urlpatterns = [
    path('metrics/', metrics_view, name='prometheus-metrics'),
    path('health/', health_check_view, name='health-check'),
]
```

Available metrics:
- Request count and latency
- Database query count and duration
- Cache hit/miss rates
- System resources (CPU, memory, disk)
- WebSocket connections
- Celery task metrics

#### Manual Metrics Collection
```python
from platform_core.performance import metrics_collector

# Collect custom metrics
metrics_collector.collect_request_metrics('GET', '/api/users/', 200, 0.150)
metrics_collector.collect_query_metrics('SELECT * FROM users', 25.0)
metrics_collector.collect_cache_metrics('get', hit=True)
metrics_collector.collect_celery_metrics('send_email', 'success', 1.5)
```

### 3. Performance Monitoring

#### Health Checks
```python
from platform_core.performance import performance_monitor

# Check system health
health = performance_monitor.check_health()
# Returns:
# {
#     'status': 'healthy',  # or 'degraded', 'unhealthy'
#     'checks': {
#         'response_time': {'status': 'ok', 'value': 150, 'threshold': 1000},
#         'error_rate': {'status': 'ok', 'value': 0.01, 'threshold': 0.05},
#         'cpu_usage': {'status': 'ok', 'value': 45, 'threshold': 80},
#         'memory_usage': {'status': 'warning', 'value': 85, 'threshold': 90}
#     }
# }
```

#### Performance Reports
```python
# Generate comprehensive performance report
report = performance_monitor.get_performance_report()
# Returns:
# {
#     'summary': {
#         'requests_per_second': 125.5,
#         'average_response_time': 185.3,
#         'error_rate': 0.8,
#         'cache_hit_rate': 82.5
#     },
#     'recommendations': [
#         'High average response time detected...',
#         'Low cache hit rate...'
#     ]
# }
```

### 4. Query Optimization

#### Automatic Query Optimization
```python
from platform_core.performance import QueryOptimizer

optimizer = QueryOptimizer()

# Optimize queryset
queryset = MyModel.objects.all()
optimized = optimizer.optimize_queryset(queryset)
# Automatically adds select_related() and prefetch_related()

# Analyze slow queries
slow_queries = optimizer.analyze_slow_queries(threshold_ms=100)

# Get index suggestions
suggestions = optimizer.suggest_indexes(MyModel)
```

#### Query Analysis
```python
from platform_core.performance import query_analyzer

# Analyze query patterns
analysis = query_analyzer.analyze_queries(recent_queries)
# Detects:
# - N+1 query patterns
# - Duplicate queries
# - Missing indexes
# - Inefficient filters
```

### 5. Cache Optimization

#### Cache Warming
```python
from platform_core.performance import CacheWarmer

warmer = CacheWarmer()

# Register warming strategy
def warm_user_cache():
    users = User.objects.filter(is_active=True).select_related('profile')
    cache.set('active_users', list(users), 3600)
    return ['active_users']

warmer.register_warming_strategy('users', warm_user_cache)

# Warm cache
results = warmer.warm_cache()  # Warms all registered patterns
# or
results = warmer.warm_cache('users')  # Warm specific pattern
```

#### Automatic Cache Warming
```python
# Warm querysets
warmed_keys = warmer.warm_queryset_cache(
    MyModel,
    filters={'status': 'active'}
)

# Warm aggregations
warmed_keys = warmer.warm_aggregation_cache(MyModel)
```

### 6. Performance Optimization

#### Run Full Optimization Suite
```python
from platform_core.performance import performance_optimizer

# Run comprehensive optimization
results = performance_optimizer.run_optimization_suite()
# Performs:
# - Slow query analysis
# - Index suggestions
# - Cache warming
# - Query pattern analysis
# - Generates recommendations
```

#### Model-Specific Optimization
```python
# Optimize specific model
results = performance_optimizer.optimize_model_queries(MyModel)
# Measures and optimizes common query patterns
```

## Management Commands

### analyze_performance

Comprehensive performance analysis command:

```bash
# Full analysis
python manage.py analyze_performance

# Query analysis only
python manage.py analyze_performance --type=queries --threshold=50

# Health check
python manage.py analyze_performance --type=health

# Cache analysis
python manage.py analyze_performance --type=cache

# Run optimization
python manage.py analyze_performance --type=optimize

# Model-specific analysis
python manage.py analyze_performance --model=myapp.MyModel

# Generate index SQL
python manage.py analyze_performance --type=queries --apply-indexes

# Output to file
python manage.py analyze_performance --output=performance_report.json
```

## Configuration

### Django Settings

```python
# Enable/disable performance features
ENABLE_PROFILING = True
ENABLE_METRICS = True

# Profiling settings
PROFILER_EXCLUDED_PATHS = ['/static/', '/media/', '/health/']
SLOW_QUERY_THRESHOLD = 100  # milliseconds

# Monitoring thresholds
PERFORMANCE_THRESHOLDS = {
    'response_time': 1000,  # ms
    'error_rate': 0.05,     # 5%
    'cpu_usage': 80,        # %
    'memory_usage': 90,     # %
    'cache_hit_rate': 70    # %
}

# Cache warming schedule (use with Celery beat)
CACHE_WARMING_SCHEDULE = {
    'warm-all-caches': {
        'task': 'platform_core.tasks.warm_caches',
        'schedule': crontab(minute=0),  # Every hour
    },
}
```

## Best Practices

### 1. Profile in Development
- Enable `DEBUG = True` for detailed profiling
- Use Django Debug Toolbar alongside
- Review slow query logs regularly

### 2. Monitor in Production
- Set up Prometheus + Grafana dashboards
- Configure alerts for threshold breaches
- Use sampling for high-traffic endpoints

### 3. Optimize Queries
- Run `analyze_performance --type=queries` weekly
- Apply suggested indexes after testing
- Use `select_related()` and `prefetch_related()`

### 4. Cache Strategy
- Warm critical caches on deployment
- Monitor cache hit rates
- Use tag-based invalidation

### 5. Regular Health Checks
- Integrate health endpoint with monitoring
- Set up automated alerts
- Review performance reports weekly

## Integration with Other Systems

### Prometheus/Grafana

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'django'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics/'
```

### Celery Integration

```python
# tasks.py
from platform_core.performance import metrics_collector

@app.task(bind=True)
def my_task(self):
    start_time = time.time()
    
    try:
        # Task logic
        result = process_data()
        
        # Collect metrics
        duration = time.time() - start_time
        metrics_collector.collect_celery_metrics(
            self.name, 'success', duration
        )
        
        return result
        
    except Exception as e:
        metrics_collector.collect_celery_metrics(
            self.name, 'failure'
        )
        raise
```

### Custom Dashboards

Create custom monitoring dashboards:

```python
# views.py
from platform_core.performance import performance_monitor

def performance_dashboard(request):
    context = {
        'health': performance_monitor.check_health(),
        'report': performance_monitor.get_performance_report(),
        'metrics': performance_monitor.collector.get_aggregated_metrics('1h')
    }
    return render(request, 'dashboard.html', context)
```

## Troubleshooting

### High Memory Usage
1. Check for query result caching of large datasets
2. Review profiler data retention settings
3. Ensure cache entries have appropriate TTLs

### Slow Queries Not Detected
1. Verify `SLOW_QUERY_THRESHOLD` setting
2. Check that profiling is enabled
3. Ensure database has query logging enabled

### Metrics Not Collected
1. Verify Prometheus client is installed
2. Check that metrics endpoint is accessible
3. Review metric collection settings

## Performance Optimization Workflow

1. **Profile**: Enable profiling to identify bottlenecks
2. **Analyze**: Use management command to analyze patterns
3. **Optimize**: Apply suggested optimizations
4. **Monitor**: Track improvements with metrics
5. **Iterate**: Continuously refine based on data

---

*The performance profiling module provides comprehensive tools for maintaining optimal application performance. Regular monitoring and optimization ensure the platform scales efficiently while maintaining responsiveness.*