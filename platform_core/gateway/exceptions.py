"""
Gateway Exceptions

Custom exceptions for the API Gateway.
"""


class GatewayException(Exception):
    """Base exception for gateway errors"""
    status_code = 500
    
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        if status_code:
            self.status_code = status_code


class RouteNotFound(GatewayException):
    """Route not found in gateway"""
    status_code = 404


class ServiceUnavailable(GatewayException):
    """Backend service is unavailable"""
    status_code = 503


class CircuitBreakerOpen(GatewayException):
    """Circuit breaker is open for service"""
    status_code = 503


class TransformationError(GatewayException):
    """Error during request/response transformation"""
    status_code = 500


class AggregationError(GatewayException):
    """Error during API aggregation"""
    status_code = 500


class AuthenticationRequired(GatewayException):
    """Authentication is required"""
    status_code = 401


class RateLimitExceeded(GatewayException):
    """Rate limit exceeded"""
    status_code = 429


class InvalidConfiguration(GatewayException):
    """Invalid gateway configuration"""
    status_code = 500