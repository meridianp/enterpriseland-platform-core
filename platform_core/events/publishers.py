"""
Event Publishers

Handles publishing events to the message broker.
"""

import uuid
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Event, EventSchema
from .brokers import BrokerFactory, Message
from .exceptions import (
    EventPublishError,
    EventValidationError,
    EventSchemaNotFound
)

User = get_user_model()
logger = logging.getLogger(__name__)


class EventPublisher:
    """Publishes events to message broker."""
    
    def __init__(self, broker=None):
        """Initialize publisher with optional broker."""
        self.broker = broker or BrokerFactory.from_settings()
        self._ensure_broker_connected()
    
    def _ensure_broker_connected(self):
        """Ensure broker is connected."""
        try:
            self.broker.ensure_connected()
        except Exception as e:
            logger.error(f"Failed to connect to broker: {e}")
            raise EventPublishError(f"Broker connection failed: {e}")
    
    def publish(self, 
                event_type: str,
                data: Dict[str, Any],
                user: Optional[User] = None,
                correlation_id: Optional[str] = None,
                metadata: Optional[Dict[str, Any]] = None,
                version: str = '1.0',
                source: Optional[str] = None) -> Event:
        """
        Publish an event.
        
        Args:
            event_type: Type of event (e.g., 'user.created')
            data: Event payload data
            user: User who triggered the event
            correlation_id: ID for correlating related events
            metadata: Additional metadata
            version: Event schema version
            source: Source system/module
            
        Returns:
            Created Event instance
        """
        # Find event schema
        try:
            schema = EventSchema.objects.get(
                event_type=event_type,
                version=version,
                is_active=True
            )
        except EventSchema.DoesNotExist:
            # Allow publishing without schema if configured
            if not getattr(settings, 'EVENTS_REQUIRE_SCHEMA', True):
                schema = None
            else:
                raise EventSchemaNotFound(
                    f"No active schema found for {event_type} v{version}"
                )
        
        # Validate data against schema
        if schema and not schema.validate_event_data(data):
            raise EventValidationError(
                f"Event data does not match schema for {event_type}"
            )
        
        # Create event record
        with transaction.atomic():
            event = Event.objects.create(
                event_type=event_type,
                version=version,
                data=data,
                metadata=metadata or {},
                source=source or 'platform',
                correlation_id=correlation_id or str(uuid.uuid4()),
                user=user,
                status='pending'
            )
            
            # Create message
            message = Message(
                id=str(event.event_id),
                event_type=event_type,
                data=data,
                metadata={
                    'version': version,
                    'source': event.source,
                    'user_id': str(user.id) if user else None,
                    'tenant_id': str(event.group_id) if hasattr(event, 'group_id') else None,
                    **(metadata or {})
                },
                correlation_id=event.correlation_id
            )
            
            # Determine routing
            exchange = schema.exchange if schema else 'events'
            routing_key = schema.routing_key if schema else event_type
            
            # Publish to broker
            try:
                success = self.broker.publish(
                    message=message,
                    exchange=exchange,
                    routing_key=routing_key
                )
                
                if success:
                    event.mark_published()
                    logger.info(f"Published event {event.event_id} ({event_type})")
                else:
                    event.publish_attempts += 1
                    event.save()
                    raise EventPublishError("Failed to publish event to broker")
                    
            except Exception as e:
                event.mark_failed(str(e))
                logger.error(f"Error publishing event {event.event_id}: {e}")
                raise EventPublishError(f"Event publish failed: {e}")
        
        return event
    
    def publish_batch(self, events: List[Dict[str, Any]]) -> List[Event]:
        """
        Publish multiple events.
        
        Args:
            events: List of event dictionaries with same structure as publish()
            
        Returns:
            List of created Event instances
        """
        created_events = []
        
        for event_data in events:
            try:
                event = self.publish(**event_data)
                created_events.append(event)
            except Exception as e:
                logger.error(f"Failed to publish event in batch: {e}")
                if getattr(settings, 'EVENTS_BATCH_FAIL_FAST', True):
                    raise
        
        return created_events
    
    def republish_failed(self, 
                         since: Optional[datetime] = None,
                         max_attempts: int = 3) -> Dict[str, Any]:
        """
        Retry publishing failed events.
        
        Args:
            since: Only retry events failed after this time
            max_attempts: Maximum publish attempts before giving up
            
        Returns:
            Dictionary with retry statistics
        """
        # Query failed events
        queryset = Event.objects.filter(
            status='failed',
            publish_attempts__lt=max_attempts
        )
        
        if since:
            queryset = queryset.filter(created_at__gte=since)
        
        stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0
        }
        
        for event in queryset:
            stats['total'] += 1
            
            try:
                # Create message from event
                message = Message(
                    id=str(event.event_id),
                    event_type=event.event_type,
                    data=event.data,
                    metadata=event.metadata,
                    correlation_id=event.correlation_id
                )
                
                # Determine routing
                try:
                    schema = EventSchema.objects.get(
                        event_type=event.event_type,
                        version=event.version,
                        is_active=True
                    )
                    exchange = schema.exchange
                    routing_key = schema.routing_key
                except EventSchema.DoesNotExist:
                    exchange = 'events'
                    routing_key = event.event_type
                
                # Attempt to publish
                success = self.broker.publish(
                    message=message,
                    exchange=exchange,
                    routing_key=routing_key
                )
                
                if success:
                    event.mark_published()
                    stats['success'] += 1
                else:
                    event.publish_attempts += 1
                    event.save()
                    stats['failed'] += 1
                    
            except Exception as e:
                logger.error(f"Error republishing event {event.event_id}: {e}")
                event.publish_attempts += 1
                event.error_message = str(e)
                event.save()
                stats['failed'] += 1
        
        logger.info(
            f"Republish complete: {stats['success']}/{stats['total']} succeeded"
        )
        
        return stats


class DomainEventPublisher:
    """
    Publisher for domain events with built-in patterns.
    """
    
    def __init__(self, domain: str, publisher: Optional[EventPublisher] = None):
        """
        Initialize domain publisher.
        
        Args:
            domain: Domain name (e.g., 'user', 'order')
            publisher: Optional EventPublisher instance
        """
        self.domain = domain
        self.publisher = publisher or EventPublisher()
    
    def _build_event_type(self, action: str) -> str:
        """Build event type from domain and action."""
        return f"{self.domain}.{action}"
    
    def created(self, entity_id: str, data: Dict[str, Any], **kwargs) -> Event:
        """Publish entity created event."""
        return self.publisher.publish(
            event_type=self._build_event_type('created'),
            data={
                'id': entity_id,
                **data
            },
            **kwargs
        )
    
    def updated(self, entity_id: str, 
                changes: Dict[str, Any],
                previous: Optional[Dict[str, Any]] = None,
                **kwargs) -> Event:
        """Publish entity updated event."""
        return self.publisher.publish(
            event_type=self._build_event_type('updated'),
            data={
                'id': entity_id,
                'changes': changes,
                'previous': previous
            },
            **kwargs
        )
    
    def deleted(self, entity_id: str, 
                data: Optional[Dict[str, Any]] = None,
                **kwargs) -> Event:
        """Publish entity deleted event."""
        return self.publisher.publish(
            event_type=self._build_event_type('deleted'),
            data={
                'id': entity_id,
                **(data or {})
            },
            **kwargs
        )
    
    def state_changed(self, entity_id: str,
                      from_state: str,
                      to_state: str,
                      **kwargs) -> Event:
        """Publish state change event."""
        return self.publisher.publish(
            event_type=self._build_event_type('state_changed'),
            data={
                'id': entity_id,
                'from_state': from_state,
                'to_state': to_state,
                'transition': f"{from_state}_to_{to_state}"
            },
            **kwargs
        )
    
    def action_performed(self, action: str,
                         entity_id: str,
                         data: Dict[str, Any],
                         **kwargs) -> Event:
        """Publish custom action event."""
        return self.publisher.publish(
            event_type=self._build_event_type(action),
            data={
                'id': entity_id,
                'action': action,
                **data
            },
            **kwargs
        )


# Convenience publishers for common domains
class UserEventPublisher(DomainEventPublisher):
    """Publisher for user-related events."""
    
    def __init__(self):
        super().__init__('user')
    
    def registered(self, user_id: str, email: str, **kwargs) -> Event:
        """Publish user registered event."""
        return self.created(
            entity_id=user_id,
            data={'email': email},
            **kwargs
        )
    
    def logged_in(self, user_id: str, ip_address: str, **kwargs) -> Event:
        """Publish user login event."""
        return self.action_performed(
            action='logged_in',
            entity_id=user_id,
            data={'ip_address': ip_address},
            **kwargs
        )
    
    def password_changed(self, user_id: str, **kwargs) -> Event:
        """Publish password changed event."""
        return self.action_performed(
            action='password_changed',
            entity_id=user_id,
            data={},
            **kwargs
        )


class OrderEventPublisher(DomainEventPublisher):
    """Publisher for order-related events."""
    
    def __init__(self):
        super().__init__('order')
    
    def placed(self, order_id: str, 
               customer_id: str,
               total: float,
               items: List[Dict[str, Any]],
               **kwargs) -> Event:
        """Publish order placed event."""
        return self.created(
            entity_id=order_id,
            data={
                'customer_id': customer_id,
                'total': total,
                'items': items
            },
            **kwargs
        )
    
    def shipped(self, order_id: str, 
                tracking_number: str,
                carrier: str,
                **kwargs) -> Event:
        """Publish order shipped event."""
        return self.state_changed(
            entity_id=order_id,
            from_state='processing',
            to_state='shipped',
            metadata={
                'tracking_number': tracking_number,
                'carrier': carrier
            },
            **kwargs
        )
    
    def cancelled(self, order_id: str, 
                  reason: str,
                  **kwargs) -> Event:
        """Publish order cancelled event."""
        return self.action_performed(
            action='cancelled',
            entity_id=order_id,
            data={'reason': reason},
            **kwargs
        )


# Global publisher instances
event_publisher = EventPublisher()
user_events = UserEventPublisher()
order_events = OrderEventPublisher()