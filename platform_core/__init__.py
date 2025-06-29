"""
Platform Core Package

Provides the core platform functionality including:
- Module system for dynamic extensions
- Workflow engine for business process automation
- Shared utilities and base classes
"""

__version__ = '1.0.0'

# Import key components for easier access
from .modules.registry import module_registry
from .workflows.engine import workflow_engine

__all__ = [
    'module_registry',
    'workflow_engine',
]