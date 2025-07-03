"""
Alert Notification Channels
"""
import json
import logging
import requests
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import Alert, AlertChannel, AlertNotification

logger = logging.getLogger(__name__)


class NotificationChannel(ABC):
    """Base notification channel"""
    
    def __init__(self, channel: AlertChannel):
        self.channel = channel
        self.config = channel.configuration
    
    @abstractmethod
    def send(self, alert: Alert) -> bool:
        """Send alert notification"""
        pass
    
    def format_message(self, alert: Alert) -> Dict[str, str]:
        """Format alert message"""
        return {
            'title': f"[{alert.severity.upper()}] {alert.rule.name}",
            'message': alert.message,
            'description': alert.rule.description,
            'value': f"{alert.value:.2f}",
            'threshold': f"{alert.rule.threshold:.2f}",
            'condition': alert.rule.condition,
            'labels': alert.labels,
            'annotations': alert.annotations,
            'fired_at': alert.fired_at.isoformat(),
        }
    
    def record_notification(self, alert: Alert, success: bool, error_message: str = '') -> None:
        """Record notification attempt"""
        AlertNotification.objects.create(
            alert=alert,
            channel=self.channel,
            success=success,
            error_message=error_message
        )


class EmailChannel(NotificationChannel):
    """Email notification channel"""
    
    def send(self, alert: Alert) -> bool:
        """Send email notification"""
        try:
            recipients = self.config.get('recipients', [])
            if not recipients:
                logger.error(f"No recipients configured for email channel {self.channel.name}")
                return False
            
            data = self.format_message(alert)
            
            # Render email template
            subject = f"{data['title']}"
            html_message = render_to_string('alerts/email_notification.html', data)
            text_message = render_to_string('alerts/email_notification.txt', data)
            
            # Send email
            send_mail(
                subject=subject,
                message=text_message,
                html_message=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=False
            )
            
            self.record_notification(alert, True)
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            self.record_notification(alert, False, str(e))
            return False


class SlackChannel(NotificationChannel):
    """Slack notification channel"""
    
    def send(self, alert: Alert) -> bool:
        """Send Slack notification"""
        try:
            webhook_url = self.config.get('webhook_url')
            if not webhook_url:
                logger.error(f"No webhook URL configured for Slack channel {self.channel.name}")
                return False
            
            data = self.format_message(alert)
            
            # Format Slack message
            color = {
                'info': '#36a64f',
                'warning': '#ff9800',
                'error': '#f44336',
                'critical': '#d32f2f'
            }.get(alert.severity, '#808080')
            
            payload = {
                'attachments': [{
                    'color': color,
                    'title': data['title'],
                    'text': data['message'],
                    'fields': [
                        {
                            'title': 'Value',
                            'value': f"{data['value']} {data['condition']} {data['threshold']}",
                            'short': True
                        },
                        {
                            'title': 'Time',
                            'value': data['fired_at'],
                            'short': True
                        }
                    ],
                    'footer': 'EnterpriseLand Alerts',
                    'ts': int(alert.fired_at.timestamp())
                }]
            }
            
            # Add custom channel if specified
            channel = self.config.get('channel')
            if channel:
                payload['channel'] = channel
            
            # Send to Slack
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            
            self.record_notification(alert, True)
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            self.record_notification(alert, False, str(e))
            return False


class PagerDutyChannel(NotificationChannel):
    """PagerDuty notification channel"""
    
    def send(self, alert: Alert) -> bool:
        """Send PagerDuty notification"""
        try:
            integration_key = self.config.get('integration_key')
            if not integration_key:
                logger.error(f"No integration key configured for PagerDuty channel {self.channel.name}")
                return False
            
            data = self.format_message(alert)
            
            # Map severity to PagerDuty severity
            severity = {
                'info': 'info',
                'warning': 'warning',
                'error': 'error',
                'critical': 'critical'
            }.get(alert.severity, 'error')
            
            # Create PagerDuty event
            payload = {
                'routing_key': integration_key,
                'event_action': 'trigger',
                'dedup_key': alert.fingerprint,
                'payload': {
                    'summary': data['title'],
                    'source': 'EnterpriseLand',
                    'severity': severity,
                    'custom_details': {
                        'message': data['message'],
                        'value': data['value'],
                        'threshold': data['threshold'],
                        'condition': data['condition'],
                        'labels': data['labels'],
                        'annotations': data['annotations']
                    }
                }
            }
            
            # Send to PagerDuty
            response = requests.post(
                'https://events.pagerduty.com/v2/enqueue',
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            
            self.record_notification(alert, True)
            return True
            
        except Exception as e:
            logger.error(f"Failed to send PagerDuty notification: {e}")
            self.record_notification(alert, False, str(e))
            return False


class WebhookChannel(NotificationChannel):
    """Webhook notification channel"""
    
    def send(self, alert: Alert) -> bool:
        """Send webhook notification"""
        try:
            url = self.config.get('url')
            if not url:
                logger.error(f"No URL configured for webhook channel {self.channel.name}")
                return False
            
            data = self.format_message(alert)
            
            # Prepare webhook payload
            payload = {
                'alert_id': str(alert.id),
                'rule_name': alert.rule.name,
                'severity': alert.severity,
                'status': alert.status,
                **data
            }
            
            # Get custom headers
            headers = self.config.get('headers', {})
            headers['Content-Type'] = 'application/json'
            
            # Get authentication
            auth = None
            if self.config.get('auth_type') == 'basic':
                auth = (
                    self.config.get('username'),
                    self.config.get('password')
                )
            elif self.config.get('auth_type') == 'bearer':
                headers['Authorization'] = f"Bearer {self.config.get('token')}"
            
            # Send webhook
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                auth=auth,
                timeout=self.config.get('timeout', 30)
            )
            response.raise_for_status()
            
            self.record_notification(alert, True)
            return True
            
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
            self.record_notification(alert, False, str(e))
            return False


class SMSChannel(NotificationChannel):
    """SMS notification channel (placeholder for future implementation)"""
    
    def send(self, alert: Alert) -> bool:
        """Send SMS notification"""
        try:
            # This would integrate with services like Twilio, AWS SNS, etc.
            provider = self.config.get('provider', 'twilio')
            recipients = self.config.get('recipients', [])
            
            if not recipients:
                logger.error(f"No recipients configured for SMS channel {self.channel.name}")
                return False
            
            data = self.format_message(alert)
            
            # Format SMS message (limited to 160 chars)
            message = f"{data['title'][:50]}: {data['message'][:100]}"
            
            # Placeholder for actual SMS sending
            logger.info(f"Would send SMS to {recipients}: {message}")
            
            self.record_notification(alert, True)
            return True
            
        except Exception as e:
            logger.error(f"Failed to send SMS notification: {e}")
            self.record_notification(alert, False, str(e))
            return False


# Channel factory
CHANNEL_CLASSES = {
    'email': EmailChannel,
    'slack': SlackChannel,
    'pagerduty': PagerDutyChannel,
    'webhook': WebhookChannel,
    'sms': SMSChannel,
}


def get_channel_class(channel_type: str) -> Optional[type]:
    """Get channel class by type"""
    return CHANNEL_CLASSES.get(channel_type)