"""
WebSocket Middleware

Middleware for WebSocket connections including authentication, rate limiting, and logging.
"""

import time
import logging
from typing import Dict, Any, Optional
from collections import defaultdict
from datetime import datetime, timedelta

from channels.middleware import BaseMiddleware
from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from django.core.cache import cache
from jwt import decode as jwt_decode, InvalidTokenError

from platform_core.security.authentication.models import TokenBlacklist

User = get_user_model()
logger = logging.getLogger(__name__)


class JWTAuthMiddleware(BaseMiddleware):
    """
    JWT authentication middleware for WebSocket connections.
    """
    
    async def __call__(self, scope, receive, send):
        """Process WebSocket connection with JWT auth."""
        # Get token from query string
        query_string = scope.get('query_string', b'').decode()
        token = self._extract_token(query_string)
        
        if token:
            # Authenticate with JWT
            user = await self.authenticate_jwt(token)
            if user:
                scope['user'] = user
            else:
                scope['user'] = AnonymousUser()
        else:
            # Fall back to session auth
            scope = await AuthMiddlewareStack(self.inner)(scope, receive, send)
            return
        
        return await super().__call__(scope, receive, send)
    
    def _extract_token(self, query_string: str) -> Optional[str]:
        """Extract JWT token from query string."""
        params = {}
        for param in query_string.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                if key == 'token':
                    return value
        return None
    
    @database_sync_to_async
    def authenticate_jwt(self, token: str) -> Optional[User]:
        """Authenticate user with JWT token."""
        try:
            # Decode token
            payload = jwt_decode(
                token,
                settings.SECRET_KEY,
                algorithms=['HS256']
            )
            
            # Check if token is blacklisted
            if TokenBlacklist.objects.filter(token=token).exists():
                return None
            
            # Get user
            user_id = payload.get('user_id')
            if user_id:
                return User.objects.get(id=user_id, is_active=True)
            
        except (InvalidTokenError, User.DoesNotExist):
            pass
        
        return None


class RateLimitMiddleware:
    """
    Rate limiting middleware for WebSocket messages.
    """
    
    def __init__(self):
        self.rate_limits = getattr(
            settings,
            'WEBSOCKET_RATE_LIMITS',
            {
                'default': {'messages': 60, 'window': 60},  # 60 messages per minute
                'authenticated': {'messages': 120, 'window': 60},  # 120 messages per minute
            }
        )
    
    async def check_rate_limit(self, user) -> bool:
        """Check if user has exceeded rate limit."""
        if isinstance(user, AnonymousUser):
            limit_key = 'default'
            identifier = 'anonymous'
        else:
            limit_key = 'authenticated'
            identifier = f'user:{user.id}'
        
        limit = self.rate_limits.get(limit_key, self.rate_limits['default'])
        cache_key = f'ws_rate_limit:{identifier}'
        
        # Get current count
        current = cache.get(cache_key, 0)
        
        if current >= limit['messages']:
            return False
        
        # Increment count
        cache.set(
            cache_key,
            current + 1,
            timeout=limit['window']
        )
        
        return True


class LoggingMiddleware(BaseMiddleware):
    """
    Logging middleware for WebSocket connections.
    """
    
    async def __call__(self, scope, receive, send):
        """Log WebSocket connection lifecycle."""
        start_time = time.time()
        connection_id = scope.get('client', ['unknown', ''])[0]
        
        logger.info(
            f"WebSocket connection started: {connection_id} - {scope['path']}"
        )
        
        try:
            return await super().__call__(scope, receive, send)
        finally:
            duration = time.time() - start_time
            logger.info(
                f"WebSocket connection ended: {connection_id} - "
                f"Duration: {duration:.2f}s"
            )


class OriginValidationMiddleware(BaseMiddleware):
    """
    Validates WebSocket connection origin.
    """
    
    def __init__(self, inner):
        self.inner = inner
        self.allowed_origins = getattr(
            settings,
            'WEBSOCKET_ALLOWED_ORIGINS',
            []
        )
    
    async def __call__(self, scope, receive, send):
        """Validate origin header."""
        headers = dict(scope.get('headers', []))
        origin = headers.get(b'origin', b'').decode()
        
        if self.allowed_origins and origin not in self.allowed_origins:
            logger.warning(f"WebSocket connection rejected - Invalid origin: {origin}")
            await send({
                'type': 'websocket.close',
                'code': 4003,
                'reason': 'Invalid origin'
            })
            return
        
        return await super().__call__(scope, receive, send)


class ConnectionThrottleMiddleware(BaseMiddleware):
    """
    Throttles WebSocket connections per user/IP.
    """
    
    def __init__(self, inner):
        self.inner = inner
        self.max_connections = getattr(
            settings,
            'WEBSOCKET_MAX_CONNECTIONS_PER_USER',
            5
        )
        self.connections = defaultdict(set)
    
    async def __call__(self, scope, receive, send):
        """Check connection limit."""
        user = scope.get('user')
        
        if user and not isinstance(user, AnonymousUser):
            identifier = f'user:{user.id}'
        else:
            # Use IP for anonymous users
            identifier = f'ip:{scope.get("client", ["unknown"])[0]}'
        
        # Check current connections
        channel_name = scope.get('channel_name', '')
        current_connections = self.connections[identifier]
        
        if len(current_connections) >= self.max_connections:
            logger.warning(
                f"WebSocket connection rejected - "
                f"Too many connections for {identifier}"
            )
            await send({
                'type': 'websocket.close',
                'code': 4004,
                'reason': 'Too many connections'
            })
            return
        
        # Track connection
        current_connections.add(channel_name)
        
        try:
            return await super().__call__(scope, receive, send)
        finally:
            # Remove connection on close
            current_connections.discard(channel_name)
            if not current_connections:
                del self.connections[identifier]


class MessageSizeMiddleware(BaseMiddleware):
    """
    Limits WebSocket message size.
    """
    
    def __init__(self, inner):
        self.inner = inner
        self.max_message_size = getattr(
            settings,
            'WEBSOCKET_MAX_MESSAGE_SIZE',
            65536  # 64KB
        )
    
    async def __call__(self, scope, receive, send):
        """Check message size."""
        async def receive_wrapper():
            message = await receive()
            
            if message['type'] == 'websocket.receive':
                # Check message size
                text = message.get('text', '')
                bytes_data = message.get('bytes', b'')
                
                if len(text) > self.max_message_size or len(bytes_data) > self.max_message_size:
                    await send({
                        'type': 'websocket.close',
                        'code': 4005,
                        'reason': 'Message too large'
                    })
                    return {'type': 'websocket.disconnect'}
            
            return message
        
        return await self.inner(scope, receive_wrapper, send)


def WebSocketMiddlewareStack(inner):
    """
    Complete WebSocket middleware stack.
    """
    return (
        OriginValidationMiddleware(
            ConnectionThrottleMiddleware(
                MessageSizeMiddleware(
                    LoggingMiddleware(
                        JWTAuthMiddleware(inner)
                    )
                )
            )
        )
    )