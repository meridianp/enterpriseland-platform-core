# Runbook: Production Deployment

## Overview
This runbook provides step-by-step procedures for deploying the EnterpriseLand platform to production.

## Prerequisites
- GitHub repository access
- Google Cloud Platform access
- Docker registry credentials
- Production database credentials
- Monitoring dashboard access

## Pre-Deployment Checklist

### Code Review
- [ ] All PRs approved and merged
- [ ] CI/CD pipeline passing
- [ ] Security scan completed
- [ ] Performance tests passed

### Communication
- [ ] Deployment window scheduled
- [ ] Stakeholders notified
- [ ] Maintenance page prepared
- [ ] Rollback plan documented

## Deployment Steps

### 1. Pre-Deployment Validation

```bash
# Verify current production version
kubectl get deployment enterpriseland-app -o jsonpath='{.spec.template.spec.containers[0].image}'

# Check system health
curl http://app.enterpriseland.com/health/

# Backup current deployment config
kubectl get deployment enterpriseland-app -o yaml > backup/deployment-$(date +%Y%m%d-%H%M%S).yaml

# Verify database backup exists
gsutil ls gs://enterpriseland-backups/postgres/$(date +%Y%m%d)*
```

### 2. Build and Push Images

```bash
# Set version
export VERSION=$(git describe --tags --always)
export IMAGE_TAG=gcr.io/enterpriseland-prod/app:${VERSION}

# Build Docker image
docker build -t ${IMAGE_TAG} -f Dockerfile.production .

# Run security scan
docker scan ${IMAGE_TAG}

# Push to registry
docker push ${IMAGE_TAG}

# Verify image
gcloud container images describe ${IMAGE_TAG}
```

### 3. Database Migrations

```bash
# Create migration job
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: migrate-${VERSION}
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: ${IMAGE_TAG}
        command: ["python", "manage.py", "migrate", "--no-input"]
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: database-credentials
              key: url
      restartPolicy: Never
EOF

# Monitor migration
kubectl logs -f job/migrate-${VERSION}

# Verify migration success
kubectl get job migrate-${VERSION} -o jsonpath='{.status.succeeded}'
```

### 4. Deploy to Staging (Canary)

```bash
# Deploy canary version (10% traffic)
kubectl set image deployment/enterpriseland-canary app=${IMAGE_TAG}

# Wait for rollout
kubectl rollout status deployment/enterpriseland-canary

# Monitor canary metrics
watch -n 5 'kubectl top pods -l app=enterpriseland,version=canary'

# Check canary health
for i in {1..10}; do
  curl -H "X-Canary: true" http://app.enterpriseland.com/health/
  sleep 10
done
```

### 5. Monitor Canary Deployment

```python
# Check error rates
curl -G http://prometheus:9090/api/v1/query \
  --data-urlencode 'query=rate(http_requests_total{job="enterpriseland-canary",status=~"5.."}[5m])'

# Verify no increase in errors
# If error rate > 1%, rollback canary
```

### 6. Full Production Deployment

```bash
# If canary is healthy, proceed with full deployment
kubectl set image deployment/enterpriseland-app app=${IMAGE_TAG}

# Monitor rollout
kubectl rollout status deployment/enterpriseland-app --timeout=10m

# Verify all pods are running
kubectl get pods -l app=enterpriseland -o wide

# Scale if needed
kubectl scale deployment enterpriseland-app --replicas=20
```

### 7. Update Supporting Services

```bash
# Update workers
kubectl set image deployment/enterpriseland-worker worker=${IMAGE_TAG}
kubectl rollout status deployment/enterpriseland-worker

# Update beat scheduler
kubectl set image deployment/enterpriseland-beat beat=${IMAGE_TAG}
kubectl rollout status deployment/enterpriseland-beat

# Clear caches
kubectl exec -it redis-master-0 -- redis-cli FLUSHDB
```

### 8. Post-Deployment Validation

```bash
# Health checks
curl http://app.enterpriseland.com/health/
curl http://app.enterpriseland.com/health/ready/

# Run smoke tests
python scripts/smoke_tests.py --env=production

# Check key endpoints
endpoints=(
  "/api/auth/login/"
  "/api/leads/"
  "/api/assessments/"
  "/api/market-intelligence/"
)

for endpoint in "${endpoints[@]}"; do
  echo "Testing $endpoint"
  curl -s -o /dev/null -w "%{http_code}" http://app.enterpriseland.com$endpoint
  echo
done
```

### 9. Update CDN and Clear Caches

```bash
# Purge CDN cache
curl -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
     -H "Authorization: Bearer ${CF_API_TOKEN}" \
     -H "Content-Type: application/json" \
     --data '{"purge_everything":true}'

# Warm up cache with critical paths
for path in "/" "/api/docs/" "/static/js/main.js"; do
  curl -s http://app.enterpriseland.com${path} > /dev/null
done
```

## Rollback Procedures

### Quick Rollback (< 5 minutes)

```bash
# Rollback to previous version
kubectl rollout undo deployment/enterpriseland-app

# Monitor rollback
kubectl rollout status deployment/enterpriseland-app

# Verify health
curl http://app.enterpriseland.com/health/
```

### Database Rollback

```bash
# Only if migrations need reverting
kubectl run migrate-rollback --rm -it --image=${PREVIOUS_IMAGE_TAG} --restart=Never -- \
  python manage.py migrate app_name migration_name

# Restore from backup if needed
gsutil cp gs://enterpriseland-backups/postgres/backup-${TIMESTAMP}.sql .
psql $DATABASE_URL < backup-${TIMESTAMP}.sql
```

## Verification

### 1. Functional Testing
```bash
# Run integration tests
python manage.py test --tag=integration --settings=settings.production

# User journey tests
python scripts/user_journey_test.py --env=production
```

### 2. Performance Validation
```bash
# Load test (careful in production!)
locust -f tests/load_test.py --host=https://app.enterpriseland.com --users=100 --spawn-rate=10 --run-time=5m

# Check response times
for i in {1..20}; do
  curl -w "Total time: %{time_total}s\n" -o /dev/null -s https://app.enterpriseland.com/api/health/
done | awk '{sum+=$3; count++} END {print "Average:", sum/count "s"}'
```

### 3. Monitoring Checks
- [ ] No increase in error rates
- [ ] Response times within SLA
- [ ] CPU/Memory usage normal
- [ ] No new alerts firing

## Post-Deployment

### Immediate Actions
- [ ] Remove canary deployment
- [ ] Update deployment documentation
- [ ] Notify stakeholders of completion
- [ ] Monitor for 30 minutes

### Within 24 Hours
- [ ] Review deployment metrics
- [ ] Document any issues
- [ ] Update runbooks if needed
- [ ] Plan improvements

## Deployment Schedule

### Standard Deployments
- **Day**: Tuesday or Thursday
- **Time**: 10:00 AM PST
- **Duration**: 30-60 minutes
- **Notification**: 24 hours advance

### Emergency Deployments
- **Approval**: VP Engineering required
- **Notification**: 1 hour advance minimum
- **Documentation**: Incident ticket required

## Common Issues

### Image Pull Errors
```bash
# Check image exists
gcloud container images list --repository=gcr.io/enterpriseland-prod

# Verify credentials
kubectl get secret gcr-secret -o yaml

# Re-create if needed
kubectl create secret docker-registry gcr-secret \
  --docker-server=gcr.io \
  --docker-username=_json_key \
  --docker-password="$(cat key.json)"
```

### Migration Failures
```bash
# Check migration status
python manage.py showmigrations

# Run specific migration
python manage.py migrate app_name --fake

# Skip problematic migration
python manage.py migrate app_name 0001 --fake
```

### Pod Startup Issues
```bash
# Check pod events
kubectl describe pod POD_NAME

# View startup logs
kubectl logs POD_NAME --previous

# Common fixes
kubectl delete pod POD_NAME  # Force recreation
kubectl set env deployment/enterpriseland-app FORCE_RESTART=$(date +%s)  # Force new rollout
```

## Escalation

- **Deployment Issues**: DevOps Team
- **Application Errors**: Development Team
- **Database Problems**: DBA Team
- **Business Impact**: Product Manager

## Related Documents
- [Rollback Procedures](./rollback-procedures.md)
- [Database Maintenance](./database-maintenance.md)
- [Monitoring Setup](./monitoring-setup.md)
- [CI/CD Pipeline](../ci-cd/pipeline.md)