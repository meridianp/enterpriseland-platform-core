"""
Compliance Provider Integration

Abstraction layer for various KYC/AML providers.
"""
from typing import Dict, Type
from .base import BaseComplianceProvider
from .complyadvantage import ComplyAdvantageProvider
from .onfido import OnfidoProvider
from .refinitiv import RefinitivProvider


# Provider registry
PROVIDERS: Dict[str, Type[BaseComplianceProvider]] = {
    'complyadvantage': ComplyAdvantageProvider,
    'onfido': OnfidoProvider,
    'refinitiv': RefinitivProvider,
}


def get_provider(provider_name: str) -> BaseComplianceProvider:
    """
    Get a compliance provider instance.
    
    Args:
        provider_name: Name of the provider
        
    Returns:
        Provider instance
        
    Raises:
        ValueError: If provider not found
    """
    provider_class = PROVIDERS.get(provider_name.lower())
    if not provider_class:
        raise ValueError(f"Unknown compliance provider: {provider_name}")
    
    return provider_class()


def register_providers():
    """Register all available providers."""
    # This is called during app initialization
    # Providers can perform any setup needed
    for provider_name, provider_class in PROVIDERS.items():
        try:
            provider = provider_class()
            provider.validate_configuration()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to initialize provider {provider_name}: {e}")


__all__ = [
    'BaseComplianceProvider',
    'ComplyAdvantageProvider',
    'OnfidoProvider',
    'RefinitivProvider',
    'get_provider',
    'register_providers',
    'PROVIDERS'
]