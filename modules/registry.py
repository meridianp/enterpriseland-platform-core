"""
Module registry for managing loaded modules.

The registry keeps track of all loaded modules and provides
methods for discovering and accessing them.
"""

from typing import Dict, List, Optional, Set
import logging
from django.db import models
from django.core.exceptions import ImproperlyConfigured

from .base import BaseModule


logger = logging.getLogger(__name__)


class ModuleRegistry:
    """
    Central registry for all loaded modules.
    
    This is a singleton that maintains the list of available modules
    and provides methods for module discovery and access.
    """
    
    def __init__(self):
        self._modules: Dict[str, BaseModule] = {}
        self._enabled_modules: Dict[str, Set[str]] = {}  # group_id -> module_ids
        self._service_registry: Dict[str, Dict[str, BaseModule]] = {}  # service_name -> {module_id: module}
        self._model_registry: Dict[str, str] = {}  # model_label -> module_id
    
    def register(self, module: BaseModule) -> None:
        """
        Register a module with the platform.
        
        Args:
            module: The module instance to register
            
        Raises:
            ImproperlyConfigured: If module is already registered
        """
        module_id = module.module_id
        
        if module_id in self._modules:
            raise ImproperlyConfigured(
                f"Module '{module_id}' is already registered"
            )
        
        # Store the module
        self._modules[module_id] = module
        
        # Register services
        for service_info in module.manifest.services:
            service_name = service_info.get('interface', service_info.get('class'))
            if service_name:
                if service_name not in self._service_registry:
                    self._service_registry[service_name] = {}
                self._service_registry[service_name][module_id] = module
        
        # Register models
        for model in module.get_models():
            model_label = f"{model._meta.app_label}.{model._meta.model_name}"
            self._model_registry[model_label] = module_id
        
        logger.info(f"Registered module: {module_id} v{module.version}")
    
    def unregister(self, module_id: str) -> None:
        """
        Unregister a module from the platform.
        
        Args:
            module_id: ID of the module to unregister
        """
        if module_id not in self._modules:
            logger.warning(f"Attempted to unregister unknown module: {module_id}")
            return
        
        module = self._modules[module_id]
        
        # Remove from service registry
        for service_info in module.manifest.services:
            service_name = service_info.get('interface', service_info.get('class'))
            if service_name and service_name in self._service_registry:
                self._service_registry[service_name].pop(module_id, None)
                if not self._service_registry[service_name]:
                    del self._service_registry[service_name]
        
        # Remove from model registry
        models_to_remove = [
            label for label, mid in self._model_registry.items()
            if mid == module_id
        ]
        for label in models_to_remove:
            del self._model_registry[label]
        
        # Remove from enabled modules
        for group_modules in self._enabled_modules.values():
            group_modules.discard(module_id)
        
        # Remove the module
        del self._modules[module_id]
        
        logger.info(f"Unregistered module: {module_id}")
    
    def get_module(self, module_id: str) -> Optional[BaseModule]:
        """
        Get a module by ID.
        
        Args:
            module_id: The module ID
            
        Returns:
            The module instance or None if not found
        """
        return self._modules.get(module_id)
    
    def get_all_modules(self) -> List[BaseModule]:
        """
        Get all registered modules.
        
        Returns:
            List of all module instances
        """
        return list(self._modules.values())
    
    def get_modules_for_group(self, group_id: str) -> List[BaseModule]:
        """
        Get modules enabled for a specific group/tenant.
        
        Args:
            group_id: The group/tenant ID
            
        Returns:
            List of enabled module instances
        """
        module_ids = self._enabled_modules.get(group_id, set())
        return [
            self._modules[module_id]
            for module_id in module_ids
            if module_id in self._modules
        ]
    
    def enable_module(self, module_id: str, group_id: str) -> bool:
        """
        Enable a module for a specific group/tenant.
        
        Args:
            module_id: The module ID
            group_id: The group/tenant ID
            
        Returns:
            True if enabling was successful
        """
        if module_id not in self._modules:
            logger.error(f"Cannot enable unknown module: {module_id}")
            return False
        
        module = self._modules[module_id]
        
        # Call module's enable method
        if not module.enable(group_id):
            return False
        
        # Track in registry
        if group_id not in self._enabled_modules:
            self._enabled_modules[group_id] = set()
        self._enabled_modules[group_id].add(module_id)
        
        logger.info(f"Enabled module '{module_id}' for group '{group_id}'")
        return True
    
    def disable_module(self, module_id: str, group_id: str) -> bool:
        """
        Disable a module for a specific group/tenant.
        
        Args:
            module_id: The module ID
            group_id: The group/tenant ID
            
        Returns:
            True if disabling was successful
        """
        if module_id not in self._modules:
            logger.error(f"Cannot disable unknown module: {module_id}")
            return False
        
        module = self._modules[module_id]
        
        # Call module's disable method
        if not module.disable(group_id):
            return False
        
        # Remove from registry
        if group_id in self._enabled_modules:
            self._enabled_modules[group_id].discard(module_id)
        
        logger.info(f"Disabled module '{module_id}' for group '{group_id}'")
        return True
    
    def get_service(self, service_name: str, module_id: Optional[str] = None) -> Optional[object]:
        """
        Get a service by name.
        
        Args:
            service_name: Name of the service
            module_id: Optional module ID to get service from specific module
            
        Returns:
            The service instance or None if not found
        """
        if service_name not in self._service_registry:
            return None
        
        if module_id:
            # Get from specific module
            module = self._service_registry[service_name].get(module_id)
            if module:
                return module.get_service(service_name)
        else:
            # Get from first available module
            for module in self._service_registry[service_name].values():
                service = module.get_service(service_name)
                if service:
                    return service
        
        return None
    
    def get_model_module(self, model: type[models.Model]) -> Optional[str]:
        """
        Get the module ID that provides a specific model.
        
        Args:
            model: The model class
            
        Returns:
            Module ID or None if not found
        """
        model_label = f"{model._meta.app_label}.{model._meta.model_name}"
        return self._model_registry.get(model_label)
    
    def check_dependencies(self, module: BaseModule) -> Dict[str, bool]:
        """
        Check if a module's dependencies are satisfied.
        
        Args:
            module: The module to check
            
        Returns:
            Dictionary mapping dependency names to availability status
        """
        results = {}
        
        for dep_name, dep_version in module.manifest.dependencies.items():
            # Check if dependency module is registered
            dep_module = self.get_module(dep_name)
            if dep_module:
                # TODO: Add version checking
                results[dep_name] = True
            else:
                results[dep_name] = False
        
        return results
    
    def get_module_health(self) -> Dict[str, Dict]:
        """
        Get health status of all modules.
        
        Returns:
            Dictionary mapping module IDs to health status
        """
        health_status = {}
        
        for module_id, module in self._modules.items():
            try:
                health_status[module_id] = module.health_check()
            except Exception as e:
                health_status[module_id] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        return health_status


# Global module registry instance
module_registry = ModuleRegistry()