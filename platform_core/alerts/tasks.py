"""
Alert Background Tasks
"""
import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .services import AlertManager
from .models import Alert, AlertStatus, AlertSilence

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_alerts(self):
    """Process alert rules and send notifications"""
    try:
        manager = AlertManager()
        manager.process_alerts()
        logger.info("Alert processing completed")
    except Exception as e:
        logger.error(f"Alert processing failed: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def cleanup_old_alerts():
    """Clean up old resolved alerts"""
    try:
        # Get retention period from settings
        retention_days = getattr(settings, 'ALERT_RETENTION_DAYS', 30)
        cutoff_date = timezone.now() - timezone.timedelta(days=retention_days)
        
        # Delete old resolved alerts
        deleted_count = Alert.objects.filter(
            status=AlertStatus.RESOLVED.value,
            resolved_at__lt=cutoff_date
        ).delete()[0]
        
        logger.info(f"Deleted {deleted_count} old alerts")
        
    except Exception as e:
        logger.error(f"Alert cleanup failed: {e}")


@shared_task
def expire_silences():
    """Expire old alert silences"""
    try:
        now = timezone.now()
        
        # Find expired silences
        expired = AlertSilence.objects.filter(
            active=True,
            ends_at__lt=now
        ).update(active=False)
        
        logger.info(f"Expired {expired} alert silences")
        
    except Exception as e:
        logger.error(f"Silence expiration failed: {e}")


@shared_task
def alert_health_check():
    """Health check for alerting system"""
    try:
        # Check if alert processing is working
        last_alert = Alert.objects.order_by('-fired_at').first()
        
        if last_alert:
            time_since_last = timezone.now() - last_alert.fired_at
            if time_since_last.total_seconds() > 3600:  # 1 hour
                logger.warning("No alerts fired in the last hour")
        
        # Check for stuck alerts
        stuck_count = Alert.objects.filter(
            status=AlertStatus.PENDING.value,
            fired_at__lt=timezone.now() - timezone.timedelta(minutes=30)
        ).count()
        
        if stuck_count > 0:
            logger.error(f"Found {stuck_count} stuck alerts")
        
        return True
        
    except Exception as e:
        logger.error(f"Alert health check failed: {e}")
        return False


@shared_task
def send_alert_summary():
    """Send daily alert summary"""
    try:
        from django.core.mail import send_mail
        from django.template.loader import render_to_string
        
        manager = AlertManager()
        stats = manager.get_alert_stats()
        
        # Only send if there were alerts
        if stats['last_24h'] == 0:
            return
        
        # Render email
        subject = f"EnterpriseLand Alert Summary - {stats['last_24h']} alerts in last 24h"
        html_message = render_to_string('alerts/daily_summary.html', {'stats': stats})
        text_message = render_to_string('alerts/daily_summary.txt', {'stats': stats})
        
        # Send to configured recipients
        recipients = getattr(settings, 'ALERT_SUMMARY_RECIPIENTS', [])
        if recipients:
            send_mail(
                subject=subject,
                message=text_message,
                html_message=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=False
            )
            
            logger.info(f"Sent alert summary to {len(recipients)} recipients")
        
    except Exception as e:
        logger.error(f"Failed to send alert summary: {e}")