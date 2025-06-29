"""
Module Loader

Handles dynamic loading of module code from the filesystem.
"""

import importlib
import importlib.util
import sys
import logging
from pathlib import Path
from typing import Type, Optional, List
from django.conf import settings

from .base import BaseModule
from .exceptions import ModuleLoadError, ModuleNotFoundError

logger = logging.getLogger(__name__)


class ModuleLoader:
    """
    Handles dynamic loading of module code.
    
    Modules can be loaded from:
    1. Installed Python packages
    2. Local filesystem paths
    3. Module directories configured in settings
    """
    
    def __init__(self):
        self.module_paths = self._get_module_paths()
        self._module_cache = {}
    
    def load_module_class(self, module_id: str) -> Type[BaseModule]:
        """
        Dynamically load a module class.
        
        Args:
            module_id: Module identifier (e.g., 'com.enterpriseland.investment')
            
        Returns:
            Module class that inherits from BaseModule
            
        Raises:
            ModuleNotFoundError: If module cannot be found
            ModuleLoadError: If module fails to load or is invalid
        """
        # Check cache first
        if module_id in self._module_cache:
            return self._module_cache[module_id]
        
        # Try different loading strategies
        module_class = None
        
        # Strategy 1: Try as installed package
        module_class = self._try_load_installed_package(module_id)
        
        # Strategy 2: Try from configured module paths
        if not module_class:
            module_class = self._try_load_from_paths(module_id)
        
        # Strategy 3: Try from modules directory
        if not module_class:
            module_class = self._try_load_from_modules_dir(module_id)
        
        if not module_class:
            raise ModuleNotFoundError(f"Module {module_id} not found in any location")
        
        # Validate module class
        self._validate_module_class(module_class, module_id)
        
        # Cache the loaded class
        self._module_cache[module_id] = module_class
        
        logger.info(f"Loaded module class for {module_id}")
        return module_class
    
    def _try_load_installed_package(self, module_id: str) -> Optional[Type[BaseModule]]:
        """Try to load module as an installed Python package"""
        # Convert module ID to Python package name
        # e.g., 'com.enterpriseland.investment' -> 'enterpriseland_investment'
        package_name = module_id.replace('.', '_').replace('-', '_')
        
        try:
            # Try to import the package
            module = importlib.import_module(package_name)
            
            # Look for Module class
            if hasattr(module, 'Module'):
                return getattr(module, 'Module')
            
            # Try .module submodule
            try:
                submodule = importlib.import_module(f"{package_name}.module")
                if hasattr(submodule, 'Module'):
                    return getattr(submodule, 'Module')
            except ImportError:
                pass
                
        except ImportError:
            pass
        
        return None
    
    def _try_load_from_paths(self, module_id: str) -> Optional[Type[BaseModule]]:
        """Try to load module from configured paths"""
        for base_path in self.module_paths:
            module_class = self._try_load_from_path(base_path, module_id)
            if module_class:
                return module_class
        return None
    
    def _try_load_from_path(self, base_path: Path, module_id: str) -> Optional[Type[BaseModule]]:
        """Try to load module from a specific path"""
        # Convert module ID to directory name
        # e.g., 'com.enterpriseland.investment' -> 'enterpriseland-investment'
        dir_name = module_id.split('.')[-1].replace('_', '-')
        module_path = base_path / dir_name
        
        if not module_path.exists() or not module_path.is_dir():
            return None
        
        # Look for module.py or __init__.py
        for filename in ['module.py', '__init__.py']:
            file_path = module_path / filename
            if file_path.exists():
                return self._load_module_from_file(file_path, module_id)
        
        return None
    
    def _try_load_from_modules_dir(self, module_id: str) -> Optional[Type[BaseModule]]:
        """Try to load from the modules directory in the project"""
        # Look in backend/modules/ directory
        backend_path = Path(settings.BASE_DIR).parent / 'modules'
        if backend_path.exists():
            return self._try_load_from_path(backend_path, module_id)
        
        # Look in platform-specific modules directory
        platform_modules = Path(settings.BASE_DIR).parent / 'platform_modules'
        if platform_modules.exists():
            return self._try_load_from_path(platform_modules, module_id)
        
        return None
    
    def _load_module_from_file(self, file_path: Path, module_id: str) -> Optional[Type[BaseModule]]:
        """Load a module from a specific Python file"""
        try:
            # Create module spec
            spec = importlib.util.spec_from_file_location(
                f"dynamic_{module_id.replace('.', '_')}",
                file_path
            )
            
            if not spec or not spec.loader:
                return None
            
            # Load the module
            module = importlib.util.module_from_spec(spec)
            
            # Add to sys.modules to handle imports within the module
            sys.modules[spec.name] = module
            
            # Execute the module
            spec.loader.exec_module(module)
            
            # Look for Module class
            if hasattr(module, 'Module'):
                return getattr(module, 'Module')
            
            # Try to find any class that inherits from BaseModule
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, BaseModule) and 
                    attr != BaseModule):
                    return attr
            
        except Exception as e:
            logger.error(f"Failed to load module from {file_path}: {e}")
            raise ModuleLoadError(f"Failed to load module {module_id}: {e}")
        
        return None
    
    def _validate_module_class(self, module_class: Type[BaseModule], module_id: str) -> None:
        """Validate that the loaded class is a valid module"""
        if not issubclass(module_class, BaseModule):
            raise ModuleLoadError(
                f"Module {module_id} must inherit from BaseModule"
            )
        
        # Check required properties
        required_attrs = ['name', 'description']
        for attr in required_attrs:
            try:
                # Try to access the property on a dummy instance
                # We can't instantiate without manifest, so check the property exists
                if not hasattr(module_class, attr):
                    raise ModuleLoadError(
                        f"Module {module_id} missing required property: {attr}"
                    )
            except Exception:
                pass  # Property might require instance
        
        # Check required methods are implemented
        abstract_methods = ['initialize', 'shutdown']
        for method in abstract_methods:
            if not hasattr(module_class, method):
                raise ModuleLoadError(
                    f"Module {module_id} missing required method: {method}"
                )
    
    def _get_module_paths(self) -> List[Path]:
        """Get configured module search paths"""
        paths = []
        
        # Default paths
        base_dir = Path(settings.BASE_DIR)
        
        # Add paths from settings
        for path_str in getattr(settings, 'MODULE_PATHS', []):
            path = Path(path_str)
            if not path.is_absolute():
                path = base_dir / path
            if path.exists():
                paths.append(path)
        
        # Add default module directories
        default_paths = [
            base_dir / 'modules',
            base_dir.parent / 'modules',
            base_dir.parent / 'platform_modules',
        ]
        
        for path in default_paths:
            if path.exists() and path not in paths:
                paths.append(path)
        
        return paths
    
    def reload_module(self, module_id: str) -> Type[BaseModule]:
        """
        Reload a module class (useful for development).
        
        Args:
            module_id: Module to reload
            
        Returns:
            Reloaded module class
        """
        # Remove from cache
        if module_id in self._module_cache:
            del self._module_cache[module_id]
        
        # Remove from sys.modules if loaded
        dynamic_name = f"dynamic_{module_id.replace('.', '_')}"
        if dynamic_name in sys.modules:
            del sys.modules[dynamic_name]
        
        # Reload
        return self.load_module_class(module_id)
    
    def get_available_modules(self) -> List[str]:
        """
        Scan for available modules in all paths.
        
        Returns:
            List of discovered module IDs
        """
        modules = []
        
        for path in self.module_paths:
            if not path.exists():
                continue
            
            for item in path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    # Check if it contains a module
                    if (item / 'module.py').exists() or (item / '__init__.py').exists():
                        # Try to determine module ID
                        manifest_file = item / 'module.json'
                        if manifest_file.exists():
                            import json
                            try:
                                with open(manifest_file) as f:
                                    manifest = json.load(f)
                                    if 'id' in manifest:
                                        modules.append(manifest['id'])
                            except Exception:
                                pass
        
        return modules