"""
Test Cache Manager
"""

import time
from django.test import TestCase, override_settings
from unittest.mock import patch, MagicMock

from ..cache import CacheManager, cache_manager, make_cache_key
from ..backends import RedisCache, TieredCache, TaggedCache


class CacheManagerTest(TestCase):
    """Test cache manager functionality."""
    
    def setUp(self):
        """Set up test cache manager."""
        self.cache_manager = CacheManager()
        
    def test_make_cache_key(self):
        """Test cache key generation."""
        # Simple key
        key = make_cache_key('test', 123)
        self.assertEqual(key, 'test:123')
        
        # Complex key with kwargs
        key = make_cache_key('user', 456, role='admin', active=True)
        self.assertIn('user:456', key)
        self.assertIn('active:True', key)
        self.assertIn('role:admin', key)
        
        # Object hashing
        obj = {'complex': 'object'}
        key = make_cache_key('data', obj)
        self.assertIn('data:', key)
        
    def test_basic_operations(self):
        """Test basic cache operations."""
        # Set and get
        result = self.cache_manager.set('test_key', 'test_value', timeout=60)
        self.assertTrue(result)
        
        value = self.cache_manager.get('test_key')
        self.assertEqual(value, 'test_value')
        
        # Delete
        result = self.cache_manager.delete('test_key')
        self.assertTrue(result)
        
        value = self.cache_manager.get('test_key')
        self.assertIsNone(value)
        
    def test_default_values(self):
        """Test default value handling."""
        # Non-existent key with default
        value = self.cache_manager.get('nonexistent', default='default')
        self.assertEqual(value, 'default')
        
        # None value storage
        self.cache_manager.set('none_key', None)
        value = self.cache_manager.get('none_key', default='default')
        # Django cache backends may not store None
        self.assertIn(value, [None, 'default'])
        
    def test_multiple_operations(self):
        """Test multiple key operations."""
        # Set many
        data = {
            'key1': 'value1',
            'key2': 'value2',
            'key3': 'value3',
        }
        result = self.cache_manager.set_many(data)
        self.assertTrue(result)
        
        # Get many
        keys = list(data.keys())
        values = self.cache_manager.get_many(keys)
        self.assertEqual(len(values), 3)
        self.assertEqual(values.get('key1'), 'value1')
        
        # Delete many
        count = self.cache_manager.delete_many(keys)
        self.assertGreater(count, 0)
        
    def test_key_prefix(self):
        """Test key prefix handling."""
        # With prefix
        self.cache_manager.set('test', 'value', prefix='myapp')
        
        # Should include prefix in actual key
        full_key = self.cache_manager.make_key('test', prefix='myapp')
        self.assertTrue(full_key.startswith('myapp:'))
        
    def test_get_or_set(self):
        """Test get_or_set functionality."""
        # Non-existent key with static default
        value = self.cache_manager.get_or_set('new_key', 'default_value')
        self.assertEqual(value, 'default_value')
        
        # Should be cached now
        value = self.cache_manager.get('new_key')
        self.assertEqual(value, 'default_value')
        
        # Existing key
        value = self.cache_manager.get_or_set('new_key', 'other_value')
        self.assertEqual(value, 'default_value')  # Should return cached value
        
        # Callable default
        def expensive_function():
            return 'computed_value'
            
        self.cache_manager.delete('computed_key')
        value = self.cache_manager.get_or_set('computed_key', expensive_function)
        self.assertEqual(value, 'computed_value')
        
    @patch('platform_core.cache.backends.RedisCache')
    def test_backend_selection(self, mock_redis):
        """Test cache backend selection."""
        # Default backend
        cache = self.cache_manager.get_cache('default')
        self.assertIsNotNone(cache)
        
        # Redis backend
        cache = self.cache_manager.get_cache('redis')
        self.assertIsInstance(cache, RedisCache)
        
        # Tiered backend
        cache = self.cache_manager.get_cache('tiered')
        self.assertIsInstance(cache, TieredCache)
        
        # Tagged backend
        cache = self.cache_manager.get_cache('tagged')
        self.assertIsInstance(cache, TaggedCache)
        
        # Unknown backend falls back to default
        cache = self.cache_manager.get_cache('unknown')
        self.assertEqual(cache, self.cache_manager._caches['default'])
        
    def test_error_handling(self):
        """Test error handling in cache operations."""
        # Mock cache backend that raises errors
        with patch.object(self.cache_manager, 'get_cache') as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.get.side_effect = Exception('Cache error')
            mock_get_cache.return_value = mock_cache
            
            # Should return default on error
            value = self.cache_manager.get('error_key', default='safe_default')
            self.assertEqual(value, 'safe_default')
            
            # Set should return False on error
            mock_cache.set.side_effect = Exception('Cache error')
            result = self.cache_manager.set('error_key', 'value')
            self.assertFalse(result)
            
    def test_increment_decrement(self):
        """Test counter operations."""
        # Set initial value
        self.cache_manager.set('counter', 0, backend='redis')
        
        # Increment
        with patch.object(self.cache_manager._caches['redis'], 'increment', return_value=1):
            value = self.cache_manager.increment('counter')
            self.assertEqual(value, 1)
            
        # Decrement
        with patch.object(self.cache_manager._caches['redis'], 'decrement', return_value=0):
            value = self.cache_manager.decrement('counter')
            self.assertEqual(value, 0)
            
    def test_tag_invalidation(self):
        """Test tag-based cache invalidation."""
        # Mock tagged cache
        with patch.object(self.cache_manager._caches['tagged'], 'invalidate_tag', return_value=5):
            count = self.cache_manager.invalidate_tag('user_data')
            self.assertEqual(count, 5)
            
        # Multiple tags
        with patch.object(self.cache_manager._caches['tagged'], 'invalidate_tags', return_value=10):
            count = self.cache_manager.invalidate_tags(['tag1', 'tag2'])
            self.assertEqual(count, 10)
            
    def test_touch(self):
        """Test cache touch (update expiry)."""
        # Set value
        self.cache_manager.set('touch_key', 'value', timeout=60)
        
        # Mock touch method
        with patch.object(self.cache_manager._caches['default'], 'touch', return_value=True) as mock_touch:
            result = self.cache_manager.touch('touch_key', timeout=120)
            
            # For backends without touch, it should get and set
            if not result:
                value = self.cache_manager.get('touch_key')
                self.assertEqual(value, 'value')
                
    @patch('platform_core.cache.backends.RedisCache')
    def test_distributed_lock(self, mock_redis_class):
        """Test distributed locking."""
        # Create mock lock
        mock_lock = MagicMock()
        mock_redis_instance = MagicMock()
        mock_redis_instance.lock.return_value = mock_lock
        mock_redis_class.return_value = mock_redis_instance
        
        # Reinitialize cache manager to use mocked Redis
        self.cache_manager = CacheManager()
        
        # Get lock
        lock = self.cache_manager.lock('resource_key', timeout=10)
        self.assertIsNotNone(lock)
        
        # Verify lock was requested with correct parameters
        mock_redis_instance.lock.assert_called_once()
        
    def test_cache_stats(self):
        """Test cache statistics."""
        # Mock tiered cache with stats
        mock_stats = {
            'l1_hits': 100,
            'l1_misses': 20,
            'l2_hits': 15,
            'l2_misses': 5,
            'l1_hit_rate': 83.3,
            'l2_hit_rate': 75.0,
        }
        
        with patch.object(self.cache_manager._caches['tiered'], 'get_stats', return_value=mock_stats):
            stats = self.cache_manager.get_stats('tiered')
            self.assertEqual(stats['l1_hits'], 100)
            self.assertEqual(stats['l1_hit_rate'], 83.3)