"""
Module System Exceptions

Custom exceptions for the module system.
"""


class ModuleError(Exception):
    """Base exception for module system errors"""
    pass


class ModuleNotFoundError(ModuleError):
    """Raised when a module cannot be found"""
    pass


class ModuleLoadError(ModuleError):
    """Raised when a module fails to load"""
    pass


class ModuleValidationError(ModuleError):
    """Raised when module validation fails"""
    pass


class DependencyError(ModuleError):
    """Base exception for dependency-related errors"""
    pass


class DependencyNotFoundError(DependencyError):
    """Raised when a required dependency is not found"""
    pass


class CircularDependencyError(DependencyError):
    """Raised when circular dependencies are detected"""
    pass


class DependencyVersionError(DependencyError):
    """Raised when dependency version requirements are not met"""
    pass


class ModuleInstallationError(ModuleError):
    """Raised when module installation fails"""
    pass


class ModuleConfigurationError(ModuleError):
    """Raised when module configuration is invalid"""
    pass


class ModulePermissionError(ModuleError):
    """Raised when module lacks required permissions"""
    pass


class ModuleResourceError(ModuleError):
    """Raised when module exceeds resource limits"""
    pass


class ModuleStateError(ModuleError):
    """Raised when module is in an invalid state for the requested operation"""
    pass


class ModuleIsolationError(ModuleError):
    """Raised when module isolation is breached"""
    pass