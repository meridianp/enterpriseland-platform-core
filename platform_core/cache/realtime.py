"""
Real-time Data Structures

Redis-backed real-time data structures for counters, leaderboards, etc.
"""

import json
import time
import logging
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone

from .backends import RedisCache

logger = logging.getLogger(__name__)


class Counter:
    """
    Distributed counter with time-based windows.
    """
    
    def __init__(self, name: str, cache: Optional[RedisCache] = None):
        """Initialize counter."""
        self.name = name
        self.cache = cache or RedisCache()
        self.prefix = f"counter:{name}"
        
    def increment(self, delta: int = 1, window: Optional[str] = None) -> int:
        """
        Increment counter.
        
        Args:
            delta: Increment value
            window: Time window (e.g., 'hour', 'day', 'month')
            
        Returns:
            New counter value
        """
        if window:
            key = self._get_window_key(window)
            # Set expiry for windowed counters
            expiry = self._get_window_expiry(window)
        else:
            key = self.prefix
            expiry = None
            
        value = self.cache.increment(key, delta)
        
        if expiry:
            self.cache.expire(key, expiry)
            
        return value
        
    def decrement(self, delta: int = 1, window: Optional[str] = None) -> int:
        """Decrement counter."""
        if window:
            key = self._get_window_key(window)
        else:
            key = self.prefix
            
        return self.cache.decrement(key, delta)
        
    def get(self, window: Optional[str] = None) -> int:
        """Get counter value."""
        if window:
            key = self._get_window_key(window)
        else:
            key = self.prefix
            
        value = self.cache.get(key)
        return int(value) if value is not None else 0
        
    def reset(self, window: Optional[str] = None) -> bool:
        """Reset counter to zero."""
        if window:
            key = self._get_window_key(window)
        else:
            key = self.prefix
            
        return self.cache.delete(key)
        
    def get_time_series(
        self,
        window: str,
        periods: int = 24
    ) -> List[Tuple[str, int]]:
        """
        Get time series data.
        
        Args:
            window: Time window ('hour', 'day', 'month')
            periods: Number of periods to retrieve
            
        Returns:
            List of (timestamp, value) tuples
        """
        series = []
        now = timezone.now()
        
        for i in range(periods):
            if window == 'hour':
                timestamp = now - timedelta(hours=i)
                key_suffix = timestamp.strftime('%Y%m%d%H')
            elif window == 'day':
                timestamp = now - timedelta(days=i)
                key_suffix = timestamp.strftime('%Y%m%d')
            elif window == 'month':
                timestamp = now - timedelta(days=30*i)
                key_suffix = timestamp.strftime('%Y%m')
            else:
                raise ValueError(f"Unknown window: {window}")
                
            key = f"{self.prefix}:{window}:{key_suffix}"
            value = self.cache.get(key) or 0
            
            series.append((timestamp.isoformat(), int(value)))
            
        return list(reversed(series))
        
    def _get_window_key(self, window: str) -> str:
        """Get key for time window."""
        now = timezone.now()
        
        if window == 'hour':
            suffix = now.strftime('%Y%m%d%H')
        elif window == 'day':
            suffix = now.strftime('%Y%m%d')
        elif window == 'month':
            suffix = now.strftime('%Y%m')
        elif window == 'year':
            suffix = now.strftime('%Y')
        else:
            raise ValueError(f"Unknown window: {window}")
            
        return f"{self.prefix}:{window}:{suffix}"
        
    def _get_window_expiry(self, window: str) -> int:
        """Get expiry time for window in seconds."""
        expiry_map = {
            'hour': 3600 * 25,      # Keep for 25 hours
            'day': 86400 * 32,      # Keep for 32 days
            'month': 86400 * 366,   # Keep for 1 year
            'year': 86400 * 366 * 2,  # Keep for 2 years
        }
        return expiry_map.get(window, 86400)


class Leaderboard:
    """
    Redis-backed leaderboard with scoring.
    """
    
    def __init__(self, name: str, cache: Optional[RedisCache] = None):
        """Initialize leaderboard."""
        self.name = name
        self.cache = cache or RedisCache()
        self.key = f"leaderboard:{name}"
        
    def add_score(self, member: str, score: float) -> float:
        """
        Add or update member score.
        
        Args:
            member: Member identifier
            score: Score value
            
        Returns:
            New score
        """
        self.cache.client.zadd(self.key, {member: score})
        return score
        
    def increment_score(self, member: str, delta: float = 1.0) -> float:
        """
        Increment member score.
        
        Args:
            member: Member identifier
            delta: Score increment
            
        Returns:
            New score
        """
        return self.cache.client.zincrby(self.key, delta, member)
        
    def get_score(self, member: str) -> Optional[float]:
        """Get member score."""
        score = self.cache.client.zscore(self.key, member)
        return float(score) if score is not None else None
        
    def get_rank(self, member: str, reverse: bool = True) -> Optional[int]:
        """
        Get member rank (1-based).
        
        Args:
            member: Member identifier
            reverse: True for descending order (highest score = rank 1)
            
        Returns:
            Rank or None if not found
        """
        if reverse:
            rank = self.cache.client.zrevrank(self.key, member)
        else:
            rank = self.cache.client.zrank(self.key, member)
            
        return rank + 1 if rank is not None else None
        
    def get_top(
        self,
        count: int = 10,
        with_scores: bool = True,
        offset: int = 0
    ) -> List[Union[str, Tuple[str, float]]]:
        """
        Get top members.
        
        Args:
            count: Number of members to retrieve
            with_scores: Include scores in result
            offset: Starting offset
            
        Returns:
            List of members or (member, score) tuples
        """
        results = self.cache.client.zrevrange(
            self.key,
            offset,
            offset + count - 1,
            withscores=with_scores
        )
        
        if with_scores:
            return [(m.decode() if isinstance(m, bytes) else m, s) 
                    for m, s in results]
        else:
            return [m.decode() if isinstance(m, bytes) else m 
                    for m in results]
            
    def get_around(
        self,
        member: str,
        radius: int = 5,
        with_scores: bool = True
    ) -> List[Union[str, Tuple[str, float]]]:
        """
        Get members around a specific member.
        
        Args:
            member: Center member
            radius: Number of members above and below
            with_scores: Include scores
            
        Returns:
            List of members around the specified member
        """
        rank = self.cache.client.zrevrank(self.key, member)
        if rank is None:
            return []
            
        start = max(0, rank - radius)
        end = rank + radius
        
        results = self.cache.client.zrevrange(
            self.key,
            start,
            end,
            withscores=with_scores
        )
        
        if with_scores:
            return [(m.decode() if isinstance(m, bytes) else m, s) 
                    for m, s in results]
        else:
            return [m.decode() if isinstance(m, bytes) else m 
                    for m in results]
            
    def remove_member(self, member: str) -> bool:
        """Remove member from leaderboard."""
        return bool(self.cache.client.zrem(self.key, member))
        
    def get_size(self) -> int:
        """Get total number of members."""
        return self.cache.client.zcard(self.key)
        
    def clear(self) -> bool:
        """Clear entire leaderboard."""
        return self.cache.delete(self.key)
        
    def get_percentile(self, member: str) -> Optional[float]:
        """
        Get member percentile (0-100).
        
        Args:
            member: Member identifier
            
        Returns:
            Percentile or None if not found
        """
        rank = self.get_rank(member)
        if rank is None:
            return None
            
        size = self.get_size()
        if size == 0:
            return None
            
        return ((size - rank + 1) / size) * 100


class RateLimiter:
    """
    Redis-backed rate limiter.
    """
    
    def __init__(
        self,
        name: str,
        limit: int,
        window: int,
        cache: Optional[RedisCache] = None
    ):
        """
        Initialize rate limiter.
        
        Args:
            name: Limiter name
            limit: Maximum requests allowed
            window: Time window in seconds
            cache: Redis cache instance
        """
        self.name = name
        self.limit = limit
        self.window = window
        self.cache = cache or RedisCache()
        
    def check(self, identifier: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if request is allowed.
        
        Args:
            identifier: Request identifier (e.g., user ID, IP)
            
        Returns:
            Tuple of (allowed, info dict)
        """
        key = f"ratelimit:{self.name}:{identifier}"
        
        # Use sliding window with Redis sorted sets
        now = time.time()
        window_start = now - self.window
        
        # Remove old entries
        self.cache.client.zremrangebyscore(key, 0, window_start)
        
        # Count current entries
        current_count = self.cache.client.zcard(key)
        
        info = {
            'limit': self.limit,
            'remaining': max(0, self.limit - current_count),
            'reset': int(now + self.window),
            'window': self.window
        }
        
        if current_count < self.limit:
            # Add new entry
            self.cache.client.zadd(key, {str(now): now})
            self.cache.expire(key, self.window)
            return True, info
        else:
            # Get oldest entry to calculate retry time
            oldest = self.cache.client.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_time = oldest[0][1]
                info['retry_after'] = int(oldest_time + self.window - now)
                
            return False, info
            
    def reset(self, identifier: str) -> bool:
        """Reset rate limit for identifier."""
        key = f"ratelimit:{self.name}:{identifier}"
        return self.cache.delete(key)


class RealtimeAnalytics:
    """
    Real-time analytics tracking.
    """
    
    def __init__(self, namespace: str = 'analytics'):
        """Initialize analytics."""
        self.namespace = namespace
        self.cache = RedisCache()
        
    def track_event(
        self,
        event: str,
        properties: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ):
        """
        Track analytics event.
        
        Args:
            event: Event name
            properties: Event properties
            user_id: User identifier
            timestamp: Event timestamp
        """
        timestamp = timestamp or timezone.now()
        
        # Increment event counter
        counter = Counter(f"{self.namespace}:events:{event}", self.cache)
        counter.increment(window='hour')
        counter.increment(window='day')
        counter.increment(window='month')
        
        # Track unique users
        if user_id:
            day_key = timestamp.strftime('%Y%m%d')
            unique_key = f"{self.namespace}:unique:{event}:{day_key}"
            self.cache.sadd(unique_key, user_id)
            self.cache.expire(unique_key, 86400 * 32)  # Keep for 32 days
            
        # Store event details (optional, for recent events)
        if properties:
            event_data = {
                'event': event,
                'properties': properties,
                'user_id': user_id,
                'timestamp': timestamp.isoformat()
            }
            
            # Store in a list (keep last 1000 events)
            list_key = f"{self.namespace}:recent:{event}"
            self.cache.lpush(list_key, json.dumps(event_data))
            self.cache.client.ltrim(list_key, 0, 999)
            self.cache.expire(list_key, 86400)  # Keep for 1 day
            
    def get_event_count(
        self,
        event: str,
        window: str = 'day'
    ) -> int:
        """Get event count for window."""
        counter = Counter(f"{self.namespace}:events:{event}", self.cache)
        return counter.get(window)
        
    def get_unique_count(
        self,
        event: str,
        date: Optional[datetime] = None
    ) -> int:
        """Get unique user count for event."""
        date = date or timezone.now()
        day_key = date.strftime('%Y%m%d')
        unique_key = f"{self.namespace}:unique:{event}:{day_key}"
        
        return self.cache.client.scard(unique_key)
        
    def get_recent_events(
        self,
        event: str,
        count: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent events."""
        list_key = f"{self.namespace}:recent:{event}"
        events = self.cache.lrange(list_key, 0, count - 1)
        
        return [json.loads(e) for e in events]
        
    def get_funnel(
        self,
        events: List[str],
        date: Optional[datetime] = None
    ) -> Dict[str, int]:
        """
        Get funnel statistics for event sequence.
        
        Args:
            events: Ordered list of events
            date: Date to analyze
            
        Returns:
            Dict with event counts
        """
        date = date or timezone.now()
        funnel = {}
        
        for event in events:
            count = self.get_unique_count(event, date)
            funnel[event] = count
            
        return funnel


class Presence:
    """
    User presence tracking.
    """
    
    def __init__(self, timeout: int = 300):
        """
        Initialize presence tracker.
        
        Args:
            timeout: Presence timeout in seconds (default 5 minutes)
        """
        self.timeout = timeout
        self.cache = RedisCache()
        self.key_prefix = "presence"
        
    def set_active(
        self,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Mark user as active.
        
        Args:
            user_id: User identifier
            metadata: Additional metadata (location, device, etc.)
        """
        key = f"{self.key_prefix}:{user_id}"
        
        data = {
            'last_seen': timezone.now().isoformat(),
            'active': True
        }
        
        if metadata:
            data.update(metadata)
            
        self.cache.set(key, data, self.timeout)
        
        # Add to active users set
        active_key = f"{self.key_prefix}:active"
        self.cache.sadd(active_key, user_id)
        
    def set_inactive(self, user_id: str):
        """Mark user as inactive."""
        key = f"{self.key_prefix}:{user_id}"
        
        # Update presence data
        data = self.cache.get(key) or {}
        data['active'] = False
        data['last_seen'] = timezone.now().isoformat()
        
        self.cache.set(key, data, 86400)  # Keep for 1 day
        
        # Remove from active set
        active_key = f"{self.key_prefix}:active"
        self.cache.srem(active_key, user_id)
        
    def is_active(self, user_id: str) -> bool:
        """Check if user is active."""
        key = f"{self.key_prefix}:{user_id}"
        data = self.cache.get(key)
        
        return data.get('active', False) if data else False
        
    def get_presence(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user presence data."""
        key = f"{self.key_prefix}:{user_id}"
        return self.cache.get(key)
        
    def get_active_users(self) -> List[str]:
        """Get list of active users."""
        active_key = f"{self.key_prefix}:active"
        
        # Clean up expired users
        users = list(self.cache.smembers(active_key))
        active_users = []
        
        for user_id in users:
            if self.is_active(user_id):
                active_users.append(user_id)
            else:
                # Remove from active set
                self.cache.srem(active_key, user_id)
                
        return active_users
        
    def get_active_count(self) -> int:
        """Get count of active users."""
        return len(self.get_active_users())