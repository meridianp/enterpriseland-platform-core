"""
Rate Limiting Backends

Different backend implementations for rate limiting.
"""

import time
import json
from typing import Tuple, Optional, Dict, Any
from django.core.cache import cache
from django.conf import settings
import redis


class RateLimitBackend:
    """Base rate limit backend"""
    
    def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int,
        burst: Optional[int] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if rate limit is exceeded.
        
        Args:
            key: Unique identifier for the limit
            limit: Maximum requests allowed
            window: Time window in seconds
            burst: Optional burst allowance
            
        Returns:
            Tuple of (is_allowed, metadata)
        """
        raise NotImplementedError
    
    def reset(self, key: str):
        """Reset rate limit for a key"""
        raise NotImplementedError
    
    def get_usage(self, key: str) -> Dict[str, Any]:
        """Get current usage for a key"""
        raise NotImplementedError


class SlidingWindowBackend(RateLimitBackend):
    """
    Sliding window rate limiting using Redis.
    
    More accurate than fixed window, prevents bursts at window boundaries.
    """
    
    def __init__(self):
        # Initialize Redis connection
        redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/1')
        self.redis = redis.from_url(redis_url, decode_responses=True)
        
    def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int,
        burst: Optional[int] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check rate limit using sliding window algorithm.
        """
        now = time.time()
        pipeline = self.redis.pipeline()
        
        # Remove old entries outside the window
        pipeline.zremrangebyscore(key, 0, now - window)
        
        # Count requests in current window
        pipeline.zcard(key)
        
        # Add current request
        pipeline.zadd(key, {str(now): now})
        
        # Set expiry on the key
        pipeline.expire(key, window)
        
        results = pipeline.execute()
        current_requests = results[1]
        
        # Check burst limit
        if burst and current_requests <= burst:
            allowed = True
        else:
            allowed = current_requests <= limit
        
        # Calculate reset time
        if not allowed:
            # Get oldest request time
            oldest = self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                reset_time = oldest[0][1] + window
            else:
                reset_time = now + window
        else:
            reset_time = now + window
        
        metadata = {
            'limit': limit,
            'remaining': max(0, limit - current_requests),
            'reset': int(reset_time),
            'retry_after': int(reset_time - now) if not allowed else None,
            'burst_limit': burst,
            'current_requests': current_requests
        }
        
        return allowed, metadata
    
    def reset(self, key: str):
        """Reset rate limit for a key"""
        self.redis.delete(key)
    
    def get_usage(self, key: str) -> Dict[str, Any]:
        """Get current usage for a key"""
        now = time.time()
        count = self.redis.zcard(key)
        
        return {
            'count': count,
            'key': key,
            'timestamp': now
        }


class TokenBucketBackend(RateLimitBackend):
    """
    Token bucket algorithm for rate limiting.
    
    Allows for burst capacity while maintaining average rate.
    """
    
    def __init__(self):
        redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/1')
        self.redis = redis.from_url(redis_url, decode_responses=True)
    
    def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int,
        burst: Optional[int] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check rate limit using token bucket algorithm.
        """
        bucket_key = f"bucket:{key}"
        max_tokens = burst or limit
        refill_rate = limit / window  # tokens per second
        
        # Get current bucket state
        bucket_data = self.redis.get(bucket_key)
        now = time.time()
        
        if bucket_data:
            data = json.loads(bucket_data)
            tokens = data['tokens']
            last_refill = data['last_refill']
            
            # Calculate tokens to add
            time_passed = now - last_refill
            tokens_to_add = time_passed * refill_rate
            tokens = min(max_tokens, tokens + tokens_to_add)
        else:
            tokens = max_tokens
            last_refill = now
        
        # Check if request is allowed
        if tokens >= 1:
            tokens -= 1
            allowed = True
        else:
            allowed = False
        
        # Save bucket state
        bucket_data = {
            'tokens': tokens,
            'last_refill': now
        }
        self.redis.setex(
            bucket_key,
            window * 2,  # Keep for twice the window
            json.dumps(bucket_data)
        )
        
        # Calculate metadata
        retry_after = None if allowed else int((1 - tokens) / refill_rate)
        
        metadata = {
            'limit': limit,
            'remaining': int(tokens),
            'reset': int(now + window),
            'retry_after': retry_after,
            'burst_limit': max_tokens,
            'refill_rate': refill_rate
        }
        
        return allowed, metadata
    
    def reset(self, key: str):
        """Reset rate limit for a key"""
        bucket_key = f"bucket:{key}"
        self.redis.delete(bucket_key)
    
    def get_usage(self, key: str) -> Dict[str, Any]:
        """Get current usage for a key"""
        bucket_key = f"bucket:{key}"
        bucket_data = self.redis.get(bucket_key)
        
        if bucket_data:
            data = json.loads(bucket_data)
            return {
                'tokens': data['tokens'],
                'last_refill': data['last_refill']
            }
        return {'tokens': 0, 'last_refill': 0}


class FixedWindowBackend(RateLimitBackend):
    """
    Fixed window rate limiting using Django cache.
    
    Simple but can allow bursts at window boundaries.
    """
    
    def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int,
        burst: Optional[int] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check rate limit using fixed window algorithm.
        """
        # Get current window
        now = int(time.time())
        window_start = now - (now % window)
        window_key = f"{key}:{window_start}"
        
        # Get current count
        current_count = cache.get(window_key, 0)
        
        # Check limit
        if burst and current_count < burst:
            allowed = True
        else:
            allowed = current_count < limit
        
        if allowed:
            # Increment counter
            try:
                current_count = cache.incr(window_key)
            except ValueError:
                # Key doesn't exist, set it
                cache.set(window_key, 1, timeout=window)
                current_count = 1
        
        # Calculate metadata
        reset_time = window_start + window
        retry_after = reset_time - now if not allowed else None
        
        metadata = {
            'limit': limit,
            'remaining': max(0, limit - current_count),
            'reset': reset_time,
            'retry_after': retry_after,
            'burst_limit': burst,
            'window_start': window_start
        }
        
        return allowed, metadata
    
    def reset(self, key: str):
        """Reset rate limit for a key"""
        # We need to clear all windows for this key
        # This is a limitation of fixed window approach
        now = int(time.time())
        for i in range(5):  # Clear last 5 windows
            window_start = now - (now % 60) - (i * 60)
            window_key = f"{key}:{window_start}"
            cache.delete(window_key)
    
    def get_usage(self, key: str) -> Dict[str, Any]:
        """Get current usage for a key"""
        now = int(time.time())
        window_start = now - (now % 60)
        window_key = f"{key}:{window_start}"
        
        return {
            'count': cache.get(window_key, 0),
            'window_start': window_start
        }


def get_backend(backend_type: Optional[str] = None) -> RateLimitBackend:
    """
    Get rate limit backend instance.
    
    Args:
        backend_type: Type of backend to use
        
    Returns:
        RateLimitBackend instance
    """
    if not backend_type:
        backend_type = getattr(settings, 'RATELIMIT_BACKEND', 'sliding_window')
    
    backends = {
        'sliding_window': SlidingWindowBackend,
        'token_bucket': TokenBucketBackend,
        'fixed_window': FixedWindowBackend,
    }
    
    backend_class = backends.get(backend_type, SlidingWindowBackend)
    return backend_class()