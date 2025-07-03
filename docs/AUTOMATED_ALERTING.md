# Automated Alerting System

## Overview

The EnterpriseLand platform includes a comprehensive automated alerting system that monitors system health, performance metrics, and business KPIs. The system integrates with Prometheus/Alertmanager for rule evaluation and supports multiple notification channels including email, Slack, PagerDuty, and webhooks.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Metrics        │────▶│  Alert       │────▶│  Alert      │
│  Registry       │     │  Processor   │     │  Manager    │
└─────────────────┘     └──────────────┘     └─────────────┘
                               │                     │
                               ▼                     ▼
                        ┌──────────────┐     ┌─────────────┐
                        │ Alert Rules  │     │  Channels   │
                        └──────────────┘     └─────────────┘
                                                    │
                          ┌─────────────────────────┴────────────────┐
                          ▼                   ▼                      ▼
                    ┌──────────┐       ┌──────────┐          ┌──────────┐
                    │  Email   │       │  Slack   │          │ PagerDuty│
                    └──────────┘       └──────────┘          └──────────┘
```

## Components

### 1. Alert Rules
Define conditions that trigger alerts when metrics exceed thresholds.

### 2. Alert Channels
Configure notification destinations and routing rules.

### 3. Alert Manager
Processes alerts, manages state, and sends notifications.

### 4. Alert Processor
Evaluates rules against current metric values.

## Quick Start

### 1. Setup Default Alerts

```bash
python manage.py setup_default_alerts
```

This creates pre-configured alert rules for:
- High error rate (>5%)
- Slow response time (p95 > 1s)
- Low cache hit rate (<80%)
- High memory usage (>90%)
- Database connection pool exhaustion
- Low lead conversion rate
- Service health degradation

### 2. Configure Notification Channels

#### Email Channel
```python
channel = AlertChannel.objects.create(
    name='Team Email',
    type='email',
    configuration={
        'recipients': ['team@example.com', 'oncall@example.com']
    },
    severities=['error', 'critical'],
    labels={'team': 'backend'}
)
```

#### Slack Channel
```python
channel = AlertChannel.objects.create(
    name='Ops Slack',
    type='slack',
    configuration={
        'webhook_url': 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL',
        'channel': '#alerts'
    },
    severities=['warning', 'error', 'critical']
)
```

#### PagerDuty Channel
```python
channel = AlertChannel.objects.create(
    name='Critical Alerts',
    type='pagerduty',
    configuration={
        'integration_key': 'YOUR_PAGERDUTY_INTEGRATION_KEY'
    },
    severities=['critical']
)
```

#### Webhook Channel
```python
channel = AlertChannel.objects.create(
    name='External System',
    type='webhook',
    configuration={
        'url': 'https://api.example.com/alerts',
        'auth_type': 'bearer',
        'token': 'YOUR_API_TOKEN',
        'headers': {'X-Source': 'EnterpriseLand'}
    }
)
```

### 3. Create Custom Alert Rules

```python
rule = AlertRule.objects.create(
    name='API Rate Limit',
    description='Alert when API rate limit is close to exhaustion',
    metric_name='api_rate_limit_remaining',
    condition='<',
    threshold=1000.0,
    severity='warning',
    evaluation_interval=60,  # Check every minute
    for_duration=300,        # Alert if true for 5 minutes
    cooldown_period=3600,    # Wait 1 hour before re-alerting
    max_alerts_per_day=10,
    labels={'service': 'api', 'team': 'backend'}
)
```

## Alert Management

### API Endpoints

#### List Alert Rules
```http
GET /api/alerts/rules/
```

#### Create Alert Rule
```http
POST /api/alerts/rules/
Content-Type: application/json

{
    "name": "High CPU Usage",
    "metric_name": "system_cpu_usage_percent",
    "condition": ">",
    "threshold": 80.0,
    "severity": "warning"
}
```

#### List Active Alerts
```http
GET /api/alerts/alerts/?status=firing
```

#### Acknowledge Alerts
```http
POST /api/alerts/alerts/acknowledge/
Content-Type: application/json

{
    "alert_ids": [1, 2, 3]
}
```

#### Create Alert Silence
```http
POST /api/alerts/silences/
Content-Type: application/json

{
    "name": "Maintenance Window",
    "matchers": {"environment": "staging"},
    "duration_hours": 4
}
```

### CLI Commands

#### Process Alerts Manually
```bash
python manage.py process_alerts
```

#### View Alert Statistics
```bash
from platform_core.alerts.services import AlertManager

manager = AlertManager()
stats = manager.get_alert_stats()
print(f"Active alerts: {stats['active']}")
print(f"Last 24h: {stats['last_24h']}")
```

## Alert Rule Configuration

### Severity Levels
- **info**: Informational alerts
- **warning**: Potential issues requiring attention
- **error**: Service degradation or errors
- **critical**: Immediate action required

### Conditions
- `>`: Greater than
- `>=`: Greater than or equal
- `<`: Less than
- `<=`: Less than or equal
- `==`: Equal to
- `!=`: Not equal to

### Timing Parameters
- **evaluation_interval**: How often to check the rule (seconds)
- **for_duration**: How long condition must be true before alerting (seconds)
- **cooldown_period**: Minimum time between alerts (seconds)
- **max_alerts_per_day**: Daily alert limit per rule

## Notification Channels

### Channel Types

#### Email
- Supports multiple recipients
- HTML and plain text templates
- Customizable subject lines

#### Slack
- Webhook-based integration
- Color-coded by severity
- Supports channel override

#### PagerDuty
- Integration key authentication
- Automatic incident creation
- Severity mapping

#### Webhook
- Custom HTTP endpoints
- Flexible authentication (Basic, Bearer, Custom headers)
- Configurable timeout

#### SMS (Future)
- Twilio integration placeholder
- Character-limited messages

### Routing Rules

Channels can filter alerts based on:
- **Severity**: Only route specific severity levels
- **Labels**: Match alerts with specific labels
- **Rate Limiting**: Maximum notifications per hour

Example:
```python
channel = AlertChannel.objects.create(
    name='Database Team',
    type='email',
    configuration={'recipients': ['dba@example.com']},
    severities=['error', 'critical'],
    labels={'service': 'database'},
    rate_limit=20  # Max 20 notifications per hour
)
```

## Alert Lifecycle

### 1. Pending
Alert condition met but waiting for duration threshold.

### 2. Firing
Alert is active and notifications are being sent.

### 3. Acknowledged
Alert has been acknowledged by a user.

### 4. Resolved
Alert condition is no longer met.

### 5. Silenced
Alert is temporarily muted.

## Silencing Alerts

### Create Silence via API
```python
from platform_core.alerts.services import AlertManager

manager = AlertManager()
silence = manager.create_silence(
    user=request.user,
    name='Database Maintenance',
    matchers={'service': 'database', 'environment': 'production'},
    duration_hours=2
)
```

### Silence Matching
Silences match alerts based on label equality. All specified labels must match.

## Integration with Prometheus

### Prometheus Configuration
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'enterpriseland'
    metrics_path: '/metrics/'
    static_configs:
      - targets: ['app:8000']
```

### Alert Rules in Prometheus
```yaml
# alerts.yml
groups:
  - name: application
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: error
        annotations:
          summary: High error rate detected
```

## Performance Considerations

### Alert Processing
- Alerts are evaluated every minute by default
- Use Celery for background processing
- Batch similar alerts to reduce noise

### Notification Deduplication
- Fingerprinting prevents duplicate alerts
- Cooldown periods limit alert frequency
- Daily limits prevent alert storms

### Database Indexes
```python
# Optimized for common queries
indexes = [
    models.Index(fields=['status', 'severity']),
    models.Index(fields=['rule', 'status']),
    models.Index(fields=['fingerprint', 'status']),
]
```

## Best Practices

### 1. Alert Design
- Be specific in alert descriptions
- Include remediation steps in annotations
- Use appropriate severity levels
- Set reasonable thresholds to avoid noise

### 2. Channel Configuration
- Test channels before production use
- Use rate limiting to prevent spam
- Configure appropriate routing rules
- Have escalation paths for critical alerts

### 3. Alert Management
- Regularly review and tune alert rules
- Clean up obsolete alerts
- Document runbooks for common alerts
- Practice incident response procedures

### 4. Monitoring the Monitors
- Set up alerts for the alerting system itself
- Monitor notification delivery success
- Track alert volume and patterns
- Review silence usage

## Troubleshooting

### Alerts Not Firing

1. Check metric exists:
```python
from platform_core.monitoring.metrics import metrics_registry
metric = metrics_registry.get_metric('metric_name')
print(metric.value if metric else "Metric not found")
```

2. Verify rule evaluation:
```python
from platform_core.alerts.models import AlertRule
rule = AlertRule.objects.get(name='Rule Name')
print(f"Would fire: {rule.evaluate(current_value)}")
```

3. Check for silences:
```python
from platform_core.alerts.models import AlertSilence
active_silences = AlertSilence.objects.filter(active=True)
```

### Notifications Not Sent

1. Verify channel configuration
2. Check channel is enabled
3. Review notification history
4. Check rate limits

### Performance Issues

1. Reduce evaluation frequency for non-critical rules
2. Increase cooldown periods
3. Use alert aggregation
4. Archive old alerts regularly

## Security

### Authentication
- Metrics endpoint can require authentication
- API endpoints use standard Django permissions
- Webhook channels support various auth methods

### Data Protection
- Sensitive data should not be included in alerts
- Use secure channels for critical notifications
- Rotate webhook tokens regularly

### Audit Trail
- All alert actions are logged
- User acknowledgments are tracked
- Configuration changes are audited

---

The automated alerting system provides comprehensive monitoring and notification capabilities, ensuring that teams are promptly notified of issues while avoiding alert fatigue through intelligent routing and deduplication.