"""
Base provider interfaces and data structures.
"""
from abc import ABC, abstractmethod
from typing import Protocol, TypeVar, Generic, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class RateLimits:
    """Rate limit configuration for providers."""
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: Optional[int] = None
    concurrent_requests: int = 10


@dataclass
class ProviderConfig:
    """Base configuration for all providers."""
    name: str
    enabled: bool = True
    timeout: int = 30
    retry_count: int = 3
    retry_delay: int = 1
    cache_ttl: int = 3600
    rate_limits: Optional[RateLimits] = None
    params: Optional[Dict[str, Any]] = None


class Provider(Protocol[T]):
    """Base provider protocol that all providers must implement."""
    config: ProviderConfig
    
    async def execute(self, **kwargs) -> T:
        """Execute the provider operation."""
        ...
    
    async def health_check(self) -> bool:
        """Check if the provider is healthy and operational."""
        ...
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get provider usage and performance metrics."""
        ...


class BaseProvider(ABC):
    """Base implementation with common provider functionality."""
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._request_count = 0
        self._error_count = 0
        self._last_request_time = None
        self._total_request_time = 0.0
    
    @abstractmethod
    async def execute(self, **kwargs):
        """Execute the provider operation - must be implemented by subclasses."""
        pass
    
    async def health_check(self) -> bool:
        """Default health check implementation."""
        try:
            # Subclasses can override this for specific health checks
            return self.config.enabled
        except Exception as e:
            logger.error(f"Health check failed for {self.config.name}: {e}")
            return False
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get basic provider metrics."""
        avg_request_time = (
            self._total_request_time / self._request_count 
            if self._request_count > 0 
            else 0
        )
        
        return {
            'name': self.config.name,
            'enabled': self.config.enabled,
            'request_count': self._request_count,
            'error_count': self._error_count,
            'error_rate': self._error_count / max(self._request_count, 1),
            'average_request_time': avg_request_time,
            'last_request_time': self._last_request_time,
        }
    
    def _record_request(self, duration: float, success: bool = True):
        """Record request metrics."""
        self._request_count += 1
        self._total_request_time += duration
        self._last_request_time = datetime.now()
        
        if not success:
            self._error_count += 1