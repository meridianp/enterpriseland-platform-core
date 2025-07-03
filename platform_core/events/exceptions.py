"""
Event System Exceptions
"""


class EventException(Exception):
    """Base exception for event system."""
    pass


class EventPublishError(EventException):
    """Error publishing event."""
    pass


class EventValidationError(EventException):
    """Event validation error."""
    pass


class EventSchemaNotFound(EventException):
    """Event schema not found."""
    pass


class EventProcessingError(EventException):
    """Error processing event."""
    pass


class EventSubscriptionError(EventException):
    """Error with event subscription."""
    pass


class EventRouterError(EventException):
    """Error routing event."""
    pass


class EventTimeoutError(EventException):
    """Event processing timeout."""
    pass


class EventRetryExhausted(EventException):
    """All retry attempts exhausted."""
    pass


class SagaException(EventException):
    """Base exception for saga operations."""
    pass


class SagaCompensationError(SagaException):
    """Error during saga compensation."""
    pass


class SagaTimeoutError(SagaException):
    """Saga execution timeout."""
    pass