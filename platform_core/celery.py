"""
Celery Configuration
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_core.settings')

app = Celery('platform_core')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery Beat Schedule
app.conf.beat_schedule = {
    # Process alerts every minute
    'process-alerts': {
        'task': 'platform_core.alerts.tasks.process_alerts',
        'schedule': crontab(minute='*'),  # Every minute
    },
    
    # Clean up old alerts daily at 2 AM
    'cleanup-old-alerts': {
        'task': 'platform_core.alerts.tasks.cleanup_old_alerts',
        'schedule': crontab(hour=2, minute=0),
    },
    
    # Expire silences every 5 minutes
    'expire-silences': {
        'task': 'platform_core.alerts.tasks.expire_silences',
        'schedule': crontab(minute='*/5'),
    },
    
    # Alert health check every 15 minutes
    'alert-health-check': {
        'task': 'platform_core.alerts.tasks.alert_health_check',
        'schedule': crontab(minute='*/15'),
    },
    
    # Send daily alert summary at 9 AM
    'send-alert-summary': {
        'task': 'platform_core.alerts.tasks.send_alert_summary',
        'schedule': crontab(hour=9, minute=0),
    },
    
    # Collect performance metrics every 30 seconds
    'collect-performance-metrics': {
        'task': 'platform_core.monitoring.tasks.collect_metrics',
        'schedule': 30.0,  # Every 30 seconds
    },
    
    # Clean up old performance profiles weekly
    'cleanup-performance-profiles': {
        'task': 'platform_core.performance.tasks.cleanup_old_profiles',
        'schedule': crontab(day_of_week=0, hour=3, minute=0),  # Sunday at 3 AM
    },
    
    # Optimize cache strategy hourly
    'optimize-cache-strategy': {
        'task': 'platform_core.caching.tasks.optimize_cache_strategy',
        'schedule': crontab(minute=0),  # Every hour
    },
    
    # Purge CDN cache daily
    'purge-cdn-stale-content': {
        'task': 'platform_core.cdn.tasks.purge_stale_content',
        'schedule': crontab(hour=4, minute=0),  # Daily at 4 AM
    },
}

# Celery configuration
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)