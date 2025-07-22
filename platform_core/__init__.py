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
try:
    from .celery import app as celery_app
except ImportError:
    # Celery app may not be available during Django setup
    celery_app = None

# Lazy import functions to avoid Django app registry issues
def get_module_registry():
    """Lazy import module registry to avoid early Django model loading"""
    from .modules.registry import module_registry
    return module_registry

def get_workflow_engine():
    """Lazy import workflow engine to avoid early Django model loading"""
    from .workflows.engine import workflow_engine
    return workflow_engine

# Don't import anything at module level that requires Django apps to be ready
__all__ = [
    'celery_app',
    'get_module_registry', 
    'get_workflow_engine',
]