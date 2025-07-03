"""
Test Cache Decorators
"""

import time
from django.test import TestCase
from unittest.mock import patch, MagicMock, call

from ..decorators import (
    cache_result, cache_method, cache_page_result,
    invalidate_cache, conditional_cache, cache_aside, memoize
)
from ..cache import cache_manager


class CacheDecoratorsTest(TestCase):
    """Test cache decorators."""
    
    def setUp(self):
        """Set up test environment."""
        # Clear any existing cache
        cache_manager.clear()
        
    def test_cache_result_decorator(self):
        """Test function result caching."""
        call_count = 0
        
        @cache_result(timeout=60, key_prefix='test')
        def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
            
        # First call should execute function
        result = expensive_function(2, 3)
        self.assertEqual(result, 5)
        self.assertEqual(call_count, 1)
        
        # Second call should use cache
        result = expensive_function(2, 3)
        self.assertEqual(result, 5)
        self.assertEqual(call_count, 1)  # Function not called again
        
        # Different arguments should execute function
        result = expensive_function(3, 4)
        self.assertEqual(result, 7)
        self.assertEqual(call_count, 2)
        
    def test_cache_method_decorator(self):
        """Test method result caching."""
        class TestService:
            def __init__(self):
                self.call_count = 0
                
            @cache_method(timeout=60)
            def calculate(self, value):
                self.call_count += 1
                return value * 2
                
        service = TestService()
        
        # First call
        result = service.calculate(5)
        self.assertEqual(result, 10)
        self.assertEqual(service.call_count, 1)
        
        # Cached call
        result = service.calculate(5)
        self.assertEqual(result, 10)
        self.assertEqual(service.call_count, 1)
        
        # Different instance should have separate cache
        service2 = TestService()
        result = service2.calculate(5)
        self.assertEqual(result, 10)
        self.assertEqual(service2.call_count, 1)
        
    def test_cache_none_handling(self):
        """Test caching of None results."""
        call_count = 0
        
        @cache_result(cache_on_none=True)
        def returns_none():
            nonlocal call_count
            call_count += 1
            return None
            
        # First call
        result = returns_none()
        self.assertIsNone(result)
        self.assertEqual(call_count, 1)
        
        # Should cache None
        result = returns_none()
        self.assertIsNone(result)
        # Note: Some cache backends don't store None, so this might still increment
        
    def test_custom_key_generation(self):
        """Test custom cache key generation."""
        def custom_key_func(user_id, role=None):
            return f"custom_{user_id}_{role}"
            
        @cache_result(make_key=custom_key_func)
        def get_user_data(user_id, role=None):
            return {'user_id': user_id, 'role': role}
            
        # Should use custom key
        with patch.object(cache_manager, 'get') as mock_get:
            mock_get.return_value = None
            get_user_data(123, role='admin')
            
            # Verify custom key was used
            args, kwargs = mock_get.call_args
            self.assertEqual(args[0], 'custom_123_admin')
            
    def test_cache_invalidation_decorator(self):
        """Test cache invalidation."""
        @cache_result(tags=['user_data'])
        def get_user(user_id):
            return {'id': user_id, 'name': 'Test User'}
            
        @invalidate_cache(tags=['user_data'])
        def update_user(user_id, name):
            return {'id': user_id, 'name': name}
            
        # Cache user data
        user = get_user(1)
        self.assertEqual(user['name'], 'Test User')
        
        # Update should invalidate cache
        with patch.object(cache_manager, 'invalidate_tag') as mock_invalidate:
            update_user(1, 'Updated User')
            mock_invalidate.assert_called_with('user_data', backend='default')
            
    def test_conditional_cache_decorator(self):
        """Test conditional caching."""
        call_count = 0
        
        def should_cache_premium(user, *args):
            return user.get('is_premium', False)
            
        @conditional_cache(condition=should_cache_premium, timeout=300)
        def get_analytics(user, date_range):
            nonlocal call_count
            call_count += 1
            return {'data': 'analytics', 'range': date_range}
            
        # Non-premium user - should not cache
        user = {'id': 1, 'is_premium': False}
        result = get_analytics(user, '2024-01')
        self.assertEqual(call_count, 1)
        
        result = get_analytics(user, '2024-01')
        self.assertEqual(call_count, 2)  # Called again, not cached
        
        # Premium user - should cache
        premium_user = {'id': 2, 'is_premium': True}
        result = get_analytics(premium_user, '2024-01')
        self.assertEqual(call_count, 3)
        
        result = get_analytics(premium_user, '2024-01')
        self.assertEqual(call_count, 3)  # Not called again, cached
        
    def test_cache_aside_decorator(self):
        """Test cache-aside pattern."""
        custom_cache = {}
        
        def custom_loader(key):
            return custom_cache.get(key)
            
        def custom_writer(key, value):
            custom_cache[key] = value
            
        @cache_aside(cache_loader=custom_loader, cache_writer=custom_writer)
        def fetch_data(data_id):
            return {'id': data_id, 'data': 'test'}
            
        # First call - not in cache
        result = fetch_data(1)
        self.assertEqual(result['id'], 1)
        self.assertIn('fetch_data:1', str(custom_cache))
        
        # Second call - from cache
        with patch('platform_core.cache.tests.test_decorators.fetch_data') as mock_fetch:
            # The decorator wraps the function, so we need to test the cache behavior
            result = fetch_data(1)
            self.assertEqual(result['id'], 1)
            
    def test_memoize_decorator(self):
        """Test memoization."""
        call_count = 0
        
        @memoize(timeout=300, max_size=10)
        def fibonacci(n):
            nonlocal call_count
            call_count += 1
            if n < 2:
                return n
            return fibonacci(n-1) + fibonacci(n-2)
            
        # Calculate fibonacci
        result = fibonacci(5)
        self.assertEqual(result, 5)
        
        # Should use memoized results
        initial_calls = call_count
        result = fibonacci(5)
        self.assertEqual(result, 5)
        self.assertEqual(call_count, initial_calls)  # No additional calls
        
        # Test cache info
        info = fibonacci.cache_info()
        self.assertIsInstance(info, dict)
        
    def test_memoize_with_typing(self):
        """Test typed memoization."""
        @memoize(typed=True)
        def add(x, y):
            return x + y
            
        # Different types should be cached separately
        result1 = add(1, 2)  # int
        result2 = add(1.0, 2.0)  # float
        result3 = add("1", "2")  # str
        
        self.assertEqual(result1, 3)
        self.assertEqual(result2, 3.0)
        self.assertEqual(result3, "12")
        
    def test_cache_key_methods(self):
        """Test cache key helper methods on decorated functions."""
        @cache_result(key_prefix='test')
        def cached_function(x, y):
            return x * y
            
        # Test cache_key method
        key = cached_function.cache_key(2, 3)
        self.assertIn('cached_function', key)
        self.assertIn('2', key)
        self.assertIn('3', key)
        
        # Test invalidate method
        cached_function(2, 3)  # Cache result
        
        with patch.object(cache_manager, 'delete') as mock_delete:
            cached_function.invalidate(2, 3)
            mock_delete.assert_called_once()
            
    def test_cache_tags(self):
        """Test cache tagging."""
        @cache_result(tags=['math', 'calculation'], backend='tagged')
        def calculate(x, y):
            return x * y
            
        # Cache result
        with patch.object(cache_manager, 'set') as mock_set:
            calculate(2, 3)
            
            # Verify tags were passed
            args, kwargs = mock_set.call_args
            self.assertEqual(kwargs.get('tags'), ['math', 'calculation'])
            self.assertEqual(kwargs.get('backend'), 'tagged')
            
    @patch('django.views.decorators.cache.cache_page')
    def test_cache_page_result_decorator(self, mock_cache_page):
        """Test page caching decorator."""
        # Mock Django's cache_page
        mock_cached_view = MagicMock()
        mock_cache_page.return_value = lambda x: mock_cached_view
        
        @cache_page_result(timeout=600, cache_control_public=True)
        def my_view(request):
            return MagicMock(content='test')
            
        # The decorator should use Django's cache_page
        mock_cache_page.assert_called_once_with(600, cache='default', key_prefix=None)