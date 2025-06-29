"""
Module System Signals

Django signals for module lifecycle events.
"""

from django.dispatch import Signal

# Module lifecycle signals
module_registered = Signal()  # When a new module is registered
module_installed = Signal()   # When a module is installed for a tenant
module_enabled = Signal()     # When a module is enabled
module_disabled = Signal()    # When a module is disabled
module_uninstalled = Signal() # When a module is uninstalled
module_upgraded = Signal()    # When a module is upgraded

# Module runtime signals
module_loaded = Signal()      # When a module is loaded into memory
module_unloaded = Signal()    # When a module is unloaded from memory
module_error = Signal()       # When a module encounters an error

# Module health signals
module_health_check = Signal()     # When a health check is performed
module_health_degraded = Signal()  # When module health degrades
module_health_restored = Signal()  # When module health is restored