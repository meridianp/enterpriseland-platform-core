"""
Tests for notifications views and API endpoints.
"""
from django.urls import reverse
from rest_framework import status
from unittest.mock import patch, Mock
from django.utils import timezone

from tests.base import BaseAPITestCase
from tests.factories.assessment_factories import AssessmentFactory
from notifications.models import Notification, EmailNotification, WebhookEndpoint, WebhookDelivery


class NotificationViewSetTest(BaseAPITestCase):
    """Test NotificationViewSet."""
    
    def setUp(self):
        super().setUp()
        self.url = reverse('notification-list')
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
    def test_list_notifications_authenticated(self):
        """Test listing notifications requires authentication."""
        # Create test notification
        Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test Notification",
            message="Test message"
        )
        
        # Test unauthenticated
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        # Test authenticated
        self.login(self.analyst_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
    def test_user_only_sees_own_notifications(self):
        """Test users only see their own notifications."""
        # Create notification for analyst
        notification1 = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Analyst Notification",
            message="For analyst"
        )
        
        # Create notification for manager
        notification2 = Notification.objects.create(
            recipient=self.manager_user,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title="Manager Notification",
            message="For manager"
        )
        
        self.login(self.analyst_user)
        response = self.client.get(self.url)
        
        notification_ids = [n['id'] for n in response.data['results']]
        self.assertIn(str(notification1.id), notification_ids)
        self.assertNotIn(str(notification2.id), notification_ids)
        
    def test_unread_notifications_endpoint(self):
        """Test unread notifications endpoint."""
        # Create read and unread notifications
        read_notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Read Notification",
            message="This is read",
            is_read=True
        )
        
        unread_notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_UPDATED,
            title="Unread Notification",
            message="This is unread"
        )
        
        self.login(self.analyst_user)
        url = reverse('notification-unread')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(unread_notification.id))
        
    def test_mark_notification_read(self):
        """Test marking notification as read."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test Notification",
            message="Test message"
        )
        
        self.assertFalse(notification.is_read)
        
        self.login(self.analyst_user)
        url = reverse('notification-mark-read', kwargs={'pk': notification.id})
        
        with patch('django.utils.timezone.now') as mock_now:
            mock_time = timezone.now()
            mock_now.return_value = mock_time
            
            response = self.client.post(url)
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            
            notification.refresh_from_db()
            self.assertTrue(notification.is_read)
            self.assertEqual(notification.read_at, mock_time)
            
    def test_mark_all_notifications_read(self):
        """Test marking all notifications as read."""
        # Create multiple unread notifications
        notification1 = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Notification 1",
            message="Message 1"
        )
        
        notification2 = Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_UPDATED,
            title="Notification 2",
            message="Message 2"
        )
        
        # Create notification for different user (should not be affected)
        other_notification = Notification.objects.create(
            recipient=self.manager_user,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title="Other Notification",
            message="Other message"
        )
        
        self.login(self.analyst_user)
        url = reverse('notification-mark-all-read')
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Marked 2 notifications as read', response.data['message'])
        
        # Verify notifications are marked as read
        notification1.refresh_from_db()
        notification2.refresh_from_db()
        other_notification.refresh_from_db()
        
        self.assertTrue(notification1.is_read)
        self.assertTrue(notification2.is_read)
        self.assertFalse(other_notification.is_read)  # Should not be affected
        
    def test_notification_count_endpoint(self):
        """Test notification count endpoint."""
        # Create notifications
        Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Read Notification",
            message="Read message",
            is_read=True
        )
        
        Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_UPDATED,
            title="Unread Notification 1",
            message="Unread message 1"
        )
        
        Notification.objects.create(
            recipient=self.analyst_user,
            type=Notification.Type.ASSESSMENT_APPROVED,
            title="Unread Notification 2",
            message="Unread message 2"
        )
        
        self.login(self.analyst_user)
        url = reverse('notification-count')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total'], 3)
        self.assertEqual(response.data['unread'], 2)
        
    def test_notification_serialization(self):
        """Test notification serialization includes all fields."""
        notification = Notification.objects.create(
            recipient=self.analyst_user,
            sender=self.manager_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test Notification",
            message="Test message",
            assessment=self.assessment
        )
        
        self.login(self.analyst_user)
        response = self.client.get(self.url)
        
        notification_data = response.data['results'][0]
        
        self.assertEqual(notification_data['id'], str(notification.id))
        self.assertEqual(notification_data['type'], notification.type)
        self.assertEqual(notification_data['title'], notification.title)
        self.assertEqual(notification_data['message'], notification.message)
        self.assertIn('sender_name', notification_data)
        self.assertIn('assessment_title', notification_data)
        self.assertIn('created_at', notification_data)
        
    def test_cannot_access_other_user_notification(self):
        """Test user cannot access another user's notification."""
        notification = Notification.objects.create(
            recipient=self.manager_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Manager Notification",
            message="For manager only"
        )
        
        self.login(self.analyst_user)
        url = reverse('notification-detail', kwargs={'pk': notification.id})
        response = self.client.get(url)
        
        # Should return 404 due to queryset filtering
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class EmailNotificationViewSetTest(BaseAPITestCase):
    """Test EmailNotificationViewSet."""
    
    def setUp(self):
        super().setUp()
        self.url = reverse('emailnotification-list')
        
    def test_only_admin_can_view_email_notifications(self):
        """Test only admin users can view email notifications."""
        # Create email notification
        EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Test Email",
            body="Test body"
        )
        
        # Test non-admin user
        self.login(self.analyst_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)  # Empty queryset
        
        # Test admin user
        self.login(self.admin_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        
    def test_email_notification_serialization(self):
        """Test email notification serialization."""
        email_notification = EmailNotification.objects.create(
            recipient_email="test@example.com",
            subject="Test Subject",
            body="Test body",
            html_body="<p>Test HTML body</p>",
            status=EmailNotification.Status.SENT
        )
        
        self.login(self.admin_user)
        response = self.client.get(self.url)
        
        email_data = response.data['results'][0]
        
        self.assertEqual(email_data['id'], str(email_notification.id))
        self.assertEqual(email_data['recipient_email'], "test@example.com")
        self.assertEqual(email_data['subject'], "Test Subject")
        self.assertEqual(email_data['body'], "Test body")
        self.assertEqual(email_data['status'], EmailNotification.Status.SENT)


class WebhookEndpointViewSetTest(BaseAPITestCase):
    """Test WebhookEndpointViewSet."""
    
    def setUp(self):
        super().setUp()
        self.url = reverse('webhookendpoint-list')
        
    def test_create_webhook_endpoint(self):
        """Test creating webhook endpoint."""
        self.login(self.admin_user)
        
        data = {
            'name': 'Test Webhook',
            'url': 'https://example.com/webhook',
            'secret_key': 'secret123',
            'events': ['assessment.created', 'assessment.approved'],
            'is_active': True
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        webhook = WebhookEndpoint.objects.get(id=response.data['id'])
        self.assertEqual(webhook.name, 'Test Webhook')
        self.assertEqual(webhook.url, 'https://example.com/webhook')
        self.assertEqual(webhook.events, ['assessment.created', 'assessment.approved'])
        self.assertEqual(webhook.created_by, self.admin_user)
        
    def test_non_admin_cannot_create_webhook(self):
        """Test non-admin users cannot create webhooks."""
        self.login(self.analyst_user)
        
        data = {
            'name': 'Test Webhook',
            'url': 'https://example.com/webhook'
        }
        
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
    def test_test_webhook_endpoint(self):
        """Test webhook endpoint test functionality."""
        webhook = WebhookEndpoint.objects.create(
            name='Test Webhook',
            url='https://example.com/webhook',
            events=['webhook.test'],
            created_by=self.admin_user
        )
        
        self.login(self.admin_user)
        url = reverse('webhookendpoint-test', kwargs={'pk': webhook.id})
        
        with patch('notifications.tasks.deliver_webhook.delay') as mock_deliver:
            response = self.client.post(url)
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn('Test webhook queued for delivery', response.data['message'])
            self.assertIn('delivery_id', response.data)
            
            # Verify webhook delivery was created
            delivery = WebhookDelivery.objects.get(id=response.data['delivery_id'])
            self.assertEqual(delivery.endpoint, webhook)
            self.assertEqual(delivery.event_type, 'webhook.test')
            
            # Verify task was called
            mock_deliver.assert_called_once_with(delivery.id)
            
    def test_webhook_endpoint_serialization(self):
        """Test webhook endpoint serialization."""
        webhook = WebhookEndpoint.objects.create(
            name='API Webhook',
            url='https://api.example.com/hooks',
            events=['assessment.created'],
            created_by=self.admin_user
        )
        
        self.login(self.admin_user)
        response = self.client.get(self.url)
        
        webhook_data = response.data['results'][0]
        
        self.assertEqual(webhook_data['id'], str(webhook.id))
        self.assertEqual(webhook_data['name'], 'API Webhook')
        self.assertEqual(webhook_data['url'], 'https://api.example.com/hooks')
        self.assertEqual(webhook_data['events'], ['assessment.created'])
        self.assertIn('created_by_name', webhook_data)


class WebhookDeliveryViewSetTest(BaseAPITestCase):
    """Test WebhookDeliveryViewSet."""
    
    def setUp(self):
        super().setUp()
        self.webhook = WebhookEndpoint.objects.create(
            name='Test Webhook',
            url='https://example.com/webhook',
            created_by=self.admin_user
        )
        self.url = reverse('webhookdelivery-list')
        
    def test_view_webhook_deliveries(self):
        """Test viewing webhook deliveries."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type='assessment.created',
            payload={'test': 'data'},
            status=WebhookDelivery.Status.SUCCESS
        )
        
        self.login(self.admin_user)
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        delivery_data = response.data['results'][0]
        self.assertEqual(delivery_data['id'], str(delivery.id))
        self.assertEqual(delivery_data['event_type'], 'assessment.created')
        self.assertEqual(delivery_data['status'], WebhookDelivery.Status.SUCCESS)
        self.assertIn('endpoint_name', delivery_data)
        
    def test_retry_failed_webhook_delivery(self):
        """Test retrying failed webhook delivery."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type='assessment.created',
            payload={'test': 'data'},
            status=WebhookDelivery.Status.FAILED,
            attempt_count=1
        )
        
        self.login(self.admin_user)
        url = reverse('webhookdelivery-retry', kwargs={'pk': delivery.id})
        
        with patch('notifications.tasks.deliver_webhook.delay') as mock_deliver:
            response = self.client.post(url)
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['message'], 'Webhook delivery retry queued')
            
            # Verify status was reset
            delivery.refresh_from_db()
            self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)
            
            # Verify task was called
            mock_deliver.assert_called_once_with(delivery.id)
            
    def test_cannot_retry_successful_delivery(self):
        """Test cannot retry successful delivery."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type='assessment.created',
            payload={'test': 'data'},
            status=WebhookDelivery.Status.SUCCESS
        )
        
        self.login(self.admin_user)
        url = reverse('webhookdelivery-retry', kwargs={'pk': delivery.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Only failed deliveries can be retried', response.data['error'])
        
    def test_cannot_retry_max_attempts_exceeded(self):
        """Test cannot retry when max attempts exceeded."""
        delivery = WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type='assessment.created',
            payload={'test': 'data'},
            status=WebhookDelivery.Status.FAILED,
            attempt_count=3,
            max_attempts=3
        )
        
        self.login(self.admin_user)
        url = reverse('webhookdelivery-retry', kwargs={'pk': delivery.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Maximum retry attempts exceeded', response.data['error'])
        
    def test_non_admin_cannot_access_webhook_deliveries(self):
        """Test non-admin users cannot access webhook deliveries."""
        WebhookDelivery.objects.create(
            endpoint=self.webhook,
            event_type='test.event',
            payload={'test': 'data'}
        )
        
        self.login(self.analyst_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class NotificationPermissionTest(BaseAPITestCase):
    """Test notification permission handling."""
    
    def test_unauthenticated_access_denied(self):
        """Test unauthenticated users cannot access notifications."""
        urls = [
            reverse('notification-list'),
            reverse('emailnotification-list'),
            reverse('webhookendpoint-list'),
            reverse('webhookdelivery-list')
        ]
        
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            
    def test_viewer_user_notification_access(self):
        """Test viewer user can access notifications but not webhooks."""
        # Create notification for viewer
        Notification.objects.create(
            recipient=self.viewer_user,
            type=Notification.Type.ASSESSMENT_CREATED,
            title="Test",
            message="Test message"
        )
        
        self.login(self.viewer_user)
        
        # Can access own notifications
        response = self.client.get(reverse('notification-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Cannot access email notifications
        response = self.client.get(reverse('emailnotification-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)  # Empty queryset
        
        # Cannot access webhooks
        response = self.client.get(reverse('webhookendpoint-list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
    def test_partner_user_notification_access(self):
        """Test external partner user notification access."""
        # Create notification for partner
        Notification.objects.create(
            recipient=self.partner_user,
            type=Notification.Type.ASSESSMENT_UPDATED,
            title="Assessment Update",
            message="Your assessment has been updated"
        )
        
        self.login(self.partner_user)
        
        # Can access own notifications
        response = self.client.get(reverse('notification-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        
        # Cannot create webhook endpoints
        webhook_data = {
            'name': 'Partner Webhook',
            'url': 'https://partner.example.com/webhook'
        }
        response = self.client.post(reverse('webhookendpoint-list'), webhook_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)