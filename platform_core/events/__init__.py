"""
Event-Driven Messaging System

Provides a unified interface for event-driven architecture with support for:
- Multiple message brokers (RabbitMQ, Kafka, Redis)
- Event publishing and subscription
- Message routing and filtering
- Dead letter queues
- Event sourcing
- Saga pattern coordination
- Retry mechanisms
- Event schemas and validation
"""

default_app_config = 'platform_core.events.apps.EventsConfig'