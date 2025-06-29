"""
Tests for module system signals
"""

from django.test import TestCase
from django.dispatch import receiver

from platform_core.accounts.models import Tenant, User
from platform_core.modules.models import ModuleManifest, ModuleInstallation
from platform_core.modules import signals


class ModuleSignalsTestCase(TestCase):
    """Test module system signals"""
    
    def setUp(self):
        # Create test data
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            schema_name='test_tenant'
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            tenant=self.tenant
        )
        
        self.manifest = ModuleManifest.objects.create(
            module_id='com.example.signals',
            name='Signal Test Module',
            version='1.0.0'
        )
        
        # Track signal calls
        self.signal_calls = []
    
    def tearDown(self):
        # Clear signal handlers
        self.signal_calls.clear()
    
    def create_signal_handler(self, signal_name):
        """Create a signal handler that tracks calls"""
        def handler(sender, **kwargs):
            self.signal_calls.append({
                'signal': signal_name,
                'sender': sender,
                'kwargs': kwargs
            })
        return handler
    
    def test_module_registered_signal(self):
        """Test module_registered signal"""
        handler = self.create_signal_handler('module_registered')
        signals.module_registered.connect(handler)
        
        try:
            # Send the signal
            signals.module_registered.send(
                sender=self.manifest,
                manifest=self.manifest
            )
            
            # Check it was called
            self.assertEqual(len(self.signal_calls), 1)
            call = self.signal_calls[0]
            self.assertEqual(call['signal'], 'module_registered')
            self.assertEqual(call['sender'], self.manifest)
            self.assertEqual(call['kwargs']['manifest'], self.manifest)
        finally:
            signals.module_registered.disconnect(handler)
    
    def test_module_installed_signal(self):
        """Test module_installed signal"""
        handler = self.create_signal_handler('module_installed')
        signals.module_installed.connect(handler)
        
        try:
            installation = ModuleInstallation.objects.create(
                tenant=self.tenant,
                module=self.manifest,
                status='active',
                installed_by=self.user
            )
            
            # Send the signal
            signals.module_installed.send(
                sender=installation,
                installation=installation,
                tenant=self.tenant,
                user=self.user
            )
            
            # Check it was called
            self.assertEqual(len(self.signal_calls), 1)
            call = self.signal_calls[0]
            self.assertEqual(call['signal'], 'module_installed')
            self.assertEqual(call['kwargs']['installation'], installation)
            self.assertEqual(call['kwargs']['tenant'], self.tenant)
            self.assertEqual(call['kwargs']['user'], self.user)
        finally:
            signals.module_installed.disconnect(handler)
    
    def test_module_enabled_disabled_signals(self):
        """Test module_enabled and module_disabled signals"""
        enable_handler = self.create_signal_handler('module_enabled')
        disable_handler = self.create_signal_handler('module_disabled')
        
        signals.module_enabled.connect(enable_handler)
        signals.module_disabled.connect(disable_handler)
        
        try:
            installation = ModuleInstallation.objects.create(
                tenant=self.tenant,
                module=self.manifest,
                status='disabled'
            )
            
            # Enable the module
            installation.status = 'active'
            installation.save()
            
            signals.module_enabled.send(
                sender=installation,
                installation=installation,
                tenant=self.tenant
            )
            
            # Check enabled signal
            self.assertEqual(len(self.signal_calls), 1)
            self.assertEqual(self.signal_calls[0]['signal'], 'module_enabled')
            
            # Disable the module
            installation.status = 'disabled'
            installation.save()
            
            signals.module_disabled.send(
                sender=installation,
                installation=installation,
                tenant=self.tenant
            )
            
            # Check disabled signal
            self.assertEqual(len(self.signal_calls), 2)
            self.assertEqual(self.signal_calls[1]['signal'], 'module_disabled')
        finally:
            signals.module_enabled.disconnect(enable_handler)
            signals.module_disabled.disconnect(disable_handler)
    
    def test_module_uninstalled_signal(self):
        """Test module_uninstalled signal"""
        handler = self.create_signal_handler('module_uninstalled')
        signals.module_uninstalled.connect(handler)
        
        try:
            installation = ModuleInstallation.objects.create(
                tenant=self.tenant,
                module=self.manifest,
                status='active'
            )
            
            # Send the signal before deletion
            signals.module_uninstalled.send(
                sender=installation,
                installation=installation,
                tenant=self.tenant
            )
            
            # Check it was called
            self.assertEqual(len(self.signal_calls), 1)
            call = self.signal_calls[0]
            self.assertEqual(call['signal'], 'module_uninstalled')
            self.assertEqual(call['kwargs']['installation'], installation)
        finally:
            signals.module_uninstalled.disconnect(handler)
    
    def test_module_upgraded_signal(self):
        """Test module_upgraded signal"""
        handler = self.create_signal_handler('module_upgraded')
        signals.module_upgraded.connect(handler)
        
        try:
            installation = ModuleInstallation.objects.create(
                tenant=self.tenant,
                module=self.manifest,
                status='active'
            )
            
            old_version = '1.0.0'
            new_version = '1.1.0'
            
            # Send the signal
            signals.module_upgraded.send(
                sender=installation,
                installation=installation,
                old_version=old_version,
                new_version=new_version
            )
            
            # Check it was called
            self.assertEqual(len(self.signal_calls), 1)
            call = self.signal_calls[0]
            self.assertEqual(call['signal'], 'module_upgraded')
            self.assertEqual(call['kwargs']['old_version'], old_version)
            self.assertEqual(call['kwargs']['new_version'], new_version)
        finally:
            signals.module_upgraded.disconnect(handler)
    
    def test_module_runtime_signals(self):
        """Test module runtime signals (loaded/unloaded/error)"""
        load_handler = self.create_signal_handler('module_loaded')
        unload_handler = self.create_signal_handler('module_unloaded')
        error_handler = self.create_signal_handler('module_error')
        
        signals.module_loaded.connect(load_handler)
        signals.module_unloaded.connect(unload_handler)
        signals.module_error.connect(error_handler)
        
        try:
            # Test loaded signal
            signals.module_loaded.send(
                sender=self.manifest,
                module_id=self.manifest.module_id,
                tenant=self.tenant
            )
            
            self.assertEqual(len(self.signal_calls), 1)
            self.assertEqual(self.signal_calls[0]['signal'], 'module_loaded')
            
            # Test unloaded signal
            signals.module_unloaded.send(
                sender=self.manifest,
                module_id=self.manifest.module_id,
                tenant=self.tenant
            )
            
            self.assertEqual(len(self.signal_calls), 2)
            self.assertEqual(self.signal_calls[1]['signal'], 'module_unloaded')
            
            # Test error signal
            error = ValueError("Module error")
            signals.module_error.send(
                sender=self.manifest,
                module_id=self.manifest.module_id,
                error=error,
                context={'operation': 'initialize'}
            )
            
            self.assertEqual(len(self.signal_calls), 3)
            self.assertEqual(self.signal_calls[2]['signal'], 'module_error')
            self.assertEqual(self.signal_calls[2]['kwargs']['error'], error)
        finally:
            signals.module_loaded.disconnect(load_handler)
            signals.module_unloaded.disconnect(unload_handler)
            signals.module_error.disconnect(error_handler)
    
    def test_module_health_signals(self):
        """Test module health monitoring signals"""
        check_handler = self.create_signal_handler('module_health_check')
        degraded_handler = self.create_signal_handler('module_health_degraded')
        restored_handler = self.create_signal_handler('module_health_restored')
        
        signals.module_health_check.connect(check_handler)
        signals.module_health_degraded.connect(degraded_handler)
        signals.module_health_restored.connect(restored_handler)
        
        try:
            installation = ModuleInstallation.objects.create(
                tenant=self.tenant,
                module=self.manifest,
                status='active'
            )
            
            # Test health check signal
            health_data = {
                'status': 'healthy',
                'metrics': {
                    'cpu_usage': 25,
                    'memory_usage': 150,
                    'response_time': 0.5
                }
            }
            
            signals.module_health_check.send(
                sender=installation,
                installation=installation,
                health_data=health_data
            )
            
            self.assertEqual(len(self.signal_calls), 1)
            self.assertEqual(self.signal_calls[0]['signal'], 'module_health_check')
            self.assertEqual(
                self.signal_calls[0]['kwargs']['health_data'],
                health_data
            )
            
            # Test degraded signal
            signals.module_health_degraded.send(
                sender=installation,
                installation=installation,
                reason='High memory usage',
                metrics={'memory_usage': 450}
            )
            
            self.assertEqual(len(self.signal_calls), 2)
            self.assertEqual(self.signal_calls[1]['signal'], 'module_health_degraded')
            
            # Test restored signal
            signals.module_health_restored.send(
                sender=installation,
                installation=installation,
                metrics={'memory_usage': 200}
            )
            
            self.assertEqual(len(self.signal_calls), 3)
            self.assertEqual(self.signal_calls[2]['signal'], 'module_health_restored')
        finally:
            signals.module_health_check.disconnect(check_handler)
            signals.module_health_degraded.disconnect(degraded_handler)
            signals.module_health_restored.disconnect(restored_handler)
    
    def test_multiple_handlers(self):
        """Test multiple handlers for the same signal"""
        handler1 = self.create_signal_handler('handler1')
        handler2 = self.create_signal_handler('handler2')
        
        signals.module_registered.connect(handler1)
        signals.module_registered.connect(handler2)
        
        try:
            # Send the signal
            signals.module_registered.send(
                sender=self.manifest,
                manifest=self.manifest
            )
            
            # Both handlers should be called
            self.assertEqual(len(self.signal_calls), 2)
            self.assertEqual(self.signal_calls[0]['signal'], 'handler1')
            self.assertEqual(self.signal_calls[1]['signal'], 'handler2')
        finally:
            signals.module_registered.disconnect(handler1)
            signals.module_registered.disconnect(handler2)
    
    def test_signal_with_exception(self):
        """Test that signal continues to other handlers even if one fails"""
        def failing_handler(sender, **kwargs):
            raise ValueError("Handler failed")
        
        good_handler = self.create_signal_handler('good_handler')
        
        # Connect failing handler first
        signals.module_registered.connect(failing_handler)
        signals.module_registered.connect(good_handler)
        
        try:
            # Send the signal - should not raise
            signals.module_registered.send(
                sender=self.manifest,
                manifest=self.manifest
            )
            
            # Good handler should still be called
            self.assertEqual(len(self.signal_calls), 1)
            self.assertEqual(self.signal_calls[0]['signal'], 'good_handler')
        finally:
            signals.module_registered.disconnect(failing_handler)
            signals.module_registered.disconnect(good_handler)