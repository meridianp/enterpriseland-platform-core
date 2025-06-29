"""
Tests for module loader
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock
from django.test import TestCase, override_settings

from platform_core.modules.loader import ModuleLoader
from platform_core.modules.base import BaseModule
from platform_core.modules.exceptions import ModuleLoadError, ModuleNotFoundError


class TestModule(BaseModule):
    """Test module implementation"""
    
    @property
    def name(self):
        return "Test Module"
    
    @property
    def description(self):
        return "A test module"
    
    def initialize(self):
        self.initialized = True
    
    def shutdown(self):
        self.initialized = False


class ModuleLoaderTestCase(TestCase):
    """Test ModuleLoader"""
    
    def setUp(self):
        self.loader = ModuleLoader()
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
    
    def tearDown(self):
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def create_test_module(self, module_id: str, content: str = None):
        """Create a test module in the temp directory"""
        # Convert module ID to directory name
        dir_name = module_id.split('.')[-1].replace('_', '-')
        module_dir = self.temp_path / dir_name
        module_dir.mkdir(exist_ok=True)
        
        # Create module.py
        if content is None:
            content = '''
from platform_core.modules.base import BaseModule

class Module(BaseModule):
    @property
    def name(self):
        return "Test Module"
    
    @property
    def description(self):
        return "A test module"
    
    def initialize(self):
        pass
    
    def shutdown(self):
        pass
'''
        
        module_file = module_dir / 'module.py'
        module_file.write_text(content)
        
        # Create module.json manifest
        manifest = {
            'id': module_id,
            'name': 'Test Module',
            'version': '1.0.0'
        }
        manifest_file = module_dir / 'module.json'
        manifest_file.write_text(json.dumps(manifest))
        
        return module_dir
    
    @override_settings(MODULE_PATHS=[])
    def test_load_module_from_filesystem(self):
        """Test loading a module from the filesystem"""
        # Create a test module
        module_id = 'com.example.filesystem'
        self.create_test_module(module_id)
        
        # Add temp dir to module paths
        self.loader.module_paths.append(self.temp_path)
        
        # Load the module
        module_class = self.loader.load_module_class(module_id)
        
        self.assertTrue(issubclass(module_class, BaseModule))
        self.assertEqual(module_class().name, "Test Module")
    
    def test_load_module_from_package(self):
        """Test loading a module from an installed package"""
        module_id = 'com.example.installed'
        
        # Mock importlib to simulate an installed package
        with patch('platform_core.modules.loader.importlib.import_module') as mock_import:
            # Create a mock module
            mock_module = Mock()
            mock_module.Module = TestModule
            mock_import.return_value = mock_module
            
            # Load the module
            module_class = self.loader.load_module_class(module_id)
            
            self.assertEqual(module_class, TestModule)
            mock_import.assert_called_with('com_example_installed')
    
    def test_load_module_not_found(self):
        """Test loading a non-existent module"""
        with self.assertRaises(ModuleNotFoundError):
            self.loader.load_module_class('com.example.nonexistent')
    
    def test_load_invalid_module(self):
        """Test loading a module that doesn't inherit from BaseModule"""
        module_id = 'com.example.invalid'
        
        # Create an invalid module
        content = '''
class Module:
    """This doesn't inherit from BaseModule"""
    pass
'''
        self.create_test_module(module_id, content)
        self.loader.module_paths.append(self.temp_path)
        
        with self.assertRaises(ModuleLoadError) as cm:
            self.loader.load_module_class(module_id)
        
        self.assertIn("must inherit from BaseModule", str(cm.exception))
    
    def test_load_module_missing_methods(self):
        """Test loading a module missing required methods"""
        module_id = 'com.example.incomplete'
        
        # Create a module missing required methods
        content = '''
from platform_core.modules.base import BaseModule

class Module(BaseModule):
    @property
    def name(self):
        return "Incomplete Module"
    
    @property
    def description(self):
        return "Missing initialize/shutdown"
    
    # Missing initialize and shutdown methods
'''
        self.create_test_module(module_id, content)
        self.loader.module_paths.append(self.temp_path)
        
        with self.assertRaises(ModuleLoadError) as cm:
            self.loader.load_module_class(module_id)
        
        self.assertIn("missing required method", str(cm.exception))
    
    def test_module_caching(self):
        """Test that loaded modules are cached"""
        module_id = 'com.example.cached'
        self.create_test_module(module_id)
        self.loader.module_paths.append(self.temp_path)
        
        # Load twice
        class1 = self.loader.load_module_class(module_id)
        class2 = self.loader.load_module_class(module_id)
        
        # Should be the same class (cached)
        self.assertIs(class1, class2)
    
    def test_reload_module(self):
        """Test reloading a module"""
        module_id = 'com.example.reload'
        module_dir = self.create_test_module(module_id)
        self.loader.module_paths.append(self.temp_path)
        
        # Load initial version
        class1 = self.loader.load_module_class(module_id)
        instance1 = class1(None, None)
        self.assertEqual(instance1.name, "Test Module")
        
        # Modify the module
        new_content = '''
from platform_core.modules.base import BaseModule

class Module(BaseModule):
    @property
    def name(self):
        return "Updated Module"
    
    @property
    def description(self):
        return "An updated module"
    
    def initialize(self):
        pass
    
    def shutdown(self):
        pass
'''
        (module_dir / 'module.py').write_text(new_content)
        
        # Reload
        class2 = self.loader.reload_module(module_id)
        instance2 = class2(None, None)
        self.assertEqual(instance2.name, "Updated Module")
        
        # Classes should be different
        self.assertIsNot(class1, class2)
    
    def test_get_available_modules(self):
        """Test discovering available modules"""
        # Create several test modules
        modules = [
            'com.example.module1',
            'com.example.module2',
            'com.test.module3'
        ]
        
        for module_id in modules:
            self.create_test_module(module_id)
        
        # Add a non-module directory
        (self.temp_path / 'not-a-module').mkdir()
        
        # Add a hidden directory (should be ignored)
        (self.temp_path / '.hidden').mkdir()
        
        self.loader.module_paths.append(self.temp_path)
        
        # Get available modules
        available = self.loader.get_available_modules()
        
        # Should find all our test modules
        self.assertEqual(len(available), 3)
        for module_id in modules:
            self.assertIn(module_id, available)
    
    def test_load_from_init_file(self):
        """Test loading a module from __init__.py"""
        module_id = 'com.example.init'
        dir_name = module_id.split('.')[-1].replace('_', '-')
        module_dir = self.temp_path / dir_name
        module_dir.mkdir()
        
        # Create __init__.py instead of module.py
        content = '''
from platform_core.modules.base import BaseModule

class Module(BaseModule):
    @property
    def name(self):
        return "Init Module"
    
    @property
    def description(self):
        return "Module from __init__.py"
    
    def initialize(self):
        pass
    
    def shutdown(self):
        pass
'''
        (module_dir / '__init__.py').write_text(content)
        
        self.loader.module_paths.append(self.temp_path)
        
        # Should load successfully
        module_class = self.loader.load_module_class(module_id)
        self.assertEqual(module_class().name, "Init Module")
    
    def test_load_module_with_imports(self):
        """Test loading a module that imports other modules"""
        module_id = 'com.example.imports'
        
        # Create a module with imports
        content = '''
import json
import datetime
from pathlib import Path
from platform_core.modules.base import BaseModule

class Module(BaseModule):
    @property
    def name(self):
        return "Module with Imports"
    
    @property
    def description(self):
        return f"Created at {datetime.datetime.now()}"
    
    def initialize(self):
        self.config = json.dumps({"initialized": True})
        self.path = Path(".")
    
    def shutdown(self):
        pass
'''
        self.create_test_module(module_id, content)
        self.loader.module_paths.append(self.temp_path)
        
        # Should load successfully with imports
        module_class = self.loader.load_module_class(module_id)
        instance = module_class(None, None)
        self.assertEqual(instance.name, "Module with Imports")
    
    def test_load_module_with_alternative_class_name(self):
        """Test loading a module where the class isn't named 'Module'"""
        module_id = 'com.example.altname'
        
        # Create a module with a different class name
        content = '''
from platform_core.modules.base import BaseModule

class CustomModuleClass(BaseModule):
    @property
    def name(self):
        return "Custom Named Module"
    
    @property
    def description(self):
        return "Module with custom class name"
    
    def initialize(self):
        pass
    
    def shutdown(self):
        pass
'''
        self.create_test_module(module_id, content)
        self.loader.module_paths.append(self.temp_path)
        
        # Should find the class that inherits from BaseModule
        module_class = self.loader.load_module_class(module_id)
        self.assertEqual(module_class().name, "Custom Named Module")
    
    @override_settings(BASE_DIR='/test/base/dir')
    def test_default_module_paths(self):
        """Test default module search paths"""
        loader = ModuleLoader()
        
        # Should include default paths relative to BASE_DIR
        path_strs = [str(p) for p in loader.module_paths]
        
        # Note: These might not exist in test environment
        # but they should be in the list
        expected_paths = [
            '/test/base/dir/modules',
            '/test/base/modules',
            '/test/platform_modules'
        ]
        
        for expected in expected_paths:
            # Check if any path ends with the expected suffix
            suffix = expected.split('/')[-1]
            self.assertTrue(
                any(p.endswith(suffix) for p in path_strs),
                f"Expected to find path ending with {suffix}"
            )