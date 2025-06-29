"""
Tests for notifications Celery tasks.
"""
from django.test import TestCase
from django.core import mail
from django.utils import timezone
from unittest.mock import patch, Mock, MagicMock
from datetime import timedelta
import requests
import json

from tests.base import BaseTestCase
from tests.factories.assessment_factories import AssessmentFactory
from notifications.models import Notification, EmailNotification, WebhookEndpoint, WebhookDelivery
from notifications.tasks import (
    send_email_notification, deliver_webhook, create_notification,
    send_webhook_event, cleanup_old_notifications
)


class SendEmailNotificationTaskTest(BaseTestCase):
    """Test send_email_notification Celery task."""
    
    def test_successful_email_send(self):
        """Test successful email sending."""
        email_notification = EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Test Email Subject",
            body="Test email body content",
            html_body="<p>Test HTML content</p>"
        )
        
        with patch('django.core.mail.send_mail') as mock_send_mail:
            mock_send_mail.return_value = True
            
            with patch('django.utils.timezone.now') as mock_now:
                mock_time = timezone.now()
                mock_now.return_value = mock_time
                
                send_email_notification(email_notification.id)
                
                # Verify email was sent
                mock_send_mail.assert_called_once_with(
                    subject="Test Email Subject",
                    message="Test email body content",
                    from_email=None,  # Uses DEFAULT_FROM_EMAIL from settings
                    recipient_list=["test@example.com"],
                    html_message="<p>Test HTML content</p>",
                    fail_silently=False
                )
                
                # Verify status was updated
                email_notification.refresh_from_db()
                self.assertEqual(email_notification.status, EmailNotification.Status.SENT)
                self.assertEqual(email_notification.sent_at, mock_time)
                
    def test_email_send_failure(self):
        """Test email sending failure handling."""
        email_notification = EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Test Subject",
            body="Test body"
        )
        
        with patch('django.core.mail.send_mail') as mock_send_mail:
            mock_send_mail.side_effect = Exception("SMTP server error")
            
            with self.assertRaises(Exception):
                send_email_notification(email_notification.id)
                
            # Verify status was updated
            email_notification.refresh_from_db()
            self.assertEqual(email_notification.status, EmailNotification.Status.FAILED)
            self.assertEqual(email_notification.error_message, "SMTP server error")
            
    def test_email_notification_not_found(self):
        """Test handling of non-existent email notification."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        
        with patch('notifications.tasks.logger') as mock_logger:
            send_email_notification(fake_id)
            
            mock_logger.error.assert_called_with(
                f"Email notification {fake_id} not found"
            )
            
    def test_email_without_html_body(self):
        """Test email sending without HTML body."""
        email_notification = EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Plain Text Email",
            body="Plain text content only"
            # No html_body
        )
        
        with patch('django.core.mail.send_mail') as mock_send_mail:
            send_email_notification(email_notification.id)
            
            # Verify html_message is None when html_body is empty
            mock_send_mail.assert_called_once()
            call_kwargs = mock_send_mail.call_args[1]
            self.assertIsNone(call_kwargs['html_message'])


class DeliverWebhookTaskTest(BaseTestCase):
    """Test deliver_webhook Celery task."""
    
    def setUp(self):
        super().setUp()
        self.endpoint = WebhookEndpoint.objects.create(
            name="Test Webhook",
            url="https://example.com/webhook",
            secret_key="secret123",
            is_active=True,
            created_by=self.admin_user
        )
        
        self.payload = {
            "event": "assessment.created",
            "timestamp": "2023-01-01T00:00:00Z",
            "data": {"assessment_id": "123"}
        }
        
    def test_successful_webhook_delivery(self):
        """Test successful webhook delivery."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="assessment.created",
            payload=self.payload
        )
        
        with patch('requests.post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_post.return_value = mock_response
            
            with patch('django.utils.timezone.now') as mock_now:
                mock_time = timezone.now()
                mock_now.return_value = mock_time
                
                deliver_webhook(delivery.id)
                
                # Verify request was made
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                
                self.assertEqual(call_args[1]['json'], self.payload)
                self.assertEqual(call_args[0][0], self.endpoint.url)
                self.assertIn('Content-Type', call_args[1]['headers'])
                self.assertIn('X-Signature-SHA256', call_args[1]['headers'])
                
                # Verify delivery status
                delivery.refresh_from_db()
                self.assertEqual(delivery.status, WebhookDelivery.Status.SUCCESS)
                self.assertEqual(delivery.response_status_code, 200)
                self.assertEqual(delivery.response_body, "OK")
                self.assertEqual(delivery.delivered_at, mock_time)
                self.assertEqual(delivery.attempt_count, 1)
                
    def test_webhook_delivery_failure(self):
        """Test webhook delivery failure."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="assessment.created",
            payload=self.payload
        )
        
        with patch('requests.post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response
            
            deliver_webhook(delivery.id)
            
            # Verify delivery status
            delivery.refresh_from_db()
            self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)
            self.assertEqual(delivery.response_status_code, 500)
            self.assertIn("HTTP 500", delivery.error_message)
            self.assertEqual(delivery.attempt_count, 1)
            
    def test_webhook_delivery_network_error_with_retry(self):
        """Test webhook delivery network error and retry scheduling."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="assessment.created",
            payload=self.payload,
            max_attempts=3
        )
        
        with patch('requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("Connection failed")
            
            with patch('notifications.tasks.deliver_webhook.apply_async') as mock_apply_async:
                deliver_webhook(delivery.id)
                
                # Verify retry was scheduled
                mock_apply_async.assert_called_once()
                call_args = mock_apply_async.call_args
                self.assertEqual(call_args[1]['args'], [delivery.id])
                self.assertIn('countdown', call_args[1])
                
                # Verify delivery status
                delivery.refresh_from_db()
                self.assertEqual(delivery.status, WebhookDelivery.Status.RETRYING)
                self.assertIsNotNone(delivery.next_retry_at)
                self.assertEqual(delivery.attempt_count, 1)
                
    def test_webhook_delivery_max_attempts_exceeded(self):
        """Test webhook delivery when max attempts exceeded."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="assessment.created",
            payload=self.payload,
            attempt_count=3,
            max_attempts=3
        )
        
        with patch('requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout("Request timeout")
            
            with patch('notifications.tasks.deliver_webhook.apply_async') as mock_apply_async:
                deliver_webhook(delivery.id)
                
                # Verify no retry was scheduled
                mock_apply_async.assert_not_called()
                
                # Verify delivery status
                delivery.refresh_from_db()
                self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)
                self.assertEqual(delivery.attempt_count, 4)  # Incremented but no retry
                
    def test_webhook_delivery_inactive_endpoint(self):
        """Test webhook delivery to inactive endpoint."""
        self.endpoint.is_active = False
        self.endpoint.save()
        
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="assessment.created",
            payload=self.payload
        )
        
        with patch('requests.post') as mock_post:
            deliver_webhook(delivery.id)
            
            # Verify no request was made
            mock_post.assert_not_called()
            
            # Delivery status should remain pending
            delivery.refresh_from_db()
            self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)
            
    def test_webhook_signature_generation(self):
        """Test webhook signature generation."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="assessment.created",
            payload=self.payload
        )
        
        with patch('requests.post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_post.return_value = mock_response
            
            deliver_webhook(delivery.id)
            
            # Verify signature header was included
            headers = mock_post.call_args[1]['headers']
            self.assertIn('X-Signature-SHA256', headers)
            self.assertTrue(headers['X-Signature-SHA256'].startswith('sha256='))
            
    def test_webhook_without_secret_key(self):
        """Test webhook delivery without secret key."""
        endpoint_without_secret = WebhookEndpoint.objects.create(
            name="No Secret Webhook",
            url="https://example.com/webhook",
            secret_key="",  # No secret
            is_active=True,
            created_by=self.admin_user
        )
        
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint_without_secret,
            event_type="assessment.created",
            payload=self.payload
        )
        
        with patch('requests.post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_post.return_value = mock_response
            
            deliver_webhook(delivery.id)
            
            # Verify no signature header was included
            headers = mock_post.call_args[1]['headers']
            self.assertNotIn('X-Signature-SHA256', headers)
            
    def test_webhook_delivery_not_found(self):
        """Test handling of non-existent webhook delivery."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        
        with patch('notifications.tasks.logger') as mock_logger:
            deliver_webhook(fake_id)
            
            mock_logger.error.assert_called_with(
                f"Webhook delivery {fake_id} not found"
            )


class CreateNotificationTaskTest(BaseTestCase):
    """Test create_notification Celery task."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
    def test_create_notification_success(self):
        """Test successful notification creation."""
        with patch('notifications.tasks.send_email_notification.delay') as mock_email_task:
            create_notification(
                recipient_id=str(self.analyst_user.id),
                notification_type=Notification.Type.ASSESSMENT_CREATED,
                title="Assessment Created",
                message="A new assessment has been created.",
                assessment_id=str(self.assessment.id),
                sender_id=str(self.manager_user.id)
            )
            
            # Verify notification was created
            notification = Notification.objects.get(
                recipient=self.analyst_user,
                type=Notification.Type.ASSESSMENT_CREATED
            )
            
            self.assertEqual(notification.title, "Assessment Created")
            self.assertEqual(notification.message, "A new assessment has been created.")
            self.assertEqual(notification.assessment, self.assessment)
            self.assertEqual(notification.sender, self.manager_user)
            
            # Verify email notification was created and task scheduled
            email_notification = EmailNotification.objects.get(notification=notification)
            self.assertEqual(email_notification.recipient_email, self.analyst_user.email)
            self.assertEqual(email_notification.subject, "Assessment Created")
            
            mock_email_task.assert_called_once_with(email_notification.id)
            
    def test_create_notification_without_email_preferences(self):
        """Test notification creation when user doesn't want emails."""
        # Mock user without email preferences
        with patch.object(self.analyst_user, 'email_preferences', {'notifications': False}):
            with patch('notifications.tasks.send_email_notification.delay') as mock_email_task:
                create_notification(
                    recipient_id=str(self.analyst_user.id),
                    notification_type=Notification.Type.SYSTEM_ALERT,
                    title="System Alert",
                    message="System maintenance scheduled."
                )
                
                # Verify notification was created
                notification = Notification.objects.get(
                    recipient=self.analyst_user,
                    type=Notification.Type.SYSTEM_ALERT
                )
                
                self.assertEqual(notification.title, "System Alert")
                
                # Verify no email notification was created
                self.assertFalse(
                    EmailNotification.objects.filter(notification=notification).exists()
                )
                mock_email_task.assert_not_called()
                
    def test_create_notification_without_sender(self):
        """Test creating system notification without sender."""
        create_notification(
            recipient_id=str(self.analyst_user.id),
            notification_type=Notification.Type.SYSTEM_ALERT,
            title="System Notification",
            message="This is a system-generated notification."
        )
        
        notification = Notification.objects.get(
            recipient=self.analyst_user,
            type=Notification.Type.SYSTEM_ALERT
        )
        
        self.assertIsNone(notification.sender)
        self.assertEqual(notification.title, "System Notification")
        
    def test_create_notification_recipient_not_found(self):
        """Test handling of non-existent recipient."""
        fake_user_id = "00000000-0000-0000-0000-000000000000"
        
        with patch('notifications.tasks.logger') as mock_logger:
            create_notification(
                recipient_id=fake_user_id,
                notification_type=Notification.Type.ASSESSMENT_CREATED,
                title="Test",
                message="Test message"
            )
            
            mock_logger.error.assert_called_with(f"User {fake_user_id} not found")
            
            # Verify no notification was created
            self.assertFalse(
                Notification.objects.filter(type=Notification.Type.ASSESSMENT_CREATED).exists()
            )


class SendWebhookEventTaskTest(BaseTestCase):
    """Test send_webhook_event Celery task."""
    
    def setUp(self):
        super().setUp()
        self.event_payload = {
            "event": "assessment.approved",
            "timestamp": "2023-01-01T00:00:00Z",
            "data": {"assessment_id": "123", "status": "approved"}
        }
        
    def test_send_webhook_event_to_subscribed_endpoints(self):
        """Test sending webhook event to subscribed endpoints."""
        # Create endpoints with different event subscriptions
        endpoint1 = WebhookEndpoint.objects.create(
            name="Assessment Webhook",
            url="https://example1.com/webhook",
            events=["assessment.created", "assessment.approved"],
            is_active=True,
            created_by=self.admin_user
        )
        
        endpoint2 = WebhookEndpoint.objects.create(
            name="File Webhook",
            url="https://example2.com/webhook",
            events=["file.uploaded"],
            is_active=True,
            created_by=self.admin_user
        )
        
        endpoint3 = WebhookEndpoint.objects.create(
            name="All Events Webhook",
            url="https://example3.com/webhook",
            events=["assessment.approved", "file.uploaded"],
            is_active=True,
            created_by=self.admin_user
        )
        
        with patch('notifications.tasks.deliver_webhook.delay') as mock_deliver:
            send_webhook_event("assessment.approved", self.event_payload)
            
            # Verify deliveries were created for subscribed endpoints only
            deliveries = WebhookDelivery.objects.filter(event_type="assessment.approved")
            self.assertEqual(deliveries.count(), 2)  # endpoint1 and endpoint3
            
            delivery_endpoints = [d.endpoint for d in deliveries]
            self.assertIn(endpoint1, delivery_endpoints)
            self.assertIn(endpoint3, delivery_endpoints)
            self.assertNotIn(endpoint2, delivery_endpoints)
            
            # Verify delivery tasks were scheduled
            self.assertEqual(mock_deliver.call_count, 2)
            
    def test_send_webhook_event_inactive_endpoints_excluded(self):
        """Test inactive endpoints are excluded from webhook events."""
        active_endpoint = WebhookEndpoint.objects.create(
            name="Active Webhook",
            url="https://active.example.com/webhook",
            events=["assessment.approved"],
            is_active=True,
            created_by=self.admin_user
        )
        
        inactive_endpoint = WebhookEndpoint.objects.create(
            name="Inactive Webhook",
            url="https://inactive.example.com/webhook",
            events=["assessment.approved"],
            is_active=False,
            created_by=self.admin_user
        )
        
        with patch('notifications.tasks.deliver_webhook.delay') as mock_deliver:
            send_webhook_event("assessment.approved", self.event_payload)
            
            # Verify only active endpoint received delivery
            deliveries = WebhookDelivery.objects.filter(event_type="assessment.approved")
            self.assertEqual(deliveries.count(), 1)
            self.assertEqual(deliveries.first().endpoint, active_endpoint)
            
            mock_deliver.assert_called_once()
            
    def test_send_webhook_event_no_subscribers(self):
        """Test webhook event with no subscribers."""
        # Create endpoint that doesn't subscribe to the event
        WebhookEndpoint.objects.create(
            name="Different Event Webhook",
            url="https://example.com/webhook",
            events=["file.uploaded"],
            is_active=True,
            created_by=self.admin_user
        )
        
        with patch('notifications.tasks.deliver_webhook.delay') as mock_deliver:
            send_webhook_event("assessment.approved", self.event_payload)
            
            # Verify no deliveries were created
            self.assertEqual(
                WebhookDelivery.objects.filter(event_type="assessment.approved").count(),
                0
            )
            mock_deliver.assert_not_called()


class CleanupOldNotificationsTaskTest(BaseTestCase):
    """Test cleanup_old_notifications Celery task."""
    
    def test_cleanup_old_read_notifications(self):
        """Test cleanup of old read notifications."""
        old_date = timezone.now() - timedelta(days=100)
        recent_date = timezone.now() - timedelta(days=30)
        
        # Create old read notification
        old_read_notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Old Read Notification",
            message="Old message",
            is_read=True,
            read_at=old_date
        )
        
        # Create recent read notification
        recent_read_notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_UPDATED,
            title="Recent Read Notification",
            message="Recent message",
            is_read=True,
            read_at=recent_date
        )
        
        # Create old unread notification (should not be deleted)
        old_unread_notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title="Old Unread Notification",
            message="Old unread message"
        )
        
        result = cleanup_old_notifications()
        
        # Verify old read notification was deleted
        self.assertFalse(
            Notification.objects.filter(id=old_read_notification.id).exists()
        )
        
        # Verify recent and unread notifications still exist
        self.assertTrue(
            Notification.objects.filter(id=recent_read_notification.id).exists()
        )
        self.assertTrue(
            Notification.objects.filter(id=old_unread_notification.id).exists()
        )
        
        self.assertEqual(result['notifications'], 1)
        
    def test_cleanup_old_email_notifications(self):
        """Test cleanup of old email notifications."""
        old_date = timezone.now() - timedelta(days=100)
        recent_date = timezone.now() - timedelta(days=30)
        
        # Create old email notification
        old_email = EmailNotification.objects.create(
            recipient_email="old@example.com",
            subject="Old Email",
            body="Old body",
            created_at=old_date
        )
        
        # Create recent email notification
        recent_email = EmailNotification.objects.create(
            recipient_email="recent@example.com",
            subject="Recent Email",
            body="Recent body",
            created_at=recent_date
        )
        
        # Manually update created_at since it's auto_now_add
        EmailNotification.objects.filter(id=old_email.id).update(created_at=old_date)
        EmailNotification.objects.filter(id=recent_email.id).update(created_at=recent_date)
        
        result = cleanup_old_notifications()
        
        # Verify old email was deleted
        self.assertFalse(
            EmailNotification.objects.filter(id=old_email.id).exists()
        )
        
        # Verify recent email still exists
        self.assertTrue(
            EmailNotification.objects.filter(id=recent_email.id).exists()
        )
        
        self.assertEqual(result['emails'], 1)
        
    def test_cleanup_old_webhook_deliveries(self):
        """Test cleanup of old webhook deliveries."""
        endpoint = WebhookEndpoint.objects.create(
            name="Test Webhook",
            url="https://example.com/webhook",
            created_by=self.admin_user
        )
        
        old_date = timezone.now() - timedelta(days=100)
        recent_date = timezone.now() - timedelta(days=30)
        
        # Create old webhook delivery
        old_delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_type="old.event",
            payload={"old": "data"},
            created_at=old_date
        )
        
        # Create recent webhook delivery
        recent_delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_type="recent.event",
            payload={"recent": "data"},
            created_at=recent_date
        )
        
        # Manually update created_at since it's auto_now_add
        WebhookDelivery.objects.filter(id=old_delivery.id).update(created_at=old_date)
        WebhookDelivery.objects.filter(id=recent_delivery.id).update(created_at=recent_date)
        
        result = cleanup_old_notifications()
        
        # Verify old delivery was deleted
        self.assertFalse(
            WebhookDelivery.objects.filter(id=old_delivery.id).exists()
        )
        
        # Verify recent delivery still exists
        self.assertTrue(
            WebhookDelivery.objects.filter(id=recent_delivery.id).exists()
        )
        
        self.assertEqual(result['webhooks'], 1)
        
    def test_cleanup_returns_counts(self):
        """Test cleanup task returns correct counts."""
        # Create items to be cleaned up
        old_date = timezone.now() - timedelta(days=100)
        
        # Create multiple old items
        for i in range(3):
            notification = Notification.objects.create(
                recipient=self.analyst_user,
                type=Notification.Type.ASSESSMENT_CREATED,
                title=f"Old Notification {i}",
                message=f"Old message {i}",
                is_read=True,
                read_at=old_date
            )
            
        result = cleanup_old_notifications()
        
        self.assertIn('notifications', result)
        self.assertIn('emails', result)
        self.assertIn('webhooks', result)
        self.assertEqual(result['notifications'], 3)


class NotificationTaskIntegrationTest(BaseTestCase):
    """Test integration between notification tasks."""
    
    def test_full_notification_workflow(self):
        """Test complete notification workflow from creation to email delivery."""
        assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
        # Step 1: Create notification
        with patch('notifications.tasks.send_email_notification.delay') as mock_email_task:
            create_notification(
                recipient_id=str(self.manager_user.id),
                notification_type=Notification.Type.ASSESSMENT_CREATED,
                title="New Assessment for Review",
                message="A new assessment has been submitted for your review.",
                assessment_id=str(assessment.id),
                sender_id=str(self.analyst_user.id)
            )
            
            # Verify notification created
            notification = Notification.objects.get(
                recipient=self.manager_user,
                type=Notification.Type.ASSESSMENT_CREATED
            )
            
            # Verify email notification created
            email_notification = EmailNotification.objects.get(notification=notification)
            
            # Step 2: Send email
            mock_email_task.assert_called_once_with(email_notification.id)
            
            with patch('django.core.mail.send_mail') as mock_send_mail:
                send_email_notification(email_notification.id)
                
                # Verify email was sent
                mock_send_mail.assert_called_once()
                
                email_notification.refresh_from_db()
                self.assertEqual(email_notification.status, EmailNotification.Status.SENT)
                
    def test_webhook_event_triggered_by_assessment_update(self):
        """Test webhook event triggered by assessment status change."""
        # Create webhook endpoint
        endpoint = WebhookEndpoint.objects.create(
            name="Assessment Webhook",
            url="https://external-system.com/webhook",
            events=["assessment.approved"],
            is_active=True,
            created_by=self.admin_user
        )
        
        assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
        event_payload = {
            "event": "assessment.approved",
            "timestamp": timezone.now().isoformat(),
            "data": {
                "assessment_id": str(assessment.id),
                "status": "approved",
                "approved_by": str(self.manager_user.id)
            }
        }
        
        # Send webhook event
        with patch('notifications.tasks.deliver_webhook.delay') as mock_deliver:
            send_webhook_event("assessment.approved", event_payload)
            
            # Verify webhook delivery was created and task scheduled
            delivery = WebhookDelivery.objects.get(
                endpoint=endpoint,
                event_type="assessment.approved"
            )
            
            self.assertEqual(delivery.payload, event_payload)
            mock_deliver.assert_called_once_with(delivery.id)
            
            # Deliver webhook
            with patch('requests.post') as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.text = "Webhook received"
                mock_post.return_value = mock_response
                
                deliver_webhook(delivery.id)
                
                # Verify webhook was delivered successfully
                delivery.refresh_from_db()
                self.assertEqual(delivery.status, WebhookDelivery.Status.SUCCESS)
                self.assertEqual(delivery.response_status_code, 200)