"""
Platform Core Integrations App

Provides a provider abstraction layer for external service integrations,
enabling modules to integrate with multiple providers while avoiding vendor lock-in.

Features:
- Multi-provider support with automatic failover
- Circuit breaker pattern for fault tolerance
- Rate limiting and request throttling
- Unified interfaces for common services (email, calendar, enrichment)
- Template loading abstraction for business modules
"""

default_app_config = 'platform_core.integrations.apps.IntegrationsConfig'

from .registry import provider_registry
from .template_loaders import get_template_loader, set_template_loader

# Import services on demand to avoid import issues
def get_email_service():
    from .services.email import email_service
    return email_service

__all__ = [
    'provider_registry',
    'get_email_service',
    'get_template_loader',
    'set_template_loader',
]