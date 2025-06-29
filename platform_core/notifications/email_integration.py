"""
Email integration for notifications using the provider abstraction layer.
"""
import logging
from typing import Dict, Optional, Any
from django.conf import settings
from asgiref.sync import async_to_sync, sync_to_async

from integrations.services.email import email_service
from integrations.providers.email.base import EmailAttachment
from .models import Notification, EmailNotification

logger = logging.getLogger(__name__)


class NotificationEmailService:
    """
    Service for sending notification emails using the provider abstraction layer.
    Maps notification types to email templates and handles email sending.
    """
    
    # Map notification types to email template slugs
    TEMPLATE_MAP = {
        Notification.Type.ASSESSMENT_CREATED: 'assessment-update',
        Notification.Type.ASSESSMENT_UPDATED: 'assessment-update',
        Notification.Type.ASSESSMENT_APPROVED: 'assessment-update',
        Notification.Type.ASSESSMENT_REJECTED: 'assessment-update',
        Notification.Type.ASSESSMENT_NEEDS_INFO: 'assessment-update',
        Notification.Type.FILE_UPLOADED: 'general-follow-up',
        Notification.Type.COMMENT_ADDED: 'general-follow-up',
        Notification.Type.SYSTEM_ALERT: 'general-follow-up',
    }
    
    # Status-specific template data
    STATUS_COLORS = {
        'approved': '#BED600',  # Green
        'rejected': '#E37222',  # Orange
        'needs_info': '#00B7B2',  # Turquoise
        'created': '#215788',  # Deep Blue
        'updated': '#3C3C3B',  # Charcoal
    }
    
    async def send_notification_email(
        self,
        notification: Notification,
        email_notification: EmailNotification
    ) -> bool:
        """
        Send an email for a notification using the appropriate template.
        
        Args:
            notification: The notification object
            email_notification: The email notification tracking object
            
        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        try:
            # Get template slug based on notification type
            template_slug = self.TEMPLATE_MAP.get(
                notification.type,
                'general-follow-up'  # Default template
            )
            
            # Build template data
            template_data = await self._build_template_data(notification)
            
            # Send email using email service
            result = await email_service.send_email(
                to=email_notification.recipient_email,
                subject=None,  # Will use template subject
                template_id=template_slug,
                template_data=template_data,
                metadata={
                    'notification_id': str(notification.id),
                    'email_notification_id': str(email_notification.id),
                    'notification_type': notification.type
                },
                tags=['notification', notification.type]
            )
            
            if result.success:
                # Update email notification status
                email_notification.status = EmailNotification.Status.SENT
                email_notification.sent_at = result.timestamp
                email_notification.provider_message_id = result.message_id
                await sync_to_async(email_notification.save)()
                
                logger.info(
                    f"Email sent successfully for notification {notification.id} "
                    f"to {email_notification.recipient_email}"
                )
                return True
            else:
                # Update with error
                email_notification.status = EmailNotification.Status.FAILED
                email_notification.error_message = result.error_message or "Unknown error"
                await sync_to_async(email_notification.save)()
                
                logger.error(
                    f"Failed to send email for notification {notification.id}: "
                    f"{result.error_message}"
                )
                return False
                
        except Exception as e:
            logger.error(
                f"Exception sending email for notification {notification.id}: {str(e)}",
                exc_info=True
            )
            
            # Update email notification with error
            email_notification.status = EmailNotification.Status.FAILED
            email_notification.error_message = str(e)
            await sync_to_async(email_notification.save)()
            
            return False
    
    async def _build_template_data(self, notification: Notification) -> Dict[str, Any]:
        """
        Build template data based on notification type and content.
        """
        # Get related objects using sync_to_async
        recipient = await sync_to_async(lambda: notification.recipient)()
        sender = await sync_to_async(lambda: notification.sender)() if notification.sender_id else None
        
        # Base template data
        template_data = {
            'first_name': recipient.first_name,
            'email': recipient.email,
            'notification_title': notification.title,
            'notification_message': notification.message,
            'app_url': getattr(settings, 'FRONTEND_URL', 'https://app.enterpriseland.com'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@enterpriseland.com'),
        }
        
        # Add sender information if available
        if sender:
            template_data.update({
                'sender_name': sender.get_full_name(),
                'sender_email': sender.email,
                'sender_title': getattr(sender, 'title', 'Team Member')
            })
        
        # Add assessment-specific data
        if notification.assessment_id:
            assessment = await sync_to_async(lambda: notification.assessment)()
            partner = await sync_to_async(lambda: assessment.development_partner)()
            
            # Determine status color
            status_key = 'created'
            if 'approved' in notification.type.lower():
                status_key = 'approved'
            elif 'rejected' in notification.type.lower():
                status_key = 'rejected'
            elif 'needs_info' in notification.type.lower():
                status_key = 'needs_info'
            elif 'updated' in notification.type.lower():
                status_key = 'updated'
            
            template_data.update({
                # Assessment data
                'partner_name': partner.name,
                'assessment_status': assessment.get_status_display(),
                'assessment_type': assessment.assessment_type,
                'assessment_url': f"{template_data['app_url']}/assessments/{assessment.id}",
                'status_color': self.STATUS_COLORS.get(status_key, '#3C3C3B'),
                'status_message': notification.message,
                
                # Additional context
                'updated_by': sender.get_full_name() if sender else 'System',
            })
            
            # Add next steps for certain statuses
            if notification.type == Notification.Type.ASSESSMENT_NEEDS_INFO:
                template_data['next_steps'] = [
                    'Review the requested information',
                    'Update the assessment with missing details',
                    'Resubmit for review'
                ]
            elif notification.type == Notification.Type.ASSESSMENT_APPROVED:
                template_data['next_steps'] = [
                    'Proceed with partnership agreement',
                    'Schedule kickoff meeting',
                    'Begin project implementation'
                ]
        
        # Add file-specific data
        if notification.type == Notification.Type.FILE_UPLOADED:
            template_data.update({
                'subject_line': 'New file uploaded',
                'follow_up_preview': 'A new file has been uploaded to your assessment',
                'follow_up_message': notification.message,
                'action_url': template_data.get('assessment_url', template_data['app_url']),
                'action_button_text': 'View File',
                'closing_message': 'Thank you for using EnterpriseLand.'
            })
        
        # Add comment-specific data
        elif notification.type == Notification.Type.COMMENT_ADDED:
            template_data.update({
                'subject_line': 'New comment added',
                'follow_up_preview': 'Someone commented on your assessment',
                'follow_up_message': notification.message,
                'action_url': template_data.get('assessment_url', template_data['app_url']),
                'action_button_text': 'View Comment',
                'closing_message': 'Stay engaged with your team on EnterpriseLand.'
            })
        
        # Add system alert data
        elif notification.type == Notification.Type.SYSTEM_ALERT:
            template_data.update({
                'subject_line': 'System notification',
                'follow_up_preview': 'Important system update',
                'follow_up_message': notification.message,
                'action_url': template_data['app_url'],
                'action_button_text': 'View Details',
                'closing_message': 'Thank you for your attention to this matter.'
            })
        
        return template_data
    
    async def send_lead_notification_email(
        self,
        lead_data: Dict[str, Any],
        recipient_email: str,
        recipient_name: str
    ) -> bool:
        """
        Send a lead notification email using the lead-notification template.
        
        Args:
            lead_data: Dictionary containing lead information
            recipient_email: Email address to send to
            recipient_name: Recipient's name
            
        Returns:
            bool: True if email was sent successfully
        """
        try:
            # Build template data for lead notification
            template_data = {
                'first_name': recipient_name.split()[0] if recipient_name else 'Team',
                'lead_company': lead_data.get('company_name', 'Unknown Company'),
                'lead_score': lead_data.get('score', 0),
                'contact_name': lead_data.get('contact_name', 'N/A'),
                'contact_title': lead_data.get('contact_title', 'N/A'),
                'lead_source': lead_data.get('source', 'Market Intelligence'),
                'lead_priority': lead_data.get('priority', 'Medium'),
                'priority_color': self._get_priority_color(lead_data.get('priority', 'Medium')),
                'lead_url': f"{getattr(settings, 'FRONTEND_URL', '')}/leads/{lead_data.get('id', '')}",
                'key_insights': lead_data.get('insights', []),
                'app_url': getattr(settings, 'FRONTEND_URL', 'https://app.enterpriseland.com'),
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@enterpriseland.com'),
            }
            
            # Send email
            result = await email_service.send_email(
                to=recipient_email,
                subject=None,  # Will use template subject
                template_id='lead-notification',
                template_data=template_data,
                metadata={
                    'lead_id': str(lead_data.get('id', '')),
                    'notification_type': 'lead_notification'
                },
                tags=['lead', 'notification']
            )
            
            return result.success
            
        except Exception as e:
            logger.error(
                f"Exception sending lead notification email to {recipient_email}: {str(e)}",
                exc_info=True
            )
            return False
    
    def _get_priority_color(self, priority: str) -> str:
        """Get color for priority level."""
        priority_colors = {
            'High': '#E37222',  # Orange
            'Medium': '#00B7B2',  # Turquoise
            'Low': '#3C3C3B',  # Charcoal
        }
        return priority_colors.get(priority, '#3C3C3B')


# Global instance
notification_email_service = NotificationEmailService()