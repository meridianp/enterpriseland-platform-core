"""
Tests for Event Publishers
"""

from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model

from platform_core.events.models import EventSchema, Event
from platform_core.events.publishers import (
    EventPublisher,
    DomainEventPublisher,
    UserEventPublisher,
    OrderEventPublisher
)
from platform_core.events.brokers import Message
from platform_core.events.exceptions import (
    EventPublishError,
    EventValidationError,
    EventSchemaNotFound
)

User = get_user_model()


class EventPublisherTestCase(TestCase):
    """Test EventPublisher."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        
        # Create test schema
        self.schema = EventSchema.objects.create(
            event_type='test.event',
            version='1.0',
            name='Test Event',
            schema={
                'type': 'object',
                'properties': {
                    'test_id': {'type': 'string'},
                    'value': {'type': 'number'}
                },
                'required': ['test_id']
            }
        )
        
        # Mock broker
        self.mock_broker = Mock()
        self.mock_broker.ensure_connected = Mock()
        self.mock_broker.publish = Mock(return_value=True)
        
        self.publisher = EventPublisher(broker=self.mock_broker)
    
    def test_publish_with_valid_schema(self):
        """Test publishing event with valid schema."""
        event = self.publisher.publish(
            event_type='test.event',
            data={
                'test_id': '123',
                'value': 42
            },
            user=self.user
        )
        
        self.assertEqual(event.event_type, 'test.event')
        self.assertEqual(event.status, 'published')
        self.assertEqual(event.data['test_id'], '123')
        self.assertEqual(event.user, self.user)
        
        # Check broker was called
        self.mock_broker.publish.assert_called_once()
        call_args = self.mock_broker.publish.call_args[1]
        self.assertIsInstance(call_args['message'], Message)
        self.assertEqual(call_args['exchange'], 'events')
    
    def test_publish_with_invalid_schema(self):
        """Test publishing event with invalid schema."""
        with self.assertRaises(EventValidationError):
            self.publisher.publish(
                event_type='test.event',
                data={
                    'value': 42  # Missing required 'test_id'
                }
            )
    
    def test_publish_without_schema(self):
        """Test publishing event without schema when allowed."""
        with patch('django.conf.settings.EVENTS_REQUIRE_SCHEMA', False):
            event = self.publisher.publish(
                event_type='no.schema.event',
                data={'any': 'data'}
            )
            
            self.assertEqual(event.event_type, 'no.schema.event')
            self.assertEqual(event.status, 'published')
    
    def test_publish_with_correlation_id(self):
        """Test publishing with correlation ID."""
        correlation_id = 'corr-123'
        
        event = self.publisher.publish(
            event_type='test.event',
            data={'test_id': '123'},
            correlation_id=correlation_id
        )
        
        self.assertEqual(event.correlation_id, correlation_id)
    
    def test_publish_failure(self):
        """Test handling publish failure."""
        self.mock_broker.publish.return_value = False
        
        with self.assertRaises(EventPublishError):
            self.publisher.publish(
                event_type='test.event',
                data={'test_id': '123'}
            )
        
        # Check event was marked as failed
        event = Event.objects.get(event_type='test.event')
        self.assertEqual(event.status, 'failed')
    
    def test_publish_batch(self):
        """Test batch publishing."""
        events = [
            {
                'event_type': 'test.event',
                'data': {'test_id': '1'}
            },
            {
                'event_type': 'test.event',
                'data': {'test_id': '2'}
            }
        ]
        
        published = self.publisher.publish_batch(events)
        
        self.assertEqual(len(published), 2)
        self.assertEqual(self.mock_broker.publish.call_count, 2)
    
    def test_republish_failed(self):
        """Test republishing failed events."""
        # Create failed events
        failed_event = Event.objects.create(
            event_type='test.event',
            data={'test_id': '123'},
            status='failed',
            publish_attempts=1
        )
        
        stats = self.publisher.republish_failed(max_attempts=3)
        
        self.assertEqual(stats['total'], 1)
        self.assertEqual(stats['success'], 1)
        self.assertEqual(stats['failed'], 0)
        
        # Check event was updated
        failed_event.refresh_from_db()
        self.assertEqual(failed_event.status, 'published')


class DomainEventPublisherTestCase(TestCase):
    """Test DomainEventPublisher."""
    
    def setUp(self):
        self.mock_publisher = Mock()
        self.domain_publisher = DomainEventPublisher(
            'test',
            publisher=self.mock_publisher
        )
    
    def test_created_event(self):
        """Test entity created event."""
        self.domain_publisher.created(
            entity_id='123',
            data={'name': 'Test'}
        )
        
        self.mock_publisher.publish.assert_called_once()
        call_args = self.mock_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'test.created')
        self.assertEqual(call_args['data']['id'], '123')
        self.assertEqual(call_args['data']['name'], 'Test')
    
    def test_updated_event(self):
        """Test entity updated event."""
        self.domain_publisher.updated(
            entity_id='123',
            changes={'name': 'New Name'},
            previous={'name': 'Old Name'}
        )
        
        call_args = self.mock_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'test.updated')
        self.assertEqual(call_args['data']['changes']['name'], 'New Name')
        self.assertEqual(call_args['data']['previous']['name'], 'Old Name')
    
    def test_deleted_event(self):
        """Test entity deleted event."""
        self.domain_publisher.deleted(entity_id='123')
        
        call_args = self.mock_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'test.deleted')
        self.assertEqual(call_args['data']['id'], '123')
    
    def test_state_changed_event(self):
        """Test state change event."""
        self.domain_publisher.state_changed(
            entity_id='123',
            from_state='pending',
            to_state='active'
        )
        
        call_args = self.mock_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'test.state_changed')
        self.assertEqual(call_args['data']['from_state'], 'pending')
        self.assertEqual(call_args['data']['to_state'], 'active')
        self.assertEqual(call_args['data']['transition'], 'pending_to_active')


class UserEventPublisherTestCase(TestCase):
    """Test UserEventPublisher."""
    
    def setUp(self):
        self.mock_base_publisher = Mock()
        with patch('platform_core.events.publishers.EventPublisher', return_value=self.mock_base_publisher):
            self.user_publisher = UserEventPublisher()
            self.user_publisher.publisher = self.mock_base_publisher
    
    def test_user_registered(self):
        """Test user registered event."""
        self.user_publisher.registered(
            user_id='123',
            email='user@example.com'
        )
        
        self.mock_base_publisher.publish.assert_called_once()
        call_args = self.mock_base_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'user.created')
        self.assertEqual(call_args['data']['email'], 'user@example.com')
    
    def test_user_logged_in(self):
        """Test user login event."""
        self.user_publisher.logged_in(
            user_id='123',
            ip_address='192.168.1.1'
        )
        
        call_args = self.mock_base_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'user.logged_in')
        self.assertEqual(call_args['data']['ip_address'], '192.168.1.1')
    
    def test_password_changed(self):
        """Test password changed event."""
        self.user_publisher.password_changed(user_id='123')
        
        call_args = self.mock_base_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'user.password_changed')


class OrderEventPublisherTestCase(TestCase):
    """Test OrderEventPublisher."""
    
    def setUp(self):
        self.mock_base_publisher = Mock()
        with patch('platform_core.events.publishers.EventPublisher', return_value=self.mock_base_publisher):
            self.order_publisher = OrderEventPublisher()
            self.order_publisher.publisher = self.mock_base_publisher
    
    def test_order_placed(self):
        """Test order placed event."""
        items = [
            {'sku': 'ABC', 'quantity': 2, 'price': 10.00},
            {'sku': 'XYZ', 'quantity': 1, 'price': 20.00}
        ]
        
        self.order_publisher.placed(
            order_id='456',
            customer_id='123',
            total=40.00,
            items=items
        )
        
        call_args = self.mock_base_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'order.created')
        self.assertEqual(call_args['data']['total'], 40.00)
        self.assertEqual(len(call_args['data']['items']), 2)
    
    def test_order_shipped(self):
        """Test order shipped event."""
        self.order_publisher.shipped(
            order_id='456',
            tracking_number='1Z999AA1',
            carrier='UPS'
        )
        
        call_args = self.mock_base_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'order.state_changed')
        self.assertEqual(call_args['data']['from_state'], 'processing')
        self.assertEqual(call_args['data']['to_state'], 'shipped')
        self.assertEqual(call_args['metadata']['tracking_number'], '1Z999AA1')
    
    def test_order_cancelled(self):
        """Test order cancelled event."""
        self.order_publisher.cancelled(
            order_id='456',
            reason='Customer request'
        )
        
        call_args = self.mock_base_publisher.publish.call_args[1]
        self.assertEqual(call_args['event_type'], 'order.cancelled')
        self.assertEqual(call_args['data']['reason'], 'Customer request')