"""
Central registry for managing all providers.
"""
import importlib
import logging
from typing import Dict, List, Optional, Any
from django.conf import settings
from django.core.cache import cache

from .circuit_breaker import CircuitBreaker
from .exceptions import (
    ProviderNotFoundError,
    AllProvidersFailedError,
    CircuitBreakerOpenError
)
from .providers.base import Provider, ProviderConfig, RateLimits

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Central registry for all providers.
    
    Manages provider lifecycle, routing, and fallback logic.
    """
    
    def __init__(self):
        self._providers: Dict[str, Dict[str, Provider]] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._initialized = False
    
    def initialize(self):
        """Initialize the registry by loading all configured providers."""
        if self._initialized:
            return
        
        logger.info("Initializing provider registry")
        self._load_providers()
        self._initialized = True
    
    def _load_providers(self):
        """Load providers from Django settings configuration."""
        provider_config = getattr(settings, 'PROVIDER_CONFIG', {})
        
        for service, config in provider_config.items():
            self._providers[service] = {}
            
            for provider_name, provider_config in config.get('providers', {}).items():
                if not provider_config.get('enabled', True):
                    logger.info(f"Skipping disabled provider: {service}.{provider_name}")
                    continue
                
                try:
                    provider = self._create_provider(provider_name, provider_config)
                    self._providers[service][provider_name] = provider
                    
                    # Create circuit breaker for this provider
                    breaker_name = f"{service}.{provider_name}"
                    self._circuit_breakers[breaker_name] = CircuitBreaker(
                        name=breaker_name,
                        failure_threshold=provider_config.get('circuit_breaker_threshold', 5),
                        recovery_timeout=provider_config.get('circuit_breaker_timeout', 60)
                    )
                    
                    logger.info(f"Loaded provider: {breaker_name}")
                    
                except Exception as e:
                    logger.error(f"Failed to load provider {provider_name}: {e}", exc_info=True)
    
    def _create_provider(self, name: str, config: dict) -> Provider:
        """Dynamically create a provider instance from configuration."""
        # Get the provider class
        class_path = config['class']
        module_path, class_name = class_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        provider_class = getattr(module, class_name)
        
        # Create provider configuration
        rate_limits = None
        if 'rate_limits' in config:
            rate_limits = RateLimits(**config['rate_limits'])
        
        provider_config = ProviderConfig(
            name=name,
            enabled=config.get('enabled', True),
            timeout=config.get('timeout', 30),
            retry_count=config.get('retry_count', 3),
            retry_delay=config.get('retry_delay', 1),
            cache_ttl=config.get('cache_ttl', 3600),
            rate_limits=rate_limits
        )
        
        # Store params in the config for the provider to access
        setattr(provider_config, 'params', config.get('params', {}))
        
        # Instantiate the provider
        return provider_class(config=provider_config)
    
    def get_provider(self, service: str, provider: str) -> Provider:
        """Get a specific provider instance."""
        if not self._initialized:
            self.initialize()
        
        if service not in self._providers:
            raise ProviderNotFoundError(f"Unknown service: {service}")
        
        if provider not in self._providers[service]:
            raise ProviderNotFoundError(
                f"Unknown provider '{provider}' for service '{service}'"
            )
        
        return self._providers[service][provider]
    
    def get_providers(self, service: str) -> Dict[str, Provider]:
        """Get all providers for a service."""
        if not self._initialized:
            self.initialize()
        
        if service not in self._providers:
            raise ProviderNotFoundError(f"Unknown service: {service}")
        
        return self._providers[service]
    
    def get_available_providers(self, service: str) -> List[str]:
        """Get list of available provider names for a service."""
        providers = self.get_providers(service)
        available = []
        
        for name, provider in providers.items():
            breaker = self._circuit_breakers.get(f"{service}.{name}")
            if provider.config.enabled and breaker and breaker.can_attempt():
                available.append(name)
        
        return available
    
    async def execute(
        self,
        service: str,
        operation: str,
        providers: Optional[List[str]] = None,
        **kwargs
    ) -> Any:
        """
        Execute an operation with automatic fallback.
        
        Args:
            service: The service type (e.g., 'contact_enrichment', 'email')
            operation: The operation to perform (e.g., 'enrich_contact', 'send')
            providers: Optional list of provider names to try (in order)
            **kwargs: Arguments to pass to the operation
        
        Returns:
            The result from the first successful provider
        
        Raises:
            AllProvidersFailedError: If all providers fail
        """
        if not self._initialized:
            self.initialize()
        
        # Get provider list
        if providers:
            # Validate requested providers exist
            for p in providers:
                if p not in self._providers.get(service, {}):
                    raise ProviderNotFoundError(
                        f"Provider '{p}' not found for service '{service}'"
                    )
            available_providers = providers
        else:
            # Use configured order or all available
            config = getattr(settings, 'PROVIDER_CONFIG', {}).get(service, {})
            fallback_order = config.get('fallback_order', [])
            
            if fallback_order:
                available_providers = [
                    p for p in fallback_order 
                    if p in self._providers[service]
                ]
            else:
                available_providers = list(self._providers[service].keys())
        
        # Try each provider
        errors = []
        
        for provider_name in available_providers:
            provider = self._providers[service][provider_name]
            breaker = self._circuit_breakers[f"{service}.{provider_name}"]
            
            # Check circuit breaker
            if not breaker.can_attempt():
                error_msg = f"{provider_name}: Circuit breaker is open"
                logger.warning(error_msg)
                errors.append(error_msg)
                continue
            
            try:
                # Check cache first
                cache_key = self._get_cache_key(service, provider_name, operation, kwargs)
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    logger.debug(f"Cache hit for {service}.{provider_name}.{operation}")
                    return cached_result
                
                # Execute the operation
                logger.info(f"Executing {operation} with provider {provider_name}")
                method = getattr(provider, operation)
                
                import time
                start_time = time.time()
                
                result = await method(**kwargs)
                
                duration = time.time() - start_time
                logger.info(
                    f"Provider {provider_name} succeeded in {duration:.2f}s"
                )
                
                # Record success
                breaker.record_success()
                
                # Cache the result
                if provider.config.cache_ttl > 0:
                    cache.set(cache_key, result, provider.config.cache_ttl)
                
                return result
                
            except Exception as e:
                # Record failure
                breaker.record_failure(e)
                error_msg = f"{provider_name}: {type(e).__name__}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"Provider {provider_name} failed: {e}", exc_info=True)
                continue
        
        # All providers failed
        raise AllProvidersFailedError(service, errors)
    
    def _get_cache_key(self, service: str, provider: str, operation: str, kwargs: dict) -> str:
        """Generate a cache key for the operation."""
        # Create a stable key from the arguments
        import hashlib
        import json
        
        # Sort kwargs for consistent hashing
        sorted_kwargs = json.dumps(kwargs, sort_keys=True)
        kwargs_hash = hashlib.md5(sorted_kwargs.encode()).hexdigest()
        
        return f"provider:{service}:{provider}:{operation}:{kwargs_hash}"
    
    def get_circuit_breaker_states(self) -> Dict[str, dict]:
        """Get the state of all circuit breakers."""
        states = {}
        for name, breaker in self._circuit_breakers.items():
            states[name] = breaker.get_state()
        return states
    
    def reset_circuit_breaker(self, service: str, provider: str):
        """Manually reset a circuit breaker."""
        breaker_name = f"{service}.{provider}"
        if breaker_name in self._circuit_breakers:
            breaker = self._circuit_breakers[breaker_name]
            breaker.failure_count = 0
            breaker.state = breaker.CircuitState.CLOSED
            logger.info(f"Circuit breaker {breaker_name} manually reset")
        else:
            raise ProviderNotFoundError(f"Circuit breaker {breaker_name} not found")
    
    def get_provider_metrics(self) -> Dict[str, Dict[str, dict]]:
        """Get metrics for all providers."""
        metrics = {}
        
        for service, providers in self._providers.items():
            metrics[service] = {}
            
            for name, provider in providers.items():
                metrics[service][name] = provider.get_metrics()
        
        return metrics


# Global registry instance
provider_registry = ProviderRegistry()