"""
Custom exceptions for the provider abstraction layer.
"""


class ProviderException(Exception):
    """Base exception for provider-related errors."""
    pass


class ProviderNotFoundError(ProviderException):
    """Raised when a requested provider is not found."""
    pass


class AllProvidersFailedError(ProviderException):
    """Raised when all available providers have failed."""
    
    def __init__(self, service: str, errors: list):
        self.service = service
        self.errors = errors
        super().__init__(
            f"All providers failed for service '{service}'. "
            f"Errors: {'; '.join(errors)}"
        )


class CircuitBreakerOpenError(ProviderException):
    """Raised when circuit breaker is open."""
    
    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"Circuit breaker is open for provider '{provider}'")


class RateLimitExceededError(ProviderException):
    """Raised when provider rate limit is exceeded."""
    
    def __init__(self, provider: str, limit: str):
        self.provider = provider
        self.limit = limit
        super().__init__(
            f"Rate limit exceeded for provider '{provider}': {limit}"
        )


class ProviderTimeoutError(ProviderException):
    """Raised when provider request times out."""
    
    def __init__(self, provider: str, timeout: int):
        self.provider = provider
        self.timeout = timeout
        super().__init__(
            f"Provider '{provider}' timed out after {timeout} seconds"
        )