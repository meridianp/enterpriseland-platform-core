"""
EnterpriseLand Platform Module System.

This package provides the infrastructure for loading and managing
business modules that extend the platform's functionality.

Key components:
- BaseModule: Abstract base class for all modules
- ModuleRegistry: Central registry of loaded modules
- ModuleLoader: Discovers and loads modules
- ModuleManifest: Represents module metadata

Usage:
    from platform_core.modules import module_loader, module_registry
    
    # Load all available modules
    modules = module_loader.load_all()
    
    # Get a specific module
    investment_module = module_registry.get_module('enterpriseland-investment')
    
    # Get a service from a module
    assessment_service = module_registry.get_service('AssessmentService')
"""

from .base import BaseModule, ModuleManifest, ModuleConfig
from .registry import module_registry, ModuleRegistry
from .loader import module_loader, ModuleLoader

__all__ = [
    'BaseModule',
    'ModuleManifest',
    'ModuleConfig',
    'module_registry',
    'ModuleRegistry',
    'module_loader',
    'ModuleLoader',
]