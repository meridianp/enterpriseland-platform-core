"""
Event Consumers

Handles consuming and processing events from message brokers.
"""

import importlib
import logging
import time
import traceback
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Event, EventSubscription, EventProcessor
from .brokers import BrokerFactory, Message, MessageBroker
from .exceptions import (
    EventProcessingError,
    EventTimeoutError,
    EventRetryExhausted
)

logger = logging.getLogger(__name__)


class RetryPolicy:
    """Retry policy for event processing."""
    
    def __init__(self, 
                 max_retries: int = 3,
                 retry_delay: int = 60,
                 retry_policy: str = 'exponential'):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_policy = retry_policy
    
    def get_retry_delay(self, attempt: int) -> int:
        """Calculate retry delay based on attempt number."""
        if self.retry_policy == 'exponential':
            return self.retry_delay * (2 ** (attempt - 1))
        elif self.retry_policy == 'linear':
            return self.retry_delay * attempt
        else:  # fixed
            return self.retry_delay
    
    def should_retry(self, attempts: int) -> bool:
        """Check if should retry based on attempts."""
        return attempts < self.max_retries


class EventConsumer:
    """Consumes and processes events from message broker."""
    
    def __init__(self, 
                 subscription: EventSubscription,
                 broker: Optional[MessageBroker] = None,
                 executor: Optional[ThreadPoolExecutor] = None):
        """
        Initialize consumer.
        
        Args:
            subscription: EventSubscription to process
            broker: Optional message broker instance
            executor: Optional thread pool executor
        """
        self.subscription = subscription
        self.broker = broker or BrokerFactory.from_settings()
        self.executor = executor or ThreadPoolExecutor(
            max_workers=subscription.concurrent_workers
        )
        self.retry_policy = RetryPolicy(
            max_retries=subscription.max_retries,
            retry_delay=subscription.retry_delay,
            retry_policy=subscription.retry_policy
        )
        self._handler = None
        self._running = False
    
    def _load_handler(self) -> Callable:
        """Load handler function from string path."""
        if self._handler:
            return self._handler
        
        if not self.subscription.handler:
            raise EventProcessingError(
                f"No handler configured for subscription {self.subscription.name}"
            )
        
        try:
            # Parse handler path
            module_path, func_name = self.subscription.handler.rsplit('.', 1)
            
            # Import module and get function
            module = importlib.import_module(module_path)
            handler = getattr(module, func_name)
            
            if not callable(handler):
                raise EventProcessingError(
                    f"Handler {self.subscription.handler} is not callable"
                )
            
            self._handler = handler
            return handler
            
        except Exception as e:
            raise EventProcessingError(
                f"Failed to load handler {self.subscription.handler}: {e}"
            )
    
    def _process_message(self, message: Message) -> None:
        """Process a single message."""
        # Check if we should process this event type
        if message.event_type not in self.subscription.event_types:
            logger.debug(
                f"Skipping event {message.event_type} - not in subscription types"
            )
            return
        
        # Apply filter if configured
        if self.subscription.filter_expression:
            if not self._apply_filter(message):
                logger.debug(f"Event {message.id} filtered out")
                return
        
        # Get or create event record
        try:
            event = Event.objects.get(event_id=message.id)
        except Event.DoesNotExist:
            # Create event record if it doesn't exist
            event = Event.objects.create(
                event_id=message.id,
                event_type=message.event_type,
                data=message.data,
                metadata=message.metadata,
                correlation_id=message.correlation_id,
                occurred_at=datetime.fromtimestamp(message.timestamp, tz=timezone.utc),
                status='published'
            )
        
        # Get or create processor record
        processor, created = EventProcessor.objects.get_or_create(
            event=event,
            subscription=self.subscription,
            defaults={'status': 'pending'}
        )
        
        # Skip if already processed
        if processor.status in ['completed', 'skipped']:
            logger.debug(f"Event {event.event_id} already processed")
            return
        
        # Process event
        try:
            self._process_event(event, processor)
        except Exception as e:
            self._handle_processing_error(event, processor, e)
    
    def _process_event(self, event: Event, processor: EventProcessor) -> None:
        """Process event with handler."""
        handler = self._load_handler()
        
        # Update processor status
        processor.status = 'processing'
        processor.started_at = timezone.now()
        processor.attempts += 1
        processor.save()
        
        try:
            # Execute handler with timeout
            future = self.executor.submit(handler, event)
            result = future.result(timeout=self.subscription.visibility_timeout)
            
            # Mark as completed
            processor.status = 'completed'
            processor.completed_at = timezone.now()
            processor.result = result if isinstance(result, dict) else None
            processor.save()
            
            logger.info(
                f"Successfully processed event {event.event_id} "
                f"with subscription {self.subscription.name}"
            )
            
        except TimeoutError:
            raise EventTimeoutError(
                f"Handler timeout after {self.subscription.visibility_timeout}s"
            )
        except Exception as e:
            raise EventProcessingError(f"Handler error: {e}")
    
    def _handle_processing_error(self, 
                                 event: Event,
                                 processor: EventProcessor,
                                 error: Exception) -> None:
        """Handle processing error with retry logic."""
        processor.error_message = str(error)
        processor.error_details = {
            'type': type(error).__name__,
            'traceback': traceback.format_exc()
        }
        
        # Check retry policy
        if self.retry_policy.should_retry(processor.attempts):
            # Schedule retry
            retry_delay = self.retry_policy.get_retry_delay(processor.attempts)
            processor.next_retry_at = timezone.now() + timedelta(seconds=retry_delay)
            processor.status = 'pending'
            
            logger.warning(
                f"Event {event.event_id} processing failed (attempt {processor.attempts}). "
                f"Retrying in {retry_delay}s"
            )
        else:
            # Max retries exhausted
            processor.status = 'failed'
            
            # Send to dead letter queue if configured
            if self.subscription.dead_letter_queue:
                self._send_to_dead_letter(event, processor)
                processor.status = 'dead_lettered'
            
            logger.error(
                f"Event {event.event_id} processing failed after "
                f"{processor.attempts} attempts"
            )
        
        processor.save()
    
    def _send_to_dead_letter(self, event: Event, processor: EventProcessor) -> None:
        """Send event to dead letter queue."""
        try:
            # Create dead letter message
            dead_letter_message = Message(
                id=str(event.event_id),
                event_type=event.event_type,
                data=event.data,
                metadata={
                    **event.metadata,
                    'dead_letter_reason': processor.error_message,
                    'dead_letter_subscription': self.subscription.name,
                    'dead_letter_attempts': processor.attempts,
                    'dead_letter_timestamp': timezone.now().isoformat()
                },
                correlation_id=event.correlation_id
            )
            
            # Publish to dead letter queue
            self.broker.publish(
                message=dead_letter_message,
                routing_key=self.subscription.dead_letter_queue
            )
            
            logger.info(
                f"Sent event {event.event_id} to dead letter queue "
                f"{self.subscription.dead_letter_queue}"
            )
            
        except Exception as e:
            logger.error(f"Failed to send event to dead letter queue: {e}")
    
    def _apply_filter(self, message: Message) -> bool:
        """Apply JMESPath filter to message."""
        try:
            import jmespath
            
            # Combine message data and metadata for filtering
            filter_data = {
                'data': message.data,
                'metadata': message.metadata,
                'event_type': message.event_type,
                'correlation_id': message.correlation_id
            }
            
            # Apply filter expression
            result = jmespath.search(
                self.subscription.filter_expression,
                filter_data
            )
            
            # Filter passes if result is truthy
            return bool(result)
            
        except Exception as e:
            logger.error(f"Filter expression error: {e}")
            # If filter fails, process the message
            return True
    
    def start(self) -> None:
        """Start consuming events."""
        if self._running:
            logger.warning(f"Consumer for {self.subscription.name} already running")
            return
        
        self._running = True
        logger.info(f"Starting consumer for subscription {self.subscription.name}")
        
        try:
            # Create queue if needed
            if self.subscription.subscription_type == 'queue':
                self.broker.create_queue(
                    queue=self.subscription.endpoint,
                    durable=True
                )
            
            # Subscribe to events
            self.broker.subscribe(
                queue=self.subscription.endpoint,
                callback=self._process_message,
                routing_key='#'  # Subscribe to all routing keys
            )
            
        except KeyboardInterrupt:
            logger.info(f"Consumer {self.subscription.name} interrupted")
        except Exception as e:
            logger.error(f"Consumer error: {e}")
        finally:
            self._running = False
    
    def stop(self) -> None:
        """Stop consuming events."""
        self._running = False
        self.broker.disconnect()
        self.executor.shutdown(wait=True)
        logger.info(f"Stopped consumer for subscription {self.subscription.name}")


class ConsumerManager:
    """Manages multiple event consumers."""
    
    def __init__(self):
        self.consumers: Dict[str, EventConsumer] = {}
        self.broker = BrokerFactory.from_settings()
    
    def start_all(self) -> None:
        """Start all active subscriptions."""
        subscriptions = EventSubscription.objects.filter(
            is_active=True,
            is_paused=False
        )
        
        for subscription in subscriptions:
            self.start_consumer(subscription)
    
    def start_consumer(self, subscription: EventSubscription) -> None:
        """Start a single consumer."""
        if subscription.name in self.consumers:
            logger.warning(f"Consumer {subscription.name} already started")
            return
        
        try:
            consumer = EventConsumer(subscription, self.broker)
            self.consumers[subscription.name] = consumer
            
            # Start in thread
            import threading
            thread = threading.Thread(
                target=consumer.start,
                name=f"consumer-{subscription.name}"
            )
            thread.daemon = True
            thread.start()
            
            logger.info(f"Started consumer thread for {subscription.name}")
            
        except Exception as e:
            logger.error(f"Failed to start consumer {subscription.name}: {e}")
    
    def stop_consumer(self, subscription_name: str) -> None:
        """Stop a single consumer."""
        if subscription_name not in self.consumers:
            logger.warning(f"Consumer {subscription_name} not found")
            return
        
        consumer = self.consumers[subscription_name]
        consumer.stop()
        del self.consumers[subscription_name]
        
        logger.info(f"Stopped consumer {subscription_name}")
    
    def stop_all(self) -> None:
        """Stop all consumers."""
        for name in list(self.consumers.keys()):
            self.stop_consumer(name)
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all consumers."""
        return {
            'active_consumers': len(self.consumers),
            'consumers': {
                name: {
                    'running': consumer._running,
                    'subscription': consumer.subscription.name,
                    'event_types': consumer.subscription.event_types
                }
                for name, consumer in self.consumers.items()
            }
        }


# Global consumer manager
consumer_manager = ConsumerManager()


def start_consumers():
    """Start all configured consumers."""
    consumer_manager.start_all()


def stop_consumers():
    """Stop all consumers."""
    consumer_manager.stop_all()