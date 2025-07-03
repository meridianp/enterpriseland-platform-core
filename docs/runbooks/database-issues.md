# Runbook: Database Issues

## Overview
This runbook covers procedures for diagnosing and resolving database-related issues in the EnterpriseLand platform.

## Prerequisites
- PostgreSQL admin credentials
- Access to database monitoring tools
- SSH access to database servers
- Knowledge of PostgreSQL commands

## Detection
Database issues are indicated by:
- `DatabaseHealthCheck` alerts
- Slow query alerts
- Connection pool exhaustion
- Application timeouts with database errors

## Impact
- **Business Impact**: Complete service unavailability
- **Data Impact**: Potential data inconsistency
- **Performance Impact**: Severe degradation across all services

## Resolution Steps

### 1. Initial Database Health Check

```bash
# Check database connectivity
psql -h db-server -U postgres -d enterpriseland -c "SELECT 1;"

# Check database status
kubectl exec -it postgres-0 -- pg_isready

# View current connections
psql -h db-server -U postgres -d enterpriseland -c "
SELECT count(*) as total_connections,
       state,
       wait_event_type,
       wait_event
FROM pg_stat_activity
GROUP BY state, wait_event_type, wait_event
ORDER BY count(*) DESC;"
```

### 2. Common Issues and Solutions

#### A. Connection Pool Exhaustion

**Symptoms**: "too many connections" errors

```sql
-- Check current connections
SELECT count(*) FROM pg_stat_activity;

-- View connections by application
SELECT application_name, count(*) 
FROM pg_stat_activity 
GROUP BY application_name 
ORDER BY count(*) DESC;

-- Kill idle connections older than 5 minutes
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE state = 'idle' 
  AND state_change < now() - interval '5 minutes';
```

**Fix**:
```bash
# Increase connection limit temporarily
kubectl exec -it postgres-0 -- psql -U postgres -c "ALTER SYSTEM SET max_connections = 500;"
kubectl exec -it postgres-0 -- psql -U postgres -c "SELECT pg_reload_conf();"

# Restart application to reset connections
kubectl rollout restart deployment/enterpriseland-app
```

#### B. Slow Queries

**Identify slow queries**:
```sql
-- Current running queries over 30 seconds
SELECT pid, 
       now() - pg_stat_activity.query_start AS duration,
       query,
       state
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '30 seconds'
  AND state != 'idle'
ORDER BY duration DESC;

-- Kill specific slow query
SELECT pg_cancel_backend(PID_HERE);
-- Or force kill if cancel doesn't work
SELECT pg_terminate_backend(PID_HERE);
```

**Analyze query performance**:
```sql
-- Enable query timing
SET log_min_duration_statement = 1000; -- Log queries over 1 second

-- Check for missing indexes
SELECT schemaname, tablename, 
       n_live_tup, n_dead_tup, 
       last_vacuum, last_autovacuum
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;
```

#### C. Lock Contention

**Check for locks**:
```sql
-- View blocking locks
SELECT blocked_locks.pid AS blocked_pid,
       blocked_activity.usename AS blocked_user,
       blocking_locks.pid AS blocking_pid,
       blocking_activity.usename AS blocking_user,
       blocked_activity.query AS blocked_statement,
       blocking_activity.query AS current_statement_in_blocking_process
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

### 3. Database Maintenance

#### Emergency VACUUM
```sql
-- Check table bloat
SELECT schemaname, tablename, 
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
       n_dead_tup
FROM pg_stat_user_tables
WHERE n_dead_tup > 10000
ORDER BY n_dead_tup DESC;

-- Run vacuum on specific table
VACUUM ANALYZE schema.tablename;

-- Or full vacuum (locks table!)
VACUUM FULL schema.tablename;
```

#### Reindex Critical Tables
```sql
-- Check index bloat
SELECT schemaname, tablename, indexname,
       pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 20;

-- Reindex (brief lock)
REINDEX INDEX CONCURRENTLY index_name;
```

### 4. Emergency Recovery Procedures

#### A. Restart Database (Last Resort)
```bash
# Graceful restart
kubectl exec -it postgres-0 -- su postgres -c "pg_ctl restart -D /var/lib/postgresql/data"

# Force restart if graceful fails
kubectl delete pod postgres-0

# Monitor restart
kubectl logs -f postgres-0
```

#### B. Failover to Replica
```bash
# Promote replica to primary
kubectl exec -it postgres-replica-0 -- su postgres -c "pg_ctl promote -D /var/lib/postgresql/data"

# Update application connection string
kubectl set env deployment/enterpriseland-app DATABASE_URL="postgresql://user:pass@postgres-replica-0:5432/enterpriseland"
```

## Verification

### 1. Database Health
```sql
-- Check database is accepting connections
SELECT version();

-- Verify replication lag (if using replicas)
SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
       sent_lsn - replay_lsn as lag_bytes
FROM pg_stat_replication;

-- Check critical tables
SELECT count(*) FROM django_migrations;
SELECT count(*) FROM auth_user;
```

### 2. Application Verification
```bash
# Test application database connectivity
curl http://app-server:8000/health/check/database/

# Run Django database check
kubectl exec -it deployment/enterpriseland-app -- python manage.py dbshell -c "SELECT 1;"
```

## Post-Incident

### 1. Immediate Actions
- [ ] Verify data integrity
- [ ] Check for data loss
- [ ] Review slow query log

### 2. Within 24 Hours
- [ ] Analyze root cause
- [ ] Plan index optimizations
- [ ] Review connection pool settings

### 3. Preventive Measures
- [ ] Implement query timeout limits
- [ ] Add missing indexes
- [ ] Schedule regular VACUUM
- [ ] Set up automated failover

## Performance Tuning Commands

```sql
-- Update table statistics
ANALYZE;

-- Show current settings
SHOW shared_buffers;
SHOW effective_cache_size;
SHOW work_mem;
SHOW max_connections;

-- Temporary performance boost
SET work_mem = '256MB';
SET maintenance_work_mem = '1GB';
```

## Monitoring Queries

```sql
-- Database size
SELECT pg_database.datname,
       pg_size_pretty(pg_database_size(pg_database.datname)) AS size
FROM pg_database
ORDER BY pg_database_size(pg_database.datname) DESC;

-- Table sizes
SELECT schemaname, tablename,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
       pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS data_size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 20;
```

## Escalation

- **DBA Team**: For complex query optimization
- **Infrastructure**: For hardware/resource issues
- **Engineering**: For application-level fixes
- **Vendor Support**: For PostgreSQL bugs

## Related Runbooks
- [High Error Rate](./high-error-rate.md)
- [Performance Degradation](./performance-degradation.md)
- [Disaster Recovery](./disaster-recovery.md)

## References
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Database Monitoring Dashboard](http://grafana.local/d/postgres)
- [Connection Pool Configuration](../configuration/database.md)