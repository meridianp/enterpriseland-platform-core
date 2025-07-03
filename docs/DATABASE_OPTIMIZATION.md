# Database Query Optimization

## Overview

The EnterpriseLand platform includes comprehensive database optimization tools for analyzing query performance, managing indexes, monitoring connections, and creating optimized migrations. This module provides real-time monitoring, automatic optimization suggestions, and tools for maintaining optimal database performance at scale.

## Features

### 1. Query Plan Analysis

#### Automatic Query Analysis
```python
from platform_core.database import QueryPlanAnalyzer

analyzer = QueryPlanAnalyzer()

# Analyze a specific query
query = "SELECT * FROM users WHERE status = 'active' ORDER BY created_date DESC"
analysis = analyzer.analyze_query(query)

# Results include:
# - Execution time and planning time
# - Detected issues (sequential scans, nested loops)
# - Optimization suggestions
# - Full execution plan details
```

#### Pattern Detection
The analyzer automatically detects common performance issues:
- Sequential scans on large tables
- High-cost nested loop joins
- Missing indexes on filtered/joined columns
- Expensive sort operations

### 2. Index Analysis and Management

#### Missing Index Detection
```python
from platform_core.database import IndexAnalyzer

analyzer = IndexAnalyzer()

# Find missing indexes across database
missing_indexes = analyzer.analyze_missing_indexes()
# Returns suggestions for:
# - Tables with high sequential scan activity
# - Foreign keys without indexes
# - Frequently filtered columns

# Suggest composite indexes for a model
from myapp.models import MyModel
suggestions = analyzer.suggest_composite_indexes(MyModel)
```

#### Index Usage Analysis
```python
# Analyze current index usage
usage_stats = analyzer.analyze_index_usage()
# Returns:
# - Total index count
# - Unused indexes (never scanned)
# - Inefficient indexes (low selectivity)
# - Duplicate/redundant indexes
```

### 3. Database Performance Monitoring

#### Real-time Query Monitoring
```python
from platform_core.database import database_monitor

# Get current monitoring dashboard
dashboard = database_monitor.get_dashboard_data()
# Includes:
# - Recent slow queries with patterns
# - Connection pool statistics
# - Health score and alerts
# - Performance trends

# Export metrics for Prometheus
metrics = database_monitor.export_metrics(format='prometheus')
```

#### Slow Query Logging
Automatic logging of queries exceeding threshold:
```python
# Configure in settings.py
SLOW_QUERY_THRESHOLD = 100  # milliseconds

# Queries are automatically logged and analyzed
# Access via monitor dashboard or management command
```

#### Connection Pool Monitoring
```python
from platform_core.database import ConnectionMonitor

monitor = ConnectionMonitor()

# Get current connection stats
stats = monitor.get_current_stats()
# Shows active, idle, and idle-in-transaction connections

# Get historical data
history = monitor.get_connection_history(minutes=60)
```

### 4. Comprehensive Database Optimization

#### Run Full Optimization Analysis
```python
from platform_core.database import DatabaseOptimizer

optimizer = DatabaseOptimizer()

# Run comprehensive analysis
results = optimizer.run_optimization_analysis()
# Analyzes:
# - Slow queries
# - Missing indexes
# - Index usage
# - Table statistics
# - Connection pool health

# Optimize specific model
from myapp.models import MyModel
model_results = optimizer.optimize_model_queries(MyModel)
```

#### Connection Pool Optimization
```python
from platform_core.database import ConnectionPoolManager

manager = ConnectionPoolManager()

# Get optimization recommendations
recommendations = manager.optimize_pool_settings()
# Suggests optimal settings for:
# - max_connections
# - pool timeout
# - connection recycling
```

### 5. Optimized Migrations

#### Create Performance-Aware Migrations
```python
from platform_core.database.migrations import OptimizedMigrationExecutor

executor = OptimizedMigrationExecutor()

# Create optimized migration
migration = executor.create_optimized_migration(
    operations=[...],
    dependencies=[...],
    app_label='myapp',
    migration_name='0001_initial'
)
# Automatically:
# - Orders operations by dependencies
# - Batches similar operations
# - Adds performance hints
# - Defers index creation
```

#### Generate Index Migrations
```python
from platform_core.database.migrations import IndexMigrationGenerator

generator = IndexMigrationGenerator()

# Generate migration for suggested indexes
migration = generator.generate_index_migration(
    MyModel,
    index_suggestions
)
# Creates migration with:
# - Concurrent index creation for large tables
# - Proper naming conventions
# - Rollback support
```

## Management Commands

### optimize_database

Comprehensive database optimization command:

```bash
# Run analysis only
python manage.py optimize_database --analyze

# Analyze specific model
python manage.py optimize_database --analyze --model=myapp.MyModel

# Apply optimizations (vacuum, analyze)
python manage.py optimize_database --optimize

# Create suggested indexes
python manage.py optimize_database --create-indexes

# Monitor current performance
python manage.py optimize_database --monitor

# Export metrics
python manage.py optimize_database --monitor --export=prometheus --output=metrics.txt

# Full analysis with output file
python manage.py optimize_database --analyze --output=analysis.json
```

## Configuration

### Django Settings

```python
# Database optimization settings
SLOW_QUERY_THRESHOLD = 100  # milliseconds

# Connection pool settings
DB_POOL_MAX_CONNECTIONS = 100
DB_POOL_MIN_CONNECTIONS = 10
DB_POOL_MAX_OVERFLOW = 20
DB_POOL_TIMEOUT = 30
DB_POOL_RECYCLE = 3600

# Enable query logging
ENABLE_QUERY_LOGGING = True

# Monitoring settings
DB_MONITOR_INTERVAL = 30  # seconds
DB_MONITOR_HISTORY_SIZE = 1000
```

### Middleware Configuration

```python
# Add to MIDDLEWARE for automatic query logging
MIDDLEWARE = [
    # ... other middleware
    'platform_core.database.middleware.QueryLoggingMiddleware',
]
```

## Usage Examples

### 1. Daily Performance Check

```python
# Run as scheduled task
from platform_core.database import database_monitor

def daily_db_check():
    # Get performance report
    report = database_monitor.create_monitoring_report()
    
    # Check health score
    if report['summary']['health_score']['score'] < 70:
        # Send alert
        send_alert("Database health degraded", report)
    
    # Apply automatic optimizations
    for recommendation in report['recommendations']:
        if 'VACUUM' in recommendation:
            execute_vacuum_command()
```

### 2. Pre-deployment Optimization

```python
# Check query performance before deployment
def pre_deploy_check():
    optimizer = DatabaseOptimizer()
    
    # Analyze all models
    issues = []
    for model in apps.get_models():
        results = optimizer.optimize_model_queries(model)
        if results['optimizations']:
            issues.extend(results['optimizations'])
    
    if issues:
        raise DeploymentError(f"Found {len(issues)} query issues")
```

### 3. Continuous Monitoring Integration

```python
# Integrate with monitoring systems
from platform_core.database import database_monitor

# Add callback for metric events
def send_to_monitoring(metric_type, data):
    if metric_type == 'slow_query':
        statsd.increment('db.slow_queries')
    elif metric_type == 'connection_leak':
        statsd.gauge('db.connection_leaks', data['count'])

database_monitor.add_metric_callback(send_to_monitoring)
```

### 4. Migration Optimization Workflow

```python
# Before creating migration
from platform_core.database.migrations import MigrationOptimizationAdvisor

def create_safe_migration(operations):
    # Analyze for issues
    migration = Migration('temp', operations=operations)
    advice = MigrationOptimizationAdvisor.analyze_migration(migration)
    
    if advice['warnings']:
        print("Migration warnings:")
        for warning in advice['warnings']:
            print(f"  - {warning}")
        
        if not confirm("Proceed anyway?"):
            return
    
    # Create optimized version
    executor = OptimizedMigrationExecutor()
    return executor.create_optimized_migration(operations, ...)
```

## Best Practices

### 1. Regular Monitoring
- Run `optimize_database --monitor` daily
- Set up alerts for health score < 70
- Review slow query patterns weekly
- Check for unused indexes monthly

### 2. Query Optimization
- Always use `select_related()` and `prefetch_related()`
- Add indexes on foreign keys
- Create composite indexes for common filter combinations
- Use database views for complex queries

### 3. Index Management
- Create indexes during low-traffic periods
- Use `CREATE INDEX CONCURRENTLY` for production
- Regularly remove unused indexes
- Monitor index bloat

### 4. Connection Pool Tuning
- Set max_connections based on expected load
- Monitor for idle-in-transaction connections
- Use connection pooling middleware
- Set appropriate timeouts

### 5. Migration Best Practices
- Test migrations on production data copy
- Use concurrent operations for large tables
- Add nullable fields in two steps
- Create indexes after data population

## Troubleshooting

### High Query Times
1. Check execution plan: `optimize_database --analyze`
2. Look for sequential scans
3. Add suggested indexes
4. Consider query rewrite

### Connection Exhaustion
1. Check current connections: `optimize_database --monitor`
2. Look for connection leaks
3. Increase pool size if needed
4. Add connection timeout

### Migration Failures
1. Check migration advice before applying
2. Use `--fake` for metadata-only changes
3. Apply in maintenance window
4. Have rollback plan ready

### Index Bloat
1. Check index usage statistics
2. Rebuild bloated indexes
3. Consider partial indexes
4. Regular VACUUM ANALYZE

## Performance Benchmarks

Expected performance after optimization:
- Query response time: < 100ms for 95th percentile
- Index usage: > 80% queries use indexes
- Connection pool efficiency: < 10% idle connections
- Health score: > 85

## Integration with CI/CD

### Pre-commit Hooks
```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: check-db-queries
      name: Check Database Queries
      entry: python manage.py optimize_database --analyze --model=
      language: system
      files: 'models\.py$'
```

### CI Pipeline
```yaml
# .github/workflows/db-optimization.yml
- name: Run Database Analysis
  run: |
    python manage.py optimize_database --analyze --output=db-analysis.json
    python scripts/check_db_health.py db-analysis.json
```

### Deployment Checklist
1. Run optimization analysis
2. Apply recommended indexes
3. Update connection pool settings
4. Warm caches
5. Monitor post-deployment

---

*The database optimization module ensures your application maintains peak performance as it scales. Regular monitoring and proactive optimization prevent performance degradation and provide insights for capacity planning.*