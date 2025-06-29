"""
Tests for notifications serializers.
"""
from django.test import TestCase
from rest_framework.test import APIRequestFactory
from unittest.mock import Mock

from tests.base import BaseTestCase
from tests.factories.assessment_factories import AssessmentFactory
from notifications.models import Notification, EmailNotification, WebhookEndpoint, WebhookDelivery
from notifications.serializers import (
    NotificationSerializer, EmailNotificationSerializer,
    WebhookEndpointSerializer, WebhookDeliverySerializer
)


class NotificationSerializerTest(BaseTestCase):
    """Test NotificationSerializer."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
    def test_notification_serialization(self):
        """Test serializing a notification."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            sender=self.manager_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Assessment Created",
            message="A new assessment has been created for your review.",
            assessment=self.assessment
        )
        
        serializer = NotificationSerializer(notification)
        
        self.assertIn('id', serializer.data)
        self.assertIn('type', serializer.data)
        self.assertIn('title', serializer.data)
        self.assertIn('message', serializer.data)
        self.assertIn('assessment', serializer.data)
        self.assertIn('assessment_title', serializer.data)
        self.assertIn('sender', serializer.data)
        self.assertIn('sender_name', serializer.data)
        self.assertIn('is_read', serializer.data)
        self.assertIn('created_at', serializer.data)
        
        self.assertEqual(serializer.data['id'], str(notification.id))
        self.assertEqual(serializer.data['type'], notification.type)
        self.assertEqual(serializer.data['title'], notification.title)
        self.assertEqual(serializer.data['message'], notification.message)
        self.assertEqual(serializer.data['assessment'], str(notification.assessment.id))
        self.assertEqual(serializer.data['sender'], str(notification.sender.id))
        self.assertEqual(serializer.data['is_read'], notification.is_read)
        
    def test_sender_name_field(self):
        """Test sender_name computed field."""
        # Test with sender
        notification_with_sender = Notification.objects.create(
            recipient=self.analyst_user,
            sender=self.manager_user,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title="Assessment Approved",
            message="Your assessment has been approved."
        )
        
        serializer = NotificationSerializer(notification_with_sender)
        self.assertEqual(
            serializer.data['sender_name'], 
            self.manager_user.get_full_name()
        )
        
        # Test without sender (system notification)
        notification_without_sender = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.SYSTEM_ALERT,
            title="System Alert",
            message="This is a system notification."
        )
        
        serializer = NotificationSerializer(notification_without_sender)
        self.assertIsNone(serializer.data['sender_name'])
        
    def test_assessment_title_field(self):
        """Test assessment_title computed field."""
        # Test with assessment
        notification_with_assessment = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Assessment Created",
            message="Assessment created.",
            assessment=self.assessment
        )
        
        serializer = NotificationSerializer(notification_with_assessment)
        self.assertEqual(
            serializer.data['assessment_title'],
            str(self.assessment)
        )
        
        # Test without assessment
        notification_without_assessment = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.SYSTEM_ALERT,
            title="System Alert",
            message="General system alert."
        )
        
        serializer = NotificationSerializer(notification_without_assessment)
        self.assertIsNone(serializer.data['assessment_title'])
        
    def test_read_only_fields(self):
        """Test read-only fields cannot be modified."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test",
            message="Test message"
        )
        
        data = {
            'id': 'new-id',
            'sender': str(self.manager_user.id),
            'read_at': '2023-01-01T00:00:00Z',
            'created_at': '2023-01-01T00:00:00Z',
            'title': 'Updated Title'
        }
        
        serializer = NotificationSerializer(notification, data=data, partial=True)
        self.assertTrue(serializer.is_valid())
        
        updated_notification = serializer.save()
        
        # Read-only fields should not change
        self.assertEqual(updated_notification.id, notification.id)
        self.assertEqual(updated_notification.sender, notification.sender)
        self.assertEqual(updated_notification.created_at, notification.created_at)
        
        # Non-read-only fields should change
        self.assertEqual(updated_notification.title, 'Updated Title')


class EmailNotificationSerializerTest(BaseTestCase):
    """Test EmailNotificationSerializer."""
    
    def test_email_notification_serialization(self):
        """Test serializing an email notification."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test",
            message="Test message"
        )
        
        email_notification = EmailNotification.objects.create(
            recipient_email=self.analyst_user.email,
            subject="Test Email Subject",
            body="Test email body content",
            html_body="<p>Test HTML content</p>",
            notification=notification,
            status=EmailNotification.Status.SENT
        )
        
        serializer = EmailNotificationSerializer(email_notification)
        
        self.assertIn('id', serializer.data)
        self.assertIn('recipient_email', serializer.data)
        self.assertIn('subject', serializer.data)
        self.assertIn('body', serializer.data)
        self.assertIn('html_body', serializer.data)
        self.assertIn('status', serializer.data)
        self.assertIn('created_at', serializer.data)
        
        self.assertEqual(serializer.data['id'], str(email_notification.id))
        self.assertEqual(serializer.data['recipient_email'], self.analyst_user.email)
        self.assertEqual(serializer.data['subject'], "Test Email Subject")
        self.assertEqual(serializer.data['body'], "Test email body content")
        self.assertEqual(serializer.data['status'], EmailNotification.Status.SENT)
        
    def test_email_notification_validation(self):
        """Test email notification validation."""
        data = {
            'recipient_email': 'test@example.com',
            'subject': 'Test Subject',
            'body': 'Test body content'
        }
        
        serializer = EmailNotificationSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Test invalid email
        data['recipient_email'] = 'invalid-email'
        serializer = EmailNotificationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('recipient_email', serializer.errors)
        
    def test_email_notification_read_only_fields(self):
        """Test read-only fields in email notification."""
        email_notification = EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Original Subject",
            body="Original body"
        )
        
        data = {
            'id': 'new-id',
            'sent_at': '2023-01-01T00:00:00Z',
            'created_at': '2023-01-01T00:00:00Z',
            'updated_at': '2023-01-01T00:00:00Z',
            'subject': 'Updated Subject'
        }
        
        serializer = EmailNotificationSerializer(email_notification, data=data, partial=True)
        self.assertTrue(serializer.is_valid())
        
        updated_email = serializer.save()
        
        # Read-only fields should not change
        self.assertEqual(updated_email.id, email_notification.id)
        self.assertEqual(updated_email.created_at, email_notification.created_at)
        
        # Non-read-only fields should change
        self.assertEqual(updated_email.subject, 'Updated Subject')


class WebhookEndpointSerializerTest(BaseTestCase):
    """Test WebhookEndpointSerializer."""
    
    def test_webhook_endpoint_serialization(self):
        """Test serializing a webhook endpoint."""
        webhook = WebhookEndpoint.objects.create(
            name="Test Webhook",
            url="https://example.com/webhook",
            secret_key="secret123",
            events=["assessment.created", "assessment.approved"],
            is_active=True,
            created_by=self.admin_user
        )
        
        serializer = WebhookEndpointSerializer(webhook)
        
        self.assertIn('id', serializer.data)
        self.assertIn('name', serializer.data)
        self.assertIn('url', serializer.data)
        self.assertIn('secret_key', serializer.data)
        self.assertIn('events', serializer.data)
        self.assertIn('is_active', serializer.data)
        self.assertIn('created_by', serializer.data)
        self.assertIn('created_by_name', serializer.data)
        self.assertIn('created_at', serializer.data)
        
        self.assertEqual(serializer.data['id'], str(webhook.id))
        self.assertEqual(serializer.data['name'], "Test Webhook")
        self.assertEqual(serializer.data['url'], "https://example.com/webhook")
        self.assertEqual(serializer.data['secret_key'], "secret123")
        self.assertEqual(serializer.data['events'], ["assessment.created", "assessment.approved"])
        self.assertEqual(serializer.data['is_active'], True)
        self.assertEqual(serializer.data['created_by'], str(webhook.created_by.id))
        
    def test_created_by_name_field(self):
        """Test created_by_name computed field."""
        webhook = WebhookEndpoint.objects.create(
            name="API Webhook",
            url="https://api.example.com/hooks",
            created_by=self.admin_user
        )
        
        serializer = WebhookEndpointSerializer(webhook)
        self.assertEqual(
            serializer.data['created_by_name'],
            self.admin_user.get_full_name()
        )
        
    def test_webhook_endpoint_validation(self):
        """Test webhook endpoint validation."""
        data = {
            'name': 'Valid Webhook',
            'url': 'https://example.com/webhook',
            'events': ['assessment.created'],
            'is_active': True
        }
        
        serializer = WebhookEndpointSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Test invalid URL
        data['url'] = 'not-a-valid-url'
        serializer = WebhookEndpointSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('url', serializer.errors)
        
        # Test missing required fields
        minimal_data = {}
        serializer = WebhookEndpointSerializer(data=minimal_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('name', serializer.errors)
        self.assertIn('url', serializer.errors)
        
    def test_webhook_events_field(self):
        """Test webhook events field handling."""
        data = {
            'name': 'Event Webhook',
            'url': 'https://example.com/webhook',
            'events': [
                'assessment.created',
                'assessment.updated',
                'assessment.approved',
                'file.uploaded'
            ]
        }
        
        serializer = WebhookEndpointSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        webhook = serializer.save(created_by=self.admin_user)
        self.assertEqual(len(webhook.events), 4)
        self.assertIn('assessment.created', webhook.events)
        self.assertIn('file.uploaded', webhook.events)
        
    def test_webhook_endpoint_read_only_fields(self):
        """Test read-only fields in webhook endpoint."""
        webhook = WebhookEndpoint.objects.create(
            name="Original Webhook",
            url="https://example.com/webhook",
            created_by=self.admin_user
        )
        
        data = {
            'id': 'new-id',
            'created_by': str(self.manager_user.id),
            'created_at': '2023-01-01T00:00:00Z',
            'updated_at': '2023-01-01T00:00:00Z',
            'name': 'Updated Webhook'
        }
        
        serializer = WebhookEndpointSerializer(webhook, data=data, partial=True)
        self.assertTrue(serializer.is_valid())
        
        updated_webhook = serializer.save()
        
        # Read-only fields should not change
        self.assertEqual(updated_webhook.id, webhook.id)
        self.assertEqual(updated_webhook.created_by, webhook.created_by)
        self.assertEqual(updated_webhook.created_at, webhook.created_at)
        
        # Non-read-only fields should change
        self.assertEqual(updated_webhook.name, 'Updated Webhook')


class WebhookDeliverySerializerTest(BaseTestCase):
    """Test WebhookDeliverySerializer."""
    
    def setUp(self):
        super().setUp()
        self.webhook = WebhookEndpoint.objects.create(
            name="Test Webhook",
            url="https://example.com/webhook",
            created_by=self.admin_user
        )
        
    def test_webhook_delivery_serialization(self):
        """Test serializing a webhook delivery."""
        payload = {
            "event": "assessment.created",
            "timestamp": "2023-01-01T00:00:00Z",
            "data": {"assessment_id": "123", "status": "created"}
        }
        
        delivery = WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type="assessment.created",
            payload=payload,
            status=WebhookDelivery.Status.SUCCESS,
            response_status_code=200,
            response_body="OK",
            attempt_count=1
        )
        
        serializer = WebhookDeliverySerializer(delivery)
        
        self.assertIn('id', serializer.data)
        self.assertIn('endpoint', serializer.data)
        self.assertIn('endpoint_name', serializer.data)
        self.assertIn('event_type', serializer.data)
        self.assertIn('payload', serializer.data)
        self.assertIn('status', serializer.data)
        self.assertIn('response_status_code', serializer.data)
        self.assertIn('response_body', serializer.data)
        self.assertIn('attempt_count', serializer.data)
        self.assertIn('created_at', serializer.data)
        
        self.assertEqual(serializer.data['id'], str(delivery.id))
        self.assertEqual(serializer.data['endpoint'], str(delivery.endpoint.id))
        self.assertEqual(serializer.data['endpoint_name'], self.webhook.name)
        self.assertEqual(serializer.data['event_type'], "assessment.created")
        self.assertEqual(serializer.data['payload'], payload)
        self.assertEqual(serializer.data['status'], WebhookDelivery.Status.SUCCESS)
        self.assertEqual(serializer.data['response_status_code'], 200)
        self.assertEqual(serializer.data['attempt_count'], 1)
        
    def test_endpoint_name_field(self):
        """Test endpoint_name computed field."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type="test.event",
            payload={"test": "data"}
        )
        
        serializer = WebhookDeliverySerializer(delivery)
        self.assertEqual(
            serializer.data['endpoint_name'],
            self.webhook.name
        )
        
    def test_webhook_delivery_validation(self):
        """Test webhook delivery validation."""
        data = {
            'endpoint': str(self.webhook.id),
            'event_type': 'test.event',
            'payload': {'test': 'data'}
        }
        
        serializer = WebhookDeliverySerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Test missing required fields
        minimal_data = {}
        serializer = WebhookDeliverySerializer(data=minimal_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('event_type', serializer.errors)
        self.assertIn('payload', serializer.errors)
        
    def test_webhook_delivery_read_only_fields(self):
        """Test read-only fields in webhook delivery."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type="original.event",
            payload={"original": "data"}
        )
        
        data = {
            'id': 'new-id',
            'response_status_code': 200,
            'response_body': 'OK',
            'error_message': 'Some error',
            'attempt_count': 5,
            'next_retry_at': '2023-01-01T00:00:00Z',
            'created_at': '2023-01-01T00:00:00Z',
            'delivered_at': '2023-01-01T00:00:00Z',
            'event_type': 'updated.event'
        }
        
        serializer = WebhookDeliverySerializer(delivery, data=data, partial=True)
        self.assertTrue(serializer.is_valid())
        
        updated_delivery = serializer.save()
        
        # Read-only fields should not change
        self.assertEqual(updated_delivery.id, delivery.id)
        self.assertEqual(updated_delivery.response_status_code, delivery.response_status_code)
        self.assertEqual(updated_delivery.response_body, delivery.response_body)
        self.assertEqual(updated_delivery.attempt_count, delivery.attempt_count)
        self.assertEqual(updated_delivery.created_at, delivery.created_at)
        
        # Non-read-only fields should change
        self.assertEqual(updated_delivery.event_type, 'updated.event')
        
    def test_webhook_delivery_payload_serialization(self):
        """Test webhook delivery payload JSON serialization."""
        complex_payload = {
            "event": "assessment.updated",
            "timestamp": "2023-01-01T12:00:00Z",
            "data": {
                "assessment": {
                    "id": "12345",
                    "status": "approved",
                    "score": 85.5,
                    "metrics": [
                        {"name": "Financial Stability", "score": 4},
                        {"name": "Market Position", "score": 3}
                    ]
                },
                "changes": ["status", "score"],
                "user": {
                    "id": "user123",
                    "name": "John Doe"
                }
            }
        }
        
        delivery = WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type="assessment.updated",
            payload=complex_payload
        )
        
        serializer = WebhookDeliverySerializer(delivery)
        
        # Verify complex payload is properly serialized
        self.assertEqual(serializer.data['payload'], complex_payload)
        self.assertEqual(
            serializer.data['payload']['data']['assessment']['score'],
            85.5
        )
        self.assertEqual(
            len(serializer.data['payload']['data']['metrics']),
            2
        )


class NotificationSerializerFieldTest(BaseTestCase):
    """Test computed fields and relationships in notification serializers."""
    
    def test_notification_with_all_relationships(self):
        """Test notification serialization with all relationships."""
        assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            sender=self.manager_user,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title="Assessment Approved",
            message="Your assessment has been approved by the manager.",
            assessment=assessment
        )
        
        serializer = NotificationSerializer(notification)
        
        # Verify all computed fields are present and correct
        self.assertIsNotNone(serializer.data['sender_name'])
        self.assertIsNotNone(serializer.data['assessment_title'])
        self.assertEqual(
            serializer.data['sender_name'],
            self.manager_user.get_full_name()
        )
        self.assertEqual(
            serializer.data['assessment_title'],
            str(assessment)
        )
        
    def test_serializer_performance_with_prefetch(self):
        """Test serializer performance with proper prefetching."""
        # Create multiple notifications
        assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
        notifications = []
        for i in range(5):
            notifications.append(Notification.objects.create(
                recipient=self.analyst_user,
                sender=self.manager_user,
                type=Notification.Type.ASSESSMENT_UPDATED,
                title=f"Assessment Update {i}",
                message=f"Update message {i}",
                assessment=assessment
            ))
        
        # Test serialization with proper prefetching
        notifications_qs = Notification.objects.select_related(
            'sender', 'assessment'
        ).filter(recipient=self.analyst_user)
        
        serializer = NotificationSerializer(notifications_qs, many=True)
        
        # Verify all notifications are serialized correctly
        self.assertEqual(len(serializer.data), 5)
        
        for i, notification_data in enumerate(serializer.data):
            self.assertEqual(notification_data['title'], f"Assessment Update {i}")
            self.assertIsNotNone(notification_data['sender_name'])
            self.assertIsNotNone(notification_data['assessment_title'])