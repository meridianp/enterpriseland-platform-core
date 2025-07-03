# Runbook: Performance Degradation

## Overview
This runbook provides procedures for diagnosing and resolving performance degradation issues in the EnterpriseLand platform.

## Prerequisites
- Access to performance monitoring tools
- Admin access to application servers
- Knowledge of profiling tools
- Access to CDN and cache management

## Detection
Performance issues are detected through:
- Response time p95 > 1 second alerts
- User complaints about slow loading
- High CPU/Memory usage alerts
- Cache hit rate < 80%

## Impact
- **User Experience**: Slow page loads, timeouts
- **Business Impact**: Reduced conversion rates
- **System Impact**: Cascading failures possible

## Resolution Steps

### 1. Quick Performance Assessment

```bash
# Check current response times
curl -w "@curl-format.txt" -o /dev/null -s http://app-server:8000/api/health/

# Where curl-format.txt contains:
# time_namelookup:  %{time_namelookup}\n
# time_connect:  %{time_connect}\n
# time_appconnect:  %{time_appconnect}\n
# time_pretransfer:  %{time_pretransfer}\n
# time_redirect:  %{time_redirect}\n
# time_starttransfer:  %{time_starttransfer}\n
# time_total:  %{time_total}\n

# Check system resources
kubectl top nodes
kubectl top pods -l app=enterpriseland
```

### 2. Identify Bottlenecks

#### A. Application Performance

**Check slow endpoints**:
```python
# Get performance metrics
kubectl exec -it deployment/enterpriseland-app -- python manage.py shell
>>> from platform_core.performance.profiling import profiler
>>> # Get slowest endpoints
>>> stats = profiler.get_profile_stats()
>>> for endpoint, data in sorted(stats.items(), key=lambda x: x[1]['avg_time'], reverse=True)[:10]:
...     print(f"{endpoint}: {data['avg_time']:.2f}s")
```

**Enable profiling for specific endpoint**:
```python
# Temporarily enable detailed profiling
kubectl set env deployment/enterpriseland-app PROFILING_ENABLED=True PROFILING_SAMPLE_RATE=1.0

# After collecting data, disable
kubectl set env deployment/enterpriseland-app PROFILING_ENABLED=False
```

#### B. Database Performance

```sql
-- Check slow queries
SELECT query, mean_exec_time, calls, total_exec_time
FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC
LIMIT 20;

-- Check table statistics
SELECT schemaname, tablename, last_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE last_analyze < now() - interval '7 days'
   OR last_autoanalyze < now() - interval '7 days';
```

#### C. Cache Performance

```bash
# Check Redis performance
kubectl exec -it redis-master-0 -- redis-cli INFO stats

# Check cache hit rate
kubectl exec -it redis-master-0 -- redis-cli INFO stats | grep keyspace_hits
kubectl exec -it redis-master-0 -- redis-cli INFO stats | grep keyspace_misses

# Monitor Redis slowlog
kubectl exec -it redis-master-0 -- redis-cli SLOWLOG GET 10
```

### 3. Quick Remediation

#### A. Clear Problematic Caches
```bash
# Clear specific cache pattern
kubectl exec -it redis-master-0 -- redis-cli --scan --pattern "cache:slow:*" | xargs redis-cli DEL

# Clear all caches (warning: causes temporary performance hit)
kubectl exec -it redis-master-0 -- redis-cli FLUSHDB
```

#### B. Scale Resources
```bash
# Scale up application pods
kubectl scale deployment enterpriseland-app --replicas=20

# Add more workers
kubectl scale deployment enterpriseland-worker --replicas=10

# Increase resource limits
kubectl set resources deployment enterpriseland-app -c=app --limits=cpu=2000m,memory=4Gi
```

#### C. Optimize Database Queries
```python
# Add database query optimization
kubectl exec -it deployment/enterpriseland-app -- python manage.py shell
>>> from platform_core.database.optimization import auto_optimize_queries
>>> auto_optimize_queries()  # Creates missing indexes
```

### 4. CDN and Static Asset Optimization

```bash
# Purge CDN cache for specific paths
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache" \
     -H "Authorization: Bearer ${CF_API_TOKEN}" \
     -H "Content-Type: application/json" \
     --data '{"prefixes":["https://app.enterpriseland.com/static/"]}'

# Enable CDN compression
kubectl set env deployment/enterpriseland-app CDN_COMPRESSION_ENABLED=True
```

### 5. Advanced Performance Tuning

#### A. Database Connection Pooling
```python
# Adjust connection pool settings
kubectl set env deployment/enterpriseland-app \
  DB_CONN_MAX_AGE=600 \
  DB_POOL_SIZE=50 \
  DB_MAX_OVERFLOW=100
```

#### B. Application Memory Optimization
```python
# Enable memory profiling
kubectl exec -it deployment/enterpriseland-app -- python manage.py shell
>>> from platform_core.performance.profiling import memory_profile
>>> memory_profile.start_monitoring()
>>> # Wait for data collection
>>> memory_profile.get_memory_report()
```

#### C. Async Task Optimization
```bash
# Check Celery queue sizes
kubectl exec -it deployment/enterpriseland-app -- celery -A platform_core inspect active_queues

# Purge problematic queues
kubectl exec -it deployment/enterpriseland-app -- celery -A platform_core purge -f

# Increase worker concurrency
kubectl set env deployment/enterpriseland-worker CELERY_WORKER_CONCURRENCY=20
```

## Verification

### 1. Performance Metrics
```bash
# Check response times improved
for i in {1..10}; do
  curl -w "Response time: %{time_total}s\n" -o /dev/null -s http://app-server:8000/api/health/
  sleep 1
done

# Verify in monitoring
# Check Grafana dashboard: http://grafana.local/d/performance
```

### 2. Resource Utilization
```bash
# Confirm CPU/Memory usage is normal
kubectl top pods -l app=enterpriseland
kubectl top nodes

# Check database connections
kubectl exec -it postgres-0 -- psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
```

### 3. User Experience
```bash
# Run synthetic tests
python scripts/performance_test.py --endpoint=/api/leads/ --concurrent=10

# Check real user metrics in monitoring
```

## Performance Optimization Checklist

### Immediate Actions
- [ ] Enable caching headers
- [ ] Compress responses
- [ ] Optimize images
- [ ] Enable HTTP/2

### Database Optimizations
- [ ] Add missing indexes
- [ ] Update table statistics
- [ ] Optimize slow queries
- [ ] Enable query caching

### Application Optimizations
- [ ] Use select_related/prefetch_related
- [ ] Implement pagination
- [ ] Cache expensive computations
- [ ] Optimize serializers

### Infrastructure
- [ ] Scale horizontally
- [ ] Upgrade instance types
- [ ] Optimize load balancer
- [ ] Enable CDN

## Post-Incident

### 1. Immediate Actions
- [ ] Document performance bottlenecks
- [ ] Create tickets for optimizations
- [ ] Update monitoring thresholds

### 2. Within 24 Hours
- [ ] Review profiling data
- [ ] Plan optimization sprint
- [ ] Update capacity planning

### 3. Long-term Improvements
- [ ] Implement performance budget
- [ ] Add performance tests to CI/CD
- [ ] Regular performance reviews

## Common Performance Issues

### 1. N+1 Queries
```python
# Detect in Django
# Look for multiple similar queries in logs

# Fix with select_related
Model.objects.select_related('related_field').all()

# Fix with prefetch_related
Model.objects.prefetch_related('many_to_many_field').all()
```

### 2. Large Payload Sizes
```python
# Check response sizes
# Look for responses > 1MB

# Fix with pagination
class LargeViewSet(ModelViewSet):
    pagination_class = LimitOffsetPagination
    page_size = 50
```

### 3. Synchronous External Calls
```python
# Move to async tasks
from celery import shared_task

@shared_task
def call_external_api():
    # Long running API call
    pass
```

## Tools and Commands

### Performance Testing
```bash
# Load testing with locust
locust -f tests/load_test.py --host=http://app-server:8000

# API performance testing
ab -n 1000 -c 50 http://app-server:8000/api/health/
```

### Profiling
```bash
# CPU profiling
py-spy record -o profile.svg -- python manage.py runserver

# Memory profiling
mprof run python manage.py runserver
mprof plot
```

## Escalation

- **DevOps**: Infrastructure scaling
- **Database Team**: Query optimization
- **Development**: Code optimization
- **Architecture**: System design changes

## Related Runbooks
- [Database Issues](./database-issues.md)
- [High Error Rate](./high-error-rate.md)
- [Scaling Operations](./scaling-operations.md)

## References
- [Performance Monitoring Guide](../monitoring/performance.md)
- [Caching Strategy](../architecture/caching.md)
- [Database Optimization](../database/optimization.md)