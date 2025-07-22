"""
Circuit breaker implementation for provider resilience.
"""
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """States of the circuit breaker."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker pattern implementation to prevent cascading failures.
    
    The circuit breaker has three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, requests are rejected immediately
    - HALF_OPEN: Testing if service has recovered
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception,
        name: Optional[str] = None
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type to catch
            name: Optional name for logging
        """
        self.name = name or "CircuitBreaker"
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED
        self._half_open_attempts = 0
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing)."""
        return self.state == CircuitState.OPEN
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal)."""
        return self.state == CircuitState.CLOSED
    
    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing)."""
        return self.state == CircuitState.HALF_OPEN
    
    def record_success(self):
        """Record a successful call."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info(f"{self.name}: Circuit recovered, closing")
        
        self.failure_count = 0
        self._half_open_attempts = 0
        self.state = CircuitState.CLOSED
    
    def record_failure(self, exception: Optional[Exception] = None):
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == CircuitState.HALF_OPEN:
            self._half_open_attempts += 1
            logger.warning(
                f"{self.name}: Failed in HALF_OPEN state "
                f"(attempt {self._half_open_attempts})"
            )
            
            # If we fail in half-open, go back to open
            self.state = CircuitState.OPEN
        
        elif self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.error(
                    f"{self.name}: Failure threshold reached "
                    f"({self.failure_count}/{self.failure_threshold}), "
                    f"opening circuit"
                )
            self.state = CircuitState.OPEN
    
    def can_attempt(self) -> bool:
        """Check if we can attempt a call through the circuit."""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # Check if we should try recovery
            if self.last_failure_time and \
               datetime.now() - self.last_failure_time > timedelta(seconds=self.recovery_timeout):
                logger.info(
                    f"{self.name}: Recovery timeout reached, "
                    f"attempting recovery"
                )
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        
        # HALF_OPEN - allow one attempt
        return self._half_open_attempts == 0
    
    def __enter__(self):
        """Context manager entry."""
        if not self.can_attempt():
            raise Exception(f"Circuit breaker {self.name} is OPEN")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type is None:
            self.record_success()
        elif issubclass(exc_type, self.expected_exception):
            self.record_failure(exc_val)
        
        # Don't suppress the exception
        return False
    
    def get_state(self) -> dict:
        """Get current state information."""
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'failure_threshold': self.failure_threshold,
            'last_failure_time': self.last_failure_time.isoformat() if self.last_failure_time else None,
            'recovery_timeout': self.recovery_timeout,
            'can_attempt': self.can_attempt()
        }