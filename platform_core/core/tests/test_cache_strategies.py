"""
Tests for comprehensive caching strategies.

Tests cache performance, multi-tier caching, cache warming,
and monitoring functionality.
"""

import json
import time
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.core.cache import cache, caches
from django.contrib.auth import get_user_model
from accounts.models import Group
from platform_core.core.cache_strategies import (
    CacheStrategy, ModelCacheStrategy, ViewCacheStrategy,
    SessionCacheStrategy, CacheWarmer, CacheMonitor,
    cache_result, invalidate_cache_on_save
)

User = get_user_model()


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
    'test_cache': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
})
class CacheStrategyTest(TestCase):
    """
    Test cases for base CacheStrategy functionality.
    """
    
    def setUp(self):
        cache.clear()
        self.strategy = CacheStrategy()
    
    def test_generate_key(self):
        """
        Test cache key generation.
        """
        # Simple key
        key = self.strategy.generate_key('test', id=123)
        self.assertIn('test', key)
        self.assertIn('id:123', key)
        
        # Complex key with dict
        key = self.strategy.generate_key('complex', data={'a': 1, 'b': 2})
        self.assertIn('complex', key)
        self.assertIn('data:', key)
        
        # Long key should be hashed
        long_key = self.strategy.generate_key('very_long_prefix' * 20, param='value' * 50)
        self.assertTrue(len(long_key) <= 200)
    
    def test_get_or_set(self):
        """
        Test get_or_set functionality.
        """
        call_count = 0
        
        def expensive_function():
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"
        
        # First call should execute function
        result1 = self.strategy.get_or_set('test_key', expensive_function, 300)
        self.assertEqual(result1, 'result_1')
        self.assertEqual(call_count, 1)
        
        # Second call should use cache
        result2 = self.strategy.get_or_set('test_key', expensive_function, 300)
        self.assertEqual(result2, 'result_1')
        self.assertEqual(call_count, 1)  # Function not called again
    
    @patch('core.cache_strategies.CacheStrategy._get_redis_client')
    def test_invalidate_pattern(self, mock_redis_client):
        """
        Test pattern-based cache invalidation.
        """
        mock_redis = MagicMock()
        mock_redis.keys.return_value = ['key1', 'key2', 'key3']
        mock_redis.delete.return_value = 3
        mock_redis_client.return_value = mock_redis
        
        strategy = CacheStrategy()
        count = strategy.invalidate_pattern('test:*')
        
        self.assertEqual(count, 3)
        mock_redis.keys.assert_called_once_with('test:*')
        mock_redis.delete.assert_called_once_with('key1', 'key2', 'key3')


class ModelCacheStrategyTest(TestCase):
    """
    Test cases for ModelCacheStrategy.
    """
    
    def setUp(self):
        cache.clear()
        self.group = Group.objects.create(name='Test Group')
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.strategy = ModelCacheStrategy(User)
    
    def test_cache_model_instance(self):
        """
        Test caching model instances.
        """
        cache_key = self.strategy.cache_model_instance(self.user)
        
        # Verify key format
        self.assertIn('model:user', cache_key)
        self.assertIn(str(self.user.id), cache_key)
        
        # Verify cached data
        cached_data = self.strategy.get_cached_instance(self.user.id)
        self.assertIsNotNone(cached_data)
        self.assertEqual(cached_data['email'], self.user.email)
        self.assertIn('_cached_at', cached_data)
    
    def test_cache_queryset(self):
        """
        Test caching queryset results.
        """
        # Create additional users
        User.objects.create_user(username='user2', email='user2@example.com', password='pass')
        User.objects.create_user(username='user3', email='user3@example.com', password='pass')
        
        queryset = User.objects.all()
        cache_key = self.strategy.cache_queryset(queryset, 'all_users')
        
        # Verify cached data
        cached_data = cache.get('all_users')
        self.assertIsNotNone(cached_data)
        self.assertEqual(len(cached_data), 3)
    
    def test_invalidate_model_cache(self):
        """
        Test model cache invalidation.
        """
        # Cache the instance
        self.strategy.cache_model_instance(self.user)
        
        # Verify it's cached
        cached_data = self.strategy.get_cached_instance(self.user.id)
        self.assertIsNotNone(cached_data)
        
        # Invalidate cache
        self.strategy.invalidate_model_cache(self.user.id)
        
        # Verify it's removed
        cached_data = self.strategy.get_cached_instance(self.user.id)
        self.assertIsNone(cached_data)


class ViewCacheStrategyTest(TestCase):
    """
    Test cases for ViewCacheStrategy.
    """
    
    def setUp(self):
        cache.clear()
        self.strategy = ViewCacheStrategy()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.group = Group.objects.create(name='Test Group')
    
    def test_cache_view_response(self):
        """
        Test caching view responses.
        """
        response_data = {'result': 'success', 'data': [1, 2, 3]}
        
        cache_key = self.strategy.cache_view_response(
            'test_view',
            response_data,
            user_id=str(self.user.id),
            group_id=str(self.group.id)
        )
        
        # Verify key format
        self.assertIn('view_response', cache_key)
        
        # Verify cached data
        cached_response = self.strategy.get_cached_view_response(
            'test_view',
            user_id=str(self.user.id),
            group_id=str(self.group.id)
        )
        
        self.assertEqual(cached_response, response_data)
    
    def test_cache_view_response_with_params(self):
        """
        Test caching view responses with parameters.
        """
        response_data = {'filtered': True}
        params = {'status': 'active', 'limit': 10}
        
        self.strategy.cache_view_response(
            'filtered_view',
            response_data,
            params=params
        )
        
        # Should find with same params
        cached_response = self.strategy.get_cached_view_response(
            'filtered_view',
            params=params
        )
        self.assertEqual(cached_response, response_data)
        
        # Should not find with different params
        cached_response = self.strategy.get_cached_view_response(
            'filtered_view',
            params={'status': 'inactive', 'limit': 10}
        )
        self.assertIsNone(cached_response)
    
    @patch('core.cache_strategies.ViewCacheStrategy.invalidate_pattern')
    def test_invalidate_view_cache(self, mock_invalidate):
        """
        Test view cache invalidation.
        """
        mock_invalidate.return_value = 5
        
        # Invalidate by view name
        count = self.strategy.invalidate_view_cache(view_name='test_view')
        self.assertEqual(count, 5)
        mock_invalidate.assert_called_with('*view_response*view:test_view*')
        
        # Invalidate by user
        self.strategy.invalidate_view_cache(user_id=str(self.user.id))
        mock_invalidate.assert_called_with(f'*view_response*user:{self.user.id}*')


class SessionCacheStrategyTest(TestCase):
    """
    Test cases for SessionCacheStrategy.
    """
    
    def setUp(self):
        cache.clear()
        self.strategy = SessionCacheStrategy()
    
    def test_session_data_operations(self):
        """
        Test session data storage and retrieval.
        """
        session_key = 'test_session_123'
        test_data = {'user_preferences': {'theme': 'dark'}, 'temp_data': [1, 2, 3]}
        
        # Store session data
        cache_key = self.strategy.set_session_data(session_key, test_data)
        self.assertIn('session', cache_key)
        
        # Retrieve session data
        retrieved_data = self.strategy.get_session_data(session_key)
        self.assertEqual(retrieved_data, test_data)
        
        # Invalidate session
        self.strategy.invalidate_session(session_key)
        
        # Verify data is removed
        retrieved_data = self.strategy.get_session_data(session_key)
        self.assertIsNone(retrieved_data)


class CacheWarmerTest(TestCase):
    """
    Test cases for CacheWarmer.
    """
    
    def setUp(self):
        cache.clear()
        self.warmer = CacheWarmer()
        
        # Create test data
        self.group = Group.objects.create(name='Test Group')
        for i in range(5):
            User.objects.create_user(
                username=f'user{i}',
                email=f'user{i}@example.com',
                password='testpass123'
            )
    
    def test_warm_model_cache(self):
        """
        Test warming model cache.
        """
        # Warm cache for all users
        cached_count = self.warmer.warm_model_cache(User)
        self.assertEqual(cached_count, 5)
        
        # Verify instances are cached
        strategy = ModelCacheStrategy(User)
        for user in User.objects.all():
            cached_data = strategy.get_cached_instance(user.id)
            self.assertIsNotNone(cached_data)
            self.assertEqual(cached_data['email'], user.email)
    
    def test_warm_model_cache_limited(self):
        """
        Test warming model cache with limited queryset.
        """
        # Warm only first 3 users
        limited_queryset = User.objects.all()[:3]
        cached_count = self.warmer.warm_model_cache(User, limited_queryset)
        self.assertEqual(cached_count, 3)


class CacheMonitorTest(TestCase):
    """
    Test cases for CacheMonitor.
    """
    
    def setUp(self):
        cache.clear()
        self.monitor = CacheMonitor()
    
    def test_get_cache_stats(self):
        """
        Test getting cache statistics.
        """
        stats = self.monitor.get_cache_stats()
        
        self.assertIn('timestamp', stats)
        self.assertIn('backend', stats)
        self.assertIsInstance(stats['timestamp'], str)
    
    @patch('core.cache_strategies.CacheMonitor._get_redis_client')
    def test_get_key_count_by_pattern(self, mock_redis_client):
        """
        Test getting key count by pattern.
        """
        mock_redis = MagicMock()
        mock_redis.keys.return_value = ['key1', 'key2', 'key3']
        mock_redis_client.return_value = mock_redis
        
        monitor = CacheMonitor()
        count = monitor.get_key_count_by_pattern('test:*')
        
        self.assertEqual(count, 3)
        mock_redis.keys.assert_called_once_with('test:*')


class CacheDecoratorsTest(TestCase):
    """
    Test cases for cache decorators.
    """
    
    def setUp(self):
        cache.clear()
    
    def test_cache_result_decorator(self):
        """
        Test cache_result decorator.
        """
        call_count = 0
        
        @cache_result(timeout=300, key_prefix='test_func', vary_on=['arg1'])
        def expensive_function(arg1, arg2=None):
            nonlocal call_count
            call_count += 1
            return f"result_{arg1}_{call_count}"
        
        # First call
        result1 = expensive_function('value1', arg2='ignored')
        self.assertEqual(result1, 'result_value1_1')
        self.assertEqual(call_count, 1)
        
        # Second call with same arg1 should use cache
        result2 = expensive_function('value1', arg2='different')
        self.assertEqual(result2, 'result_value1_1')
        self.assertEqual(call_count, 1)
        
        # Call with different arg1 should execute function
        result3 = expensive_function('value2')
        self.assertEqual(result3, 'result_value2_2')
        self.assertEqual(call_count, 2)
    
    @patch('core.cache_strategies.CacheStrategy.invalidate_pattern')
    def test_invalidate_cache_on_save_decorator(self, mock_invalidate):
        """
        Test invalidate_cache_on_save decorator.
        """
        mock_invalidate.return_value = 3
        
        @invalidate_cache_on_save(User, ['user:*', 'view:*'])
        def update_user_function():
            return 'updated'
        
        result = update_user_function()
        self.assertEqual(result, 'updated')
        
        # Verify invalidation was called for each pattern
        self.assertEqual(mock_invalidate.call_count, 2)


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
})
class CacheIntegrationTest(TestCase):
    """
    Integration tests for cache strategies working together.
    """
    
    def setUp(self):
        cache.clear()
        self.group = Group.objects.create(name='Test Group')
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.groups.add(self.group)
    
    def test_full_cache_workflow(self):
        """
        Test complete cache workflow with multiple strategies.
        """
        # 1. Warm model cache
        warmer = CacheWarmer()
        cached_count = warmer.warm_model_cache(User)
        self.assertEqual(cached_count, 1)
        
        # 2. Cache view response
        view_strategy = ViewCacheStrategy()
        response_data = {'users': [{'id': self.user.id, 'email': self.user.email}]}
        view_strategy.cache_view_response(
            'user_list',
            response_data,
            group_id=str(self.group.id)
        )
        
        # 3. Verify both caches work
        model_strategy = ModelCacheStrategy(User)
        cached_user = model_strategy.get_cached_instance(self.user.id)
        self.assertIsNotNone(cached_user)
        
        cached_view = view_strategy.get_cached_view_response(
            'user_list',
            group_id=str(self.group.id)
        )
        self.assertEqual(cached_view, response_data)
        
        # 4. Test cache invalidation affects both
        model_strategy.invalidate_model_cache(self.user.id)
        view_strategy.invalidate_view_cache(group_id=str(self.group.id))
        
        # 5. Verify caches are cleared
        cached_user = model_strategy.get_cached_instance(self.user.id)
        self.assertIsNone(cached_user)
        
        cached_view = view_strategy.get_cached_view_response(
            'user_list',
            group_id=str(self.group.id)
        )
        self.assertIsNone(cached_view)
    
    def test_cache_performance_monitoring(self):
        """
        Test cache performance monitoring.
        """
        # Add some cache entries
        cache.set('test_key_1', 'value1', 300)
        cache.set('test_key_2', 'value2', 300)
        cache.set('test_key_3', 'value3', 300)
        
        # Get cache statistics
        monitor = CacheMonitor()
        stats = monitor.get_cache_stats()
        
        # Basic stats should be available
        self.assertIn('timestamp', stats)
        self.assertIn('backend', stats)
        
        # Test hit/miss tracking
        cache.get('test_key_1')  # Hit
        cache.get('nonexistent_key')  # Miss
        
        # Stats should reflect activity
        new_stats = monitor.get_cache_stats()
        self.assertIn('timestamp', new_stats)