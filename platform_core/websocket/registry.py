"""
WebSocket Consumer Registry

Registry for managing WebSocket consumers.
"""

import logging
from typing import Dict, Type, Optional
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .exceptions import WebSocketException

logger = logging.getLogger(__name__)


class ConsumerRegistry:
    """
    Registry for WebSocket consumers.
    """
    
    def __init__(self):
        self._consumers: Dict[str, Type[AsyncJsonWebsocketConsumer]] = {}
    
    def register(self, name: str, consumer_class: Type[AsyncJsonWebsocketConsumer]):
        """
        Register a consumer.
        
        Args:
            name: Consumer name
            consumer_class: Consumer class
        """
        if name in self._consumers:
            logger.warning(f"Consumer {name} already registered, overwriting")
        
        self._consumers[name] = consumer_class
        logger.info(f"Registered WebSocket consumer: {name}")
    
    def unregister(self, name: str):
        """
        Unregister a consumer.
        
        Args:
            name: Consumer name
        """
        if name in self._consumers:
            del self._consumers[name]
            logger.info(f"Unregistered WebSocket consumer: {name}")
    
    def get(self, name: str) -> Optional[Type[AsyncJsonWebsocketConsumer]]:
        """
        Get a consumer by name.
        
        Args:
            name: Consumer name
            
        Returns:
            Consumer class or None
        """
        return self._consumers.get(name)
    
    def get_all(self) -> Dict[str, Type[AsyncJsonWebsocketConsumer]]:
        """
        Get all registered consumers.
        
        Returns:
            Dictionary of consumer names to classes
        """
        return self._consumers.copy()
    
    def exists(self, name: str) -> bool:
        """
        Check if a consumer is registered.
        
        Args:
            name: Consumer name
            
        Returns:
            True if registered
        """
        return name in self._consumers


# Global consumer registry
consumer_registry = ConsumerRegistry()