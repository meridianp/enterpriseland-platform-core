"""
Tests for Event Consumers
"""

from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from django.test import TestCase
from django.utils import timezone

from platform_core.events.models import Event, EventSubscription, EventProcessor
from platform_core.events.consumers import (
    EventConsumer,
    RetryPolicy,
    ConsumerManager
)
from platform_core.events.brokers import Message
from platform_core.events.exceptions import (
    EventProcessingError,
    EventTimeoutError
)


class RetryPolicyTestCase(TestCase):
    """Test RetryPolicy."""
    
    def test_exponential_retry(self):
        """Test exponential backoff retry."""
        policy = RetryPolicy(
            max_retries=3,
            retry_delay=60,
            retry_policy='exponential'
        )
        
        self.assertEqual(policy.get_retry_delay(1), 60)    # 60 * 2^0
        self.assertEqual(policy.get_retry_delay(2), 120)   # 60 * 2^1
        self.assertEqual(policy.get_retry_delay(3), 240)   # 60 * 2^2
    
    def test_linear_retry(self):
        """Test linear retry."""
        policy = RetryPolicy(
            max_retries=3,
            retry_delay=60,
            retry_policy='linear'
        )
        
        self.assertEqual(policy.get_retry_delay(1), 60)    # 60 * 1
        self.assertEqual(policy.get_retry_delay(2), 120)   # 60 * 2
        self.assertEqual(policy.get_retry_delay(3), 180)   # 60 * 3
    
    def test_fixed_retry(self):
        """Test fixed interval retry."""
        policy = RetryPolicy(
            max_retries=3,
            retry_delay=60,
            retry_policy='fixed'
        )
        
        self.assertEqual(policy.get_retry_delay(1), 60)
        self.assertEqual(policy.get_retry_delay(2), 60)
        self.assertEqual(policy.get_retry_delay(3), 60)
    
    def test_should_retry(self):
        """Test retry decision."""
        policy = RetryPolicy(max_retries=3)
        
        self.assertTrue(policy.should_retry(0))
        self.assertTrue(policy.should_retry(1))
        self.assertTrue(policy.should_retry(2))
        self.assertFalse(policy.should_retry(3))


class EventConsumerTestCase(TestCase):
    """Test EventConsumer."""
    
    def setUp(self):
        # Create subscription
        self.subscription = EventSubscription.objects.create(
            name='test-consumer',
            event_types=['test.event', 'test.other'],
            subscription_type='queue',
            endpoint='test-queue',
            handler='myapp.handlers.test_handler',
            max_retries=3,
            retry_delay=60,
            concurrent_workers=1
        )
        
        # Mock broker
        self.mock_broker = Mock()
        self.mock_broker.ensure_connected = Mock()
        self.mock_broker.subscribe = Mock()
        self.mock_broker.create_queue = Mock()
        
        # Create consumer
        self.consumer = EventConsumer(
            subscription=self.subscription,
            broker=self.mock_broker
        )
    
    def test_load_handler_success(self):
        """Test loading handler function."""
        # Mock the handler
        mock_handler = Mock()
        with patch('importlib.import_module') as mock_import:
            mock_module = Mock()
            mock_module.test_handler = mock_handler
            mock_import.return_value = mock_module
            
            handler = self.consumer._load_handler()
            
            self.assertEqual(handler, mock_handler)
            mock_import.assert_called_once_with('myapp.handlers')
    
    def test_load_handler_invalid(self):
        """Test loading invalid handler."""
        self.subscription.handler = 'invalid.module.handler'
        self.subscription.save()
        
        with self.assertRaises(EventProcessingError):
            self.consumer._load_handler()
    
    def test_process_message_success(self):
        """Test successful message processing."""
        # Create message
        message = Message(
            id='msg-123',
            event_type='test.event',
            data={'test': 'data'},
            metadata={},
            timestamp=timezone.now().timestamp()
        )
        
        # Mock handler
        mock_handler = Mock(return_value={'processed': True})
        self.consumer._handler = mock_handler
        
        # Process message
        self.consumer._process_message(message)
        
        # Check handler was called
        mock_handler.assert_called_once()
        
        # Check processor was created
        processor = EventProcessor.objects.get(
            event__event_id='msg-123'
        )
        self.assertEqual(processor.status, 'completed')
        self.assertEqual(processor.result, {'processed': True})
    
    def test_process_message_with_filter(self):
        """Test message filtering."""
        # Add filter to subscription
        self.subscription.filter_expression = 'data.priority == "high"'
        self.subscription.save()
        
        # Create low priority message
        message = Message(
            id='msg-456',
            event_type='test.event',
            data={'priority': 'low'},
            metadata={}
        )
        
        # Mock filter
        with patch.object(self.consumer, '_apply_filter', return_value=False):
            self.consumer._process_message(message)
        
        # Check no processor was created
        self.assertFalse(
            EventProcessor.objects.filter(
                event__event_id='msg-456'
            ).exists()
        )
    
    def test_process_message_failure_with_retry(self):
        """Test message processing failure with retry."""
        # Create event
        event = Event.objects.create(
            event_id='event-123',
            event_type='test.event',
            data={'test': 'data'}
        )
        
        # Create message
        message = Message(
            id='event-123',
            event_type='test.event',
            data={'test': 'data'},
            metadata={}
        )
        
        # Mock handler to fail
        mock_handler = Mock(side_effect=Exception('Test error'))
        self.consumer._handler = mock_handler
        
        # Process message
        self.consumer._process_message(message)
        
        # Check processor status
        processor = EventProcessor.objects.get(event=event)
        self.assertEqual(processor.status, 'pending')  # Ready for retry
        self.assertIsNotNone(processor.next_retry_at)
        self.assertEqual(processor.error_message, 'Test error')
    
    def test_process_message_max_retries_exhausted(self):
        """Test max retries exhausted."""
        # Create event and processor with max attempts
        event = Event.objects.create(
            event_id='event-789',
            event_type='test.event',
            data={'test': 'data'}
        )
        
        processor = EventProcessor.objects.create(
            event=event,
            subscription=self.subscription,
            attempts=2  # One less than max_retries
        )
        
        # Create message
        message = Message(
            id='event-789',
            event_type='test.event',
            data={'test': 'data'},
            metadata={}
        )
        
        # Mock handler to fail
        mock_handler = Mock(side_effect=Exception('Final error'))
        self.consumer._handler = mock_handler
        
        # Process message
        self.consumer._process_message(message)
        
        # Check processor marked as failed
        processor.refresh_from_db()
        self.assertEqual(processor.status, 'failed')
        self.assertEqual(processor.attempts, 3)
    
    def test_apply_filter_success(self):
        """Test JMESPath filter application."""
        message = Message(
            id='msg-filter',
            event_type='test.event',
            data={'priority': 'high', 'amount': 100},
            metadata={'source': 'api'}
        )
        
        # Test various filters
        self.subscription.filter_expression = 'data.priority == `high`'
        self.assertTrue(self.consumer._apply_filter(message))
        
        self.subscription.filter_expression = 'data.amount > `50`'
        self.assertTrue(self.consumer._apply_filter(message))
        
        self.subscription.filter_expression = 'metadata.source == `web`'
        self.assertFalse(self.consumer._apply_filter(message))


class ConsumerManagerTestCase(TestCase):
    """Test ConsumerManager."""
    
    def setUp(self):
        # Create subscriptions
        self.sub1 = EventSubscription.objects.create(
            name='consumer-1',
            event_types=['test.event1'],
            endpoint='queue-1',
            is_active=True,
            is_paused=False
        )
        
        self.sub2 = EventSubscription.objects.create(
            name='consumer-2',
            event_types=['test.event2'],
            endpoint='queue-2',
            is_active=True,
            is_paused=True  # Paused
        )
        
        self.sub3 = EventSubscription.objects.create(
            name='consumer-3',
            event_types=['test.event3'],
            endpoint='queue-3',
            is_active=False  # Inactive
        )
        
        # Mock broker
        with patch('platform_core.events.consumers.BrokerFactory.from_settings') as mock_factory:
            mock_broker = Mock()
            mock_factory.return_value = mock_broker
            self.manager = ConsumerManager()
    
    @patch('threading.Thread')
    def test_start_all(self, mock_thread):
        """Test starting all active subscriptions."""
        self.manager.start_all()
        
        # Should only start active, non-paused subscriptions
        self.assertEqual(len(self.manager.consumers), 1)
        self.assertIn('consumer-1', self.manager.consumers)
        self.assertNotIn('consumer-2', self.manager.consumers)  # Paused
        self.assertNotIn('consumer-3', self.manager.consumers)  # Inactive
        
        # Check thread was started
        mock_thread.assert_called_once()
    
    @patch('threading.Thread')
    def test_start_consumer(self, mock_thread):
        """Test starting specific consumer."""
        self.manager.start_consumer(self.sub1)
        
        self.assertIn('consumer-1', self.manager.consumers)
        mock_thread.assert_called_once()
    
    def test_stop_consumer(self):
        """Test stopping consumer."""
        # Add consumer
        mock_consumer = Mock()
        self.manager.consumers['consumer-1'] = mock_consumer
        
        # Stop it
        self.manager.stop_consumer('consumer-1')
        
        mock_consumer.stop.assert_called_once()
        self.assertNotIn('consumer-1', self.manager.consumers)
    
    def test_get_status(self):
        """Test getting consumer status."""
        # Add mock consumers
        mock_consumer1 = Mock()
        mock_consumer1._running = True
        mock_consumer1.subscription.name = 'consumer-1'
        mock_consumer1.subscription.event_types = ['test.event1']
        
        self.manager.consumers['consumer-1'] = mock_consumer1
        
        status = self.manager.get_status()
        
        self.assertEqual(status['active_consumers'], 1)
        self.assertIn('consumer-1', status['consumers'])
        self.assertTrue(status['consumers']['consumer-1']['running'])