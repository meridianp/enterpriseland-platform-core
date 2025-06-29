"""
Provider abstraction layer for external service integrations.

This module provides a unified interface for integrating with multiple
external services while avoiding vendor lock-in.
"""

from .registry import provider_registry

# Import services on demand to avoid import issues
def get_email_service():
    from .services.email import email_service
    return email_service

__all__ = [
    'provider_registry',
    'get_email_service',
]