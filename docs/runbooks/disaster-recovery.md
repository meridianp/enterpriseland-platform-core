# Runbook: Disaster Recovery

## Overview
This runbook provides comprehensive procedures for recovering the EnterpriseLand platform from catastrophic failures including data loss, regional outages, and complete system failures.

## Prerequisites
- Access to backup storage (Google Cloud Storage)
- Database admin credentials
- Infrastructure provisioning access
- DNS management access
- Communication channels for stakeholders

## Disaster Scenarios

### Severity Levels
- **Level 1**: Single component failure (use specific runbooks)
- **Level 2**: Multiple component failure
- **Level 3**: Complete region failure
- **Level 4**: Total system failure with data loss

## Recovery Time Objectives (RTO)

| Component | RTO | RPO | Priority |
|-----------|-----|-----|----------|
| Database | 2 hours | 15 minutes | Critical |
| Application | 1 hour | N/A | Critical |
| File Storage | 4 hours | 1 hour | High |
| Cache | 30 minutes | N/A | Medium |
| Monitoring | 2 hours | 1 hour | Medium |

## Disaster Recovery Procedures

### Phase 1: Assessment (15 minutes)

#### 1. Determine Scope
```bash
# Check all regions
for region in us-central1 us-east1 europe-west1; do
  echo "Checking $region"
  gcloud compute instances list --filter="zone:($region-*)"
done

# Check all services
services=("database" "app" "redis" "monitoring")
for service in "${services[@]}"; do
  kubectl get pods -l app=$service --all-namespaces
done

# Check external dependencies
curl -I https://api.stripe.com
curl -I https://api.sendgrid.com
```

#### 2. Activate Crisis Team
- [ ] Notify incident commander
- [ ] Assemble recovery team
- [ ] Set up war room (physical/virtual)
- [ ] Start incident timeline documentation

#### 3. Communication
```bash
# Update status page
curl -X POST https://api.statuspage.io/v1/pages/{page_id}/incidents \
  -H "Authorization: OAuth $STATUSPAGE_TOKEN" \
  -d '{"incident": {"name": "Major Service Disruption", "status": "investigating"}}'

# Send initial notification
python scripts/notify_stakeholders.py --severity=critical --message="Investigating major service disruption"
```

### Phase 2: Database Recovery

#### 1. Locate Latest Backup
```bash
# List available backups
gsutil ls -l gs://enterpriseland-backups/postgres/ | sort -k2 -r | head -20

# Identify latest consistent backup
LATEST_BACKUP=$(gsutil ls gs://enterpriseland-backups/postgres/ | sort -r | head -1)
echo "Latest backup: $LATEST_BACKUP"

# Download backup
gsutil cp $LATEST_BACKUP ./postgres-restore.sql.gz
gunzip postgres-restore.sql.gz
```

#### 2. Provision New Database
```bash
# Create new Cloud SQL instance
gcloud sql instances create enterpriseland-db-recovery \
  --database-version=POSTGRES_13 \
  --tier=db-n1-highmem-8 \
  --region=us-central1 \
  --network=enterpriseland-vpc \
  --no-assign-ip

# Wait for instance
gcloud sql instances describe enterpriseland-db-recovery

# Create database
gcloud sql databases create enterpriseland \
  --instance=enterpriseland-db-recovery
```

#### 3. Restore Data
```bash
# Import backup
gcloud sql import sql enterpriseland-db-recovery \
  gs://enterpriseland-backups/postgres/backup-latest.sql \
  --database=enterpriseland

# Monitor import
gcloud sql operations list --instance=enterpriseland-db-recovery

# Verify restoration
gcloud sql connect enterpriseland-db-recovery --user=postgres
\dt
SELECT count(*) FROM django_migrations;
SELECT count(*) FROM auth_user;
SELECT max(created_at) FROM audit_log;
```

#### 4. Restore WAL Logs (Point-in-Time Recovery)
```bash
# If using WAL archiving, restore to specific point
RECOVERY_TIME="2024-01-20 14:30:00"

# Configure recovery
cat > /tmp/recovery.conf <<EOF
restore_command = 'gsutil cp gs://enterpriseland-wal-archive/%f %p'
recovery_target_time = '$RECOVERY_TIME'
recovery_target_action = 'promote'
EOF

# Apply WAL logs
pg_ctl -D /var/lib/postgresql/data recover
```

### Phase 3: Application Recovery

#### 1. Provision Infrastructure
```bash
# Create new GKE cluster if needed
gcloud container clusters create enterpriseland-recovery \
  --region=us-central1 \
  --num-nodes=3 \
  --node-pools=default,high-memory \
  --cluster-version=latest \
  --enable-autoscaling \
  --min-nodes=3 \
  --max-nodes=20

# Get credentials
gcloud container clusters get-credentials enterpriseland-recovery --region=us-central1
```

#### 2. Deploy Core Services
```bash
# Deploy configs and secrets
kubectl apply -f k8s/namespaces.yaml
kubectl apply -f k8s/secrets/

# Update database connection
kubectl create secret generic database-credentials \
  --from-literal=url="postgresql://user:pass@enterpriseland-db-recovery:5432/enterpriseland"

# Deploy Redis
kubectl apply -f k8s/redis/

# Deploy application
kubectl apply -f k8s/app/
```

#### 3. Restore File Storage
```bash
# List backup snapshots
gsutil ls gs://enterpriseland-backups/files/

# Sync files to new bucket
gsutil -m rsync -r gs://enterpriseland-backups/files/latest/ gs://enterpriseland-files-recovery/

# Update application configuration
kubectl set env deployment/enterpriseland-app \
  FILE_STORAGE_BUCKET=enterpriseland-files-recovery
```

### Phase 4: Service Restoration

#### 1. Update DNS
```bash
# Get new load balancer IP
NEW_IP=$(kubectl get service enterpriseland-lb -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Update DNS records (example with gcloud)
gcloud dns record-sets transaction start --zone=enterpriseland-zone
gcloud dns record-sets transaction add $NEW_IP \
  --name=app.enterpriseland.com \
  --ttl=300 \
  --type=A \
  --zone=enterpriseland-zone
gcloud dns record-sets transaction execute --zone=enterpriseland-zone

# For faster propagation, use low TTL temporarily
```

#### 2. Restore Monitoring
```bash
# Deploy monitoring stack
kubectl apply -f k8s/monitoring/

# Restore Prometheus data if available
kubectl cp prometheus-backup.tar.gz prometheus-0:/prometheus/
kubectl exec -it prometheus-0 -- tar -xzf /prometheus/prometheus-backup.tar.gz

# Restore Grafana dashboards
kubectl cp grafana-dashboards.tar.gz grafana-0:/tmp/
kubectl exec -it grafana-0 -- tar -xzf /tmp/grafana-dashboards.tar.gz -C /var/lib/grafana/
```

#### 3. Verify Services
```bash
# Health checks
curl http://$NEW_IP/health/
curl http://$NEW_IP/health/ready/

# Run smoke tests
python scripts/smoke_tests.py --host=$NEW_IP

# Check critical endpoints
for endpoint in "/api/auth/" "/api/leads/" "/api/assessments/"; do
  echo "Testing $endpoint"
  curl -s -o /dev/null -w "%{http_code}" http://$NEW_IP$endpoint
done
```

### Phase 5: Data Validation

#### 1. Check Data Integrity
```sql
-- Verify record counts
SELECT 'users' as table_name, count(*) as count FROM auth_user
UNION ALL
SELECT 'leads', count(*) FROM leads_lead
UNION ALL
SELECT 'assessments', count(*) FROM assessments_assessment;

-- Check for data gaps
SELECT date_trunc('hour', created_at) as hour, count(*)
FROM audit_log
WHERE created_at > now() - interval '7 days'
GROUP BY hour
ORDER BY hour;

-- Verify foreign key constraints
SELECT conname, conrelid::regclass, confrelid::regclass
FROM pg_constraint
WHERE contype = 'f' AND NOT convalidated;
```

#### 2. Application Data Checks
```python
# Run Django checks
python manage.py check --deploy
python manage.py showmigrations

# Verify file storage
python manage.py shell
>>> from django.core.files.storage import default_storage
>>> default_storage.exists('test.txt')

# Check cache
>>> from django.core.cache import cache
>>> cache.set('dr_test', 'success', 60)
>>> cache.get('dr_test')
```

### Phase 6: Gradual Traffic Migration

#### 1. Configure Traffic Splitting
```bash
# Start with 10% traffic to recovery environment
gcloud compute url-maps set-default-service enterpriseland-lb \
  --default-service=enterpriseland-recovery-backend \
  --traffic-split="enterpriseland-backend=90,enterpriseland-recovery-backend=10"

# Monitor for 15 minutes
watch -n 10 'curl -s http://prometheus:9090/api/v1/query?query=rate(http_requests_total[5m])'

# Increase to 50%
gcloud compute url-maps set-default-service enterpriseland-lb \
  --traffic-split="enterpriseland-backend=50,enterpriseland-recovery-backend=50"

# Full cutover
gcloud compute url-maps set-default-service enterpriseland-lb \
  --default-service=enterpriseland-recovery-backend
```

#### 2. Monitor Migration
```bash
# Watch error rates
watch 'kubectl logs -l app=enterpriseland --tail=50 | grep ERROR'

# Check performance metrics
curl http://prometheus:9090/api/v1/query?query=histogram_quantile(0.95,rate(http_request_duration_seconds_bucket[5m]))
```

## Post-Recovery Tasks

### Immediate (Within 2 Hours)
- [ ] Update status page
- [ ] Send recovery notification
- [ ] Document data loss (if any)
- [ ] Begin root cause analysis

### Within 24 Hours
- [ ] Complete incident report
- [ ] Calculate actual RTO/RPO
- [ ] Identify improvement areas
- [ ] Update DR procedures

### Within 1 Week
- [ ] Conduct post-mortem
- [ ] Update DR plans
- [ ] Test backup procedures
- [ ] Train team on lessons learned

## Backup Verification Procedures

### Daily Checks
```bash
# Verify backup completion
gsutil ls -l gs://enterpriseland-backups/postgres/$(date +%Y%m%d)*.sql.gz

# Test backup integrity
gsutil cp gs://enterpriseland-backups/postgres/latest.sql.gz - | gunzip | head -100
```

### Weekly DR Drills
```bash
# Restore to test environment
./scripts/dr_drill.sh --type=database --env=staging

# Verify restoration
./scripts/verify_dr_restore.sh
```

## Emergency Contacts

| Role | Name | Contact | Escalation |
|------|------|---------|------------|
| Incident Commander | On-Call IC | PagerDuty | CEO |
| Database Lead | DBA Team | PagerDuty | CTO |
| Infrastructure Lead | DevOps | PagerDuty | VP Eng |
| Communications | PR Team | Slack | CMO |

## Recovery Checklist

### Pre-Recovery
- [ ] Assess damage scope
- [ ] Activate recovery team
- [ ] Notify stakeholders
- [ ] Document start time

### Database Recovery
- [ ] Locate latest backup
- [ ] Provision new instance
- [ ] Restore data
- [ ] Verify integrity

### Application Recovery
- [ ] Provision infrastructure
- [ ] Deploy services
- [ ] Update configurations
- [ ] Restore file storage

### Service Restoration
- [ ] Update DNS
- [ ] Restore monitoring
- [ ] Verify health
- [ ] Migrate traffic

### Post-Recovery
- [ ] Update status
- [ ] Document timeline
- [ ] Calculate impact
- [ ] Plan improvements

## Automation Scripts

### One-Command DR
```bash
# Automated disaster recovery
./scripts/disaster_recovery.sh \
  --scenario=full \
  --backup-time="2024-01-20 14:00:00" \
  --target-region=us-east1 \
  --notify-slack=#dr-channel
```

## Related Documents
- [Backup Procedures](./backup-procedures.md)
- [Data Recovery](./data-recovery.md)
- [Service Outage](./service-outage.md)
- [Business Continuity Plan](../policies/bcp.md)