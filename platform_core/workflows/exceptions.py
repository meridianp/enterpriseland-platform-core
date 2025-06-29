"""
Workflow System Exceptions
"""


class WorkflowError(Exception):
    """Base exception for workflow errors"""
    pass


class WorkflowNotFoundError(WorkflowError):
    """Workflow or instance not found"""
    pass


class WorkflowPermissionError(WorkflowError):
    """User lacks permission for workflow operation"""
    pass


class WorkflowExecutionError(WorkflowError):
    """Error during workflow execution"""
    pass


class WorkflowValidationError(WorkflowError):
    """Workflow validation failed"""
    pass


class WorkflowTransitionError(WorkflowError):
    """Invalid workflow transition"""
    pass


class WorkflowTaskError(WorkflowError):
    """Error related to workflow tasks"""
    pass


class WorkflowTimeoutError(WorkflowError):
    """Workflow execution timeout"""
    pass


class WorkflowConfigurationError(WorkflowError):
    """Workflow configuration error"""
    pass