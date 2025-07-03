"""
Event Models

Defines event schemas, subscriptions, and event store.
"""

import uuid
from typing import Dict, Any
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from platform_core.common.models import BaseModel, TenantFilteredModel


class EventSchema(TenantFilteredModel):
    """
    Defines the schema for an event type.
    """
    
    EVENT_VERSIONS = [
        ('1.0', 'Version 1.0'),
        ('1.1', 'Version 1.1'),
        ('2.0', 'Version 2.0'),
    ]
    
    # Event identification
    event_type = models.CharField(
        max_length=100,
        unique=True,
        validators=[RegexValidator(r'^[a-zA-Z0-9._-]+$')],
        help_text=_("Event type identifier (e.g., user.created, order.placed)")
    )
    version = models.CharField(
        max_length=10,
        choices=EVENT_VERSIONS,
        default='1.0',
        help_text=_("Event schema version")
    )
    
    # Schema definition
    name = models.CharField(
        max_length=200,
        help_text=_("Human-readable event name")
    )
    description = models.TextField(
        blank=True,
        help_text=_("Event description")
    )
    schema = models.JSONField(
        help_text=_("JSON Schema for event validation"),
        default=dict
    )
    
    # Routing
    routing_key = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("Default routing key pattern")
    )
    exchange = models.CharField(
        max_length=100,
        default='events',
        help_text=_("Message exchange/topic")
    )
    
    # Configuration
    ttl = models.IntegerField(
        default=0,
        help_text=_("Time to live in seconds (0 = no expiry)")
    )
    priority = models.IntegerField(
        default=0,
        help_text=_("Default message priority")
    )
    persistent = models.BooleanField(
        default=True,
        help_text=_("Persist messages to disk")
    )
    
    # Metadata
    is_active = models.BooleanField(
        default=True,
        help_text=_("Schema is active")
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional schema metadata")
    )
    
    class Meta:
        db_table = 'events_schemas'
        verbose_name = 'Event Schema'
        verbose_name_plural = 'Event Schemas'
        unique_together = [('event_type', 'version')]
        ordering = ['event_type', '-version']
    
    def __str__(self):
        return f"{self.name} ({self.event_type} v{self.version})"
    
    def validate_event_data(self, data: Dict[str, Any]) -> bool:
        """Validate event data against schema"""
        if not self.schema:
            return True
        
        try:
            import jsonschema
            jsonschema.validate(data, self.schema)
            return True
        except jsonschema.ValidationError:
            return False


class EventSubscription(TenantFilteredModel):
    """
    Subscription to event types.
    """
    
    SUBSCRIPTION_TYPES = [
        ('queue', 'Queue Consumer'),
        ('topic', 'Topic Subscriber'),
        ('fanout', 'Fanout Subscriber'),
        ('webhook', 'Webhook'),
    ]
    
    RETRY_POLICIES = [
        ('exponential', 'Exponential Backoff'),
        ('linear', 'Linear Retry'),
        ('fixed', 'Fixed Interval'),
        ('none', 'No Retry'),
    ]
    
    # Subscription info
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Subscription identifier")
    )
    description = models.TextField(
        blank=True
    )
    
    # Event configuration
    event_types = ArrayField(
        models.CharField(max_length=100),
        help_text=_("List of event types to subscribe to")
    )
    filter_expression = models.TextField(
        blank=True,
        help_text=_("JMESPath expression for filtering events")
    )
    
    # Delivery configuration
    subscription_type = models.CharField(
        max_length=20,
        choices=SUBSCRIPTION_TYPES,
        default='queue'
    )
    endpoint = models.CharField(
        max_length=500,
        help_text=_("Queue name, topic, or webhook URL")
    )
    
    # Processing
    handler = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("Handler function path (e.g., myapp.handlers.process_order)")
    )
    max_retries = models.IntegerField(
        default=3,
        help_text=_("Maximum retry attempts")
    )
    retry_policy = models.CharField(
        max_length=20,
        choices=RETRY_POLICIES,
        default='exponential'
    )
    retry_delay = models.IntegerField(
        default=60,
        help_text=_("Initial retry delay in seconds")
    )
    
    # Dead letter queue
    dead_letter_queue = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("Dead letter queue name")
    )
    max_receive_count = models.IntegerField(
        default=5,
        help_text=_("Max receives before dead lettering")
    )
    
    # Configuration
    batch_size = models.IntegerField(
        default=1,
        help_text=_("Number of messages to process in batch")
    )
    visibility_timeout = models.IntegerField(
        default=300,
        help_text=_("Message visibility timeout in seconds")
    )
    concurrent_workers = models.IntegerField(
        default=1,
        help_text=_("Number of concurrent workers")
    )
    
    # Status
    is_active = models.BooleanField(
        default=True,
        help_text=_("Subscription is active")
    )
    is_paused = models.BooleanField(
        default=False,
        help_text=_("Subscription is paused")
    )
    last_error = models.TextField(
        blank=True,
        help_text=_("Last error message")
    )
    last_error_at = models.DateTimeField(
        null=True,
        blank=True
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True
    )
    
    class Meta:
        db_table = 'events_subscriptions'
        verbose_name = 'Event Subscription'
        verbose_name_plural = 'Event Subscriptions'
        indexes = [
            models.Index(fields=['is_active', 'is_paused']),
            models.Index(fields=['event_types']),
        ]
    
    def __str__(self):
        return f"{self.name} ({', '.join(self.event_types[:3])}...)"


class Event(TenantFilteredModel):
    """
    Represents a published event.
    Stores events for event sourcing and audit trail.
    """
    
    EVENT_STATUS = [
        ('pending', 'Pending'),
        ('published', 'Published'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
        ('expired', 'Expired'),
    ]
    
    # Event identification
    event_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        help_text=_("Unique event identifier")
    )
    event_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text=_("Event type")
    )
    version = models.CharField(
        max_length=10,
        default='1.0'
    )
    
    # Event data
    data = models.JSONField(
        help_text=_("Event payload")
    )
    metadata = models.JSONField(
        default=dict,
        help_text=_("Event metadata (headers, context)")
    )
    
    # Source information
    source = models.CharField(
        max_length=200,
        help_text=_("Event source (service/module)")
    )
    correlation_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text=_("Correlation ID for tracing")
    )
    causation_id = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("ID of event that caused this event")
    )
    
    # User context
    user = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("User who triggered the event")
    )
    
    # Timing
    occurred_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text=_("When the event occurred")
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("When the event was published")
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Event expiration time")
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=EVENT_STATUS,
        default='pending',
        db_index=True
    )
    publish_attempts = models.IntegerField(
        default=0,
        help_text=_("Number of publish attempts")
    )
    error_message = models.TextField(
        blank=True,
        help_text=_("Last error message")
    )
    
    class Meta:
        db_table = 'events_store'
        verbose_name = 'Event'
        verbose_name_plural = 'Events'
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['event_type', 'occurred_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['correlation_id']),
        ]
    
    def __str__(self):
        return f"{self.event_type} ({self.event_id})"
    
    def mark_published(self):
        """Mark event as published"""
        self.status = 'published'
        self.published_at = timezone.now()
        self.save(update_fields=['status', 'published_at'])
    
    def mark_failed(self, error: str):
        """Mark event as failed"""
        self.status = 'failed'
        self.error_message = error
        self.save(update_fields=['status', 'error_message'])


class EventProcessor(TenantFilteredModel):
    """
    Tracks event processing status for each subscription.
    """
    
    PROCESSING_STATUS = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
        ('dead_lettered', 'Dead Lettered'),
    ]
    
    # References
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='processors'
    )
    subscription = models.ForeignKey(
        EventSubscription,
        on_delete=models.CASCADE,
        related_name='processed_events'
    )
    
    # Processing info
    status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS,
        default='pending',
        db_index=True
    )
    attempts = models.IntegerField(
        default=0,
        help_text=_("Processing attempts")
    )
    
    # Timing
    started_at = models.DateTimeField(
        null=True,
        blank=True
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )
    next_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True
    )
    
    # Results
    result = models.JSONField(
        null=True,
        blank=True,
        help_text=_("Processing result")
    )
    error_message = models.TextField(
        blank=True
    )
    error_details = models.JSONField(
        null=True,
        blank=True
    )
    
    class Meta:
        db_table = 'events_processors'
        verbose_name = 'Event Processor'
        verbose_name_plural = 'Event Processors'
        unique_together = [('event', 'subscription')]
        indexes = [
            models.Index(fields=['status', 'next_retry_at']),
            models.Index(fields=['subscription', 'status']),
        ]
    
    def __str__(self):
        return f"{self.subscription.name} - {self.event.event_type}"


class SagaInstance(TenantFilteredModel):
    """
    Represents an instance of a long-running saga/process.
    """
    
    SAGA_STATUS = [
        ('started', 'Started'),
        ('running', 'Running'),
        ('compensating', 'Compensating'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Identification
    saga_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True
    )
    saga_type = models.CharField(
        max_length=100,
        help_text=_("Saga type identifier")
    )
    
    # State
    status = models.CharField(
        max_length=20,
        choices=SAGA_STATUS,
        default='started',
        db_index=True
    )
    current_step = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Current saga step")
    )
    state_data = models.JSONField(
        default=dict,
        help_text=_("Saga state data")
    )
    
    # Context
    correlation_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text=_("Correlation ID")
    )
    initiating_event_id = models.CharField(
        max_length=100,
        help_text=_("ID of event that started the saga")
    )
    
    # History
    completed_steps = ArrayField(
        models.CharField(max_length=100),
        default=list,
        help_text=_("List of completed steps")
    )
    compensated_steps = ArrayField(
        models.CharField(max_length=100),
        default=list,
        help_text=_("List of compensated steps")
    )
    
    # Timing
    started_at = models.DateTimeField(
        auto_now_add=True
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Saga expiration time")
    )
    
    # Error handling
    error_message = models.TextField(
        blank=True
    )
    retry_count = models.IntegerField(
        default=0
    )
    
    class Meta:
        db_table = 'events_saga_instances'
        verbose_name = 'Saga Instance'
        verbose_name_plural = 'Saga Instances'
        indexes = [
            models.Index(fields=['saga_type', 'status']),
            models.Index(fields=['correlation_id']),
            models.Index(fields=['status', 'expires_at']),
        ]
    
    def __str__(self):
        return f"{self.saga_type} - {self.saga_id}"
    
    def add_completed_step(self, step: str):
        """Add a completed step"""
        if step not in self.completed_steps:
            self.completed_steps.append(step)
            self.save(update_fields=['completed_steps'])
    
    def start_compensation(self):
        """Start compensation process"""
        self.status = 'compensating'
        self.save(update_fields=['status'])