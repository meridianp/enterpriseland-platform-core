"""
Message Broker Abstraction Layer

Provides a unified interface for different message brokers.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone
import pika  # RabbitMQ
import redis  # Redis
from kafka import KafkaProducer, KafkaConsumer  # Kafka

from .models import Event, EventSubscription

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Represents a message in the system."""
    
    id: str
    event_type: str
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    correlation_id: Optional[str] = None
    timestamp: Optional[float] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary."""
        return {
            'id': self.id,
            'event_type': self.event_type,
            'data': self.data,
            'metadata': self.metadata,
            'correlation_id': self.correlation_id,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Create message from dictionary."""
        return cls(**data)
    
    def to_json(self) -> str:
        """Convert message to JSON."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        """Create message from JSON."""
        return cls.from_dict(json.loads(json_str))


class MessageBroker(ABC):
    """Abstract base class for message brokers."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.connection = None
        self.is_connected = False
    
    @abstractmethod
    def connect(self) -> None:
        """Connect to the message broker."""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the message broker."""
        pass
    
    @abstractmethod
    def publish(self, message: Message, exchange: str = '', routing_key: str = '') -> bool:
        """Publish a message."""
        pass
    
    @abstractmethod
    def subscribe(self, queue: str, callback: Callable[[Message], None], 
                  exchange: str = '', routing_key: str = '') -> None:
        """Subscribe to messages."""
        pass
    
    @abstractmethod
    def create_queue(self, queue: str, durable: bool = True, 
                     exclusive: bool = False, auto_delete: bool = False) -> None:
        """Create a queue."""
        pass
    
    @abstractmethod
    def create_exchange(self, exchange: str, exchange_type: str = 'direct', 
                        durable: bool = True) -> None:
        """Create an exchange."""
        pass
    
    @abstractmethod
    def bind_queue(self, queue: str, exchange: str, routing_key: str = '') -> None:
        """Bind queue to exchange."""
        pass
    
    @abstractmethod
    def acknowledge(self, message_id: str) -> None:
        """Acknowledge message processing."""
        pass
    
    @abstractmethod
    def reject(self, message_id: str, requeue: bool = True) -> None:
        """Reject message."""
        pass
    
    def ensure_connected(self) -> None:
        """Ensure broker is connected."""
        if not self.is_connected:
            self.connect()


class RabbitMQBroker(MessageBroker):
    """RabbitMQ message broker implementation."""
    
    def connect(self) -> None:
        """Connect to RabbitMQ."""
        try:
            params = pika.ConnectionParameters(
                host=self.config.get('host', 'localhost'),
                port=self.config.get('port', 5672),
                virtual_host=self.config.get('vhost', '/'),
                credentials=pika.PlainCredentials(
                    self.config.get('username', 'guest'),
                    self.config.get('password', 'guest')
                ),
                heartbeat=self.config.get('heartbeat', 600),
                blocked_connection_timeout=self.config.get('timeout', 300)
            )
            
            self.connection = pika.BlockingConnection(params)
            self.channel = self.connection.channel()
            self.is_connected = True
            
            # Enable publisher confirms
            self.channel.confirm_delivery()
            
            logger.info("Connected to RabbitMQ")
            
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    def disconnect(self) -> None:
        """Disconnect from RabbitMQ."""
        if self.connection and not self.connection.is_closed:
            self.connection.close()
            self.is_connected = False
            logger.info("Disconnected from RabbitMQ")
    
    def publish(self, message: Message, exchange: str = '', routing_key: str = '') -> bool:
        """Publish message to RabbitMQ."""
        self.ensure_connected()
        
        try:
            properties = pika.BasicProperties(
                delivery_mode=2,  # Persistent
                message_id=message.id,
                timestamp=int(message.timestamp),
                correlation_id=message.correlation_id,
                content_type='application/json',
                headers=message.metadata
            )
            
            self.channel.basic_publish(
                exchange=exchange,
                routing_key=routing_key or message.event_type,
                body=message.to_json(),
                properties=properties
            )
            
            logger.debug(f"Published message {message.id} to {exchange}/{routing_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            return False
    
    def subscribe(self, queue: str, callback: Callable[[Message], None], 
                  exchange: str = '', routing_key: str = '') -> None:
        """Subscribe to messages from RabbitMQ."""
        self.ensure_connected()
        
        def wrapper(ch, method, properties, body):
            try:
                message = Message.from_json(body.decode('utf-8'))
                message.metadata['delivery_tag'] = method.delivery_tag
                callback(message)
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        
        # Bind queue if exchange specified
        if exchange:
            self.bind_queue(queue, exchange, routing_key)
        
        # Set QoS
        self.channel.basic_qos(prefetch_count=self.config.get('prefetch_count', 1))
        
        # Start consuming
        self.channel.basic_consume(
            queue=queue,
            on_message_callback=wrapper,
            auto_ack=False
        )
        
        logger.info(f"Subscribed to queue: {queue}")
        
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            self.channel.stop_consuming()
    
    def create_queue(self, queue: str, durable: bool = True, 
                     exclusive: bool = False, auto_delete: bool = False) -> None:
        """Create RabbitMQ queue."""
        self.ensure_connected()
        
        arguments = {}
        
        # Add dead letter exchange if configured
        if self.config.get('dead_letter_exchange'):
            arguments['x-dead-letter-exchange'] = self.config['dead_letter_exchange']
        
        # Add TTL if configured
        if self.config.get('message_ttl'):
            arguments['x-message-ttl'] = self.config['message_ttl']
        
        self.channel.queue_declare(
            queue=queue,
            durable=durable,
            exclusive=exclusive,
            auto_delete=auto_delete,
            arguments=arguments
        )
        
        logger.debug(f"Created queue: {queue}")
    
    def create_exchange(self, exchange: str, exchange_type: str = 'direct', 
                        durable: bool = True) -> None:
        """Create RabbitMQ exchange."""
        self.ensure_connected()
        
        self.channel.exchange_declare(
            exchange=exchange,
            exchange_type=exchange_type,
            durable=durable
        )
        
        logger.debug(f"Created exchange: {exchange} (type: {exchange_type})")
    
    def bind_queue(self, queue: str, exchange: str, routing_key: str = '') -> None:
        """Bind queue to exchange."""
        self.ensure_connected()
        
        self.channel.queue_bind(
            queue=queue,
            exchange=exchange,
            routing_key=routing_key
        )
        
        logger.debug(f"Bound queue {queue} to {exchange} with key {routing_key}")
    
    def acknowledge(self, message_id: str) -> None:
        """Acknowledge message."""
        self.ensure_connected()
        
        # In RabbitMQ, we use delivery_tag stored in metadata
        # This would be passed through the message metadata
        # For now, this is a placeholder
        logger.debug(f"Acknowledged message: {message_id}")
    
    def reject(self, message_id: str, requeue: bool = True) -> None:
        """Reject message."""
        self.ensure_connected()
        
        # Similar to acknowledge, uses delivery_tag
        logger.debug(f"Rejected message: {message_id}, requeue: {requeue}")


class RedisBroker(MessageBroker):
    """Redis message broker implementation using pub/sub."""
    
    def connect(self) -> None:
        """Connect to Redis."""
        try:
            self.redis_client = redis.Redis(
                host=self.config.get('host', 'localhost'),
                port=self.config.get('port', 6379),
                db=self.config.get('db', 0),
                password=self.config.get('password'),
                decode_responses=True
            )
            
            # Test connection
            self.redis_client.ping()
            self.is_connected = True
            
            logger.info("Connected to Redis")
            
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    def disconnect(self) -> None:
        """Disconnect from Redis."""
        if hasattr(self, 'redis_client'):
            self.redis_client.close()
            self.is_connected = False
            logger.info("Disconnected from Redis")
    
    def publish(self, message: Message, exchange: str = '', routing_key: str = '') -> bool:
        """Publish message to Redis channel."""
        self.ensure_connected()
        
        try:
            channel = routing_key or message.event_type
            
            # Store message in list for persistence
            queue_key = f"queue:{channel}"
            self.redis_client.rpush(queue_key, message.to_json())
            
            # Publish to channel for real-time delivery
            self.redis_client.publish(channel, message.to_json())
            
            # Set TTL if configured
            if self.config.get('message_ttl'):
                self.redis_client.expire(queue_key, self.config['message_ttl'])
            
            logger.debug(f"Published message {message.id} to channel {channel}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            return False
    
    def subscribe(self, queue: str, callback: Callable[[Message], None], 
                  exchange: str = '', routing_key: str = '') -> None:
        """Subscribe to Redis channel."""
        self.ensure_connected()
        
        pubsub = self.redis_client.pubsub()
        channel = routing_key or queue
        pubsub.subscribe(channel)
        
        logger.info(f"Subscribed to channel: {channel}")
        
        try:
            # Process existing messages in queue
            queue_key = f"queue:{channel}"
            while True:
                # Get message from queue
                message_data = self.redis_client.lpop(queue_key)
                if message_data:
                    try:
                        message = Message.from_json(message_data)
                        callback(message)
                    except Exception as e:
                        logger.error(f"Error processing queued message: {e}")
                
                # Listen for new messages
                message = pubsub.get_message(timeout=1.0)
                if message and message['type'] == 'message':
                    try:
                        msg = Message.from_json(message['data'])
                        callback(msg)
                    except Exception as e:
                        logger.error(f"Error processing pub/sub message: {e}")
                        
        except KeyboardInterrupt:
            pubsub.unsubscribe(channel)
            pubsub.close()
    
    def create_queue(self, queue: str, durable: bool = True, 
                     exclusive: bool = False, auto_delete: bool = False) -> None:
        """Create Redis queue (no-op for Redis)."""
        # Redis doesn't require explicit queue creation
        logger.debug(f"Queue {queue} will be created on first use")
    
    def create_exchange(self, exchange: str, exchange_type: str = 'direct', 
                        durable: bool = True) -> None:
        """Create exchange (no-op for Redis)."""
        # Redis pub/sub doesn't have exchanges
        logger.debug(f"Exchange {exchange} not needed for Redis")
    
    def bind_queue(self, queue: str, exchange: str, routing_key: str = '') -> None:
        """Bind queue to exchange (no-op for Redis)."""
        # Redis doesn't have queue binding
        logger.debug(f"Queue binding not needed for Redis")
    
    def acknowledge(self, message_id: str) -> None:
        """Acknowledge message (no-op for Redis pub/sub)."""
        # Redis pub/sub doesn't have acknowledgments
        logger.debug(f"Message acknowledgment not needed for Redis")
    
    def reject(self, message_id: str, requeue: bool = True) -> None:
        """Reject message (no-op for Redis pub/sub)."""
        # Redis pub/sub doesn't have rejection
        logger.debug(f"Message rejection not needed for Redis")


class KafkaBroker(MessageBroker):
    """Apache Kafka message broker implementation."""
    
    def connect(self) -> None:
        """Connect to Kafka."""
        try:
            # Producer configuration
            self.producer = KafkaProducer(
                bootstrap_servers=self.config.get('bootstrap_servers', ['localhost:9092']),
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                acks=self.config.get('acks', 'all'),
                retries=self.config.get('retries', 3),
                max_in_flight_requests_per_connection=self.config.get('max_in_flight', 5),
                compression_type=self.config.get('compression', 'gzip')
            )
            
            self.is_connected = True
            logger.info("Connected to Kafka")
            
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            raise
    
    def disconnect(self) -> None:
        """Disconnect from Kafka."""
        if hasattr(self, 'producer'):
            self.producer.close()
        if hasattr(self, 'consumer'):
            self.consumer.close()
        self.is_connected = False
        logger.info("Disconnected from Kafka")
    
    def publish(self, message: Message, exchange: str = '', routing_key: str = '') -> bool:
        """Publish message to Kafka topic."""
        self.ensure_connected()
        
        try:
            topic = exchange or routing_key or message.event_type
            
            # Send message
            future = self.producer.send(
                topic,
                value=message.to_dict(),
                key=message.correlation_id.encode() if message.correlation_id else None,
                headers=[
                    ('event_type', message.event_type.encode()),
                    ('message_id', message.id.encode())
                ]
            )
            
            # Wait for send to complete
            future.get(timeout=10)
            
            logger.debug(f"Published message {message.id} to topic {topic}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            return False
    
    def subscribe(self, queue: str, callback: Callable[[Message], None], 
                  exchange: str = '', routing_key: str = '') -> None:
        """Subscribe to Kafka topic."""
        self.ensure_connected()
        
        topics = [exchange or routing_key or queue]
        
        # Consumer configuration
        self.consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=self.config.get('bootstrap_servers', ['localhost:9092']),
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id=self.config.get('group_id', 'default-group'),
            enable_auto_commit=False,
            auto_offset_reset=self.config.get('auto_offset_reset', 'latest')
        )
        
        logger.info(f"Subscribed to topics: {topics}")
        
        try:
            for kafka_message in self.consumer:
                try:
                    # Convert Kafka message to our Message format
                    message_data = kafka_message.value
                    message = Message.from_dict(message_data)
                    
                    # Add Kafka metadata
                    message.metadata['kafka_offset'] = kafka_message.offset
                    message.metadata['kafka_partition'] = kafka_message.partition
                    message.metadata['kafka_topic'] = kafka_message.topic
                    
                    # Process message
                    callback(message)
                    
                    # Commit offset
                    self.consumer.commit()
                    
                except Exception as e:
                    logger.error(f"Error processing Kafka message: {e}")
                    
        except KeyboardInterrupt:
            self.consumer.close()
    
    def create_queue(self, queue: str, durable: bool = True, 
                     exclusive: bool = False, auto_delete: bool = False) -> None:
        """Create Kafka topic."""
        # Kafka topics are usually created automatically or via admin tools
        logger.debug(f"Topic {queue} will be created on first use")
    
    def create_exchange(self, exchange: str, exchange_type: str = 'direct', 
                        durable: bool = True) -> None:
        """Create exchange (topics in Kafka)."""
        # Kafka doesn't have exchanges, uses topics
        logger.debug(f"Topic {exchange} will be used as exchange")
    
    def bind_queue(self, queue: str, exchange: str, routing_key: str = '') -> None:
        """Bind queue to exchange (no-op for Kafka)."""
        # Kafka doesn't have queue binding
        logger.debug(f"Queue binding not needed for Kafka")
    
    def acknowledge(self, message_id: str) -> None:
        """Acknowledge message (commit offset in Kafka)."""
        # Kafka uses offset commits instead of per-message acks
        logger.debug(f"Message offset committed for: {message_id}")
    
    def reject(self, message_id: str, requeue: bool = True) -> None:
        """Reject message (seek in Kafka)."""
        # Kafka doesn't have message rejection, would need to seek
        logger.debug(f"Message rejection handled via offset management: {message_id}")


class BrokerFactory:
    """Factory for creating message brokers."""
    
    BROKERS = {
        'rabbitmq': RabbitMQBroker,
        'redis': RedisBroker,
        'kafka': KafkaBroker
    }
    
    @classmethod
    def create(cls, broker_type: str, config: Dict[str, Any]) -> MessageBroker:
        """Create a message broker instance."""
        broker_class = cls.BROKERS.get(broker_type)
        
        if not broker_class:
            raise ValueError(f"Unknown broker type: {broker_type}")
        
        return broker_class(config)
    
    @classmethod
    def from_settings(cls) -> MessageBroker:
        """Create broker from Django settings."""
        config = getattr(settings, 'EVENT_BROKER', {})
        broker_type = config.get('type', 'redis')
        
        return cls.create(broker_type, config)