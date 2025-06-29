"""
Tests for notification email integration.
"""
import asyncio
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch, Mock

from accounts.models import Group
from assessments.models import Assessment, DevelopmentPartner
from integrations.testing import get_test_provider_config
from .models import Notification, EmailNotification
from .email_integration import notification_email_service
from .tasks import send_email_notification, create_notification

User = get_user_model()


def run_async_test(coro):
    """Helper to run async tests in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@override_settings(
    PROVIDER_CONFIG=get_test_provider_config(),
    CELERY_TASK_ALWAYS_EAGER=True  # Execute tasks synchronously in tests
)
class TestNotificationEmailIntegration(TestCase):
    """Test notification system integration with email providers."""
    
    def setUp(self):
        """Set up test data."""
        # Create test group and users
        self.group = Group.objects.create(name='test_group')
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        self.user.group = self.group
        self.user.save()
        
        self.sender = User.objects.create_user(
            username='sender',
            email='sender@example.com',
            password='testpass123',
            first_name='Sender',
            last_name='User'
        )
        self.sender.group = self.group
        self.sender.save()
        
        # We'll create assessment-related objects only when needed in specific tests
    
    def test_send_notification_with_email(self):
        """Test creating a notification that triggers an email."""
        # Create notification without assessment
        notification = Notification.objects.create(
            recipient=self.user,
            sender=self.sender,
            type=Notification.Type.SYSTEM_ALERT,
            title='System Alert',
            message='This is an important system notification.'
        )
        
        # Create email notification
        email_notification = EmailNotification.objects.create(
            recipient_email=self.user.email,
            subject='Assessment Updated',
            body='Your assessment has been updated.',
            notification=notification
        )
        
        # Send email using task
        send_email_notification(str(email_notification.id))
        
        # Refresh from database
        email_notification.refresh_from_db()
        
        # Check that email was sent
        self.assertEqual(email_notification.status, EmailNotification.Status.SENT)
        self.assertIsNotNone(email_notification.sent_at)
        self.assertIsNotNone(email_notification.provider_message_id)
    
    def test_notification_email_service_assessment_approved(self):
        """Test email service for assessment approved notification."""
        # Create notification without assessment for simplicity
        notification = Notification.objects.create(
            recipient=self.user,
            sender=self.sender,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title='Assessment Approved',
            message='Congratulations! Your assessment has been approved.'
        )
        
        email_notification = EmailNotification.objects.create(
            recipient_email=self.user.email,
            subject='Assessment Approved',
            body='Your assessment has been approved.',
            notification=notification
        )
        
        # Send email
        success = run_async_test(
            notification_email_service.send_notification_email(
                notification,
                email_notification
            )
        )
        
        self.assertTrue(success)
        
        # Check email notification was updated
        email_notification.refresh_from_db()
        self.assertEqual(email_notification.status, EmailNotification.Status.SENT)
    
    def test_notification_email_service_assessment_rejected(self):
        """Test email service for assessment rejected notification."""
        notification = Notification.objects.create(
            recipient=self.user,
            sender=self.sender,
            type=Notification.Type.ASSESSMENT_REJECTED,
            title='Assessment Rejected',
            message='Your assessment requires additional information.'
        )
        
        email_notification = EmailNotification.objects.create(
            recipient_email=self.user.email,
            subject='Assessment Rejected',
            body='Your assessment has been rejected.',
            notification=notification
        )
        
        # Send email
        success = run_async_test(
            notification_email_service.send_notification_email(
                notification,
                email_notification
            )
        )
        
        self.assertTrue(success)
    
    def test_create_notification_task_with_email(self):
        """Test create_notification task that sends email."""
        # Mock user email preferences
        with patch.object(self.user, 'email_preferences', {'notifications': True}):
            # Create notification using task
            create_notification(
                recipient_id=str(self.user.id),
                notification_type=Notification.Type.ASSESSMENT_CREATED,
                title='New Assessment Created',
                message='A new assessment has been created for review.',
                assessment_id=None,  # No assessment for this test
                sender_id=str(self.sender.id)
            )
        
        # Check notification was created
        notification = Notification.objects.filter(
            recipient=self.user,
            type=Notification.Type.ASSESSMENT_CREATED
        ).first()
        self.assertIsNotNone(notification)
        
        # Check email notification was created
        email_notification = EmailNotification.objects.filter(
            notification=notification
        ).first()
        self.assertIsNotNone(email_notification)
    
    def test_send_lead_notification_email(self):
        """Test sending lead notification email."""
        lead_data = {
            'id': '12345',
            'company_name': 'Acme Corp',
            'score': 85,
            'contact_name': 'John Doe',
            'contact_title': 'CEO',
            'source': 'Market Intelligence',
            'priority': 'High',
            'insights': [
                'Strong market presence in target sector',
                'Recent funding round of $10M',
                'Expanding into new markets'
            ]
        }
        
        success = run_async_test(
            notification_email_service.send_lead_notification_email(
                lead_data,
                self.user.email,
                self.user.get_full_name()
            )
        )
        
        self.assertTrue(success)
    
    def test_fallback_to_simple_email(self):
        """Test fallback when no notification is linked."""
        # Create email notification without linked notification
        email_notification = EmailNotification.objects.create(
            recipient_email=self.user.email,
            subject='Simple Email Test',
            body='This is a simple email test.',
            html_body='<h1>Simple Email Test</h1><p>This is a test.</p>'
        )
        
        # Send email using task
        send_email_notification(str(email_notification.id))
        
        # Check that email was sent
        email_notification.refresh_from_db()
        self.assertEqual(email_notification.status, EmailNotification.Status.SENT)
        self.assertIsNotNone(email_notification.provider_message_id)
    
    def test_email_failure_handling(self):
        """Test handling of email send failures."""
        notification = Notification.objects.create(
            recipient=self.user,
            type=Notification.Type.SYSTEM_ALERT,
            title='System Alert',
            message='This email will fail to send.'
        )
        
        email_notification = EmailNotification.objects.create(
            recipient_email='invalid-email',  # Invalid email
            subject='Will Fail',
            body='This will fail.',
            notification=notification
        )
        
        # Send email
        success = run_async_test(
            notification_email_service.send_notification_email(
                notification,
                email_notification
            )
        )
        
        self.assertFalse(success)
        
        # Check email notification status
        email_notification.refresh_from_db()
        self.assertEqual(email_notification.status, EmailNotification.Status.FAILED)
        self.assertIsNotNone(email_notification.error_message)
    
    def test_template_data_building(self):
        """Test template data building for different notification types."""
        # Test notification without assessment
        notification = Notification.objects.create(
            recipient=self.user,
            sender=self.sender,
            type=Notification.Type.SYSTEM_ALERT,
            title='System Alert',
            message='Important system notification.'
        )
        
        template_data = notification_email_service._build_template_data(notification)
        
        self.assertEqual(template_data['first_name'], 'Test')
        self.assertEqual(template_data['sender_name'], 'Sender User')
        self.assertIn('app_url', template_data)
        self.assertIn('support_email', template_data)
        
        # Test file upload notification
        file_notification = Notification.objects.create(
            recipient=self.user,
            sender=self.sender,
            type=Notification.Type.FILE_UPLOADED,
            title='New File Uploaded',
            message='A new document has been uploaded to your assessment.'
        )
        
        file_template_data = notification_email_service._build_template_data(file_notification)
        
        self.assertEqual(file_template_data['action_button_text'], 'View File')
        self.assertEqual(file_template_data['subject_line'], 'New file uploaded')