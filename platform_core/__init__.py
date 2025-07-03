"""
Platform Core Package

Provides the core platform functionality including:
- Module system for dynamic extensions
- Workflow engine for business process automation
- Shared utilities and base classes
"""

__version__ = '1.0.0'

# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
from .celery import app as celery_app

# Import key components for easier access
from .modules.registry import module_registry
from .workflows.engine import workflow_engine

__all__ = [
    'celery_app',
    'module_registry',
    'workflow_engine',
]