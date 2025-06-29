"""
Module Registry

Central registry for all platform modules. Manages module discovery,
loading, and lifecycle.
"""

import logging
from typing import Dict, List, Optional, Type, Set, Tuple
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import ModuleManifest, ModuleInstallation, ModuleDependency, ModuleEvent
from .base import BaseModule
from .exceptions import (
    ModuleError, ModuleNotFoundError, DependencyError,
    CircularDependencyError, ModuleStateError
)
from .loader import ModuleLoader

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """
    Central registry for all platform modules.
    
    This is a singleton that manages:
    - Module discovery and registration
    - Module loading and unloading
    - Dependency resolution
    - Module lifecycle management
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._loaded_modules: Dict[str, BaseModule] = {}
            self._module_classes: Dict[str, Type[BaseModule]] = {}
            self._load_order: List[str] = []
            self._loader = ModuleLoader()
            self._initialized = True
    
    # Module Registration
    
    def register_module(self, manifest_data: Dict) -> ModuleManifest:
        """
        Register a new module from manifest data.
        
        Args:
            manifest_data: Module manifest as dictionary
            
        Returns:
            Created ModuleManifest instance
            
        Raises:
            ModuleValidationError: If manifest is invalid
        """
        with transaction.atomic():
            # Check if module already exists
            existing = ModuleManifest.objects.filter(
                module_id=manifest_data['module_id'],
                version=manifest_data['version']
            ).first()
            
            if existing:
                logger.info(f"Module {manifest_data['module_id']} v{manifest_data['version']} already registered")
                return existing
            
            # Create manifest
            manifest = ModuleManifest.objects.create(**manifest_data)
            
            # Clear cache
            self._clear_cache(manifest.module_id)
            
            logger.info(f"Registered module {manifest.module_id} v{manifest.version}")
            return manifest
    
    def update_module(self, module_id: str, version: str, updates: Dict) -> ModuleManifest:
        """
        Update an existing module manifest.
        
        Args:
            module_id: Module identifier
            version: Module version
            updates: Fields to update
            
        Returns:
            Updated ModuleManifest
        """
        with transaction.atomic():
            manifest = ModuleManifest.objects.get(
                module_id=module_id,
                version=version
            )
            
            for key, value in updates.items():
                setattr(manifest, key, value)
            
            manifest.save()
            self._clear_cache(module_id)
            
            return manifest
    
    # Module Discovery
    
    def discover_modules(self) -> List[ModuleManifest]:
        """
        Discover all available modules.
        
        Returns:
            List of available module manifests
        """
        return list(ModuleManifest.objects.filter(is_active=True))
    
    def get_module(self, module_id: str, version: Optional[str] = None) -> Optional[ModuleManifest]:
        """
        Get a specific module manifest.
        
        Args:
            module_id: Module identifier
            version: Specific version (latest if not specified)
            
        Returns:
            ModuleManifest or None if not found
        """
        cache_key = f"module_manifest:{module_id}:{version or 'latest'}"
        manifest = cache.get(cache_key)
        
        if manifest is None:
            query = ModuleManifest.objects.filter(
                module_id=module_id,
                is_active=True
            )
            
            if version:
                query = query.filter(version=version)
            else:
                query = query.order_by('-created_at')
            
            manifest = query.first()
            
            if manifest:
                cache.set(cache_key, manifest, 3600)  # Cache for 1 hour
        
        return manifest
    
    # Module Loading
    
    def load_module(self, module_id: str, tenant_id: Optional[str] = None) -> BaseModule:
        """
        Load and initialize a module.
        
        Args:
            module_id: Module to load
            tenant_id: Tenant context (optional)
            
        Returns:
            Loaded module instance
            
        Raises:
            ModuleNotFoundError: If module not found
            DependencyError: If dependencies cannot be satisfied
            ModuleLoadError: If module fails to load
        """
        # Check if already loaded
        cache_key = f"{module_id}:{tenant_id}" if tenant_id else module_id
        if cache_key in self._loaded_modules:
            return self._loaded_modules[cache_key]
        
        # Get manifest
        manifest = self.get_module(module_id)
        if not manifest:
            raise ModuleNotFoundError(f"Module {module_id} not found")
        
        # Get installation if tenant specified
        installation = None
        if tenant_id:
            installation = ModuleInstallation.objects.filter(
                tenant_id=tenant_id,
                module=manifest,
                status='active'
            ).first()
            
            if not installation:
                raise ModuleStateError(f"Module {module_id} not installed for tenant")
        
        # Check and load dependencies first
        self._load_dependencies(manifest, tenant_id)
        
        # Load module class
        module_class = self._get_module_class(module_id)
        
        # Create module instance
        module = module_class(manifest, installation)
        
        # Initialize module
        try:
            module.initialize()
            module._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize module {module_id}: {e}")
            raise
        
        # Store in registry
        self._loaded_modules[cache_key] = module
        self._load_order.append(cache_key)
        
        # Log event
        if installation:
            ModuleEvent.objects.create(
                module=manifest,
                installation=installation,
                tenant_id=tenant_id,
                event_type='module.enabled',
                event_data={'initialized': True}
            )
        
        logger.info(f"Loaded module {module_id}")
        return module
    
    def unload_module(self, module_id: str, tenant_id: Optional[str] = None) -> None:
        """
        Unload a module and its dependents.
        
        Args:
            module_id: Module to unload
            tenant_id: Tenant context (optional)
        """
        cache_key = f"{module_id}:{tenant_id}" if tenant_id else module_id
        
        if cache_key not in self._loaded_modules:
            return
        
        # Find dependent modules that need to be unloaded first
        dependents = self._find_loaded_dependents(module_id, tenant_id)
        
        # Unload dependents first
        for dep_key in dependents:
            if dep_key in self._loaded_modules:
                self._unload_single_module(dep_key)
        
        # Unload the module itself
        self._unload_single_module(cache_key)
    
    def _unload_single_module(self, cache_key: str) -> None:
        """Unload a single module"""
        module = self._loaded_modules.get(cache_key)
        if not module:
            return
        
        try:
            module.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down module {module.module_id}: {e}")
        
        del self._loaded_modules[cache_key]
        self._load_order.remove(cache_key)
        
        logger.info(f"Unloaded module {module.module_id}")
    
    # Dependency Management
    
    def _load_dependencies(self, manifest: ModuleManifest, tenant_id: Optional[str] = None) -> None:
        """Load all dependencies for a module"""
        for dep_id in manifest.dependencies:
            try:
                self.load_module(dep_id, tenant_id)
            except ModuleError as e:
                raise DependencyError(f"Failed to load dependency {dep_id}: {e}")
    
    def check_dependencies(self, module_id: str) -> Tuple[bool, List[str]]:
        """
        Check if all dependencies for a module are available.
        
        Args:
            module_id: Module to check
            
        Returns:
            Tuple of (all_satisfied, missing_dependencies)
        """
        manifest = self.get_module(module_id)
        if not manifest:
            return False, [f"Module {module_id} not found"]
        
        missing = []
        for dep_id in manifest.dependencies:
            if not self.get_module(dep_id):
                missing.append(dep_id)
        
        return len(missing) == 0, missing
    
    def resolve_dependencies(self, module_ids: List[str]) -> List[str]:
        """
        Resolve dependencies and return modules in load order.
        
        Args:
            module_ids: Modules to resolve
            
        Returns:
            Modules in dependency order (dependencies first)
            
        Raises:
            CircularDependencyError: If circular dependencies detected
        """
        # Build dependency graph
        graph = {}
        for module_id in module_ids:
            manifest = self.get_module(module_id)
            if manifest:
                graph[module_id] = manifest.dependencies
        
        # Detect circular dependencies
        if self._has_circular_dependency(graph):
            raise CircularDependencyError("Circular dependency detected")
        
        # Topological sort
        return self._topological_sort(graph)
    
    def _has_circular_dependency(self, graph: Dict[str, List[str]]) -> bool:
        """Check for circular dependencies using DFS"""
        visited = set()
        rec_stack = set()
        
        def has_cycle(node):
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        for node in graph:
            if node not in visited:
                if has_cycle(node):
                    return True
        
        return False
    
    def _topological_sort(self, graph: Dict[str, List[str]]) -> List[str]:
        """Perform topological sort on dependency graph"""
        in_degree = {node: 0 for node in graph}
        
        # Calculate in-degrees
        for node in graph:
            for dep in graph[node]:
                if dep in in_degree:
                    in_degree[dep] += 1
        
        # Find nodes with no dependencies
        queue = [node for node, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            node = queue.pop(0)
            result.append(node)
            
            # Remove node from graph
            for dep in graph.get(node, []):
                if dep in in_degree:
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)
        
        return result[::-1]  # Reverse to get dependencies first
    
    def _find_loaded_dependents(self, module_id: str, tenant_id: Optional[str] = None) -> List[str]:
        """Find loaded modules that depend on the given module"""
        dependents = []
        
        for cache_key, module in self._loaded_modules.items():
            if module.module_id == module_id:
                continue
                
            manifest = self.get_module(module.module_id)
            if manifest and module_id in manifest.dependencies:
                dependents.append(cache_key)
        
        return dependents
    
    # Module Class Management
    
    def _get_module_class(self, module_id: str) -> Type[BaseModule]:
        """Get or load module class"""
        if module_id not in self._module_classes:
            self._module_classes[module_id] = self._loader.load_module_class(module_id)
        return self._module_classes[module_id]
    
    def register_module_class(self, module_id: str, module_class: Type[BaseModule]) -> None:
        """
        Register a module class directly (for testing).
        
        Args:
            module_id: Module identifier
            module_class: Module class
        """
        self._module_classes[module_id] = module_class
    
    # Module Queries
    
    def get_loaded_modules(self) -> Dict[str, BaseModule]:
        """Get all currently loaded modules"""
        return self._loaded_modules.copy()
    
    def is_module_loaded(self, module_id: str, tenant_id: Optional[str] = None) -> bool:
        """Check if a module is loaded"""
        cache_key = f"{module_id}:{tenant_id}" if tenant_id else module_id
        return cache_key in self._loaded_modules
    
    def get_modules_by_tag(self, tag: str) -> List[ModuleManifest]:
        """Get modules with a specific tag"""
        return list(ModuleManifest.objects.filter(
            tags__contains=[tag],
            is_active=True
        ))
    
    def get_modules_by_type(self, entity_type: str) -> List[ModuleManifest]:
        """Get modules that provide a specific entity type"""
        return list(ModuleManifest.objects.filter(
            entities__contains=[entity_type],
            is_active=True
        ))
    
    # Utility Methods
    
    def _clear_cache(self, module_id: str) -> None:
        """Clear cache entries for a module"""
        cache.delete_pattern(f"module_manifest:{module_id}:*")
    
    def clear(self) -> None:
        """Clear all loaded modules (for testing)"""
        for cache_key in list(self._loaded_modules.keys()):
            self._unload_single_module(cache_key)
        
        self._module_classes.clear()
        self._load_order.clear()


# Global registry instance
module_registry = ModuleRegistry()