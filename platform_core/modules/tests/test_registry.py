"""
Tests for module registry service
"""

from django.test import TestCase
from django.core.cache import cache
from unittest.mock import Mock, patch, MagicMock

from platform_core.accounts.models import Tenant, User
from platform_core.modules.models import ModuleManifest, ModuleInstallation
from platform_core.modules.registry import ModuleRegistry
from platform_core.modules.base import BaseModule
from platform_core.modules.exceptions import (
    ModuleNotFoundError, ModuleAlreadyInstalled, CircularDependencyError,
    DependencyNotSatisfied, ModuleError
)


class MockModule(BaseModule):
    """Mock module for testing"""
    
    @property
    def name(self):
        return "Mock Module"
    
    @property
    def description(self):
        return "A mock module for testing"
    
    def initialize(self):
        """Initialize the module"""
        pass
    
    def shutdown(self):
        """Shutdown the module"""
        pass


class ModuleRegistryTestCase(TestCase):
    """Test ModuleRegistry service"""
    
    def setUp(self):
        self.registry = ModuleRegistry()
        
        # Create test tenant
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            schema_name='test_tenant'
        )
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            tenant=self.tenant
        )
        
        # Create test modules
        self.base_module = ModuleManifest.objects.create(
            module_id='com.example.base',
            name='Base Module',
            version='1.0.0',
            platform_version='>=2.0.0'
        )
        
        self.dependent_module = ModuleManifest.objects.create(
            module_id='com.example.dependent',
            name='Dependent Module',
            version='1.0.0',
            platform_version='>=2.0.0',
            dependencies=['com.example.base>=1.0.0']
        )
        
        # Clear cache between tests
        cache.clear()
    
    def test_register_module(self):
        """Test registering a module manifest"""
        manifest_data = {
            'module_id': 'com.example.new',
            'name': 'New Module',
            'description': 'A new module',
            'version': '1.0.0',
            'platform_version': '>=2.0.0',
            'dependencies': [],
            'permissions': ['file.read'],
            'pricing_model': 'free'
        }
        
        manifest = self.registry.register_module(manifest_data)
        
        self.assertEqual(manifest.module_id, 'com.example.new')
        self.assertEqual(manifest.name, 'New Module')
        self.assertTrue(manifest.is_active)
    
    def test_register_duplicate_module(self):
        """Test registering a duplicate module updates existing"""
        # First registration
        manifest_data = {
            'module_id': 'com.example.test',
            'name': 'Test Module',
            'version': '1.0.0'
        }
        manifest1 = self.registry.register_module(manifest_data)
        
        # Update registration
        manifest_data['version'] = '1.1.0'
        manifest2 = self.registry.register_module(manifest_data)
        
        # Should be the same object, just updated
        self.assertEqual(manifest1.id, manifest2.id)
        self.assertEqual(manifest2.version, '1.1.0')
    
    @patch('platform_core.modules.registry.ModuleLoader')
    def test_install_module(self, mock_loader_class):
        """Test installing a module for a tenant"""
        # Mock the loader
        mock_loader = Mock()
        mock_loader.load_module_class.return_value = MockModule
        mock_loader_class.return_value = mock_loader
        
        # Install the base module
        installation = self.registry.install_module(
            self.base_module.module_id,
            self.tenant,
            self.user
        )
        
        self.assertEqual(installation.module, self.base_module)
        self.assertEqual(installation.tenant, self.tenant)
        self.assertEqual(installation.status, 'active')
        self.assertEqual(installation.installed_by, self.user)
    
    def test_install_module_already_installed(self):
        """Test installing a module that's already installed"""
        # First installation
        ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.base_module,
            status='active'
        )
        
        # Try to install again
        with self.assertRaises(ModuleAlreadyInstalled):
            self.registry.install_module(
                self.base_module.module_id,
                self.tenant,
                self.user
            )
    
    def test_install_module_not_found(self):
        """Test installing a non-existent module"""
        with self.assertRaises(ModuleNotFoundError):
            self.registry.install_module(
                'com.example.nonexistent',
                self.tenant,
                self.user
            )
    
    @patch('platform_core.modules.registry.ModuleLoader')
    def test_install_module_with_dependencies(self, mock_loader_class):
        """Test installing a module with dependencies"""
        # Mock the loader
        mock_loader = Mock()
        mock_loader.load_module_class.return_value = MockModule
        mock_loader_class.return_value = mock_loader
        
        # Install base module first
        self.registry.install_module(
            self.base_module.module_id,
            self.tenant,
            self.user
        )
        
        # Install dependent module
        installation = self.registry.install_module(
            self.dependent_module.module_id,
            self.tenant,
            self.user
        )
        
        # Check that dependency is recorded
        dependencies = installation.dependencies.all()
        self.assertEqual(dependencies.count(), 1)
        self.assertEqual(dependencies[0].required_module, self.base_module)
        self.assertTrue(dependencies[0].is_satisfied)
    
    def test_install_module_missing_dependency(self):
        """Test installing a module with missing dependencies"""
        with self.assertRaises(DependencyNotSatisfied):
            self.registry.install_module(
                self.dependent_module.module_id,
                self.tenant,
                self.user
            )
    
    def test_uninstall_module(self):
        """Test uninstalling a module"""
        # Install module
        installation = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.base_module,
            status='active'
        )
        
        # Uninstall
        self.registry.uninstall_module(
            self.base_module.module_id,
            self.tenant
        )
        
        # Check it's deleted
        self.assertFalse(
            ModuleInstallation.objects.filter(id=installation.id).exists()
        )
    
    def test_uninstall_module_with_dependents(self):
        """Test uninstalling a module that has dependents"""
        # Install both modules
        base_install = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.base_module,
            status='active'
        )
        
        dependent_install = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.dependent_module,
            status='active'
        )
        
        # Create dependency
        dependent_install.dependencies.create(
            required_module=self.base_module,
            is_satisfied=True
        )
        
        # Try to uninstall base module - should fail
        with self.assertRaises(ModuleError):
            self.registry.uninstall_module(
                self.base_module.module_id,
                self.tenant
            )
    
    def test_enable_disable_module(self):
        """Test enabling and disabling a module"""
        # Install module
        installation = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.base_module,
            status='active'
        )
        
        # Disable
        self.registry.disable_module(
            self.base_module.module_id,
            self.tenant
        )
        
        installation.refresh_from_db()
        self.assertEqual(installation.status, 'disabled')
        
        # Enable
        self.registry.enable_module(
            self.base_module.module_id,
            self.tenant
        )
        
        installation.refresh_from_db()
        self.assertEqual(installation.status, 'active')
    
    def test_get_module_instance(self):
        """Test getting a module instance"""
        # Create installation
        installation = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.base_module,
            status='active'
        )
        
        # Mock loader
        with patch('platform_core.modules.registry.ModuleLoader') as mock_loader_class:
            mock_loader = Mock()
            mock_loader.load_module_class.return_value = MockModule
            mock_loader_class.return_value = mock_loader
            
            # Get instance
            instance = self.registry.get_module_instance(
                self.base_module.module_id,
                self.tenant
            )
            
            self.assertIsInstance(instance, MockModule)
            self.assertEqual(instance.manifest, self.base_module)
            self.assertEqual(instance.installation, installation)
    
    def test_list_available_modules(self):
        """Test listing available modules"""
        # Create more modules
        ModuleManifest.objects.create(
            module_id='com.example.extra',
            name='Extra Module',
            version='1.0.0',
            is_active=True
        )
        
        ModuleManifest.objects.create(
            module_id='com.example.inactive',
            name='Inactive Module',
            version='1.0.0',
            is_active=False
        )
        
        modules = self.registry.list_available_modules()
        
        # Should include all active modules
        self.assertEqual(len(modules), 3)  # base, dependent, extra
        module_ids = [m.module_id for m in modules]
        self.assertIn('com.example.base', module_ids)
        self.assertIn('com.example.dependent', module_ids)
        self.assertIn('com.example.extra', module_ids)
        self.assertNotIn('com.example.inactive', module_ids)
    
    def test_list_installed_modules(self):
        """Test listing installed modules for a tenant"""
        # Install some modules
        ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.base_module,
            status='active'
        )
        
        ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.dependent_module,
            status='disabled'
        )
        
        # Create another tenant with different modules
        other_tenant = Tenant.objects.create(
            name='Other Tenant',
            schema_name='other_tenant'
        )
        
        ModuleInstallation.objects.create(
            tenant=other_tenant,
            module=self.base_module,
            status='active'
        )
        
        # List for our tenant
        installed = self.registry.list_installed_modules(self.tenant)
        
        self.assertEqual(len(installed), 2)
        module_ids = [i.module.module_id for i in installed]
        self.assertIn('com.example.base', module_ids)
        self.assertIn('com.example.dependent', module_ids)
    
    def test_resolve_dependencies(self):
        """Test dependency resolution"""
        # Create a more complex dependency graph
        module_a = ModuleManifest.objects.create(
            module_id='com.example.a',
            name='Module A',
            version='1.0.0'
        )
        
        module_b = ModuleManifest.objects.create(
            module_id='com.example.b',
            name='Module B',
            version='1.0.0',
            dependencies=['com.example.a>=1.0.0']
        )
        
        module_c = ModuleManifest.objects.create(
            module_id='com.example.c',
            name='Module C',
            version='1.0.0',
            dependencies=['com.example.a>=1.0.0', 'com.example.b>=1.0.0']
        )
        
        # Resolve dependencies
        module_ids = ['com.example.c', 'com.example.b', 'com.example.a']
        ordered = self.registry.resolve_dependencies(module_ids)
        
        # Should be in correct order: a, b, c
        self.assertEqual(ordered, ['com.example.a', 'com.example.b', 'com.example.c'])
    
    def test_circular_dependency_detection(self):
        """Test circular dependency detection"""
        # Create circular dependency
        module_a = ModuleManifest.objects.create(
            module_id='com.example.circular.a',
            name='Circular A',
            version='1.0.0',
            dependencies=['com.example.circular.b>=1.0.0']
        )
        
        module_b = ModuleManifest.objects.create(
            module_id='com.example.circular.b',
            name='Circular B',
            version='1.0.0',
            dependencies=['com.example.circular.a>=1.0.0']
        )
        
        # Try to resolve
        with self.assertRaises(CircularDependencyError):
            self.registry.resolve_dependencies([
                'com.example.circular.a',
                'com.example.circular.b'
            ])
    
    def test_check_dependencies(self):
        """Test dependency checking"""
        # Install base module
        ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.base_module,
            status='active'
        )
        
        # Check dependencies for dependent module - should pass
        satisfied, missing = self.registry.check_dependencies(
            self.dependent_module.module_id,
            self.tenant
        )
        
        self.assertTrue(satisfied)
        self.assertEqual(len(missing), 0)
        
        # Check for a module with missing dependencies
        complex_module = ModuleManifest.objects.create(
            module_id='com.example.complex',
            name='Complex Module',
            version='1.0.0',
            dependencies=[
                'com.example.base>=1.0.0',
                'com.example.missing>=1.0.0'
            ]
        )
        
        satisfied, missing = self.registry.check_dependencies(
            complex_module.module_id,
            self.tenant
        )
        
        self.assertFalse(satisfied)
        self.assertIn('com.example.missing>=1.0.0', missing)
    
    def test_module_instance_caching(self):
        """Test that module instances are cached"""
        # Create installation
        ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.base_module,
            status='active'
        )
        
        with patch('platform_core.modules.registry.ModuleLoader') as mock_loader_class:
            mock_loader = Mock()
            mock_loader.load_module_class.return_value = MockModule
            mock_loader_class.return_value = mock_loader
            
            # Get instance twice
            instance1 = self.registry.get_module_instance(
                self.base_module.module_id,
                self.tenant
            )
            instance2 = self.registry.get_module_instance(
                self.base_module.module_id,
                self.tenant
            )
            
            # Should be the same instance (cached)
            self.assertIs(instance1, instance2)
            
            # Loader should only be called once
            mock_loader.load_module_class.assert_called_once()