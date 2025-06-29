"""
Tests for module system models
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone

from platform_core.accounts.models import Tenant, User
from platform_core.modules.models import (
    ModuleManifest, ModuleInstallation, ModuleDependency, ModuleEvent
)


class ModuleManifestTestCase(TestCase):
    """Test ModuleManifest model"""
    
    def setUp(self):
        self.manifest_data = {
            'module_id': 'com.example.test',
            'name': 'Test Module',
            'description': 'A test module',
            'version': '1.0.0',
            'platform_version': '>=2.0.0',
            'dependencies': ['com.example.base'],
            'permissions': ['file.read', 'workflow.create'],
            'entities': ['TestEntity'],
            'workflows': ['TestWorkflow'],
            'pricing_model': 'free',
        }
    
    def test_create_module_manifest(self):
        """Test creating a module manifest"""
        manifest = ModuleManifest.objects.create(**self.manifest_data)
        
        self.assertEqual(manifest.module_id, 'com.example.test')
        self.assertEqual(manifest.name, 'Test Module')
        self.assertEqual(manifest.version, '1.0.0')
        self.assertTrue(manifest.is_active)
        self.assertFalse(manifest.is_certified)
    
    def test_module_id_validation(self):
        """Test module ID format validation"""
        # Invalid format (no dots)
        invalid_data = self.manifest_data.copy()
        invalid_data['module_id'] = 'invalidmoduleid'
        
        manifest = ModuleManifest(**invalid_data)
        with self.assertRaises(ValidationError) as cm:
            manifest.clean()
        
        self.assertIn('module_id', cm.exception.error_dict)
    
    def test_version_validation(self):
        """Test version format validation"""
        # Invalid version format
        invalid_data = self.manifest_data.copy()
        invalid_data['version'] = 'v1.0'
        
        manifest = ModuleManifest(**invalid_data)
        with self.assertRaises(ValidationError) as cm:
            manifest.clean()
        
        self.assertIn('version', cm.exception.error_dict)
    
    def test_resource_limits(self):
        """Test resource limit methods"""
        manifest = ModuleManifest.objects.create(**self.manifest_data)
        
        # Test default limits
        self.assertEqual(manifest.get_resource_limit('max_memory'), '512MB')
        self.assertEqual(manifest.get_resource_limit('max_cpu'), '1.0')
        self.assertEqual(manifest.get_resource_limit('max_api_calls_per_minute'), 100)
        
        # Test custom limits
        manifest.resource_limits = {'max_memory': '1GB', 'custom_limit': 50}
        manifest.save()
        
        self.assertEqual(manifest.get_resource_limit('max_memory'), '1GB')
        self.assertEqual(manifest.get_resource_limit('custom_limit'), 50)
    
    def test_str_representation(self):
        """Test string representation"""
        manifest = ModuleManifest.objects.create(**self.manifest_data)
        expected = f"Test Module (com.example.test@1.0.0)"
        self.assertEqual(str(manifest), expected)


class ModuleInstallationTestCase(TestCase):
    """Test ModuleInstallation model"""
    
    def setUp(self):
        # Create tenant
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            schema_name='test_tenant'
        )
        
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            tenant=self.tenant
        )
        
        # Create module manifest
        self.manifest = ModuleManifest.objects.create(
            module_id='com.example.test',
            name='Test Module',
            version='1.0.0',
            platform_version='>=2.0.0'
        )
    
    def test_create_installation(self):
        """Test creating a module installation"""
        installation = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.manifest,
            status='active',
            installed_by=self.user,
            installed_at=timezone.now()
        )
        
        self.assertEqual(installation.tenant, self.tenant)
        self.assertEqual(installation.module, self.manifest)
        self.assertEqual(installation.status, 'active')
        self.assertTrue(installation.is_active())
    
    def test_unique_constraint(self):
        """Test that a module can only be installed once per tenant"""
        ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.manifest,
            status='active'
        )
        
        # Try to create duplicate
        with self.assertRaises(Exception):  # IntegrityError
            ModuleInstallation.objects.create(
                tenant=self.tenant,
                module=self.manifest,
                status='active'
            )
    
    def test_status_methods(self):
        """Test status checking methods"""
        installation = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.manifest,
            status='active'
        )
        
        self.assertTrue(installation.is_active())
        self.assertTrue(installation.can_be_disabled())
        self.assertTrue(installation.can_be_enabled())
        
        installation.status = 'disabled'
        installation.save()
        
        self.assertFalse(installation.is_active())
        self.assertFalse(installation.can_be_disabled())
        self.assertTrue(installation.can_be_enabled())
        
        installation.status = 'failed'
        installation.save()
        
        self.assertFalse(installation.can_be_enabled())
        self.assertFalse(installation.can_be_disabled())


class ModuleDependencyTestCase(TestCase):
    """Test ModuleDependency model"""
    
    def setUp(self):
        # Create tenant
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            schema_name='test_tenant'
        )
        
        # Create modules
        self.base_module = ModuleManifest.objects.create(
            module_id='com.example.base',
            name='Base Module',
            version='1.0.0'
        )
        
        self.dependent_module = ModuleManifest.objects.create(
            module_id='com.example.dependent',
            name='Dependent Module',
            version='1.0.0',
            dependencies=['com.example.base']
        )
        
        # Create installation
        self.installation = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.dependent_module,
            status='active'
        )
    
    def test_create_dependency(self):
        """Test creating a module dependency"""
        dependency = ModuleDependency.objects.create(
            installation=self.installation,
            required_module=self.base_module,
            version_constraint='>=1.0.0',
            is_satisfied=True
        )
        
        self.assertEqual(dependency.installation, self.installation)
        self.assertEqual(dependency.required_module, self.base_module)
        self.assertTrue(dependency.is_satisfied)
    
    def test_dependency_protection(self):
        """Test that required modules are protected from deletion"""
        dependency = ModuleDependency.objects.create(
            installation=self.installation,
            required_module=self.base_module,
            is_satisfied=True
        )
        
        # Try to delete the required module - should be protected
        with self.assertRaises(Exception):  # ProtectedError
            self.base_module.delete()


class ModuleEventTestCase(TestCase):
    """Test ModuleEvent model"""
    
    def setUp(self):
        # Create tenant
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            schema_name='test_tenant'
        )
        
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            tenant=self.tenant
        )
        
        # Create module
        self.module = ModuleManifest.objects.create(
            module_id='com.example.test',
            name='Test Module',
            version='1.0.0'
        )
    
    def test_create_event(self):
        """Test creating a module event"""
        event = ModuleEvent.objects.create(
            tenant=self.tenant,
            module=self.module,
            event_type='module.published',
            user=self.user,
            event_data={'version': '1.0.0'}
        )
        
        self.assertEqual(event.module, self.module)
        self.assertEqual(event.event_type, 'module.published')
        self.assertEqual(event.user, self.user)
        self.assertIsNotNone(event.occurred_at)
    
    def test_event_ordering(self):
        """Test that events are ordered by occurred_at descending"""
        # Create multiple events
        event1 = ModuleEvent.objects.create(
            tenant=self.tenant,
            module=self.module,
            event_type='module.installed'
        )
        
        event2 = ModuleEvent.objects.create(
            tenant=self.tenant,
            module=self.module,
            event_type='module.enabled'
        )
        
        events = ModuleEvent.objects.filter(module=self.module)
        self.assertEqual(events[0], event2)  # Most recent first
        self.assertEqual(events[1], event1)