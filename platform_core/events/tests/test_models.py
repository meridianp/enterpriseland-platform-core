"""
Tests for Event System Models
"""

import json
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from platform_core.events.models import (
    EventSchema,
    EventSubscription,
    Event,
    EventProcessor,
    SagaInstance
)

User = get_user_model()


class EventSchemaTestCase(TestCase):
    """Test EventSchema model."""
    
    def setUp(self):
        self.schema = EventSchema.objects.create(
            event_type='user.created',
            version='1.0',
            name='User Created Event',
            description='Fired when a new user is created',
            schema={
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'string'},
                    'email': {'type': 'string', 'format': 'email'}
                },
                'required': ['user_id', 'email']
            },
            routing_key='user.created',
            exchange='user-events'
        )
    
    def test_schema_creation(self):
        """Test schema is created correctly."""
        self.assertEqual(self.schema.event_type, 'user.created')
        self.assertEqual(self.schema.version, '1.0')
        self.assertTrue(self.schema.is_active)
    
    def test_validate_event_data_valid(self):
        """Test validation with valid data."""
        valid_data = {
            'user_id': '123',
            'email': 'test@example.com'
        }
        
        self.assertTrue(self.schema.validate_event_data(valid_data))
    
    def test_validate_event_data_invalid(self):
        """Test validation with invalid data."""
        invalid_data = {
            'user_id': '123'
            # Missing required 'email' field
        }
        
        self.assertFalse(self.schema.validate_event_data(invalid_data))
    
    def test_validate_event_data_no_schema(self):
        """Test validation when no schema defined."""
        schema = EventSchema.objects.create(
            event_type='test.event',
            version='1.0',
            name='Test Event'
        )
        
        # Should return True when no schema defined
        self.assertTrue(schema.validate_event_data({'any': 'data'}))
    
    def test_unique_constraint(self):
        """Test unique constraint on event_type and version."""
        with self.assertRaises(Exception):
            EventSchema.objects.create(
                event_type='user.created',
                version='1.0',
                name='Duplicate Schema'
            )


class EventSubscriptionTestCase(TestCase):
    """Test EventSubscription model."""
    
    def setUp(self):
        self.subscription = EventSubscription.objects.create(
            name='user-service-subscription',
            description='Subscribes to user events',
            event_types=['user.created', 'user.updated', 'user.deleted'],
            subscription_type='queue',
            endpoint='user-events-queue',
            handler='myapp.handlers.process_user_event'
        )
    
    def test_subscription_creation(self):
        """Test subscription is created correctly."""
        self.assertEqual(self.subscription.name, 'user-service-subscription')
        self.assertEqual(len(self.subscription.event_types), 3)
        self.assertTrue(self.subscription.is_active)
        self.assertFalse(self.subscription.is_paused)
    
    def test_default_values(self):
        """Test default values are set correctly."""
        self.assertEqual(self.subscription.max_retries, 3)
        self.assertEqual(self.subscription.retry_policy, 'exponential')
        self.assertEqual(self.subscription.retry_delay, 60)
        self.assertEqual(self.subscription.batch_size, 1)
        self.assertEqual(self.subscription.concurrent_workers, 1)
    
    def test_filter_expression(self):
        """Test filter expression field."""
        self.subscription.filter_expression = "data.priority == 'high'"
        self.subscription.save()
        
        self.assertEqual(
            self.subscription.filter_expression,
            "data.priority == 'high'"
        )


class EventTestCase(TestCase):
    """Test Event model."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        
        self.event = Event.objects.create(
            event_type='order.placed',
            version='1.0',
            data={
                'order_id': '12345',
                'customer_id': '67890',
                'total': 99.99
            },
            metadata={'client': 'web'},
            source='order-service',
            correlation_id='corr-123',
            user=self.user
        )
    
    def test_event_creation(self):
        """Test event is created correctly."""
        self.assertEqual(self.event.event_type, 'order.placed')
        self.assertEqual(self.event.status, 'pending')
        self.assertEqual(self.event.source, 'order-service')
        self.assertEqual(self.event.user, self.user)
    
    def test_event_id_generation(self):
        """Test event ID is generated."""
        self.assertIsNotNone(self.event.event_id)
    
    def test_mark_published(self):
        """Test marking event as published."""
        self.event.mark_published()
        
        self.assertEqual(self.event.status, 'published')
        self.assertIsNotNone(self.event.published_at)
    
    def test_mark_failed(self):
        """Test marking event as failed."""
        error_msg = 'Connection timeout'
        self.event.mark_failed(error_msg)
        
        self.assertEqual(self.event.status, 'failed')
        self.assertEqual(self.event.error_message, error_msg)


class EventProcessorTestCase(TestCase):
    """Test EventProcessor model."""
    
    def setUp(self):
        self.event = Event.objects.create(
            event_type='test.event',
            data={'test': 'data'}
        )
        
        self.subscription = EventSubscription.objects.create(
            name='test-subscription',
            event_types=['test.event'],
            endpoint='test-queue'
        )
        
        self.processor = EventProcessor.objects.create(
            event=self.event,
            subscription=self.subscription
        )
    
    def test_processor_creation(self):
        """Test processor is created correctly."""
        self.assertEqual(self.processor.status, 'pending')
        self.assertEqual(self.processor.attempts, 0)
        self.assertEqual(self.processor.event, self.event)
        self.assertEqual(self.processor.subscription, self.subscription)
    
    def test_unique_constraint(self):
        """Test unique constraint on event and subscription."""
        with self.assertRaises(Exception):
            EventProcessor.objects.create(
                event=self.event,
                subscription=self.subscription
            )
    
    def test_status_transitions(self):
        """Test status transitions."""
        # Start processing
        self.processor.status = 'processing'
        self.processor.started_at = timezone.now()
        self.processor.attempts = 1
        self.processor.save()
        
        # Complete processing
        self.processor.status = 'completed'
        self.processor.completed_at = timezone.now()
        self.processor.result = {'processed': True}
        self.processor.save()
        
        self.assertEqual(self.processor.status, 'completed')
        self.assertIsNotNone(self.processor.started_at)
        self.assertIsNotNone(self.processor.completed_at)


class SagaInstanceTestCase(TestCase):
    """Test SagaInstance model."""
    
    def setUp(self):
        self.saga = SagaInstance.objects.create(
            saga_type='order.fulfillment',
            correlation_id='corr-456',
            initiating_event_id='event-123',
            state_data={'order_id': '12345'}
        )
    
    def test_saga_creation(self):
        """Test saga is created correctly."""
        self.assertEqual(self.saga.saga_type, 'order.fulfillment')
        self.assertEqual(self.saga.status, 'started')
        self.assertIsNotNone(self.saga.saga_id)
    
    def test_add_completed_step(self):
        """Test adding completed steps."""
        self.saga.add_completed_step('validate_order')
        self.saga.add_completed_step('reserve_inventory')
        
        self.assertEqual(len(self.saga.completed_steps), 2)
        self.assertIn('validate_order', self.saga.completed_steps)
        self.assertIn('reserve_inventory', self.saga.completed_steps)
        
        # Test duplicate step not added
        self.saga.add_completed_step('validate_order')
        self.assertEqual(len(self.saga.completed_steps), 2)
    
    def test_start_compensation(self):
        """Test starting compensation."""
        self.saga.start_compensation()
        
        self.assertEqual(self.saga.status, 'compensating')