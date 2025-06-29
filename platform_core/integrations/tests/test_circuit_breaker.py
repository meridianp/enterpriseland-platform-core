"""
Tests for the circuit breaker implementation.
"""
import time
from django.test import TestCase
from unittest.mock import Mock, patch

from ..circuit_breaker import CircuitBreaker, CircuitState
from ..exceptions import CircuitBreakerOpenError


class CircuitBreakerTestCase(TestCase):
    """Test cases for the circuit breaker."""
    
    def setUp(self):
        """Set up test circuit breaker."""
        self.breaker = CircuitBreaker(
            name="test_breaker",
            failure_threshold=3,
            recovery_timeout=1  # 1 second for faster tests
        )
    
    def test_initial_state(self):
        """Test that circuit breaker starts in closed state."""
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.breaker.failure_count, 0)
        self.assertTrue(self.breaker.can_attempt())
    
    def test_record_success(self):
        """Test recording successful calls."""
        # Record some failures first
        self.breaker.failure_count = 2
        
        # Record a success
        self.breaker.record_success()
        
        # Failure count should reset
        self.assertEqual(self.breaker.failure_count, 0)
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
    
    def test_record_failure_below_threshold(self):
        """Test recording failures below threshold keeps circuit closed."""
        # Record failures below threshold
        for i in range(2):
            self.breaker.record_failure(Exception("Test error"))
        
        self.assertEqual(self.breaker.failure_count, 2)
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertTrue(self.breaker.can_attempt())
    
    def test_record_failure_opens_circuit(self):
        """Test that reaching failure threshold opens the circuit."""
        # Record failures to reach threshold
        for i in range(3):
            self.breaker.record_failure(Exception("Test error"))
        
        self.assertEqual(self.breaker.failure_count, 3)
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertFalse(self.breaker.can_attempt())
    
    def test_open_circuit_transitions_to_half_open(self):
        """Test that open circuit transitions to half-open after timeout."""
        # Open the circuit
        for i in range(3):
            self.breaker.record_failure(Exception("Test error"))
        
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        
        # Wait for recovery timeout
        time.sleep(1.1)
        
        # Check state - accessing can_attempt should trigger transition
        self.assertTrue(self.breaker.can_attempt())
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)
    
    def test_half_open_success_closes_circuit(self):
        """Test that success in half-open state closes the circuit."""
        # Set to half-open state
        self.breaker.state = CircuitState.HALF_OPEN
        self.breaker.failure_count = 3
        
        # Record success
        self.breaker.record_success()
        
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.breaker.failure_count, 0)
    
    def test_half_open_failure_reopens_circuit(self):
        """Test that failure in half-open state reopens the circuit."""
        # Set to half-open state
        self.breaker.state = CircuitState.HALF_OPEN
        self.breaker.last_failure_time = time.time()
        
        # Record failure
        self.breaker.record_failure(Exception("Test error"))
        
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertEqual(self.breaker.failure_count, 1)
    
    def test_get_state(self):
        """Test getting circuit breaker state information."""
        state_info = self.breaker.get_state()
        
        self.assertEqual(state_info['name'], 'test_breaker')
        self.assertEqual(state_info['state'], 'closed')
        self.assertEqual(state_info['failure_count'], 0)
        self.assertTrue(state_info['can_attempt'])
        self.assertIsNone(state_info['last_failure_time'])
    
    def test_get_state_with_failures(self):
        """Test getting state with recorded failures."""
        # Record some failures
        test_time = time.time()
        with patch('time.time', return_value=test_time):
            self.breaker.record_failure(Exception("Test"))
        
        state_info = self.breaker.get_state()
        
        self.assertEqual(state_info['failure_count'], 1)
        # last_failure_time is returned as ISO format string
        self.assertIsNotNone(state_info['last_failure_time'])
    
    def test_custom_thresholds(self):
        """Test circuit breaker with custom thresholds."""
        # Create breaker with higher threshold
        breaker = CircuitBreaker(
            name="high_threshold",
            failure_threshold=5,
            recovery_timeout=60
        )
        
        # Record 4 failures - should still be closed
        for i in range(4):
            breaker.record_failure(Exception("Test"))
        
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        
        # 5th failure should open it
        breaker.record_failure(Exception("Test"))
        self.assertEqual(breaker.state, CircuitState.OPEN)
    
    def test_concurrent_access(self):
        """Test circuit breaker handles concurrent access correctly."""
        import threading
        
        def record_failures():
            for i in range(2):
                self.breaker.record_failure(Exception("Test"))
        
        # Create multiple threads recording failures
        threads = [threading.Thread(target=record_failures) for _ in range(3)]
        
        # Start all threads
        for t in threads:
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # Circuit should be open (6 failures recorded)
        self.assertEqual(self.breaker.state, CircuitState.OPEN)