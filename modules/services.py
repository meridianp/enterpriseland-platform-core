"""
Module service registration and discovery.

This module provides infrastructure for modules to register and expose services
to other parts of the platform.
"""

import logging
from typing import Dict, Type, Any, Optional, Protocol, runtime_checkable
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


@runtime_checkable
class ModuleService(Protocol):
    """Protocol that all module services must implement."""
    
    @property
    def service_name(self) -> str:
        """Return the service name."""
        ...
    
    @property
    def service_version(self) -> str:
        """Return the service version."""
        ...
    
    def health_check(self) -> Dict[str, Any]:
        """Check service health."""
        ...


class ServiceRegistry:
    """
    Central registry for module services.
    
    Allows modules to register services that can be discovered and used
    by other modules or the platform.
    """
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._service_metadata: Dict[str, Dict[str, Any]] = {}
        self._initialized = False
    
    def register(self, 
                 service_id: str, 
                 service_class: Type[Any],
                 metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Register a service with the platform.
        
        Args:
            service_id: Unique identifier for the service
            service_class: Service class or factory
            metadata: Optional metadata about the service
        """
        if service_id in self._services:
            logger.warning(f"Service {service_id} already registered, overwriting")
        
        self._services[service_id] = service_class
        self._service_metadata[service_id] = metadata or {}
        
        logger.info(f"Registered service: {service_id}")
    
    def register_from_string(self, 
                           service_id: str, 
                           service_path: str,
                           metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Register a service from a string path.
        
        Args:
            service_id: Unique identifier for the service
            service_path: Dotted path to service class
            metadata: Optional metadata about the service
        """
        try:
            service_class = import_string(service_path)
            self.register(service_id, service_class, metadata)
        except ImportError as e:
            logger.error(f"Failed to import service {service_path}: {e}")
            raise
    
    def get(self, service_id: str) -> Optional[Any]:
        """
        Get a service by ID.
        
        Args:
            service_id: Service identifier
            
        Returns:
            Service class or None if not found
        """
        return self._services.get(service_id)
    
    def get_instance(self, service_id: str, *args, **kwargs) -> Optional[Any]:
        """
        Get an instance of a service.
        
        Args:
            service_id: Service identifier
            *args: Arguments for service constructor
            **kwargs: Keyword arguments for service constructor
            
        Returns:
            Service instance or None if not found
        """
        service_class = self.get(service_id)
        if service_class:
            try:
                return service_class(*args, **kwargs)
            except Exception as e:
                logger.error(f"Failed to instantiate service {service_id}: {e}")
                raise
        return None
    
    def list_services(self) -> Dict[str, Dict[str, Any]]:
        """
        List all registered services.
        
        Returns:
            Dictionary of service IDs to metadata
        """
        result = {}
        for service_id, service_class in self._services.items():
            result[service_id] = {
                'class': f"{service_class.__module__}.{service_class.__name__}",
                'metadata': self._service_metadata.get(service_id, {}),
            }
        return result
    
    def unregister(self, service_id: str) -> bool:
        """
        Unregister a service.
        
        Args:
            service_id: Service identifier
            
        Returns:
            True if service was unregistered, False if not found
        """
        if service_id in self._services:
            del self._services[service_id]
            del self._service_metadata[service_id]
            logger.info(f"Unregistered service: {service_id}")
            return True
        return False
    
    def clear(self) -> None:
        """Clear all registered services."""
        self._services.clear()
        self._service_metadata.clear()
        logger.info("Cleared all registered services")
    
    def health_check(self) -> Dict[str, Dict[str, Any]]:
        """
        Check health of all registered services.
        
        Returns:
            Dictionary of service IDs to health status
        """
        results = {}
        
        for service_id, service_class in self._services.items():
            try:
                # Try to instantiate and check health
                if hasattr(service_class, 'health_check'):
                    # If it's a class with health_check method
                    instance = service_class()
                    health = instance.health_check()
                    results[service_id] = {
                        'status': 'healthy',
                        'details': health
                    }
                else:
                    # Just check if we can import it
                    results[service_id] = {
                        'status': 'available',
                        'details': {'class': str(service_class)}
                    }
            except Exception as e:
                results[service_id] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
        
        return results


# Global service registry instance
service_registry = ServiceRegistry()


def register_service(service_id: str, metadata: Optional[Dict[str, Any]] = None):
    """
    Decorator for registering services.
    
    Usage:
        @register_service('my_service')
        class MyService:
            pass
    """
    def decorator(service_class):
        service_registry.register(service_id, service_class, metadata)
        return service_class
    return decorator