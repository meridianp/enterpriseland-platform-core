"""
Tests for base module class
"""

from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from platform_core.accounts.models import Tenant
from platform_core.modules.models import ModuleManifest, ModuleInstallation
from platform_core.modules.base import BaseModule
from platform_core.modules.exceptions import ModuleError


class ConcreteModule(BaseModule):
    """Concrete implementation for testing"""
    
    @property
    def name(self):
        return "Concrete Test Module"
    
    @property
    def description(self):
        return "A concrete module for testing"
    
    def initialize(self):
        """Initialize the module"""
        self.initialized = True
        self._init_count = getattr(self, '_init_count', 0) + 1
    
    def shutdown(self):
        """Shutdown the module"""
        self.initialized = False
        self._shutdown_count = getattr(self, '_shutdown_count', 0) + 1
    
    def handle_install(self):
        """Handle module installation"""
        self._install_handled = True
    
    def handle_uninstall(self):
        """Handle module uninstallation"""
        self._uninstall_handled = True
    
    def handle_enable(self):
        """Handle module enabling"""
        self._enable_handled = True
    
    def handle_disable(self):
        """Handle module disabling"""
        self._disable_handled = True


class BaseModuleTestCase(TestCase):
    """Test BaseModule abstract class"""
    
    def setUp(self):
        # Create test tenant
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            schema_name='test_tenant'
        )
        
        # Create test manifest
        self.manifest = ModuleManifest.objects.create(
            module_id='com.example.base',
            name='Base Test Module',
            version='1.0.0',
            description='Base module for testing',
            author='Test Author',
            author_email='test@example.com',
            website='https://example.com',
            permissions=['file.read', 'workflow.create']
        )
        
        # Create test installation
        self.installation = ModuleInstallation.objects.create(
            tenant=self.tenant,
            module=self.manifest,
            status='active',
            configuration={'test_setting': 'test_value'}
        )
    
    def test_module_instantiation(self):
        """Test creating a module instance"""
        module = ConcreteModule(self.manifest, self.installation)
        
        self.assertEqual(module.manifest, self.manifest)
        self.assertEqual(module.installation, self.installation)
        self.assertIsNone(module._logger)  # Lazy loaded
    
    def test_module_properties_from_manifest(self):
        """Test that module properties come from manifest"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # These should come from the concrete class
        self.assertEqual(module.name, "Concrete Test Module")
        self.assertEqual(module.description, "A concrete module for testing")
        
        # These should come from manifest
        self.assertEqual(module.module_id, 'com.example.base')
        self.assertEqual(module.version, '1.0.0')
        self.assertEqual(module.author, 'Test Author')
        self.assertEqual(module.author_email, 'test@example.com')
        self.assertEqual(module.website, 'https://example.com')
        self.assertEqual(module.permissions, ['file.read', 'workflow.create'])
    
    def test_module_configuration(self):
        """Test module configuration access"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Get existing config
        self.assertEqual(
            module.get_config('test_setting'),
            'test_value'
        )
        
        # Get with default
        self.assertEqual(
            module.get_config('missing_setting', 'default'),
            'default'
        )
        
        # Set config
        module.set_config('new_setting', 'new_value')
        self.assertEqual(
            module.get_config('new_setting'),
            'new_value'
        )
        
        # Verify it's saved to installation
        self.installation.refresh_from_db()
        self.assertEqual(
            self.installation.configuration['new_setting'],
            'new_value'
        )
    
    def test_module_logger(self):
        """Test module logger lazy loading"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Logger should be created on first access
        self.assertIsNone(module._logger)
        logger = module.logger
        self.assertIsNotNone(logger)
        self.assertIs(module._logger, logger)
        
        # Should reuse same logger
        logger2 = module.logger
        self.assertIs(logger, logger2)
    
    def test_lifecycle_methods(self):
        """Test module lifecycle methods"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Test initialize
        module.initialize()
        self.assertTrue(module.initialized)
        self.assertEqual(module._init_count, 1)
        
        # Test shutdown
        module.shutdown()
        self.assertFalse(module.initialized)
        self.assertEqual(module._shutdown_count, 1)
    
    def test_event_handlers(self):
        """Test module event handlers"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Test install handler
        module.handle_install()
        self.assertTrue(module._install_handled)
        
        # Test uninstall handler
        module.handle_uninstall()
        self.assertTrue(module._uninstall_handled)
        
        # Test enable handler
        module.handle_enable()
        self.assertTrue(module._enable_handled)
        
        # Test disable handler
        module.handle_disable()
        self.assertTrue(module._disable_handled)
    
    def test_abstract_methods_not_implemented(self):
        """Test that abstract methods raise NotImplementedError"""
        # Create a module that doesn't implement required methods
        class IncompleteModule(BaseModule):
            pass
        
        module = IncompleteModule(self.manifest, self.installation)
        
        # These should raise NotImplementedError
        with self.assertRaises(NotImplementedError):
            module.name
        
        with self.assertRaises(NotImplementedError):
            module.description
        
        with self.assertRaises(NotImplementedError):
            module.initialize()
        
        with self.assertRaises(NotImplementedError):
            module.shutdown()
    
    def test_validate_method(self):
        """Test module validation"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Default validate should pass
        errors = module.validate()
        self.assertEqual(errors, [])
        
        # Create a module with custom validation
        class ValidatingModule(ConcreteModule):
            def validate(self):
                errors = super().validate()
                if not self.get_config('required_setting'):
                    errors.append("Missing required_setting")
                return errors
        
        # Test validation failure
        module = ValidatingModule(self.manifest, self.installation)
        errors = module.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("Missing required_setting", errors[0])
        
        # Fix and revalidate
        module.set_config('required_setting', 'value')
        errors = module.validate()
        self.assertEqual(errors, [])
    
    def test_module_without_installation(self):
        """Test module behavior without installation (manifest only)"""
        module = ConcreteModule(self.manifest, None)
        
        self.assertEqual(module.manifest, self.manifest)
        self.assertIsNone(module.installation)
        
        # Properties from manifest should still work
        self.assertEqual(module.module_id, 'com.example.base')
        self.assertEqual(module.version, '1.0.0')
        
        # Config should return defaults
        self.assertEqual(
            module.get_config('any_setting', 'default'),
            'default'
        )
        
        # Setting config should not crash (but won't persist)
        module.set_config('test', 'value')
    
    def test_module_state_tracking(self):
        """Test module state tracking"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Should match installation status
        self.assertTrue(module.is_enabled())
        
        # Change installation status
        self.installation.status = 'disabled'
        self.installation.save()
        
        self.assertFalse(module.is_enabled())
        
        # Module without installation is not enabled
        module_no_install = ConcreteModule(self.manifest, None)
        self.assertFalse(module_no_install.is_enabled())
    
    def test_module_api_access(self):
        """Test module API access methods"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Mock the registry
        with patch('platform_core.modules.base.apps') as mock_apps:
            mock_registry = Mock()
            mock_apps.get_app_config.return_value.registry = mock_registry
            
            # Test get_api
            mock_api = Mock()
            mock_registry.get_module_api.return_value = mock_api
            
            api = module.get_api('com.example.other')
            
            mock_registry.get_module_api.assert_called_once_with(
                'com.example.other',
                self.tenant
            )
            self.assertEqual(api, mock_api)
    
    def test_module_emit_event(self):
        """Test module event emission"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Mock signals
        with patch('platform_core.modules.base.module_error') as mock_signal:
            # Emit an event
            module.emit_event('test_event', {'key': 'value'})
            
            # For now, no specific signal for custom events
            # In a real implementation, we'd have a generic module_event signal
    
    def test_module_error_handling(self):
        """Test module error handling"""
        module = ConcreteModule(self.manifest, self.installation)
        
        # Create a module that raises errors
        class ErrorModule(ConcreteModule):
            def initialize(self):
                raise ValueError("Initialization failed")
        
        error_module = ErrorModule(self.manifest, self.installation)
        
        # Should raise the error
        with self.assertRaises(ValueError):
            error_module.initialize()