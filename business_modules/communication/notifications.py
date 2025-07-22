"""Notification dispatch system."""

import logging
from typing import Dict, Any, List, Optional

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from platform_core.integrations import EmailProvider, SMSProvider, PushProvider
from .models import Notification, NotificationPreference

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Dispatch notifications through various channels."""
    
    def __init__(self):
        """Initialize dispatcher with providers."""
        self.email_provider = EmailProvider()
        self.sms_provider = SMSProvider()
        self.push_provider = PushProvider()
    
    def dispatch(self, notification: Notification) -> Dict[str, bool]:
        """Dispatch notification through configured channels."""
        results = {}
        
        for channel in notification.channels:
            try:
                if channel == "in_app":
                    # In-app notifications are already created
                    results[channel] = True
                
                elif channel == "email":
                    results[channel] = self._send_email(notification)
                
                elif channel == "sms":
                    results[channel] = self._send_sms(notification)
                
                elif channel == "push":
                    results[channel] = self._send_push(notification)
                
                else:
                    logger.warning(f"Unknown notification channel: {channel}")
                    results[channel] = False
            
            except Exception as e:
                logger.error(f"Failed to send notification via {channel}: {e}")
                results[channel] = False
        
        # Update delivery status
        notification.delivery_status = results
        notification.save(update_fields=["delivery_status"])
        
        return results
    
    def _send_email(self, notification: Notification) -> bool:
        """Send email notification."""
        try:
            # Get email content
            subject = notification.title
            
            # Try to use HTML template
            try:
                html_content = render_to_string(
                    "communication/email/notification.html",
                    {
                        "notification": notification,
                        "user": notification.recipient,
                        "action_url": notification.action_url,
                    }
                )
            except Exception:
                html_content = None
            
            # Send email
            return self.email_provider.send(
                to=[notification.recipient.email],
                subject=subject,
                body=notification.content,
                html_body=html_content,
                metadata={
                    "notification_id": str(notification.id),
                    "notification_type": notification.notification_type,
                }
            )
        
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False
    
    def _send_sms(self, notification: Notification) -> bool:
        """Send SMS notification."""
        try:
            # Get user phone number
            phone = getattr(notification.recipient, "phone_number", None)
            if not phone:
                logger.warning(f"No phone number for user {notification.recipient}")
                return False
            
            # Truncate content for SMS
            sms_content = notification.content[:160]
            if len(notification.content) > 160:
                sms_content = sms_content[:157] + "..."
            
            return self.sms_provider.send(
                to=phone,
                message=sms_content,
                metadata={
                    "notification_id": str(notification.id),
                    "notification_type": notification.notification_type,
                }
            )
        
        except Exception as e:
            logger.error(f"Failed to send SMS notification: {e}")
            return False
    
    def _send_push(self, notification: Notification) -> bool:
        """Send push notification."""
        try:
            # Get user device tokens
            device_tokens = self._get_user_device_tokens(notification.recipient)
            if not device_tokens:
                logger.warning(f"No device tokens for user {notification.recipient}")
                return False
            
            # Send to all devices
            success_count = 0
            for token in device_tokens:
                result = self.push_provider.send(
                    token=token,
                    title=notification.title,
                    body=notification.content,
                    data={
                        "notification_id": str(notification.id),
                        "notification_type": notification.notification_type,
                        "action_url": notification.action_url,
                    },
                    badge=self._get_unread_count(notification.recipient),
                    sound="default" if notification.priority in ["HIGH", "URGENT"] else None,
                )
                if result:
                    success_count += 1
            
            return success_count > 0
        
        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")
            return False
    
    def _get_user_device_tokens(self, user) -> List[str]:
        """Get user's device tokens for push notifications."""
        # This would be implemented based on your device token storage
        # For example, from a UserDevice model
        return []
    
    def _get_unread_count(self, user) -> int:
        """Get unread notification count for badge."""
        return Notification.objects.filter(
            recipient=user,
            is_read=False,
            is_archived=False
        ).count()


class NotificationBatcher:
    """Batch notifications for efficient delivery."""
    
    def __init__(self):
        """Initialize batcher."""
        self.dispatcher = NotificationDispatcher()
    
    def process_batch(self, user, notifications: List[Notification]) -> bool:
        """Process a batch of notifications for a user."""
        if not notifications:
            return True
        
        try:
            # Group by type
            grouped = self._group_notifications(notifications)
            
            # Get user preferences
            try:
                preferences = user.notification_preferences
            except NotificationPreference.DoesNotExist:
                preferences = None
            
            # Send batched email if enabled
            if preferences and preferences.batch_email_notifications:
                self._send_batch_email(user, grouped)
            else:
                # Send individual notifications
                for notification in notifications:
                    self.dispatcher.dispatch(notification)
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to process notification batch: {e}")
            return False
    
    def _group_notifications(self, notifications: List[Notification]) -> Dict[str, List[Notification]]:
        """Group notifications by type."""
        grouped = {}
        for notification in notifications:
            type_key = notification.notification_type
            if type_key not in grouped:
                grouped[type_key] = []
            grouped[type_key].append(notification)
        return grouped
    
    def _send_batch_email(self, user, grouped_notifications: Dict[str, List[Notification]]) -> bool:
        """Send batched email notification."""
        try:
            # Render batch email template
            html_content = render_to_string(
                "communication/email/notification_batch.html",
                {
                    "user": user,
                    "grouped_notifications": grouped_notifications,
                    "total_count": sum(len(notifs) for notifs in grouped_notifications.values()),
                    "timestamp": timezone.now(),
                }
            )
            
            # Send email
            subject = f"You have {sum(len(notifs) for notifs in grouped_notifications.values())} new notifications"
            
            return send_mail(
                subject=subject,
                message="You have new notifications. Please view them in the app.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_content,
                fail_silently=False,
            )
        
        except Exception as e:
            logger.error(f"Failed to send batch email: {e}")
            return False


class NotificationScheduler:
    """Schedule notifications for future delivery."""
    
    @staticmethod
    def should_send_now(notification: Notification, preferences: Optional[NotificationPreference]) -> bool:
        """Check if notification should be sent now based on preferences."""
        if not preferences:
            return True
        
        # Check quiet hours
        if preferences.quiet_hours_enabled:
            current_time = timezone.now().time()
            if preferences.quiet_hours_start <= current_time <= preferences.quiet_hours_end:
                # During quiet hours, only send urgent notifications
                return notification.priority == "URGENT"
        
        return True
    
    @staticmethod
    def get_next_send_time(preferences: NotificationPreference) -> timezone.datetime:
        """Get next available send time based on quiet hours."""
        now = timezone.now()
        
        if not preferences.quiet_hours_enabled:
            return now
        
        current_time = now.time()
        
        # If we're in quiet hours, schedule for end of quiet hours
        if preferences.quiet_hours_start <= current_time <= preferences.quiet_hours_end:
            # Calculate next send time (end of quiet hours today or tomorrow)
            send_date = now.date()
            if current_time > preferences.quiet_hours_end:
                send_date += timezone.timedelta(days=1)
            
            return timezone.datetime.combine(
                send_date,
                preferences.quiet_hours_end,
                tzinfo=now.tzinfo
            )
        
        return now