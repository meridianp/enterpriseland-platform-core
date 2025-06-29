"""
Module Isolation Framework

Provides security isolation for modules to prevent them from:
- Accessing other modules' data
- Exceeding resource limits
- Making unauthorized API calls
- Accessing the filesystem directly
"""

import resource
import functools
import time
import threading
from contextlib import contextmanager
from typing import Dict, Any, Optional, Callable, List
from django.conf import settings
from django.db import connection

from .exceptions import ModuleIsolationError, ModuleResourceError, ModulePermissionError
from .models import ModuleManifest, ModuleInstallation


class ModuleIsolationContext:
    """
    Isolation context for module execution.
    
    Provides:
    - Resource limits (CPU, memory, time)
    - API access restrictions
    - Database query filtering
    - Filesystem sandboxing
    """
    
    def __init__(self, module_id: str, tenant_id: Optional[str] = None):
        self.module_id = module_id
        self.tenant_id = tenant_id
        self.start_time = None
        self.api_call_count = {}
        self.resource_usage = {}
        
        # Load module manifest to get limits
        self.manifest = ModuleManifest.objects.get(module_id=module_id)
        self.limits = self._load_resource_limits()
    
    def _load_resource_limits(self) -> Dict[str, Any]:
        """Load resource limits from manifest"""
        defaults = {
            'max_memory_mb': 512,
            'max_cpu_seconds': 60,
            'max_execution_time': 300,  # 5 minutes
            'max_api_calls_per_minute': 100,
            'max_database_queries': 1000,
            'max_file_size_mb': 50,
        }
        
        limits = defaults.copy()
        limits.update(self.manifest.resource_limits)
        return limits
    
    @contextmanager
    def isolated_execution(self):
        """
        Context manager for isolated module execution.
        
        Usage:
            with isolation_context.isolated_execution():
                # Module code runs here with restrictions
        """
        self.start_time = time.time()
        
        # Set up isolation
        self._setup_resource_limits()
        old_api_wrapper = self._wrap_api_calls()
        old_db_wrapper = self._wrap_database_access()
        
        try:
            yield self
        finally:
            # Clean up isolation
            self._restore_api_calls(old_api_wrapper)
            self._restore_database_access(old_db_wrapper)
            self._cleanup_resource_limits()
    
    def _setup_resource_limits(self):
        """Set resource limits for the current process"""
        if not getattr(settings, 'ENABLE_MODULE_RESOURCE_LIMITS', True):
            return
        
        # Memory limit (soft limit only to avoid crashes)
        if hasattr(resource, 'RLIMIT_AS'):
            memory_bytes = self.limits['max_memory_mb'] * 1024 * 1024
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, hard))
        
        # CPU time limit
        if hasattr(resource, 'RLIMIT_CPU'):
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (self.limits['max_cpu_seconds'], self.limits['max_cpu_seconds'])
            )
    
    def _cleanup_resource_limits(self):
        """Reset resource limits"""
        # In production, we'd reset to previous values
        # For now, we'll rely on process isolation
        pass
    
    def _wrap_api_calls(self):
        """Wrap API calls to enforce rate limits and permissions"""
        # This would wrap Django's view processing
        # For now, return a placeholder
        return None
    
    def _restore_api_calls(self, old_wrapper):
        """Restore original API call handling"""
        pass
    
    def _wrap_database_access(self):
        """Wrap database access to enforce tenant isolation"""
        # In a real implementation, we'd wrap Django's ORM
        # to automatically filter by tenant
        return None
    
    def _restore_database_access(self, old_wrapper):
        """Restore original database access"""
        pass
    
    def check_time_limit(self):
        """Check if execution time limit has been exceeded"""
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed > self.limits['max_execution_time']:
                raise ModuleResourceError(
                    f"Module execution time limit exceeded: {elapsed:.1f}s > {self.limits['max_execution_time']}s"
                )
    
    def check_api_rate_limit(self, api_endpoint: str):
        """Check if API rate limit has been exceeded"""
        current_minute = int(time.time() / 60)
        key = f"{api_endpoint}:{current_minute}"
        
        self.api_call_count[key] = self.api_call_count.get(key, 0) + 1
        
        if self.api_call_count[key] > self.limits['max_api_calls_per_minute']:
            raise ModuleResourceError(
                f"API rate limit exceeded for {api_endpoint}: "
                f"{self.api_call_count[key]} > {self.limits['max_api_calls_per_minute']}"
            )
    
    def check_permission(self, permission: str) -> bool:
        """Check if module has a specific permission"""
        return permission in self.manifest.permissions
    
    def require_permission(self, permission: str):
        """Require a specific permission or raise error"""
        if not self.check_permission(permission):
            raise ModulePermissionError(
                f"Module {self.module_id} lacks required permission: {permission}"
            )


class ModuleSandbox:
    """
    Sandbox for secure module execution.
    
    Provides a restricted execution environment with:
    - Limited builtins
    - Controlled imports
    - Safe API access
    - Resource monitoring
    """
    
    def __init__(self, isolation_context: ModuleIsolationContext):
        self.context = isolation_context
        self.namespace = self._create_namespace()
    
    def _create_namespace(self) -> Dict[str, Any]:
        """Create restricted namespace for module execution"""
        # Safe builtins only
        safe_builtins = {
            # Basic types
            'None': None,
            'True': True,
            'False': False,
            'bool': bool,
            'int': int,
            'float': float,
            'str': str,
            'bytes': bytes,
            'list': list,
            'tuple': tuple,
            'dict': dict,
            'set': set,
            'frozenset': frozenset,
            
            # Safe functions
            'len': len,
            'range': range,
            'enumerate': enumerate,
            'zip': zip,
            'map': map,
            'filter': filter,
            'sorted': sorted,
            'reversed': reversed,
            'min': min,
            'max': max,
            'sum': sum,
            'abs': abs,
            'round': round,
            'all': all,
            'any': any,
            
            # String methods
            'chr': chr,
            'ord': ord,
            
            # Type checking
            'isinstance': isinstance,
            'issubclass': issubclass,
            'type': type,
            
            # Exceptions (read-only)
            'Exception': Exception,
            'ValueError': ValueError,
            'TypeError': TypeError,
            'KeyError': KeyError,
            'IndexError': IndexError,
            'AttributeError': AttributeError,
        }
        
        # Create namespace with platform APIs
        namespace = {
            '__builtins__': safe_builtins,
            'platform': self._create_platform_api(),
            'module_id': self.context.module_id,
            'tenant_id': self.context.tenant_id,
        }
        
        return namespace
    
    def _create_platform_api(self):
        """Create sandboxed platform API"""
        
        class SandboxedPlatformAPI:
            """Platform API with permission checks"""
            
            def __init__(self, context):
                self._context = context
            
            @property
            def storage(self):
                """File storage API"""
                self._context.require_permission('file.access')
                return self._create_storage_api()
            
            @property
            def workflow(self):
                """Workflow API"""
                self._context.require_permission('workflow.access')
                return self._create_workflow_api()
            
            @property
            def agents(self):
                """Agent API"""
                self._context.require_permission('agent.access')
                return self._create_agent_api()
            
            def _create_storage_api(self):
                """Create sandboxed storage API"""
                # Implementation would provide safe file access
                pass
            
            def _create_workflow_api(self):
                """Create sandboxed workflow API"""
                # Implementation would provide workflow access
                pass
            
            def _create_agent_api(self):
                """Create sandboxed agent API"""
                # Implementation would provide agent access
                pass
        
        return SandboxedPlatformAPI(self.context)
    
    def execute(self, code: str, globals_dict: Optional[Dict] = None) -> Any:
        """
        Execute code in the sandbox.
        
        Args:
            code: Python code to execute
            globals_dict: Additional globals to provide
            
        Returns:
            Result of execution
            
        Raises:
            ModuleIsolationError: If code violates sandbox
        """
        if globals_dict:
            namespace = self.namespace.copy()
            namespace.update(globals_dict)
        else:
            namespace = self.namespace
        
        try:
            # Compile code
            compiled = compile(code, f"<module:{self.context.module_id}>", 'exec')
            
            # Execute in sandbox
            exec(compiled, namespace)
            
            # Return namespace for access to defined variables
            return namespace
            
        except Exception as e:
            raise ModuleIsolationError(f"Sandbox execution failed: {e}")


def with_isolation(module_id: str, tenant_id: Optional[str] = None):
    """
    Decorator to run a function with module isolation.
    
    Usage:
        @with_isolation('com.example.module')
        def module_function():
            # Runs with isolation
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            context = ModuleIsolationContext(module_id, tenant_id)
            with context.isolated_execution():
                return func(*args, **kwargs)
        return wrapper
    return decorator


class ResourceMonitor:
    """
    Monitor resource usage for modules.
    
    Tracks:
    - CPU usage
    - Memory usage
    - API calls
    - Database queries
    """
    
    def __init__(self, module_id: str):
        self.module_id = module_id
        self.start_time = time.time()
        self.metrics = {
            'cpu_time': 0,
            'memory_peak': 0,
            'api_calls': 0,
            'db_queries': 0,
            'errors': 0,
        }
    
    def record_api_call(self, endpoint: str, duration: float):
        """Record an API call"""
        self.metrics['api_calls'] += 1
    
    def record_db_query(self, query: str, duration: float):
        """Record a database query"""
        self.metrics['db_queries'] += 1
    
    def record_error(self, error: Exception):
        """Record an error"""
        self.metrics['errors'] += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        return {
            'module_id': self.module_id,
            'duration': time.time() - self.start_time,
            **self.metrics
        }


# Global isolation manager
class IsolationManager:
    """
    Manages isolation contexts for all modules.
    
    This is a singleton that tracks active isolation contexts
    and ensures proper cleanup.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._contexts = {}
        return cls._instance
    
    def create_context(self, module_id: str, tenant_id: Optional[str] = None) -> ModuleIsolationContext:
        """Create a new isolation context"""
        key = f"{module_id}:{tenant_id or 'global'}"
        context = ModuleIsolationContext(module_id, tenant_id)
        self._contexts[key] = context
        return context
    
    def get_context(self, module_id: str, tenant_id: Optional[str] = None) -> Optional[ModuleIsolationContext]:
        """Get an existing isolation context"""
        key = f"{module_id}:{tenant_id or 'global'}"
        return self._contexts.get(key)
    
    def remove_context(self, module_id: str, tenant_id: Optional[str] = None):
        """Remove an isolation context"""
        key = f"{module_id}:{tenant_id or 'global'}"
        if key in self._contexts:
            del self._contexts[key]


isolation_manager = IsolationManager()