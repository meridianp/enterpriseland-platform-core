"""
Tests for notifications models.
"""
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, Mock
import uuid

from tests.base import BaseTestCase
from tests.factories.assessment_factories import AssessmentFactory
from notifications.models import Notification, EmailNotification, WebhookEndpoint, WebhookDelivery


class NotificationModelTest(BaseTestCase):
    """Test Notification model."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
    def test_create_notification(self):
        """Test creating a notification."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            sender=self.manager_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="New Assessment Created",
            message="A new assessment has been created for review.",
            assessment=self.assessment
        )
        
        self.assertEqual(notification.recipient, self.analyst_user)
        self.assertEqual(notification.sender, self.manager_user)
        self.assertEqual(notification.type, Notification.Type.ASSESSMENT_CREATED)
        self.assertEqual(notification.title, "New Assessment Created")
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)
        
    def test_notification_str_representation(self):
        """Test string representation of notification."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title="Assessment Approved",
            message="Your assessment has been approved."
        )
        
        expected = f"Assessment Approved for {self.analyst_user.email}"
        self.assertEqual(str(notification), expected)
        
    def test_mark_as_read(self):
        """Test marking notification as read."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test Notification",
            message="Test message"
        )
        
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)
        
        with patch('django.utils.timezone.now') as mock_now:
            mock_time = timezone.now()
            mock_now.return_value = mock_time
            
            notification.mark_as_read()
            
            self.assertTrue(notification.is_read)
            self.assertEqual(notification.read_at, mock_time)
            
    def test_mark_as_read_already_read(self):
        """Test marking already read notification doesn't change read_at."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test Notification",
            message="Test message"
        )
        
        # Mark as read first time
        notification.mark_as_read()
        first_read_time = notification.read_at
        
        # Mark as read again
        notification.mark_as_read()
        
        # Should not change read_at
        self.assertEqual(notification.read_at, first_read_time)
        
    def test_notification_ordering(self):
        """Test notifications are ordered by creation date descending."""
        # Create notifications at different times
        notification1 = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="First Notification",
            message="First message"
        )
        
        notification2 = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_UPDATED,
            title="Second Notification",
            message="Second message"
        )
        
        notifications = list(Notification.objects.all())
        self.assertEqual(notifications[0], notification2)  # Most recent first
        self.assertEqual(notifications[1], notification1)
        
    def test_notification_types(self):
        """Test all notification type choices."""
        for choice_value, choice_label in Notification.Type.choices:
            notification = Notification.objects.create(
                recipient=self.analyst_user,
                type=choice_value,
                title=f"Test {choice_label}",
                message=f"Test message for {choice_label}"
            )
            self.assertEqual(notification.type, choice_value)
            
    def test_notification_without_sender(self):
        """Test notification can be created without sender (system notifications)."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.SYSTEM_ALERT,
            title="System Alert",
            message="This is a system-generated alert."
        )
        
        self.assertIsNone(notification.sender)
        
    def test_notification_without_assessment(self):
        """Test notification can be created without assessment."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.SYSTEM_ALERT,
            title="General Notification",
            message="This is a general notification."
        )
        
        self.assertIsNone(notification.assessment)


class EmailNotificationModelTest(BaseTestCase):
    """Test EmailNotification model."""
    
    def test_create_email_notification(self):
        """Test creating an email notification."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test Notification",
            message="Test message"
        )
        
        email_notification = EmailNotification.objects.create(
            recipient_email=self.analyst_user.email,
            subject="Test Email Subject",
            body="Test email body",
            html_body="<p>Test HTML email body</p>",
            notification=notification
        )
        
        self.assertEqual(email_notification.recipient_email, self.analyst_user.email)
        self.assertEqual(email_notification.subject, "Test Email Subject")
        self.assertEqual(email_notification.status, EmailNotification.Status.PENDING)
        self.assertEqual(email_notification.notification, notification)
        
    def test_email_notification_str_representation(self):
        """Test string representation of email notification."""
        email_notification = EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Test Subject",
            body="Test body"
        )
        
        expected = "Email to test@example.com: Test Subject"
        self.assertEqual(str(email_notification), expected)
        
    def test_email_status_choices(self):
        """Test all email status choices."""
        email_notification = EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Test",
            body="Test body"
        )
        
        for choice_value, choice_label in EmailNotification.Status.choices:
            email_notification.status = choice_value
            email_notification.save()
            email_notification.refresh_from_db()
            self.assertEqual(email_notification.status, choice_value)
            
    def test_email_notification_without_notification(self):
        """Test email notification can be created without linked notification."""
        email_notification = EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Standalone Email",
            body="This email is not linked to an in-app notification."
        )
        
        self.assertIsNone(email_notification.notification)


class WebhookEndpointModelTest(BaseTestCase):
    """Test WebhookEndpoint model."""
    
    def test_create_webhook_endpoint(self):
        """Test creating a webhook endpoint."""
        endpoint = WebhookEndpoint.objects.create(
            name="Test Webhook",
            url="https://example.com/webhook",
            secret_key="secret123",
            events=["assessment.created", "assessment.approved"],
            created_by=self.admin_user
        )
        
        self.assertEqual(endpoint.name, "Test Webhook")
        self.assertEqual(endpoint.url, "https://example.com/webhook")
        self.assertEqual(endpoint.secret_key, "secret123")
        self.assertEqual(endpoint.events, ["assessment.created", "assessment.approved"])
        self.assertTrue(endpoint.is_active)
        self.assertEqual(endpoint.created_by, self.admin_user)
        
    def test_webhook_endpoint_str_representation(self):
        """Test string representation of webhook endpoint."""
        endpoint = WebhookEndpoint.objects.create(
            name="My Webhook",
            url="https://api.example.com/hooks",
            created_by=self.admin_user
        )
        
        expected = "My Webhook (https://api.example.com/hooks)"
        self.assertEqual(str(endpoint), expected)
        
    def test_webhook_endpoint_default_values(self):
        """Test default values for webhook endpoint."""
        endpoint = WebhookEndpoint.objects.create(
            name="Simple Webhook",
            url="https://example.com/webhook",
            created_by=self.admin_user
        )
        
        self.assertEqual(endpoint.events, [])  # Default empty list
        self.assertTrue(endpoint.is_active)  # Default True
        self.assertEqual(endpoint.secret_key, "")  # Default empty string
        
    def test_webhook_endpoint_events_field(self):
        """Test webhook events JSON field."""
        endpoint = WebhookEndpoint.objects.create(
            name="Event Webhook",
            url="https://example.com/webhook",
            events=[
                "assessment.created",
                "assessment.updated", 
                "assessment.approved",
                "file.uploaded"
            ],
            created_by=self.admin_user
        )
        
        endpoint.refresh_from_db()
        self.assertEqual(len(endpoint.events), 4)
        self.assertIn("assessment.created", endpoint.events)
        self.assertIn("file.uploaded", endpoint.events)


class WebhookDeliveryModelTest(BaseTestCase):
    """Test WebhookDelivery model."""
    
    def setUp(self):
        super().setUp()
        self.endpoint = WebhookEndpoint.objects.create(
            name="Test Endpoint",
            url="https://example.com/webhook",
            created_by=self.admin_user
        )
        
    def test_create_webhook_delivery(self):
        """Test creating a webhook delivery."""
        payload = {
            "event": "assessment.created",
            "data": {"assessment_id": "123", "status": "created"}
        }
        
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="assessment.created",
            payload=payload
        )
        
        self.assertEqual(delivery.endpoint, self.endpoint)
        self.assertEqual(delivery.event_type, "assessment.created")
        self.assertEqual(delivery.payload, payload)
        self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)
        self.assertEqual(delivery.attempt_count, 0)
        self.assertEqual(delivery.max_attempts, 3)
        
    def test_webhook_delivery_str_representation(self):
        """Test string representation of webhook delivery."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="assessment.approved",
            payload={"test": "data"},
            status=WebhookDelivery.Status.SUCCESS
        )
        
        expected = f"assessment.approved to {self.endpoint.name} (success)"
        self.assertEqual(str(delivery), expected)
        
    def test_webhook_delivery_ordering(self):
        """Test webhook deliveries are ordered by creation date descending."""
        delivery1 = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="event.one",
            payload={"data": 1}
        )
        
        delivery2 = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="event.two",
            payload={"data": 2}
        )
        
        deliveries = list(WebhookDelivery.objects.all())
        self.assertEqual(deliveries[0], delivery2)  # Most recent first
        self.assertEqual(deliveries[1], delivery1)
        
    def test_webhook_delivery_status_choices(self):
        """Test all webhook delivery status choices."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="test.event",
            payload={"test": "data"}
        )
        
        for choice_value, choice_label in WebhookDelivery.Status.choices:
            delivery.status = choice_value
            delivery.save()
            delivery.refresh_from_db()
            self.assertEqual(delivery.status, choice_value)
            
    def test_webhook_delivery_retry_tracking(self):
        """Test retry tracking fields."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type="test.event",
            payload={"test": "data"},
            attempt_count=2,
            max_attempts=5,
            next_retry_at=timezone.now()
        )
        
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(delivery.max_attempts, 5)
        self.assertIsNotNone(delivery.next_retry_at)


class NotificationRelationshipTest(BaseTestCase):
    """Test relationships between notification models."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
    def test_notification_recipient_relationship(self):
        """Test notification-user relationship."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test",
            message="Test message"
        )
        
        # Test forward relationship
        self.assertEqual(notification.recipient, self.analyst_user)
        
        # Test reverse relationship
        self.assertIn(notification, self.analyst_user.notifications.all())
        
    def test_notification_sender_relationship(self):
        """Test notification sender relationship."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            sender=self.manager_user,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title="Test",
            message="Test message"
        )
        
        # Test forward relationship
        self.assertEqual(notification.sender, self.manager_user)
        
        # Test reverse relationship
        self.assertIn(notification, self.manager_user.sent_notifications.all())
        
    def test_notification_assessment_relationship(self):
        """Test notification-assessment relationship."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test",
            message="Test message",
            assessment=self.assessment
        )
        
        # Test forward relationship
        self.assertEqual(notification.assessment, self.assessment)
        
    def test_email_notification_relationship(self):
        """Test email notification relationship with notification."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test",
            message="Test message"
        )
        
        email_notification = EmailNotification.objects.create(
            recipient_email=self.analyst_user.email,
            subject="Test",
            body="Test body",
            notification=notification
        )
        
        # Test one-to-one relationship
        self.assertEqual(email_notification.notification, notification)
        self.assertEqual(notification.emailnotification, email_notification)
        
    def test_webhook_endpoint_user_relationship(self):
        """Test webhook endpoint-user relationship."""
        endpoint = WebhookEndpoint.objects.create(
            name="Test Webhook",
            url="https://example.com/webhook",
            created_by=self.admin_user
        )
        
        # Test forward relationship
        self.assertEqual(endpoint.created_by, self.admin_user)
        
        # Test reverse relationship
        self.assertIn(endpoint, self.admin_user.webhookendpoint_set.all())
        
    def test_webhook_delivery_endpoint_relationship(self):
        """Test webhook delivery-endpoint relationship."""
        endpoint = WebhookEndpoint.objects.create(
            name="Test Endpoint",
            url="https://example.com/webhook",
            created_by=self.admin_user
        )
        
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_type="test.event",
            payload={"test": "data"}
        )
        
        # Test forward relationship
        self.assertEqual(delivery.endpoint, endpoint)
        
        # Test reverse relationship
        self.assertIn(delivery, endpoint.deliveries.all())
        
    def test_cascade_delete_behavior(self):
        """Test cascade delete behavior."""
        # Create notification with assessment
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test",
            message="Test message",
            assessment=self.assessment
        )
        
        notification_id = notification.id
        
        # Delete assessment - notification should be deleted too
        self.assessment.delete()
        
        self.assertFalse(Notification.objects.filter(id=notification_id).exists())
        
    def test_webhook_delivery_cascade_delete(self):
        """Test webhook delivery cascade delete when endpoint is deleted."""
        endpoint = WebhookEndpoint.objects.create(
            name="Test Endpoint",
            url="https://example.com/webhook",
            created_by=self.admin_user
        )
        
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_type="test.event",
            payload={"test": "data"}
        )
        
        delivery_id = delivery.id
        
        # Delete endpoint - delivery should be deleted too
        endpoint.delete()
        
        self.assertFalse(WebhookDelivery.objects.filter(id=delivery_id).exists())