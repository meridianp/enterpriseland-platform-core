"""
Custom throttling classes for comprehensive rate limiting.

This module provides multiple levels of rate limiting:
- API endpoint level with different limits for different endpoints
- User level for authenticated users
- IP level for anonymous users
- Tenant level to prevent one tenant from consuming all resources
"""

import hashlib
import time
from typing import Optional, Dict, Any
from django.core.cache import cache
from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle, AnonRateThrottle
from rest_framework.exceptions import Throttled


class BaseEnhancedThrottle(SimpleRateThrottle):
    """
    Enhanced base throttle class that adds:
    - Rate limit headers in responses
    - Better cache key generation
    - Tenant-aware rate limiting
    """
    
    def get_cache_key(self, request, view):
        """Generate a cache key for rate limiting."""
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        
        # Include tenant/group in cache key if available
        group_id = None
        if hasattr(request.user, 'group_id'):
            group_id = request.user.group_id
        elif hasattr(request, 'group'):
            group_id = request.group.id
            
        components = [self.scope, ident]
        if group_id:
            components.append(str(group_id))
            
        return self.cache_format % {
            'scope': hashlib.md5(':'.join(str(c) for c in components).encode()).hexdigest(),
            'ident': ident
        }
    
    def allow_request(self, request, view):
        """
        Check if the request should be throttled.
        Adds rate limit info to request for headers.
        """
        if self.rate is None:
            return True
            
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True
            
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()
        
        # Drop any requests from the history which have now passed the throttle duration
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
            
        if len(self.history) >= self.num_requests:
            # Calculate wait time
            remaining_duration = self.duration - (self.now - self.history[-1])
            self.wait_time = remaining_duration
            
            # Store rate limit info on request for headers
            request.rate_limit_limit = self.num_requests
            request.rate_limit_remaining = 0
            request.rate_limit_reset = int(self.now + remaining_duration)
            
            return self.throttle_failure()
            
        # Request allowed - update history and store info
        self.history.insert(0, self.now)
        self.cache.set(self.key, self.history, self.duration)
        
        request.rate_limit_limit = self.num_requests
        request.rate_limit_remaining = self.num_requests - len(self.history)
        request.rate_limit_reset = int(self.now + self.duration)
        
        return self.throttle_success()
    
    def throttle_failure(self):
        """Called when a request is throttled."""
        wait = self.wait() if hasattr(self, 'wait') and callable(self.wait) else getattr(self, 'wait_time', 0)
        detail = {
            'message': f'Request was throttled. Expected available in {wait:.1f} seconds.',
            'available_in': wait,
            'throttle_scope': self.scope
        }
        raise Throttled(detail=detail, wait=wait)


class TenantRateThrottle(BaseEnhancedThrottle):
    """
    Limits requests per tenant/group to prevent one tenant from consuming all resources.
    """
    scope = 'tenant'
    rate = '10000/hour'  # Default tenant rate
    
    def get_cache_key(self, request, view):
        """Generate cache key based on tenant/group."""
        group_id = None
        if hasattr(request.user, 'group_id'):
            group_id = request.user.group_id
        elif hasattr(request, 'group'):
            group_id = request.group.id
            
        if not group_id:
            return None  # No tenant limiting if no group
            
        return self.cache_format % {
            'scope': self.scope,
            'ident': group_id
        }


class AuthenticationThrottle(BaseEnhancedThrottle):
    """
    Stricter rate limiting for authentication endpoints.
    """
    scope = 'authentication'
    rate = '10/hour'  # Very strict for auth endpoints
    
    def get_cache_key(self, request, view):
        """Use IP address for auth endpoints."""
        ident = self.get_ident(request)
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class AIAgentThrottle(BaseEnhancedThrottle):
    """
    Token/cost-based rate limiting for AI agent endpoints.
    """
    scope = 'ai_agent'
    rate = '100/hour'  # Default rate, but also checks token usage
    
    def allow_request(self, request, view):
        """
        Check both request rate and token usage.
        """
        # First check standard rate limit
        if not super().allow_request(request, view):
            return False
            
        # Then check token usage if applicable
        if hasattr(request.user, 'ai_token_usage'):
            token_limit = getattr(settings, 'AI_TOKEN_LIMIT_PER_HOUR', 10000)
            token_key = f'ai_tokens:{request.user.pk}'
            current_usage = cache.get(token_key, 0)
            
            if current_usage >= token_limit:
                wait_time = 3600  # 1 hour
                detail = {
                    'message': f'AI token limit exceeded. Limit resets hourly.',
                    'available_in': wait_time,
                    'throttle_scope': 'ai_tokens',
                    'current_usage': current_usage,
                    'limit': token_limit
                }
                raise Throttled(detail=detail, wait=wait_time)
                
        return True
    
    def update_token_usage(self, request, tokens_used):
        """Update token usage for the user."""
        if hasattr(request.user, 'pk'):
            token_key = f'ai_tokens:{request.user.pk}'
            current_usage = cache.get(token_key, 0)
            new_usage = current_usage + tokens_used
            cache.set(token_key, new_usage, 3600)  # Reset hourly


class FileUploadThrottle(BaseEnhancedThrottle):
    """
    Size and frequency-based rate limiting for file uploads.
    """
    scope = 'file_upload'
    rate = '100/hour'  # Frequency limit
    
    def allow_request(self, request, view):
        """
        Check both upload frequency and total size.
        """
        # First check standard rate limit
        if not super().allow_request(request, view):
            return False
            
        # Then check upload size if applicable
        if request.method in ['POST', 'PUT', 'PATCH'] and hasattr(request, 'FILES'):
            size_limit = getattr(settings, 'FILE_UPLOAD_SIZE_LIMIT_PER_HOUR', 1024 * 1024 * 1024)  # 1GB default
            size_key = f'upload_size:{self.get_ident(request)}'
            current_size = cache.get(size_key, 0)
            
            # Calculate size of current upload
            upload_size = sum(f.size for f in request.FILES.values())
            
            if current_size + upload_size > size_limit:
                wait_time = 3600  # 1 hour
                detail = {
                    'message': f'Upload size limit exceeded. Limit resets hourly.',
                    'available_in': wait_time,
                    'throttle_scope': 'upload_size',
                    'current_usage_mb': round(current_size / 1024 / 1024, 2),
                    'limit_mb': round(size_limit / 1024 / 1024, 2)
                }
                raise Throttled(detail=detail, wait=wait_time)
                
            # Update size tracking
            cache.set(size_key, current_size + upload_size, 3600)
            
        return True


class PublicAPIThrottle(BaseEnhancedThrottle):
    """
    Rate limiting for public API endpoints.
    """
    scope = 'public_api'
    rate = '100/hour'
    
    def get_cache_key(self, request, view):
        """Use IP address for public endpoints."""
        ident = self.get_ident(request)
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class BurstRateThrottle(BaseEnhancedThrottle):
    """
    Allows burst traffic while maintaining overall rate limits.
    Implements a token bucket algorithm.
    """
    scope = 'burst'
    burst_rate = '10/second'  # Burst allowance
    sustained_rate = '1000/hour'  # Sustained rate
    
    def allow_request(self, request, view):
        """
        Implement token bucket algorithm for burst handling.
        """
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True
            
        # Get current bucket state
        bucket_key = f'{self.key}:bucket'
        bucket_data = cache.get(bucket_key, {
            'tokens': self.parse_rate(self.burst_rate)[0],  # Start with full burst capacity
            'last_refill': time.time()
        })
        
        now = time.time()
        burst_num, burst_duration = self.parse_rate(self.burst_rate)
        sustained_num, sustained_duration = self.parse_rate(self.sustained_rate)
        
        # Calculate token refill
        time_passed = now - bucket_data['last_refill']
        refill_rate = sustained_num / sustained_duration  # Tokens per second
        tokens_to_add = time_passed * refill_rate
        
        # Update bucket (cap at burst capacity)
        bucket_data['tokens'] = min(burst_num, bucket_data['tokens'] + tokens_to_add)
        bucket_data['last_refill'] = now
        
        # Check if request can proceed
        if bucket_data['tokens'] >= 1:
            bucket_data['tokens'] -= 1
            cache.set(bucket_key, bucket_data, sustained_duration)
            
            # Set rate limit headers
            request.rate_limit_limit = burst_num
            request.rate_limit_remaining = int(bucket_data['tokens'])
            request.rate_limit_reset = int(now + (burst_num - bucket_data['tokens']) / refill_rate)
            
            return True
        else:
            # Calculate wait time
            wait_time = 1 / refill_rate
            
            request.rate_limit_limit = burst_num
            request.rate_limit_remaining = 0
            request.rate_limit_reset = int(now + wait_time)
            
            detail = {
                'message': f'Rate limit exceeded. Please retry after {wait_time:.1f} seconds.',
                'available_in': wait_time,
                'throttle_scope': self.scope
            }
            raise Throttled(detail=detail, wait=wait_time)


class ScopedRateThrottle(BaseEnhancedThrottle):
    """
    Allows different rate limits for different views/endpoints.
    Views can specify their throttle scope.
    """
    scope_attr = 'throttle_scope'
    default_scope = 'api'
    
    # Define rate limits for different scopes
    THROTTLE_RATES = {
        'api': '1000/hour',
        'search': '300/hour',
        'analytics': '100/hour',
        'export': '50/hour',
        'ai': '100/hour',
        'webhook': '1000/hour',
    }
    
    def get_scope(self, request, view):
        """Get throttle scope from view or use default."""
        return getattr(view, self.scope_attr, self.default_scope)
    
    def allow_request(self, request, view):
        """Check rate limit based on endpoint scope."""
        self.scope = self.get_scope(request, view)
        self.rate = self.THROTTLE_RATES.get(self.scope, self.THROTTLE_RATES['api'])
        return super().allow_request(request, view)


# Convenience classes for DRF compatibility
class EnhancedUserRateThrottle(BaseEnhancedThrottle, UserRateThrottle):
    """Enhanced version of DRF's UserRateThrottle with headers."""
    scope = 'user'
    rate = '1000/hour'


class EnhancedAnonRateThrottle(BaseEnhancedThrottle, AnonRateThrottle):
    """Enhanced version of DRF's AnonRateThrottle with headers."""
    scope = 'anon'
    rate = '100/hour'