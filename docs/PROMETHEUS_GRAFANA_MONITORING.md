# Prometheus & Grafana Monitoring Setup

## Overview

This document describes the complete monitoring stack implementation for the EnterpriseLand platform using Prometheus for metrics collection and Grafana for visualization. The setup includes automated alerting, comprehensive dashboards, and integration with the platform's performance monitoring system.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Application    │────▶│  Prometheus  │────▶│   Grafana   │
│  /metrics/      │     │   Scraper    │     │ Dashboards  │
└─────────────────┘     └──────────────┘     └─────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │ Alertmanager │
                        └──────────────┘
                               │
                    ┌──────────┴───────────┐
                    ▼                      ▼
              ┌──────────┐           ┌──────────┐
              │  Email   │           │  Slack   │
              └──────────┘           └──────────┘
```

## Components

### 1. Prometheus
- **Version**: 2.37.0
- **Purpose**: Time-series database and metrics collection
- **Configuration**: `deployment/prometheus/prometheus.yml`
- **Port**: 9090

### 2. Grafana
- **Version**: 9.0.0
- **Purpose**: Metrics visualization and dashboards
- **Port**: 3001
- **Default Credentials**: admin/admin (change on first login)

### 3. Alertmanager
- **Version**: 0.24.0
- **Purpose**: Alert routing and notification
- **Port**: 9093
- **Configuration**: `deployment/alertmanager/config.yml`

### 4. Exporters
- **PostgreSQL Exporter**: Database metrics (port 9187)
- **Redis Exporter**: Cache metrics (port 9121)
- **Node Exporter**: System metrics (port 9100)
- **Blackbox Exporter**: Endpoint monitoring (port 9115)
- **cAdvisor**: Container metrics (port 8080)

## Quick Start

### 1. Start the Monitoring Stack

```bash
# Start main application with monitoring
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

# Or just monitoring stack
docker-compose -f docker-compose.monitoring.yml up -d
```

### 2. Access Interfaces

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3001
- **Alertmanager**: http://localhost:9093

### 3. Verify Metrics Collection

1. Open Prometheus UI
2. Go to Status → Targets
3. All targets should show as "UP"

## Configuration

### Application Metrics Endpoint

The Django application exposes metrics at `/metrics/`. Ensure these settings:

```python
# settings.py
METRICS_ENABLED = True
METRICS_REQUIRE_AUTH = False  # Set to True in production
```

### Prometheus Scrape Configuration

```yaml
scrape_configs:
  - job_name: 'enterpriseland-app'
    metrics_path: '/metrics/'
    static_configs:
      - targets: ['app:8000']
```

### Alert Rules

Alert rules are defined in:
- `deployment/prometheus/alerts/application_alerts.yml`
- `deployment/prometheus/alerts/business_alerts.yml`

Key alerts include:
- High error rate (>5%)
- Slow response time (p95 > 1s)
- Low cache hit rate (<80%)
- High resource usage
- Service health issues

## Grafana Dashboards

### Pre-configured Dashboards

1. **System Overview**
   - CPU, Memory, Disk usage
   - Request rate and response times
   - Cache performance
   - Error tracking

2. **Business Metrics** (to be added)
   - User activity
   - Lead generation
   - Deal conversion
   - Revenue tracking

3. **Database Performance** (to be added)
   - Query performance
   - Connection pool usage
   - Slow query analysis

### Creating Custom Dashboards

1. Access Grafana at http://localhost:3001
2. Click "+" → "Create Dashboard"
3. Add panels using PromQL queries
4. Save dashboard

Example queries:
```promql
# Request rate
sum(rate(http_requests_total[5m]))

# 95th percentile response time
histogram_quantile(0.95, 
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)

# Error rate
sum(rate(http_requests_total{status=~"5.."}[5m])) 
/ 
sum(rate(http_requests_total[5m]))
```

## Alerting Configuration

### Email Alerts

Update `deployment/alertmanager/config.yml`:

```yaml
global:
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alerts@enterpriseland.com'
  smtp_auth_username: 'your-email'
  smtp_auth_password: 'your-app-password'
```

### Slack Integration

1. Create Slack webhook
2. Update configuration:

```yaml
global:
  slack_api_url: 'YOUR_SLACK_WEBHOOK_URL'
```

### PagerDuty Integration

For critical alerts:

```yaml
receivers:
  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_SERVICE_KEY'
```

## Monitoring Best Practices

### 1. Metric Naming
Follow Prometheus conventions:
- Use lowercase with underscores
- Include unit suffix: `_seconds`, `_bytes`, `_total`
- Be descriptive but concise

### 2. Dashboard Organization
- Group related metrics
- Use consistent color schemes
- Add helpful descriptions
- Set appropriate refresh intervals

### 3. Alert Tuning
- Start with conservative thresholds
- Reduce noise by grouping alerts
- Use inhibition rules
- Document runbook URLs

### 4. Resource Management
- Set retention policies (default: 30 days)
- Monitor Prometheus storage usage
- Use recording rules for complex queries
- Implement metric cardinality limits

## Production Deployment

### 1. Security
```yaml
# Enable authentication for metrics
METRICS_REQUIRE_AUTH = True

# Use TLS for exporters
tls_config:
  cert_file: /path/to/cert.pem
  key_file: /path/to/key.pem
```

### 2. High Availability
- Run multiple Prometheus instances
- Use remote storage (e.g., Thanos)
- Configure Grafana with multiple datasources
- Set up Alertmanager clustering

### 3. Backup
```bash
# Backup Prometheus data
docker exec prometheus tar czf /tmp/prometheus-backup.tar.gz /prometheus

# Backup Grafana dashboards
docker exec grafana tar czf /tmp/grafana-backup.tar.gz /var/lib/grafana
```

## Troubleshooting

### Prometheus Not Scraping

1. Check target status: http://localhost:9090/targets
2. Verify network connectivity
3. Check application logs
4. Test metrics endpoint: `curl http://localhost:8000/metrics/`

### Missing Metrics

1. Verify metric name in Prometheus
2. Check for typos in queries
3. Ensure sufficient data retention
4. Verify exporter is running

### Alert Not Firing

1. Check alert rules syntax
2. Verify metric exists
3. Test with lower threshold
4. Check Alertmanager logs

### Performance Issues

1. Optimize PromQL queries
2. Use recording rules
3. Increase scrape interval
4. Add more Prometheus resources

## Maintenance

### Regular Tasks

1. **Daily**
   - Check alert status
   - Verify all targets are up
   - Review error dashboards

2. **Weekly**
   - Review and tune alerts
   - Check storage usage
   - Update dashboards

3. **Monthly**
   - Backup dashboards
   - Review metrics cardinality
   - Update exporters

### Upgrades

```bash
# Update images in docker-compose.monitoring.yml
# Then recreate containers
docker-compose -f docker-compose.monitoring.yml up -d --force-recreate
```

## Metrics Reference

### Application Metrics
- `http_requests_total` - Total HTTP requests
- `http_request_duration_seconds` - Request duration histogram
- `http_errors_total` - Total errors
- `system_health_status` - Overall health (1-4)

### System Metrics
- `system_cpu_usage_percent` - CPU usage
- `system_memory_usage_percent` - Memory usage
- `system_disk_usage_percent` - Disk usage

### Business Metrics
- `business_users_active` - Active users
- `business_leads_total` - Total leads
- `business_deals_active` - Active deals

### Cache Metrics
- `cache_hit_rate_percent` - Cache hit rate
- `cache_hits_total` - Total cache hits
- `cache_misses_total` - Total cache misses

### Database Metrics
- `db_connections_active` - Active connections
- `db_query_duration_seconds` - Query duration
- `db_errors_total` - Database errors

## Integration with Cloud Providers

### AWS CloudWatch
```python
from platform_core.monitoring import CloudWatchExporter

exporter = CloudWatchExporter(
    namespace='EnterpriseLand/Production',
    region='us-east-1'
)
```

### Google Cloud Monitoring
Use Prometheus sidecar with Stackdriver adapter

### Azure Monitor
Configure Prometheus remote write to Azure

---

*This monitoring setup provides comprehensive observability for the EnterpriseLand platform, enabling proactive issue detection and performance optimization through real-time metrics and intelligent alerting.*