"""
Event System Signals

Django signals for event system integration.
"""

from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver, Signal

from .models import Event, EventSubscription, EventProcessor
from .publishers import event_publisher

# Custom signals
event_published = Signal()  # Sent when event is published
event_processed = Signal()  # Sent when event is processed
event_failed = Signal()     # Sent when event processing fails
subscription_created = Signal()  # Sent when subscription is created
subscription_paused = Signal()   # Sent when subscription is paused


@receiver(post_save, sender=EventSubscription)
def handle_subscription_change(sender, instance, created, **kwargs):
    """Handle subscription creation or update."""
    if created:
        subscription_created.send(
            sender=EventSubscription,
            subscription=instance
        )
        
        # Publish event about new subscription
        event_publisher.publish(
            event_type='events.subscription_created',
            data={
                'subscription_id': str(instance.id),
                'name': instance.name,
                'event_types': instance.event_types
            }
        )
    
    # Check if subscription was paused/unpaused
    if not created and 'is_paused' in kwargs.get('update_fields', []):
        if instance.is_paused:
            subscription_paused.send(
                sender=EventSubscription,
                subscription=instance,
                paused=True
            )
        else:
            subscription_paused.send(
                sender=EventSubscription,
                subscription=instance,
                paused=False
            )


@receiver(post_save, sender=Event)
def handle_event_status_change(sender, instance, **kwargs):
    """Handle event status changes."""
    if instance.status == 'published':
        event_published.send(
            sender=Event,
            event=instance
        )
    elif instance.status == 'failed':
        event_failed.send(
            sender=Event,
            event=instance,
            error=instance.error_message
        )


@receiver(post_save, sender=EventProcessor)
def handle_processor_completion(sender, instance, **kwargs):
    """Handle event processor completion."""
    if instance.status == 'completed':
        event_processed.send(
            sender=EventProcessor,
            processor=instance,
            event=instance.event,
            subscription=instance.subscription
        )
    elif instance.status == 'failed':
        event_failed.send(
            sender=EventProcessor,
            processor=instance,
            event=instance.event,
            subscription=instance.subscription,
            error=instance.error_message
        )