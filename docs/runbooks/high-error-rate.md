# Runbook: High Error Rate

## Overview
This runbook provides procedures for responding to high error rate alerts in the EnterpriseLand platform.

## Prerequisites
- Access to production logs
- Admin access to monitoring dashboards
- SSH access to application servers
- PagerDuty account (for critical alerts)

## Detection
High error rate is detected when:
- HTTP 5xx errors exceed 5% of total requests
- Alert rule `HighErrorRate` triggers
- Users report widespread issues

## Impact
- **Business Impact**: Users unable to complete transactions
- **Technical Impact**: Degraded service performance
- **SLA Impact**: Potential SLA breach if > 30 minutes

## Resolution Steps

### 1. Initial Assessment (5 minutes)

```bash
# Check current error rate
curl http://localhost:9090/api/v1/query?query=rate(http_requests_total{status=~"5.."}[5m])

# Check application health
curl http://app-server:8000/health/

# View recent errors in logs
kubectl logs -l app=enterpriseland --tail=100 | grep ERROR
```

### 2. Identify Error Source

#### Check Application Logs
```bash
# SSH to application server
ssh user@app-server

# Check Django logs
tail -n 1000 /var/log/enterpriseland/django.log | grep -E "ERROR|CRITICAL"

# Check nginx logs
tail -n 1000 /var/log/nginx/error.log
```

#### Common Error Patterns
- **Database Connection Errors**: Check database health
- **Memory Errors**: Check application memory usage
- **Third-party API Errors**: Check external service status

### 3. Quick Fixes

#### A. Database Connection Pool Exhaustion
```python
# Temporarily increase connection pool
kubectl set env deployment/enterpriseland-app DB_CONN_MAX_AGE=600
kubectl rollout restart deployment/enterpriseland-app
```

#### B. Memory Issues
```bash
# Restart workers with memory issues
kubectl delete pod -l app=enterpriseland,component=worker

# Scale up if needed
kubectl scale deployment enterpriseland-app --replicas=10
```

#### C. Cache Issues
```bash
# Clear Redis cache
kubectl exec -it redis-master-0 -- redis-cli FLUSHDB

# Restart app to rebuild cache
kubectl rollout restart deployment/enterpriseland-app
```

### 4. Rollback if Needed

If errors started after recent deployment:

```bash
# Get deployment history
kubectl rollout history deployment/enterpriseland-app

# Rollback to previous version
kubectl rollout undo deployment/enterpriseland-app

# Monitor rollback
kubectl rollout status deployment/enterpriseland-app
```

### 5. Advanced Troubleshooting

#### Enable Debug Mode (Temporary)
```python
# Enable debug logging
kubectl set env deployment/enterpriseland-app DEBUG=True LOG_LEVEL=DEBUG

# Remember to disable after investigation
kubectl set env deployment/enterpriseland-app DEBUG=False LOG_LEVEL=INFO
```

#### Check Specific Endpoints
```python
# Use the profiling tools
python manage.py shell
>>> from platform_core.performance.profiling import profiler
>>> profiler.get_profile_stats()
```

## Verification

### 1. Confirm Error Rate Reduction
```bash
# Check error rate is below threshold
curl http://localhost:9090/api/v1/query?query=rate(http_requests_total{status=~"5.."}[5m])

# Verify in Grafana dashboard
# Navigate to: http://grafana.local/d/app-errors
```

### 2. Health Check
```bash
# Run comprehensive health check
curl http://app-server:8000/health/

# Check readiness
curl http://app-server:8000/health/ready/
```

### 3. User Verification
- Check user reports/tickets
- Monitor social media for complaints
- Verify key user journeys work

## Post-Incident

### 1. Immediate Actions
- [ ] Update incident status in PagerDuty
- [ ] Notify stakeholders of resolution
- [ ] Document timeline in incident ticket

### 2. Within 24 Hours
- [ ] Conduct incident review meeting
- [ ] Create JIRA tickets for identified issues
- [ ] Update monitoring thresholds if needed

### 3. Within 1 Week
- [ ] Complete post-mortem document
- [ ] Implement preventive measures
- [ ] Update this runbook with lessons learned

## Alert Silencing

If maintenance is causing expected errors:

```python
# Create alert silence via API
curl -X POST http://app-server:8000/api/alerts/silences/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Maintenance Window",
    "matchers": {"alertname": "HighErrorRate"},
    "duration_hours": 2
  }'
```

## Escalation

- **L1 Support**: Follow steps 1-3
- **L2 Support**: Steps 4-5 and rollback decisions
- **Engineering**: Advanced troubleshooting
- **Management**: If downtime > 30 minutes

## Related Runbooks
- [Database Issues](./database-issues.md)
- [Performance Degradation](./performance-degradation.md)
- [Service Outage](./service-outage.md)

## References
- [Error Budget Policy](../policies/error-budget.md)
- [Monitoring Dashboard](http://grafana.local/d/app-overview)
- [Architecture Diagram](../architecture/system-overview.md)