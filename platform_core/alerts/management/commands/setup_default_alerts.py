"""
Setup Default Alert Rules and Channels
"""
from django.core.management.base import BaseCommand
from django.conf import settings

from platform_core.alerts.models import AlertRule, AlertChannel


class Command(BaseCommand):
    help = 'Setup default alert rules and channels'
    
    def handle(self, *args, **options):
        self.stdout.write('Setting up default alert rules and channels...')
        
        # Create default alert rules
        rules = [
            {
                'name': 'High Error Rate',
                'description': 'Alert when error rate exceeds 5%',
                'metric_name': 'http_error_rate_percent',
                'condition': '>',
                'threshold': 5.0,
                'severity': 'error',
                'evaluation_interval': 60,
                'for_duration': 300,
                'labels': {'team': 'backend'},
            },
            {
                'name': 'Slow Response Time',
                'description': 'Alert when 95th percentile response time exceeds 1 second',
                'metric_name': 'http_response_time_p95_seconds',
                'condition': '>',
                'threshold': 1.0,
                'severity': 'warning',
                'evaluation_interval': 60,
                'for_duration': 600,
                'labels': {'team': 'backend'},
            },
            {
                'name': 'Low Cache Hit Rate',
                'description': 'Alert when cache hit rate drops below 80%',
                'metric_name': 'cache_hit_rate_percent',
                'condition': '<',
                'threshold': 80.0,
                'severity': 'warning',
                'evaluation_interval': 300,
                'for_duration': 900,
                'labels': {'team': 'backend'},
            },
            {
                'name': 'High Memory Usage',
                'description': 'Alert when memory usage exceeds 90%',
                'metric_name': 'system_memory_usage_percent',
                'condition': '>',
                'threshold': 90.0,
                'severity': 'critical',
                'evaluation_interval': 60,
                'for_duration': 300,
                'labels': {'team': 'infrastructure'},
            },
            {
                'name': 'Database Connection Pool Exhausted',
                'description': 'Alert when database connection pool usage exceeds 95%',
                'metric_name': 'db_connection_pool_usage_percent',
                'condition': '>',
                'threshold': 95.0,
                'severity': 'critical',
                'evaluation_interval': 30,
                'for_duration': 120,
                'labels': {'team': 'database'},
            },
            {
                'name': 'Low Lead Conversion Rate',
                'description': 'Alert when lead conversion rate drops below 10%',
                'metric_name': 'business_lead_conversion_rate_percent',
                'condition': '<',
                'threshold': 10.0,
                'severity': 'info',
                'evaluation_interval': 3600,
                'for_duration': 7200,
                'labels': {'team': 'product'},
            },
            {
                'name': 'Service Health Degraded',
                'description': 'Alert when service health status is degraded',
                'metric_name': 'system_health_status',
                'condition': '<',
                'threshold': 3.0,
                'severity': 'error',
                'evaluation_interval': 60,
                'for_duration': 180,
                'labels': {'team': 'backend'},
            },
        ]
        
        for rule_data in rules:
            rule, created = AlertRule.objects.get_or_create(
                name=rule_data['name'],
                defaults=rule_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created rule: {rule.name}'))
            else:
                self.stdout.write(f'Rule already exists: {rule.name}')
        
        # Create default channels
        channels = [
            {
                'name': 'Backend Team Email',
                'type': 'email',
                'configuration': {
                    'recipients': ['backend-team@enterpriseland.com']
                },
                'severities': ['error', 'critical'],
                'labels': {'team': 'backend'},
            },
            {
                'name': 'Infrastructure Slack',
                'type': 'slack',
                'configuration': {
                    'webhook_url': 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL',
                    'channel': '#infrastructure-alerts'
                },
                'severities': ['warning', 'error', 'critical'],
                'labels': {'team': 'infrastructure'},
            },
            {
                'name': 'Critical PagerDuty',
                'type': 'pagerduty',
                'configuration': {
                    'integration_key': 'YOUR_PAGERDUTY_INTEGRATION_KEY'
                },
                'severities': ['critical'],
                'labels': {},
            },
            {
                'name': 'Monitoring Webhook',
                'type': 'webhook',
                'configuration': {
                    'url': 'https://monitoring.enterpriseland.com/webhook/alerts',
                    'auth_type': 'bearer',
                    'token': 'YOUR_WEBHOOK_TOKEN',
                    'timeout': 30
                },
                'severities': ['info', 'warning', 'error', 'critical'],
                'labels': {},
            },
        ]
        
        for channel_data in channels:
            channel, created = AlertChannel.objects.get_or_create(
                name=channel_data['name'],
                defaults=channel_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created channel: {channel.name}'))
            else:
                self.stdout.write(f'Channel already exists: {channel.name}')
        
        self.stdout.write(self.style.SUCCESS('Default alert setup complete!'))