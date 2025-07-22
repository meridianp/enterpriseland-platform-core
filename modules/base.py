"""
Base module class for EnterpriseLand platform modules.

All business modules must inherit from BaseModule and implement
the required abstract methods.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Type
import yaml
import json
from pathlib import Path
from django.apps import AppConfig
from django.db import models
from .services import service_registry


class ModuleManifest:
    """
    Represents a module's manifest file containing metadata and configuration.
    """
    
    def __init__(self, manifest_path: Path):
        self.path = manifest_path
        self._data = self._load_manifest()
    
    def _load_manifest(self) -> Dict[str, Any]:
        """Load manifest from YAML or JSON file."""
        if self.path.suffix == '.yaml' or self.path.suffix == '.yml':
            with open(self.path, 'r') as f:
                return yaml.safe_load(f)
        elif self.path.suffix == '.json':
            with open(self.path, 'r') as f:
                return json.load(f)
        else:
            raise ValueError(f"Unsupported manifest format: {self.path.suffix}")
    
    @property
    def module_id(self) -> str:
        """Get the module ID."""
        return self._data['module']['id']
    
    @property
    def version(self) -> str:
        """Get the module version."""
        return self._data['module']['version']
    
    @property
    def name(self) -> str:
        """Get the module display name."""
        return self._data['metadata']['name']
    
    @property
    def description(self) -> str:
        """Get the module description."""
        return self._data['metadata'].get('description', '')
    
    @property
    def dependencies(self) -> Dict[str, str]:
        """Get module dependencies."""
        deps = {}
        for dep in self._data.get('dependencies', []):
            if isinstance(dep, dict):
                deps.update(dep)
            else:
                # Handle simple string format
                parts = dep.split(':')
                deps[parts[0]] = parts[1] if len(parts) > 1 else '*'
        return deps
    
    @property
    def services(self) -> List[Dict[str, str]]:
        """Get exposed services."""
        return self._data.get('services', [])
    
    @property
    def models(self) -> List[str]:
        """Get registered models."""
        return self._data.get('models', [])
    
    @property
    def api_endpoints(self) -> List[str]:
        """Get API endpoints."""
        return self._data.get('api_endpoints', [])
    
    @property
    def ui_components(self) -> List[str]:
        """Get UI components."""
        return self._data.get('ui_components', [])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to dictionary."""
        return self._data


class BaseModule(ABC):
    """
    Abstract base class for all EnterpriseLand modules.
    
    Modules must implement all abstract methods to be loaded by the platform.
    """
    
    def __init__(self, manifest: Optional[ModuleManifest] = None):
        self.manifest = manifest
        self._initialized = False
        self._services = {}
        self._models = {}
        self._registered_services = []  # Track services registered with platform
    
    @property
    def module_id(self) -> str:
        """Get the module ID from manifest."""
        return self.manifest.module_id
    
    @property
    def version(self) -> str:
        """Get the module version from manifest."""
        return self.manifest.version
    
    @property
    def name(self) -> str:
        """Get the module display name from manifest."""
        return self.manifest.name
    
    def register_service(self, service_id: str, service_class: Type[Any], metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Register a service with the platform.
        
        Args:
            service_id: Unique identifier for the service (will be prefixed with module ID)
            service_class: Service class or factory
            metadata: Optional metadata about the service
        """
        # Prefix service ID with module ID to avoid conflicts
        full_service_id = f"{self.module_id}.{service_id}" if self.manifest else service_id
        
        # Register with platform
        service_registry.register(full_service_id, service_class, metadata)
        
        # Track internally
        self._services[service_id] = service_class
        self._registered_services.append(full_service_id)
    
    def unregister_services(self) -> None:
        """Unregister all services registered by this module."""
        for service_id in self._registered_services:
            service_registry.unregister(service_id)
        self._registered_services.clear()
        self._services.clear()
    
    @abstractmethod
    def initialize(self) -> None:
        """
        Initialize the module.
        
        This is called when the module is first loaded. Use this to:
        - Register services with self.register_service()
        - Set up signal handlers
        - Initialize module-specific configuration
        """
        pass
    
    def shutdown(self) -> None:
        """
        Shutdown the module.
        
        This is called when the module is being unloaded. Override to:
        - Clean up resources
        - Disconnect signal handlers
        - Save state if needed
        """
        self.unregister_services()
        self._initialized = False
    
    @abstractmethod
    def get_service(self, service_name: str) -> Optional[Any]:
        """
        Get a service exposed by this module.
        
        Args:
            service_name: Name of the service to retrieve
            
        Returns:
            The service instance or None if not found
        """
        pass
    
    @abstractmethod
    def get_models(self) -> List[type[models.Model]]:
        """
        Get all Django models provided by this module.
        
        Returns:
            List of model classes
        """
        pass
    
    @abstractmethod
    def get_api_urls(self) -> List:
        """
        Get URL patterns for this module's API endpoints.
        
        Returns:
            List of Django URL patterns
        """
        pass
    
    @abstractmethod
    def get_admin_urls(self) -> List:
        """
        Get URL patterns for this module's admin interface.
        
        Returns:
            List of Django URL patterns
        """
        pass
    
    def install(self, group_id: Optional[str] = None) -> bool:
        """
        Install the module for a specific group/tenant.
        
        Args:
            group_id: The group/tenant to install for (None for global)
            
        Returns:
            True if installation successful
        """
        # Default implementation - override if needed
        return True
    
    def uninstall(self, group_id: Optional[str] = None) -> bool:
        """
        Uninstall the module for a specific group/tenant.
        
        Args:
            group_id: The group/tenant to uninstall for (None for global)
            
        Returns:
            True if uninstallation successful
        """
        # Default implementation - override if needed
        return True
    
    def enable(self, group_id: Optional[str] = None) -> bool:
        """
        Enable the module for a specific group/tenant.
        
        Args:
            group_id: The group/tenant to enable for (None for global)
            
        Returns:
            True if enabling successful
        """
        # Default implementation - override if needed
        return True
    
    def disable(self, group_id: Optional[str] = None) -> bool:
        """
        Disable the module for a specific group/tenant.
        
        Args:
            group_id: The group/tenant to disable for (None for global)
            
        Returns:
            True if disabling successful
        """
        # Default implementation - override if needed
        return True
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the module.
        
        Returns:
            Dictionary with health status and any issues
        """
        return {
            'status': 'healthy',
            'module_id': self.module_id,
            'version': self.version,
            'initialized': self._initialized
        }
    
    def get_permissions(self) -> List[str]:
        """
        Get permission strings required by this module.
        
        Returns:
            List of permission strings (e.g., ['view_assessment', 'change_assessment'])
        """
        # Default implementation - extract from models
        permissions = []
        for model in self.get_models():
            app_label = model._meta.app_label
            model_name = model._meta.model_name
            permissions.extend([
                f'{app_label}.view_{model_name}',
                f'{app_label}.add_{model_name}',
                f'{app_label}.change_{model_name}',
                f'{app_label}.delete_{model_name}',
            ])
        return permissions
    
    def get_settings_schema(self) -> Dict[str, Any]:
        """
        Get JSON schema for module-specific settings.
        
        Returns:
            JSON schema dictionary
        """
        return {}
    
    def validate_settings(self, settings: Dict[str, Any]) -> bool:
        """
        Validate module-specific settings.
        
        Args:
            settings: Settings dictionary to validate
            
        Returns:
            True if settings are valid
        """
        # Default implementation - override for custom validation
        return True


class ModuleConfig(AppConfig):
    """
    Django AppConfig for modules.
    
    This can be used as a base class for module Django apps.
    """
    
    module_class = None  # Set this to your module class
    
    def ready(self):
        """Initialize the module when Django starts."""
        if self.module_class:
            # Find and load manifest
            manifest_path = Path(self.path) / 'manifest.yaml'
            if not manifest_path.exists():
                manifest_path = Path(self.path) / 'module.json'
            
            if manifest_path.exists():
                manifest = ModuleManifest(manifest_path)
                module = self.module_class(manifest)
                module.initialize()
                
                # Register module with the platform
                from ..registry import module_registry
                module_registry.register(module)