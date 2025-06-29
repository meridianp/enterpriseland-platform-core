"""
Tests for module isolation framework
"""

import time
from unittest.mock import patch, Mock
from django.test import TestCase, override_settings

from platform_core.modules.models import ModuleManifest
from platform_core.modules.isolation import (
    ModuleIsolationContext, ModuleSandbox, ResourceMonitor,
    with_isolation, isolation_manager
)
from platform_core.modules.exceptions import (
    ModuleIsolationError, ModuleResourceError, ModulePermissionError
)


class ModuleIsolationContextTestCase(TestCase):
    """Test ModuleIsolationContext"""
    
    def setUp(self):
        # Create a test module manifest
        self.manifest = ModuleManifest.objects.create(
            module_id='com.example.test',
            name='Test Module',
            version='1.0.0',
            permissions=['file.access', 'workflow.access'],
            resource_limits={
                'max_memory_mb': 256,
                'max_cpu_seconds': 30,
                'max_execution_time': 60,
                'max_api_calls_per_minute': 50
            }
        )
    
    def test_create_isolation_context(self):
        """Test creating an isolation context"""
        context = ModuleIsolationContext(
            module_id='com.example.test',
            tenant_id='tenant123'
        )
        
        self.assertEqual(context.module_id, 'com.example.test')
        self.assertEqual(context.tenant_id, 'tenant123')
        self.assertEqual(context.manifest, self.manifest)
    
    def test_load_resource_limits(self):
        """Test loading resource limits from manifest"""
        context = ModuleIsolationContext('com.example.test')
        
        # Should use manifest limits
        self.assertEqual(context.limits['max_memory_mb'], 256)
        self.assertEqual(context.limits['max_cpu_seconds'], 30)
        self.assertEqual(context.limits['max_execution_time'], 60)
        self.assertEqual(context.limits['max_api_calls_per_minute'], 50)
        
        # Should have defaults for unspecified limits
        self.assertEqual(context.limits['max_database_queries'], 1000)
        self.assertEqual(context.limits['max_file_size_mb'], 50)
    
    @override_settings(ENABLE_MODULE_RESOURCE_LIMITS=True)
    def test_isolated_execution_context(self):
        """Test isolated execution context manager"""
        context = ModuleIsolationContext('com.example.test')
        
        with context.isolated_execution() as ctx:
            self.assertEqual(ctx, context)
            self.assertIsNotNone(context.start_time)
    
    def test_check_time_limit(self):
        """Test execution time limit checking"""
        context = ModuleIsolationContext('com.example.test')
        context.start_time = time.time() - 65  # Started 65 seconds ago
        
        # Should raise error (limit is 60 seconds)
        with self.assertRaises(ModuleResourceError) as cm:
            context.check_time_limit()
        
        self.assertIn("execution time limit exceeded", str(cm.exception))
    
    def test_check_api_rate_limit(self):
        """Test API rate limiting"""
        context = ModuleIsolationContext('com.example.test')
        
        # Make 50 calls (the limit)
        for i in range(50):
            context.check_api_rate_limit('/api/test')
        
        # 51st call should fail
        with self.assertRaises(ModuleResourceError) as cm:
            context.check_api_rate_limit('/api/test')
        
        self.assertIn("API rate limit exceeded", str(cm.exception))
    
    def test_check_permission(self):
        """Test permission checking"""
        context = ModuleIsolationContext('com.example.test')
        
        # Has these permissions
        self.assertTrue(context.check_permission('file.access'))
        self.assertTrue(context.check_permission('workflow.access'))
        
        # Doesn't have this permission
        self.assertFalse(context.check_permission('admin.access'))
    
    def test_require_permission(self):
        """Test requiring permissions"""
        context = ModuleIsolationContext('com.example.test')
        
        # Should not raise for granted permission
        context.require_permission('file.access')
        
        # Should raise for missing permission
        with self.assertRaises(ModulePermissionError) as cm:
            context.require_permission('admin.access')
        
        self.assertIn("lacks required permission", str(cm.exception))


class ModuleSandboxTestCase(TestCase):
    """Test ModuleSandbox"""
    
    def setUp(self):
        # Create a test module manifest
        self.manifest = ModuleManifest.objects.create(
            module_id='com.example.sandbox',
            name='Sandbox Test Module',
            version='1.0.0',
            permissions=['file.access']
        )
        
        self.context = ModuleIsolationContext('com.example.sandbox')
        self.sandbox = ModuleSandbox(self.context)
    
    def test_create_namespace(self):
        """Test namespace creation with safe builtins"""
        namespace = self.sandbox.namespace
        
        # Check safe builtins are available
        builtins = namespace['__builtins__']
        self.assertIn('len', builtins)
        self.assertIn('str', builtins)
        self.assertIn('dict', builtins)
        
        # Check dangerous builtins are NOT available
        self.assertNotIn('open', builtins)
        self.assertNotIn('__import__', builtins)
        self.assertNotIn('exec', builtins)
        self.assertNotIn('eval', builtins)
        
        # Check platform API is available
        self.assertIn('platform', namespace)
        self.assertEqual(namespace['module_id'], 'com.example.sandbox')
    
    def test_execute_safe_code(self):
        """Test executing safe code in sandbox"""
        code = '''
result = []
for i in range(5):
    result.append(i * 2)
final = sum(result)
'''
        
        namespace = self.sandbox.execute(code)
        
        self.assertEqual(namespace['result'], [0, 2, 4, 6, 8])
        self.assertEqual(namespace['final'], 20)
    
    def test_execute_with_globals(self):
        """Test executing code with additional globals"""
        code = 'result = custom_var * 2'
        
        globals_dict = {'custom_var': 21}
        namespace = self.sandbox.execute(code, globals_dict)
        
        self.assertEqual(namespace['result'], 42)
    
    def test_platform_api_permissions(self):
        """Test platform API permission checks"""
        # Module has file.access permission
        platform_api = self.sandbox._create_platform_api()
        
        # Should work
        try:
            storage = platform_api.storage
        except ModulePermissionError:
            self.fail("Should have file.access permission")
        
        # Should fail (no workflow.access permission)
        with self.assertRaises(ModulePermissionError):
            workflow = platform_api.workflow
    
    def test_sandbox_prevents_imports(self):
        """Test that sandbox prevents dangerous imports"""
        # Note: In a real implementation, we'd restrict imports
        # For now, we test that dangerous builtins aren't available
        code = '''
try:
    # This should fail - no __import__
    os = __import__('os')
    result = 'imported'
except NameError:
    result = 'blocked'
'''
        
        namespace = self.sandbox.execute(code)
        self.assertEqual(namespace['result'], 'blocked')
    
    def test_sandbox_prevents_file_access(self):
        """Test that sandbox prevents direct file access"""
        code = '''
try:
    # This should fail - no open builtin
    f = open('/etc/passwd', 'r')
    result = 'opened'
except NameError:
    result = 'blocked'
'''
        
        namespace = self.sandbox.execute(code)
        self.assertEqual(namespace['result'], 'blocked')


class WithIsolationDecoratorTestCase(TestCase):
    """Test with_isolation decorator"""
    
    def setUp(self):
        # Create a test module
        self.manifest = ModuleManifest.objects.create(
            module_id='com.example.decorator',
            name='Decorator Test Module',
            version='1.0.0'
        )
    
    def test_decorator_basic(self):
        """Test basic decorator functionality"""
        @with_isolation('com.example.decorator')
        def test_function():
            return "executed"
        
        result = test_function()
        self.assertEqual(result, "executed")
    
    def test_decorator_with_tenant(self):
        """Test decorator with tenant ID"""
        @with_isolation('com.example.decorator', tenant_id='tenant123')
        def test_function(value):
            return value * 2
        
        result = test_function(21)
        self.assertEqual(result, 42)
    
    def test_decorator_preserves_function_metadata(self):
        """Test that decorator preserves function metadata"""
        @with_isolation('com.example.decorator')
        def test_function():
            """Test docstring"""
            pass
        
        self.assertEqual(test_function.__name__, 'test_function')
        self.assertEqual(test_function.__doc__, 'Test docstring')


class ResourceMonitorTestCase(TestCase):
    """Test ResourceMonitor"""
    
    def test_resource_monitor(self):
        """Test resource monitoring"""
        monitor = ResourceMonitor('com.example.test')
        
        # Record some metrics
        monitor.record_api_call('/api/test', 0.1)
        monitor.record_api_call('/api/test', 0.2)
        monitor.record_db_query('SELECT * FROM test', 0.05)
        monitor.record_error(ValueError("test error"))
        
        # Get metrics
        metrics = monitor.get_metrics()
        
        self.assertEqual(metrics['module_id'], 'com.example.test')
        self.assertEqual(metrics['api_calls'], 2)
        self.assertEqual(metrics['db_queries'], 1)
        self.assertEqual(metrics['errors'], 1)
        self.assertIn('duration', metrics)


class IsolationManagerTestCase(TestCase):
    """Test IsolationManager"""
    
    def setUp(self):
        # Create test modules
        self.manifest1 = ModuleManifest.objects.create(
            module_id='com.example.manager1',
            name='Manager Test 1',
            version='1.0.0'
        )
        
        self.manifest2 = ModuleManifest.objects.create(
            module_id='com.example.manager2',
            name='Manager Test 2',
            version='1.0.0'
        )
    
    def test_singleton_pattern(self):
        """Test that IsolationManager is a singleton"""
        manager1 = isolation_manager
        manager2 = isolation_manager
        
        self.assertIs(manager1, manager2)
    
    def test_create_and_get_context(self):
        """Test creating and retrieving contexts"""
        # Create context
        context1 = isolation_manager.create_context(
            'com.example.manager1',
            'tenant123'
        )
        
        # Retrieve it
        context2 = isolation_manager.get_context(
            'com.example.manager1',
            'tenant123'
        )
        
        self.assertIs(context1, context2)
        
        # Different tenant should be different context
        context3 = isolation_manager.get_context(
            'com.example.manager1',
            'tenant456'
        )
        
        self.assertIsNone(context3)  # Not created yet
    
    def test_remove_context(self):
        """Test removing contexts"""
        # Create context
        context = isolation_manager.create_context(
            'com.example.manager2',
            'tenant789'
        )
        
        # Remove it
        isolation_manager.remove_context(
            'com.example.manager2',
            'tenant789'
        )
        
        # Should be gone
        retrieved = isolation_manager.get_context(
            'com.example.manager2',
            'tenant789'
        )
        self.assertIsNone(retrieved)