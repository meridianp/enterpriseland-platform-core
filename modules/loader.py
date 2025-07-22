"""
Module loader for discovering and loading EnterpriseLand modules.

The loader searches for modules in various locations and loads them
into the platform.
"""

import os
import sys
import importlib
import importlib.util
from pathlib import Path
from typing import List, Optional, Set, Tuple
import logging
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseModule, ModuleManifest
from .registry import module_registry


logger = logging.getLogger(__name__)


class ModuleLoader:
    """
    Loads modules from various sources including filesystem and installed packages.
    """
    
    def __init__(self):
        self.search_paths: List[Path] = []
        self._loaded_modules: Set[str] = set()
        self._setup_search_paths()
    
    def _setup_search_paths(self):
        """Set up default search paths for modules."""
        # Add paths from settings
        module_paths = getattr(settings, 'MODULE_PATHS', [])
        for path in module_paths:
            self.add_search_path(path)
        
        # Add default paths
        base_dir = Path(settings.BASE_DIR)
        default_paths = [
            base_dir / 'modules',
            base_dir / 'business_modules',
            base_dir.parent / 'modules',  # For when backend is in subdirectory
        ]
        
        for path in default_paths:
            if path.exists() and path.is_dir():
                self.add_search_path(path)
    
    def add_search_path(self, path: str) -> None:
        """
        Add a path to search for modules.
        
        Args:
            path: Directory path to search
        """
        path_obj = Path(path).resolve()
        if path_obj.exists() and path_obj.is_dir():
            if path_obj not in self.search_paths:
                self.search_paths.append(path_obj)
                # Add to Python path for imports
                if str(path_obj) not in sys.path:
                    sys.path.insert(0, str(path_obj))
        else:
            logger.warning(f"Module search path does not exist: {path}")
    
    def discover_modules(self) -> List[Tuple[Path, ModuleManifest]]:
        """
        Discover all available modules by searching for manifest files.
        
        Returns:
            List of (module_path, manifest) tuples
        """
        discovered = []
        
        for search_path in self.search_paths:
            # Look for module directories
            for item in search_path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    # Check for manifest file
                    manifest_path = None
                    for manifest_name in ['manifest.yaml', 'manifest.yml', 'module.json']:
                        candidate = item / manifest_name
                        if candidate.exists():
                            manifest_path = candidate
                            break
                    
                    if manifest_path:
                        try:
                            manifest = ModuleManifest(manifest_path)
                            discovered.append((item, manifest))
                            logger.debug(f"Discovered module: {manifest.module_id} at {item}")
                        except Exception as e:
                            logger.error(f"Failed to load manifest at {manifest_path}: {e}")
        
        # Also check for installed packages with entry points
        discovered.extend(self._discover_package_modules())
        
        return discovered
    
    def _discover_package_modules(self) -> List[Tuple[Path, ModuleManifest]]:
        """
        Discover modules installed as Python packages.
        
        Returns:
            List of (module_path, manifest) tuples
        """
        discovered = []
        
        # Check for modules using entry points
        try:
            from importlib.metadata import entry_points
            
            # Look for 'enterpriseland.modules' entry points
            eps = entry_points()
            if hasattr(eps, 'select'):
                # Python 3.10+
                module_eps = eps.select(group='enterpriseland.modules')
            else:
                # Python 3.8-3.9
                module_eps = eps.get('enterpriseland.modules', [])
            
            for ep in module_eps:
                try:
                    # Load the module class
                    module_class = ep.load()
                    
                    # Find manifest in package
                    module_package = importlib.import_module(ep.module)
                    package_path = Path(module_package.__file__).parent
                    
                    manifest_path = None
                    for manifest_name in ['manifest.yaml', 'manifest.yml', 'module.json']:
                        candidate = package_path / manifest_name
                        if candidate.exists():
                            manifest_path = candidate
                            break
                    
                    if manifest_path:
                        manifest = ModuleManifest(manifest_path)
                        discovered.append((package_path, manifest))
                        logger.debug(f"Discovered package module: {manifest.module_id}")
                    
                except Exception as e:
                    logger.error(f"Failed to load module from entry point {ep.name}: {e}")
        
        except ImportError:
            # importlib.metadata not available (Python < 3.8)
            pass
        
        return discovered
    
    def load_module(self, module_path: Path, manifest: ModuleManifest) -> Optional[BaseModule]:
        """
        Load a specific module.
        
        Args:
            module_path: Path to the module directory
            manifest: The module's manifest
            
        Returns:
            Loaded module instance or None if loading failed
        """
        module_id = manifest.module_id
        
        if module_id in self._loaded_modules:
            logger.info(f"Module '{module_id}' is already loaded")
            return module_registry.get_module(module_id)
        
        try:
            # Look for module.py or __init__.py
            module_file = module_path / 'module.py'
            if not module_file.exists():
                module_file = module_path / '__init__.py'
            
            if not module_file.exists():
                logger.error(f"No module.py or __init__.py found in {module_path}")
                return None
            
            # Import the module
            spec = importlib.util.spec_from_file_location(
                f"modules.{module_id}",
                module_file
            )
            if not spec or not spec.loader:
                logger.error(f"Failed to create import spec for {module_file}")
                return None
            
            module_code = importlib.util.module_from_spec(spec)
            
            # Add module directory to sys.modules to allow relative imports
            sys.modules[spec.name] = module_code
            
            # Execute the module
            spec.loader.exec_module(module_code)
            
            # Find the module class
            module_class = None
            for attr_name in dir(module_code):
                attr = getattr(module_code, attr_name)
                if (
                    isinstance(attr, type) and
                    issubclass(attr, BaseModule) and
                    attr is not BaseModule
                ):
                    module_class = attr
                    break
            
            if not module_class:
                logger.error(f"No BaseModule subclass found in {module_file}")
                return None
            
            # Create module instance
            module_instance = module_class(manifest)
            
            # Initialize the module
            module_instance.initialize()
            
            # Register with the platform
            module_registry.register(module_instance)
            
            self._loaded_modules.add(module_id)
            logger.info(f"Successfully loaded module: {module_id} v{manifest.version}")
            
            return module_instance
            
        except Exception as e:
            logger.error(f"Failed to load module '{module_id}': {e}", exc_info=True)
            return None
    
    def load_all(self) -> List[BaseModule]:
        """
        Discover and load all available modules.
        
        Returns:
            List of successfully loaded modules
        """
        loaded_modules = []
        discovered = self.discover_modules()
        
        # Sort by dependencies (simple topological sort)
        sorted_modules = self._sort_by_dependencies(discovered)
        
        for module_path, manifest in sorted_modules:
            # Check if dependencies are satisfied
            deps_satisfied = True
            for dep_name in manifest.dependencies.keys():
                if not module_registry.get_module(dep_name):
                    logger.warning(
                        f"Module '{manifest.module_id}' depends on '{dep_name}' "
                        f"which is not loaded"
                    )
                    deps_satisfied = False
            
            if deps_satisfied:
                module = self.load_module(module_path, manifest)
                if module:
                    loaded_modules.append(module)
            else:
                logger.warning(
                    f"Skipping module '{manifest.module_id}' due to missing dependencies"
                )
        
        return loaded_modules
    
    def _sort_by_dependencies(
        self,
        modules: List[Tuple[Path, ModuleManifest]]
    ) -> List[Tuple[Path, ModuleManifest]]:
        """
        Sort modules by dependencies using topological sort.
        
        Args:
            modules: List of (path, manifest) tuples
            
        Returns:
            Sorted list with dependencies before dependents
        """
        # Create a map of module_id to (path, manifest)
        module_map = {m[1].module_id: m for m in modules}
        
        # Build dependency graph
        graph = {}
        in_degree = {}
        
        for _, manifest in modules:
            module_id = manifest.module_id
            graph[module_id] = []
            in_degree[module_id] = 0
        
        for _, manifest in modules:
            module_id = manifest.module_id
            for dep in manifest.dependencies.keys():
                if dep in graph:
                    graph[dep].append(module_id)
                    in_degree[module_id] += 1
        
        # Topological sort
        queue = [m for m in in_degree if in_degree[m] == 0]
        sorted_ids = []
        
        while queue:
            module_id = queue.pop(0)
            sorted_ids.append(module_id)
            
            for dependent in graph[module_id]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        # Check for circular dependencies
        if len(sorted_ids) != len(modules):
            logger.warning("Circular dependencies detected in modules")
            # Return original order for modules with circular deps
            return modules
        
        # Return sorted modules
        return [module_map[module_id] for module_id in sorted_ids]
    
    def reload_module(self, module_id: str) -> bool:
        """
        Reload a specific module.
        
        Args:
            module_id: ID of the module to reload
            
        Returns:
            True if reload was successful
        """
        # First unload the module
        module = module_registry.get_module(module_id)
        if not module:
            logger.error(f"Cannot reload unknown module: {module_id}")
            return False
        
        # Find the module in discovered modules
        discovered = self.discover_modules()
        module_info = None
        
        for path, manifest in discovered:
            if manifest.module_id == module_id:
                module_info = (path, manifest)
                break
        
        if not module_info:
            logger.error(f"Cannot find module '{module_id}' to reload")
            return False
        
        # Unregister the module
        module_registry.unregister(module_id)
        self._loaded_modules.discard(module_id)
        
        # Reload the module
        new_module = self.load_module(module_info[0], module_info[1])
        return new_module is not None


# Global module loader instance
module_loader = ModuleLoader()