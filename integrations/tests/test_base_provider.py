"""
Tests for base provider functionality.
"""
from django.test import TestCase
from datetime import datetime
from unittest.mock import Mock, patch

from ..providers.base import BaseProvider, ProviderConfig, RateLimits


class TestProvider(BaseProvider):
    """Test implementation of BaseProvider."""
    
    async def execute(self, **kwargs):
        """Test execute method."""
        return {"result": "success", **kwargs}


class BaseProviderTestCase(TestCase):
    """Test cases for base provider functionality."""
    
    def setUp(self):
        """Set up test provider."""
        self.config = ProviderConfig(
            name="test_provider",
            enabled=True,
            timeout=30,
            retry_count=3,
            retry_delay=1,
            cache_ttl=3600,
            rate_limits=RateLimits(
                requests_per_minute=60,
                requests_per_hour=1000,
                concurrent_requests=10
            )
        )
        self.provider = TestProvider(self.config)
    
    def test_provider_initialization(self):
        """Test provider is initialized correctly."""
        self.assertEqual(self.provider.config, self.config)
        self.assertEqual(self.provider._request_count, 0)
        self.assertEqual(self.provider._error_count, 0)
        self.assertIsNone(self.provider._last_request_time)
        self.assertEqual(self.provider._total_request_time, 0.0)
    
    def test_health_check_default(self):
        """Test default health check implementation."""
        import asyncio
        
        # Enabled provider should be healthy
        result = asyncio.run(self.provider.health_check())
        self.assertTrue(result)
        
        # Disabled provider should not be healthy
        self.provider.config.enabled = False
        result = asyncio.run(self.provider.health_check())
        self.assertFalse(result)
    
    def test_record_request_success(self):
        """Test recording successful request metrics."""
        test_duration = 0.5
        test_time = datetime.now()
        
        with patch('integrations.providers.base.datetime') as mock_datetime:
            mock_datetime.now.return_value = test_time
            self.provider._record_request(test_duration, success=True)
        
        self.assertEqual(self.provider._request_count, 1)
        self.assertEqual(self.provider._error_count, 0)
        self.assertEqual(self.provider._total_request_time, test_duration)
        self.assertEqual(self.provider._last_request_time, test_time)
    
    def test_record_request_failure(self):
        """Test recording failed request metrics."""
        test_duration = 0.3
        
        self.provider._record_request(test_duration, success=False)
        
        self.assertEqual(self.provider._request_count, 1)
        self.assertEqual(self.provider._error_count, 1)
        self.assertEqual(self.provider._total_request_time, test_duration)
    
    def test_get_metrics_empty(self):
        """Test getting metrics with no requests."""
        metrics = self.provider.get_metrics()
        
        self.assertEqual(metrics['name'], 'test_provider')
        self.assertTrue(metrics['enabled'])
        self.assertEqual(metrics['request_count'], 0)
        self.assertEqual(metrics['error_count'], 0)
        self.assertEqual(metrics['error_rate'], 0)
        self.assertEqual(metrics['average_request_time'], 0)
        self.assertIsNone(metrics['last_request_time'])
    
    def test_get_metrics_with_requests(self):
        """Test getting metrics after recording requests."""
        # Record some requests
        self.provider._record_request(0.5, success=True)
        self.provider._record_request(0.3, success=True)
        self.provider._record_request(0.4, success=False)
        
        metrics = self.provider.get_metrics()
        
        self.assertEqual(metrics['request_count'], 3)
        self.assertEqual(metrics['error_count'], 1)
        self.assertAlmostEqual(metrics['error_rate'], 1/3, places=2)
        self.assertAlmostEqual(metrics['average_request_time'], 0.4, places=2)
        self.assertIsNotNone(metrics['last_request_time'])
    
    def test_provider_config_defaults(self):
        """Test ProviderConfig default values."""
        minimal_config = ProviderConfig(name="minimal")
        
        self.assertEqual(minimal_config.name, "minimal")
        self.assertTrue(minimal_config.enabled)
        self.assertEqual(minimal_config.timeout, 30)
        self.assertEqual(minimal_config.retry_count, 3)
        self.assertEqual(minimal_config.retry_delay, 1)
        self.assertEqual(minimal_config.cache_ttl, 3600)
        self.assertIsNone(minimal_config.rate_limits)
    
    def test_rate_limits(self):
        """Test RateLimits configuration."""
        rate_limits = RateLimits(
            requests_per_minute=100,
            requests_per_hour=5000,
            requests_per_day=50000,
            concurrent_requests=20
        )
        
        self.assertEqual(rate_limits.requests_per_minute, 100)
        self.assertEqual(rate_limits.requests_per_hour, 5000)
        self.assertEqual(rate_limits.requests_per_day, 50000)
        self.assertEqual(rate_limits.concurrent_requests, 20)
    
    def test_provider_with_params(self):
        """Test provider config with params attribute."""
        config = ProviderConfig(name="with_params")
        setattr(config, 'params', {'api_key': 'test123'})
        
        self.assertEqual(config.params['api_key'], 'test123')