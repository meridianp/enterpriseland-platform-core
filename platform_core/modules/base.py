"""
Base Module Class

Abstract base class that all platform modules must inherit from.
Defines the interface and lifecycle hooks for modules.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Type
from django.db import models
from django.conf import settings


class BaseModule(ABC):
    """
    Base class for all platform modules.
    
    Modules must inherit from this class and implement the required methods.
    The module system will call these methods at appropriate times in the
    module lifecycle.
    """
    
    def __init__(self, manifest: 'ModuleManifest', installation: Optional['ModuleInstallation'] = None):
        """
        Initialize the module.
        
        Args:
            manifest: The module manifest from the database
            installation: The installation record if module is installed for a tenant
        """
        self.manifest = manifest
        self.installation = installation
        self.module_id = manifest.module_id
        self.version = manifest.version
        self.config = installation.configuration if installation else {}
        self._initialized = False
    
    # Required module metadata (must be overridden in subclasses)
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable module name"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Module description"""
        pass
    
    # Module lifecycle methods
    
    @abstractmethod
    def initialize(self) -> None:
        """
        Initialize the module.
        Called when the module is first loaded.
        """
        pass
    
    @abstractmethod
    def shutdown(self) -> None:
        """
        Shutdown the module gracefully.
        Called when the module is being unloaded.
        """
        pass
    
    def install(self, tenant: 'Tenant') -> None:
        """
        Install the module for a specific tenant.
        
        This method is called when a tenant installs the module.
        Override to perform module-specific installation tasks like:
        - Creating default data
        - Setting up integrations
        - Initializing module state
        
        Args:
            tenant: The tenant installing the module
        """
        pass
    
    def uninstall(self, tenant: 'Tenant') -> None:
        """
        Uninstall the module for a specific tenant.
        
        This method is called when a tenant uninstalls the module.
        Override to perform cleanup tasks like:
        - Removing module data (if allowed)
        - Cleaning up integrations
        - Archiving module state
        
        Args:
            tenant: The tenant uninstalling the module
        """
        pass
    
    def upgrade(self, tenant: 'Tenant', from_version: str) -> None:
        """
        Upgrade the module for a specific tenant.
        
        This method is called when a module is upgraded to a new version.
        Override to perform version-specific migrations.
        
        Args:
            tenant: The tenant upgrading the module
            from_version: The previous version of the module
        """
        pass
    
    def enable(self, tenant: 'Tenant') -> None:
        """
        Enable the module for a specific tenant.
        
        Called when a previously disabled module is re-enabled.
        
        Args:
            tenant: The tenant enabling the module
        """
        pass
    
    def disable(self, tenant: 'Tenant') -> None:
        """
        Disable the module for a specific tenant.
        
        Called when a module is temporarily disabled.
        
        Args:
            tenant: The tenant disabling the module
        """
        pass
    
    # Module component registration
    
    def get_entities(self) -> List[Type[models.Model]]:
        """
        Return module entity models.
        
        These are the Django models that this module provides.
        They should all inherit from BusinessObject.
        
        Returns:
            List of model classes
        """
        return []
    
    def get_workflows(self) -> Dict[str, Type['Workflow']]:
        """
        Return module workflow definitions.
        
        These are Viewflow workflow classes provided by this module.
        
        Returns:
            Dictionary mapping workflow IDs to workflow classes
        """
        return {}
    
    def get_agents(self) -> Dict[str, Type['Agent']]:
        """
        Return module AI agents.
        
        These are A2A-compatible agent classes provided by this module.
        
        Returns:
            Dictionary mapping agent IDs to agent classes
        """
        return {}
    
    def get_api_routes(self) -> List['APIRoute']:
        """
        Return module API routes.
        
        These are additional API endpoints exposed by this module.
        
        Returns:
            List of APIRoute objects
        """
        return []
    
    def get_ui_components(self) -> Dict[str, str]:
        """
        Return module UI component mappings.
        
        Maps component IDs to their frontend bundle locations.
        
        Returns:
            Dictionary mapping component IDs to bundle URLs
        """
        return {}
    
    def get_hooks(self) -> Dict[str, List['HookHandler']]:
        """
        Return module hook handlers.
        
        These are handlers for platform events that this module listens to.
        
        Returns:
            Dictionary mapping hook names to handler lists
        """
        return {}
    
    # Module configuration
    
    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """
        Validate module configuration.
        
        Called before configuration is saved to ensure it's valid.
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            List of validation error messages (empty if valid)
        """
        return []
    
    def get_default_configuration(self) -> Dict[str, Any]:
        """
        Get default module configuration.
        
        Returns:
            Default configuration dictionary
        """
        return {}
    
    # Module health and monitoring
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the module.
        
        Returns:
            Health check results including:
            - status: 'healthy', 'degraded', or 'unhealthy'
            - message: Human-readable status message
            - details: Additional diagnostic information
        """
        return {
            'status': 'healthy',
            'message': 'Module is functioning normally',
            'details': {}
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get module performance metrics.
        
        Returns:
            Dictionary of metric name to value mappings
        """
        return {}
    
    # Module permissions
    
    def validate_permissions(self, permission: str) -> bool:
        """
        Check if module has a specific permission.
        
        Args:
            permission: Permission to check
            
        Returns:
            True if module has the permission
        """
        return permission in self.manifest.permissions
    
    def get_required_permissions(self) -> List[str]:
        """
        Get list of permissions required by this module.
        
        Returns:
            List of permission strings
        """
        return self.manifest.permissions
    
    # Event handling
    
    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle platform events.
        
        Called when events occur that this module has subscribed to.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        pass
    
    # Utility methods
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a module configuration setting.
        
        Args:
            key: Setting key
            default: Default value if key not found
            
        Returns:
            Setting value
        """
        return self.config.get(key, default)
    
    def is_initialized(self) -> bool:
        """Check if module has been initialized"""
        return self._initialized
    
    def __str__(self) -> str:
        """String representation of the module"""
        return f"{self.name} ({self.module_id}@{self.version})"


class APIRoute:
    """Represents an API route exposed by a module"""
    
    def __init__(self, path: str, view_func, methods: List[str] = None, name: str = None):
        self.path = path
        self.view_func = view_func
        self.methods = methods or ['GET']
        self.name = name or path.replace('/', '_')


class HookHandler:
    """Represents a hook handler registered by a module"""
    
    def __init__(self, handler_func, priority: int = 50):
        self.handler_func = handler_func
        self.priority = priority  # Lower number = higher priority