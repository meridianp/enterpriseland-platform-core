"""Notification service for sending alerts and reports."""

import logging
from typing import Dict, List, Optional
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications."""
    
    def send_notification(self, user, subject: str, message: str, notification_type: str = 'info'):
        """Send a notification to a user."""
        # This would integrate with your notification system
        # For now, we'll just log it
        logger.info(f"Notification to {user.email}: {subject}")
        
        # You could also create an in-app notification here
        # Notification.objects.create(
        #     user=user,
        #     subject=subject,
        #     message=message,
        #     type=notification_type,
        # )
    
    def send_email(self, to: str, subject: str, body: str, html_body: str = None):
        """Send an email notification."""
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to],
                html_message=html_body,
                fail_silently=False,
            )
            logger.info(f"Email sent to {to}: {subject}")
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {str(e)}")
            raise
    
    def send_report_email(self, report_data: Dict, recipients: List[str], subject: str = None):
        """Send a report via email."""
        report = report_data.get('report', {})
        
        if not subject:
            subject = f"Report: {report.get('name', 'Report')}"
        
        # Render email body
        try:
            html_body = render_to_string('reporting/emails/report.html', {
                'report_data': report_data,
                'report_name': report.get('name'),
                'generated_at': report.get('generated_at'),
            })
        except:
            # Fallback to plain text
            html_body = None
        
        body = f"""
Report: {report.get('name', 'Report')}
Generated: {report.get('generated_at', 'N/A')}

This report has been generated and is ready for viewing.
Please log in to the platform to view the full report.
        """
        
        for recipient in recipients:
            self.send_email(recipient, subject, body, html_body)
    
    def send_alert_email(self, alert_data: Dict, recipients: List[str]):
        """Send an alert notification via email."""
        severity_emoji = {
            'info': 'ℹ️',
            'warning': '⚠️',
            'error': '❌',
            'critical': '🚨',
        }
        
        severity = alert_data.get('severity', 'info')
        emoji = severity_emoji.get(severity, '')
        
        subject = f"{emoji} [{severity.upper()}] {alert_data.get('alert_name', 'Alert')}"
        
        body = f"""
Alert Triggered: {alert_data.get('alert_name')}
Severity: {severity.upper()}

Metric: {alert_data.get('metric_name')}
Current Value: {alert_data.get('formatted_value')}
Change: {alert_data.get('change_value')} ({alert_data.get('change_percentage', 0):.1f}%)

Triggered at: {alert_data.get('triggered_at')}

Please log in to the platform for more details.
        """
        
        for recipient in recipients:
            self.send_email(recipient, subject, body)