
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
import requests
import json
import logging

from .models import EmailNotification, WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)

@shared_task
def send_email_notification(email_notification_id):
    """Send email notification using the provider abstraction layer"""
    from asgiref.sync import async_to_sync
    from .email_integration import notification_email_service
    
    try:
        email_notification = EmailNotification.objects.get(id=email_notification_id)
        
        # If there's a related notification, use the template system
        if email_notification.notification:
            success = async_to_sync(notification_email_service.send_notification_email)(
                email_notification.notification,
                email_notification
            )
            if success:
                logger.info(f"Email sent to {email_notification.recipient_email} via provider")
            else:
                logger.error(f"Failed to send email to {email_notification.recipient_email}")
        else:
            # Fallback to simple email for backward compatibility
            from integrations.services.email import email_service
            
            result = async_to_sync(email_service.send_email)(
                to=email_notification.recipient_email,
                subject=email_notification.subject,
                html_content=email_notification.html_body,
                text_content=email_notification.body,
                tags=['notification', 'direct']
            )
            
            if result.success:
                email_notification.status = EmailNotification.Status.SENT
                email_notification.sent_at = timezone.now()
                email_notification.provider_message_id = result.message_id
                email_notification.save()
                logger.info(f"Email sent to {email_notification.recipient_email}")
            else:
                email_notification.status = EmailNotification.Status.FAILED
                email_notification.error_message = result.error_message or "Unknown error"
                email_notification.save()
                logger.error(f"Failed to send email to {email_notification.recipient_email}: {result.error_message}")
        
    except EmailNotification.DoesNotExist:
        logger.error(f"Email notification {email_notification_id} not found")
    except Exception as e:
        try:
            email_notification = EmailNotification.objects.get(id=email_notification_id)
            email_notification.status = EmailNotification.Status.FAILED
            email_notification.error_message = str(e)
            email_notification.save()
        except:
            pass
        
        logger.error(f"Failed to send email notification {email_notification_id}: {str(e)}")
        raise

@shared_task
def deliver_webhook(delivery_id):
    """Deliver webhook to endpoint"""
    try:
        delivery = WebhookDelivery.objects.get(id=delivery_id)
        endpoint = delivery.endpoint
        
        if not endpoint.is_active:
            logger.info(f"Webhook endpoint {endpoint.name} is inactive, skipping delivery")
            return
        
        # Prepare headers
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'CASA-Rule-Diligence-Platform/1.0'
        }
        
        if endpoint.secret_key:
            import hmac
            import hashlib
            
            payload_str = json.dumps(delivery.payload)
            signature = hmac.new(
                endpoint.secret_key.encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            headers['X-Signature-SHA256'] = f"sha256={signature}"
        
        # Make request
        delivery.attempt_count += 1
        delivery.save()
        
        response = requests.post(
            endpoint.url,
            json=delivery.payload,
            headers=headers,
            timeout=30
        )
        
        delivery.response_status_code = response.status_code
        delivery.response_body = response.text[:1000]  # Limit response body size
        
        if response.status_code < 400:
            delivery.status = WebhookDelivery.Status.SUCCESS
            delivery.delivered_at = timezone.now()
            logger.info(f"Webhook delivered to {endpoint.name}")
        else:
            delivery.status = WebhookDelivery.Status.FAILED
            delivery.error_message = f"HTTP {response.status_code}: {response.text[:500]}"
            logger.error(f"Webhook delivery failed to {endpoint.name}: {delivery.error_message}")
        
        delivery.save()
        
    except WebhookDelivery.DoesNotExist:
        logger.error(f"Webhook delivery {delivery_id} not found")
    except requests.exceptions.RequestException as e:
        delivery = WebhookDelivery.objects.get(id=delivery_id)
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.error_message = str(e)
        delivery.save()
        
        # Schedule retry if attempts remaining
        if delivery.attempt_count < delivery.max_attempts:
            retry_delay = min(300 * (2 ** delivery.attempt_count), 3600)  # Exponential backoff, max 1 hour
            delivery.status = WebhookDelivery.Status.RETRYING
            delivery.next_retry_at = timezone.now() + timezone.timedelta(seconds=retry_delay)
            delivery.save()
            
            deliver_webhook.apply_async(args=[delivery_id], countdown=retry_delay)
            logger.info(f"Webhook delivery scheduled for retry in {retry_delay} seconds")
        
        logger.error(f"Webhook delivery failed to {delivery.endpoint.name}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in webhook delivery {delivery_id}: {str(e)}")
        raise

@shared_task
def create_notification(recipient_id, notification_type, title, message, assessment_id=None, sender_id=None):
    """Create notification and optionally send email"""
    from accounts.models import User
    from .models import Notification
    
    try:
        recipient = User.objects.get(id=recipient_id)
        sender = User.objects.get(id=sender_id) if sender_id else None
        
        # Create notification
        notification = Notification.objects.create(
            recipient=recipient,
            sender=sender,
            type=notification_type,
            title=title,
            message=message,
            assessment_id=assessment_id
        )
        
        # Create email notification if user wants email alerts
        if hasattr(recipient, 'email_preferences') and recipient.email_preferences.get('notifications', True):
            email_notification = EmailNotification.objects.create(
                recipient_email=recipient.email,
                subject=title,
                body=message,
                notification=notification
            )
            
            # Send email asynchronously
            send_email_notification.delay(email_notification.id)
        
        logger.info(f"Notification created for {recipient.email}: {title}")
        
    except User.DoesNotExist:
        logger.error(f"User {recipient_id} not found")
    except Exception as e:
        logger.error(f"Failed to create notification: {str(e)}")
        raise

@shared_task
def send_webhook_event(event_type, payload):
    """Send webhook event to all subscribed endpoints"""
    try:
        endpoints = WebhookEndpoint.objects.filter(
            is_active=True,
            events__contains=[event_type]
        )
        
        for endpoint in endpoints:
            delivery = WebhookDelivery.objects.create(
                endpoint=endpoint,
                event_type=event_type,
                payload=payload
            )
            
            # Deliver webhook asynchronously
            deliver_webhook.delay(delivery.id)
        
        logger.info(f"Webhook event {event_type} queued for {endpoints.count()} endpoints")
        
    except Exception as e:
        logger.error(f"Failed to send webhook event {event_type}: {str(e)}")
        raise

@shared_task
def cleanup_old_notifications():
    """Clean up old notifications and email logs"""
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=90)
    
    # Delete old read notifications
    deleted_notifications = Notification.objects.filter(
        is_read=True,
        read_at__lt=cutoff_date
    ).delete()[0]
    
    # Delete old email notifications
    deleted_emails = EmailNotification.objects.filter(
        created_at__lt=cutoff_date
    ).delete()[0]
    
    # Delete old webhook deliveries
    deleted_webhooks = WebhookDelivery.objects.filter(
        created_at__lt=cutoff_date
    ).delete()[0]
    
    logger.info(f"Cleaned up {deleted_notifications} notifications, {deleted_emails} emails, {deleted_webhooks} webhook deliveries")
    
    return {
        'notifications': deleted_notifications,
        'emails': deleted_emails,
        'webhooks': deleted_webhooks
    }
