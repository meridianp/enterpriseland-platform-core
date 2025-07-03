"""
Alert Management System

Provides automated alerting with integration to multiple notification channels.
"""

from .models import Alert, AlertRule, AlertChannel
from .services import AlertManager, AlertProcessor
from .channels import EmailChannel, SlackChannel, PagerDutyChannel, WebhookChannel

__all__ = [
    'Alert',
    'AlertRule',
    'AlertChannel',
    'AlertManager',
    'AlertProcessor',
    'EmailChannel',
    'SlackChannel',
    'PagerDutyChannel',
    'WebhookChannel',
]