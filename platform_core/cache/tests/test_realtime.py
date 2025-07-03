"""
Test Real-time Data Structures
"""

import time
from datetime import datetime, timedelta
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock

from ..realtime import (
    Counter, Leaderboard, RateLimiter,
    RealtimeAnalytics, Presence
)


class CounterTest(TestCase):
    """Test distributed counter."""
    
    def setUp(self):
        """Set up test counter."""
        self.counter = Counter('test_counter')
        
    def test_basic_operations(self):
        """Test counter increment and decrement."""
        # Reset counter
        self.counter.reset()
        
        # Increment
        value = self.counter.increment(5)
        self.assertEqual(value, 5)
        
        # Get current value
        value = self.counter.get()
        self.assertEqual(value, 5)
        
        # Decrement
        value = self.counter.decrement(2)
        self.assertEqual(value, 3)
        
        # Reset
        self.counter.reset()
        value = self.counter.get()
        self.assertEqual(value, 0)
        
    def test_windowed_counters(self):
        """Test time-windowed counters."""
        # Hourly counter
        value = self.counter.increment(1, window='hour')
        self.assertGreaterEqual(value, 1)
        
        # Daily counter
        value = self.counter.increment(1, window='day')
        self.assertGreaterEqual(value, 1)
        
        # Monthly counter
        value = self.counter.increment(1, window='month')
        self.assertGreaterEqual(value, 1)
        
    def test_time_series(self):
        """Test time series data retrieval."""
        # Mock time series data
        with patch.object(self.counter.cache, 'get') as mock_get:
            mock_get.return_value = 10
            
            series = self.counter.get_time_series('hour', periods=24)
            
            self.assertEqual(len(series), 24)
            for timestamp, value in series:
                self.assertIsInstance(timestamp, str)
                self.assertEqual(value, 10)
                
    def test_window_key_generation(self):
        """Test window key generation."""
        # Test different windows
        hour_key = self.counter._get_window_key('hour')
        self.assertIn('hour:', hour_key)
        
        day_key = self.counter._get_window_key('day')
        self.assertIn('day:', day_key)
        
        # Invalid window
        with self.assertRaises(ValueError):
            self.counter._get_window_key('invalid')


class LeaderboardTest(TestCase):
    """Test leaderboard functionality."""
    
    def setUp(self):
        """Set up test leaderboard."""
        self.leaderboard = Leaderboard('test_leaderboard')
        self.leaderboard.clear()
        
    def test_score_operations(self):
        """Test score management."""
        # Add scores
        self.leaderboard.add_score('player1', 100)
        self.leaderboard.add_score('player2', 200)
        self.leaderboard.add_score('player3', 150)
        
        # Get scores
        score = self.leaderboard.get_score('player1')
        self.assertEqual(score, 100)
        
        # Increment score
        new_score = self.leaderboard.increment_score('player1', 50)
        self.assertEqual(new_score, 150)
        
    def test_ranking(self):
        """Test ranking functionality."""
        # Setup leaderboard
        self.leaderboard.add_score('player1', 100)
        self.leaderboard.add_score('player2', 200)
        self.leaderboard.add_score('player3', 150)
        
        # Get ranks (descending order)
        rank = self.leaderboard.get_rank('player2')  # Highest score
        self.assertEqual(rank, 1)
        
        rank = self.leaderboard.get_rank('player3')  # Middle score
        self.assertEqual(rank, 2)
        
        rank = self.leaderboard.get_rank('player1')  # Lowest score
        self.assertEqual(rank, 3)
        
    def test_top_members(self):
        """Test getting top members."""
        # Add more players
        for i in range(10):
            self.leaderboard.add_score(f'player{i}', i * 10)
            
        # Get top 3
        top = self.leaderboard.get_top(3, with_scores=True)
        self.assertEqual(len(top), 3)
        
        # Should be in descending order
        self.assertEqual(top[0][0], 'player9')  # Highest score
        self.assertEqual(top[0][1], 90)
        
        # Without scores
        top = self.leaderboard.get_top(3, with_scores=False)
        self.assertEqual(len(top), 3)
        self.assertEqual(top[0], 'player9')
        
    def test_around_member(self):
        """Test getting members around a specific member."""
        # Setup leaderboard
        for i in range(10):
            self.leaderboard.add_score(f'player{i}', i * 10)
            
        # Get around player5 (score 50)
        around = self.leaderboard.get_around('player5', radius=2, with_scores=True)
        
        # Should include players 3-7
        self.assertGreaterEqual(len(around), 5)
        member_names = [m[0] for m in around]
        self.assertIn('player5', member_names)
        
    def test_percentile(self):
        """Test percentile calculation."""
        # Setup leaderboard
        for i in range(100):
            self.leaderboard.add_score(f'player{i}', i)
            
        # Top player should be ~100th percentile
        percentile = self.leaderboard.get_percentile('player99')
        self.assertGreater(percentile, 99)
        
        # Middle player should be ~50th percentile
        percentile = self.leaderboard.get_percentile('player50')
        self.assertAlmostEqual(percentile, 50, delta=1)
        
    def test_leaderboard_management(self):
        """Test leaderboard management operations."""
        # Add members
        self.leaderboard.add_score('player1', 100)
        self.leaderboard.add_score('player2', 200)
        
        # Get size
        size = self.leaderboard.get_size()
        self.assertEqual(size, 2)
        
        # Remove member
        removed = self.leaderboard.remove_member('player1')
        self.assertTrue(removed)
        
        size = self.leaderboard.get_size()
        self.assertEqual(size, 1)
        
        # Clear
        self.leaderboard.clear()
        size = self.leaderboard.get_size()
        self.assertEqual(size, 0)


class RateLimiterTest(TestCase):
    """Test rate limiter."""
    
    def test_basic_rate_limiting(self):
        """Test basic rate limiting."""
        limiter = RateLimiter('test_api', limit=5, window=60)
        
        # First 5 requests should pass
        for i in range(5):
            allowed, info = limiter.check('user1')
            self.assertTrue(allowed)
            self.assertEqual(info['remaining'], 4 - i)
            
        # 6th request should fail
        allowed, info = limiter.check('user1')
        self.assertFalse(allowed)
        self.assertEqual(info['remaining'], 0)
        self.assertIn('retry_after', info)
        
    def test_sliding_window(self):
        """Test sliding window behavior."""
        limiter = RateLimiter('test_sliding', limit=3, window=1)
        
        # Use up limit
        for i in range(3):
            allowed, info = limiter.check('user2')
            self.assertTrue(allowed)
            
        # Should be blocked
        allowed, info = limiter.check('user2')
        self.assertFalse(allowed)
        
        # Wait for window to slide
        time.sleep(1.1)
        
        # Should be allowed again
        allowed, info = limiter.check('user2')
        self.assertTrue(allowed)
        
    def test_different_identifiers(self):
        """Test rate limiting for different identifiers."""
        limiter = RateLimiter('test_multi', limit=2, window=60)
        
        # User 1 requests
        allowed, info = limiter.check('user1')
        self.assertTrue(allowed)
        
        # User 2 requests (separate limit)
        allowed, info = limiter.check('user2')
        self.assertTrue(allowed)
        self.assertEqual(info['remaining'], 1)
        
        # User 1 still has quota
        allowed, info = limiter.check('user1')
        self.assertTrue(allowed)
        self.assertEqual(info['remaining'], 0)
        
    def test_reset(self):
        """Test rate limit reset."""
        limiter = RateLimiter('test_reset', limit=1, window=60)
        
        # Use up limit
        limiter.check('user3')
        allowed, info = limiter.check('user3')
        self.assertFalse(allowed)
        
        # Reset
        limiter.reset('user3')
        
        # Should be allowed again
        allowed, info = limiter.check('user3')
        self.assertTrue(allowed)


class RealtimeAnalyticsTest(TestCase):
    """Test real-time analytics."""
    
    def setUp(self):
        """Set up analytics."""
        self.analytics = RealtimeAnalytics('test')
        
    def test_event_tracking(self):
        """Test event tracking."""
        # Track event
        self.analytics.track_event(
            'page_view',
            properties={'page': '/home'},
            user_id='user1'
        )
        
        # Get event count
        count = self.analytics.get_event_count('page_view', window='day')
        self.assertGreater(count, 0)
        
    def test_unique_counting(self):
        """Test unique user counting."""
        # Track events from different users
        self.analytics.track_event('login', user_id='user1')
        self.analytics.track_event('login', user_id='user2')
        self.analytics.track_event('login', user_id='user1')  # Duplicate
        
        # Get unique count
        unique = self.analytics.get_unique_count('login')
        self.assertEqual(unique, 2)
        
    def test_recent_events(self):
        """Test recent events retrieval."""
        # Track events with properties
        for i in range(5):
            self.analytics.track_event(
                'purchase',
                properties={'amount': i * 10, 'item': f'item{i}'},
                user_id=f'user{i}'
            )
            
        # Get recent events
        recent = self.analytics.get_recent_events('purchase', count=3)
        self.assertEqual(len(recent), 3)
        
        # Should have event data
        event = recent[0]
        self.assertEqual(event['event'], 'purchase')
        self.assertIn('properties', event)
        self.assertIn('timestamp', event)
        
    def test_funnel_analysis(self):
        """Test funnel analysis."""
        # Track funnel events
        users = ['user1', 'user2', 'user3', 'user4', 'user5']
        
        # All users view product
        for user in users:
            self.analytics.track_event('product_view', user_id=user)
            
        # 4 users add to cart
        for user in users[:4]:
            self.analytics.track_event('add_to_cart', user_id=user)
            
        # 2 users purchase
        for user in users[:2]:
            self.analytics.track_event('purchase', user_id=user)
            
        # Get funnel
        funnel = self.analytics.get_funnel([
            'product_view',
            'add_to_cart',
            'purchase'
        ])
        
        self.assertEqual(funnel['product_view'], 5)
        self.assertEqual(funnel['add_to_cart'], 4)
        self.assertEqual(funnel['purchase'], 2)


class PresenceTest(TestCase):
    """Test presence tracking."""
    
    def setUp(self):
        """Set up presence tracker."""
        self.presence = Presence(timeout=5)
        
    def test_presence_tracking(self):
        """Test basic presence tracking."""
        # Set user active
        self.presence.set_active('user1', metadata={'device': 'mobile'})
        
        # Check if active
        self.assertTrue(self.presence.is_active('user1'))
        
        # Get presence data
        data = self.presence.get_presence('user1')
        self.assertIsNotNone(data)
        self.assertTrue(data['active'])
        self.assertEqual(data['device'], 'mobile')
        
        # Set inactive
        self.presence.set_inactive('user1')
        self.assertFalse(self.presence.is_active('user1'))
        
    def test_active_users(self):
        """Test active users listing."""
        # Set multiple users active
        self.presence.set_active('user1')
        self.presence.set_active('user2')
        self.presence.set_active('user3')
        
        # Get active users
        active = self.presence.get_active_users()
        self.assertEqual(len(active), 3)
        self.assertIn('user1', active)
        
        # Get count
        count = self.presence.get_active_count()
        self.assertEqual(count, 3)
        
        # Set one inactive
        self.presence.set_inactive('user2')
        
        active = self.presence.get_active_users()
        self.assertEqual(len(active), 2)
        self.assertNotIn('user2', active)
        
    def test_presence_timeout(self):
        """Test presence timeout."""
        # Use short timeout
        presence = Presence(timeout=1)
        
        # Set active
        presence.set_active('timeout_user')
        self.assertTrue(presence.is_active('timeout_user'))
        
        # Wait for timeout
        time.sleep(1.5)
        
        # Should be inactive
        self.assertFalse(presence.is_active('timeout_user'))