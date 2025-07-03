"""
Session Storage Backend

Redis-based session storage with enhanced features.
"""

import json
import logging
from typing import Dict, Any, Optional
from django.contrib.sessions.backends.base import SessionBase, CreateError
from django.utils import timezone

from .backends import RedisCache

logger = logging.getLogger(__name__)


class RedisSessionStore(SessionBase):
    """
    Redis-based session storage.
    
    Features:
    - Fast Redis storage
    - Session tagging
    - Activity tracking
    - Concurrent access handling
    """
    
    def __init__(self, session_key=None):
        super().__init__(session_key)
        self.cache = RedisCache()
        self._session_cache = None
        
    @property
    def cache_key_prefix(self):
        return 'session'
        
    def _get_session_key(self):
        """Get full cache key for session."""
        return f"{self.cache_key_prefix}:{self.session_key}"
        
    def load(self):
        """Load session data from Redis."""
        try:
            session_data = self.cache.get(self._get_session_key())
            if session_data is None:
                self._session_key = None
                return {}
                
            # Update last activity
            self._update_activity()
            
            return session_data
        except Exception as e:
            logger.error(f"Error loading session {self.session_key}: {e}")
            self._session_key = None
            return {}
            
    def exists(self, session_key):
        """Check if session exists."""
        return self.cache.exists(f"{self.cache_key_prefix}:{session_key}")
        
    def create(self):
        """Create a new session."""
        while True:
            self._session_key = self._get_new_session_key()
            try:
                self.save(must_create=True)
            except CreateError:
                continue
            self.modified = True
            return
            
    def save(self, must_create=False):
        """Save session data to Redis."""
        if self.session_key is None:
            return self.create()
            
        if must_create and self.exists(self.session_key):
            raise CreateError
            
        data = self._get_session(no_load=must_create)
        
        # Add metadata
        session_data = {
            'data': data,
            'created': str(timezone.now()),
            'modified': str(timezone.now()),
            'user_id': data.get('_auth_user_id'),
        }
        
        # Save to Redis with expiry
        success = self.cache.set(
            self._get_session_key(),
            session_data,
            self.get_expiry_age()
        )
        
        if success:
            # Tag session for user-based invalidation
            if session_data['user_id']:
                self._tag_user_session(session_data['user_id'])
        else:
            raise Exception("Failed to save session")
            
    def delete(self, session_key=None):
        """Delete session from Redis."""
        if session_key is None:
            if self.session_key is None:
                return
            session_key = self.session_key
            
        # Get session data first for cleanup
        session_data = self.cache.get(f"{self.cache_key_prefix}:{session_key}")
        
        # Delete session
        self.cache.delete(f"{self.cache_key_prefix}:{session_key}")
        
        # Clean up user session tracking
        if session_data and session_data.get('user_id'):
            self._remove_user_session(session_data['user_id'], session_key)
            
    def clear_expired(self):
        """Clear expired sessions."""
        # Redis handles expiry automatically
        pass
        
    def _update_activity(self):
        """Update session last activity timestamp."""
        activity_key = f"{self.cache_key_prefix}:activity:{self.session_key}"
        self.cache.set(activity_key, str(timezone.now()), 86400)  # 24 hours
        
    def _tag_user_session(self, user_id):
        """Tag session for user tracking."""
        user_sessions_key = f"user:sessions:{user_id}"
        self.cache.sadd(user_sessions_key, self.session_key)
        self.cache.expire(user_sessions_key, 86400 * 30)  # 30 days
        
    def _remove_user_session(self, user_id, session_key):
        """Remove session from user tracking."""
        user_sessions_key = f"user:sessions:{user_id}"
        self.cache.srem(user_sessions_key, session_key)
        
    @classmethod
    def get_user_sessions(cls, user_id):
        """Get all sessions for a user."""
        cache = RedisCache()
        user_sessions_key = f"user:sessions:{user_id}"
        session_keys = cache.smembers(user_sessions_key)
        
        sessions = []
        for session_key in session_keys:
            session_data = cache.get(f"session:{session_key}")
            if session_data:
                sessions.append({
                    'session_key': session_key,
                    'created': session_data.get('created'),
                    'modified': session_data.get('modified'),
                })
                
        return sessions
        
    @classmethod
    def invalidate_user_sessions(cls, user_id):
        """Invalidate all sessions for a user."""
        cache = RedisCache()
        user_sessions_key = f"user:sessions:{user_id}"
        session_keys = cache.smembers(user_sessions_key)
        
        for session_key in session_keys:
            cache.delete(f"session:{session_key}")
            
        cache.delete(user_sessions_key)
        
        logger.info(f"Invalidated {len(session_keys)} sessions for user {user_id}")


class EnhancedSessionStore(RedisSessionStore):
    """
    Enhanced session store with additional features.
    """
    
    def __init__(self, session_key=None):
        super().__init__(session_key)
        self._flash_data = {}
        
    def set_flash(self, key: str, value: Any):
        """
        Set flash message that persists for one request.
        
        Args:
            key: Flash message key
            value: Flash message value
        """
        flash_key = f"_flash_{key}"
        self[flash_key] = value
        self._flash_data[key] = value
        
    def get_flash(self, key: str, default=None) -> Any:
        """
        Get and remove flash message.
        
        Args:
            key: Flash message key
            default: Default value if not found
            
        Returns:
            Flash message value
        """
        flash_key = f"_flash_{key}"
        value = self.pop(flash_key, default)
        if key in self._flash_data:
            del self._flash_data[key]
        return value
        
    def peek_flash(self, key: str, default=None) -> Any:
        """
        Get flash message without removing it.
        
        Args:
            key: Flash message key
            default: Default value if not found
            
        Returns:
            Flash message value
        """
        flash_key = f"_flash_{key}"
        return self.get(flash_key, default)
        
    def has_flash(self, key: str) -> bool:
        """
        Check if flash message exists.
        
        Args:
            key: Flash message key
            
        Returns:
            True if exists
        """
        flash_key = f"_flash_{key}"
        return flash_key in self
        
    def get_device_info(self) -> Dict[str, Any]:
        """Get device information stored in session."""
        return self.get('_device_info', {})
        
    def set_device_info(self, info: Dict[str, Any]):
        """Store device information in session."""
        self['_device_info'] = info
        
    def get_location_info(self) -> Dict[str, Any]:
        """Get location information stored in session."""
        return self.get('_location_info', {})
        
    def set_location_info(self, info: Dict[str, Any]):
        """Store location information in session."""
        self['_location_info'] = info
        
    def track_page_view(self, path: str):
        """Track page view in session."""
        views = self.get('_page_views', [])
        views.append({
            'path': path,
            'timestamp': str(timezone.now())
        })
        
        # Keep only last 50 views
        self['_page_views'] = views[-50:]
        
    def get_page_views(self) -> list:
        """Get tracked page views."""
        return self.get('_page_views', [])
        
    def increment_counter(self, key: str, delta: int = 1) -> int:
        """
        Increment a counter in session.
        
        Args:
            key: Counter key
            delta: Increment value
            
        Returns:
            New counter value
        """
        counter_key = f"_counter_{key}"
        current = self.get(counter_key, 0)
        new_value = current + delta
        self[counter_key] = new_value
        return new_value
        
    def get_counter(self, key: str) -> int:
        """
        Get counter value.
        
        Args:
            key: Counter key
            
        Returns:
            Counter value
        """
        counter_key = f"_counter_{key}"
        return self.get(counter_key, 0)


class SessionManager:
    """
    Session management utilities.
    """
    
    def __init__(self):
        self.cache = RedisCache()
        
    def get_active_sessions_count(self) -> int:
        """Get count of active sessions."""
        # This would require maintaining a set of active sessions
        # For now, return approximate count
        pattern = "session:*"
        # Note: This is expensive in production, consider maintaining counter
        return len(list(self.cache.client.scan_iter(match=pattern)))
        
    def get_user_session_count(self) -> Dict[str, int]:
        """Get session count by user."""
        counts = {}
        
        # Scan for user session sets
        pattern = "user:sessions:*"
        for key in self.cache.client.scan_iter(match=pattern):
            user_id = key.decode().split(':')[-1]
            count = self.cache.client.scard(key)
            counts[user_id] = count
            
        return counts
        
    def cleanup_orphaned_sessions(self) -> int:
        """Clean up orphaned session references."""
        cleaned = 0
        
        # Find user session sets
        pattern = "user:sessions:*"
        for key in self.cache.client.scan_iter(match=pattern):
            user_id = key.decode().split(':')[-1]
            session_keys = self.cache.smembers(key.decode())
            
            # Check each session
            for session_key in session_keys:
                if not self.cache.exists(f"session:{session_key}"):
                    # Remove orphaned reference
                    self.cache.srem(key.decode(), session_key)
                    cleaned += 1
                    
        logger.info(f"Cleaned up {cleaned} orphaned session references")
        return cleaned
        
    def get_session_analytics(self) -> Dict[str, Any]:
        """Get session analytics."""
        analytics = {
            'total_sessions': self.get_active_sessions_count(),
            'users_with_sessions': len(self.get_user_session_count()),
            'average_sessions_per_user': 0,
            'peak_hour_sessions': 0,
            'session_duration_avg': 0,
        }
        
        # Calculate average sessions per user
        user_counts = self.get_user_session_count()
        if user_counts:
            total = sum(user_counts.values())
            analytics['average_sessions_per_user'] = total / len(user_counts)
            
        return analytics


# Global session manager
session_manager = SessionManager()