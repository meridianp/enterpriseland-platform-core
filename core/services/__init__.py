"""
Platform Core Services

Provides base service classes and utilities for business logic implementation.
"""

from .base import (
    BaseService,
    ServiceError,
    ValidationServiceError,
    PermissionServiceError,
    NotFoundServiceError,
)

__all__ = [
    'BaseService',
    'ServiceError',
    'ValidationServiceError',
    'PermissionServiceError',
    'NotFoundServiceError',
]