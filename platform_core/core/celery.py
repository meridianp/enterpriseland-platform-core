
import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('core')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery beat schedule for periodic tasks
app.conf.beat_schedule = {
    'update-fx-rates': {
        'task': 'assessments.tasks.update_fx_rates',
        'schedule': 3600.0,  # Every hour
    },
    'cleanup-old-fx-rates': {
        'task': 'assessments.tasks.cleanup_old_fx_rates',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-old-notifications': {
        'task': 'notifications.tasks.cleanup_old_notifications',
        'schedule': 86400.0,  # Daily
    },
    'process-sequence-triggers': {
        'task': 'contacts.tasks_outreach.process_sequence_triggers',
        'schedule': 300.0,  # Every 5 minutes
    },
    'update-sequence-analytics': {
        'task': 'contacts.tasks_outreach.update_sequence_analytics',
        'schedule': 3600.0,  # Every hour
    },
}

app.conf.timezone = 'UTC'

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
