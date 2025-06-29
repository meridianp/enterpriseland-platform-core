"""
Enhanced JWT Authentication

Provides enhanced JWT authentication with blacklisting and rotation.
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken, Token
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from .models import BlacklistedToken, RefreshTokenRotation, AuthSession


User = get_user_model()


class EnhancedJWTAuthentication(JWTAuthentication):
    """
    Enhanced JWT authentication with blacklisting and session tracking.
    """
    
    def authenticate(self, request):
        """
        Authenticate the request and return a two-tuple of (user, token).
        """
        # Get the token
        header = self.get_header(request)
        if header is None:
            return None
            
        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None
        
        # Validate the token
        validated_token = self.get_validated_token(raw_token)
        
        # Check if token is blacklisted
        if self.is_blacklisted(validated_token):
            raise exceptions.AuthenticationFailed(
                _('Token has been blacklisted'),
                code='token_blacklisted'
            )
        
        # Get the user
        user = self.get_user(validated_token)
        
        # Update session activity if applicable
        self.update_session_activity(user, validated_token, request)
        
        return user, validated_token
    
    def is_blacklisted(self, token: Token) -> bool:
        """Check if token is blacklisted"""
        jti = token.get('jti')
        if not jti:
            return False
            
        return BlacklistedToken.objects.filter(
            token=str(token)
        ).exists()
    
    def update_session_activity(self, user, token: Token, request):
        """Update session activity tracking"""
        session_id = token.get('session_id')
        if not session_id:
            return
            
        try:
            session = AuthSession.objects.get(
                session_key=session_id,
                user=user,
                is_active=True
            )
            session.update_activity()
        except AuthSession.DoesNotExist:
            pass


class EnhancedRefreshToken(RefreshToken):
    """
    Enhanced refresh token with rotation support.
    """
    
    @classmethod
    def for_user(cls, user, request=None):
        """
        Create a refresh token for the given user with rotation tracking.
        """
        token = super().for_user(user)
        
        # Add custom claims
        token['token_family'] = str(uuid.uuid4())
        
        # Create rotation tracking
        if hasattr(user, 'group'):
            RefreshTokenRotation.objects.create(
                user=user,
                group=user.group,
                token_family=token['token_family'],
                jti=token['jti'],
                expires_at=datetime.fromtimestamp(token['exp'], tz=timezone.utc),
                ip_address=get_client_ip(request) if request else None,
                user_agent=request.META.get('HTTP_USER_AGENT', '') if request else ''
            )
        
        return token
    
    def rotate(self, request=None):
        """
        Rotate refresh token to a new one.
        """
        # Check if this token has been used before (replay attack)
        try:
            rotation = RefreshTokenRotation.objects.get(jti=self['jti'])
            
            if rotation.used_at:
                # Token reuse detected - invalidate entire family
                self._invalidate_token_family(rotation.token_family)
                raise InvalidToken(_('Token reuse detected'))
                
            # Create new token
            new_token = self.__class__()
            new_token.set_jti()
            new_token.set_exp()
            
            # Copy claims
            for claim, value in self.payload.items():
                if claim not in ['jti', 'exp', 'iat']:
                    new_token[claim] = value
            
            # Rotate the token
            new_rotation = rotation.rotate(
                new_jti=new_token['jti'],
                ip_address=get_client_ip(request) if request else None,
                user_agent=request.META.get('HTTP_USER_AGENT', '') if request else ''
            )
            
            return new_token
            
        except RefreshTokenRotation.DoesNotExist:
            raise InvalidToken(_('Invalid refresh token'))
    
    def _invalidate_token_family(self, token_family):
        """Invalidate all tokens in a family due to security concern"""
        RefreshTokenRotation.objects.filter(
            token_family=token_family
        ).update(used_at=timezone.now())


def blacklist_token(token: str, user: Optional[User] = None, reason: str = 'logout'):
    """
    Blacklist a JWT token.
    
    Args:
        token: The JWT token string
        user: The user associated with the token
        reason: Reason for blacklisting
    """
    try:
        # Parse token to get expiry
        token_obj = Token(token)
        expires_at = datetime.fromtimestamp(token_obj['exp'], tz=timezone.utc)
        
        BlacklistedToken.objects.create(
            token=token,
            user=user,
            expires_at=expires_at,
            reason=reason
        )
    except (TokenError, KeyError):
        # If we can't parse the token, blacklist it with a default expiry
        BlacklistedToken.objects.create(
            token=token,
            user=user,
            expires_at=timezone.now() + timedelta(days=7),
            reason=reason
        )


def create_auth_session(user: User, request) -> AuthSession:
    """
    Create an authentication session for tracking.
    
    Args:
        user: The authenticated user
        request: The HTTP request object
        
    Returns:
        AuthSession instance
    """
    from user_agents import parse
    
    # Parse user agent
    ua_string = request.META.get('HTTP_USER_AGENT', '')
    user_agent = parse(ua_string)
    
    device_info = {
        'browser': user_agent.browser.family,
        'browser_version': user_agent.browser.version_string,
        'os': user_agent.os.family,
        'os_version': user_agent.os.version_string,
        'device': user_agent.device.family,
        'is_mobile': user_agent.is_mobile,
        'is_tablet': user_agent.is_tablet,
        'is_pc': user_agent.is_pc,
    }
    
    # Get IP address
    ip_address = get_client_ip(request)
    
    # Create session
    session = AuthSession.objects.create(
        user=user,
        group=user.group if hasattr(user, 'group') else None,
        session_key=str(uuid.uuid4()),
        expires_at=timezone.now() + timedelta(hours=24),
        ip_address=ip_address,
        user_agent=ua_string,
        device_info=device_info
    )
    
    # Optionally get location info asynchronously
    # This would typically be done via a background task
    
    return session


def get_client_ip(request) -> Optional[str]:
    """
    Get the client's IP address from the request.
    
    Handles X-Forwarded-For and X-Real-IP headers.
    """
    if not request:
        return None
        
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('HTTP_X_REAL_IP', request.META.get('REMOTE_ADDR'))
    
    return ip


def check_concurrent_sessions(user: User, max_sessions: int = 5) -> bool:
    """
    Check if user has exceeded concurrent session limit.
    
    Args:
        user: The user to check
        max_sessions: Maximum allowed concurrent sessions
        
    Returns:
        True if within limit, False if exceeded
    """
    active_sessions = AuthSession.objects.filter(
        user=user,
        is_active=True,
        expires_at__gt=timezone.now()
    ).count()
    
    return active_sessions < max_sessions


def terminate_user_sessions(user: User, except_session: Optional[str] = None, reason: str = 'security'):
    """
    Terminate all sessions for a user.
    
    Args:
        user: The user whose sessions to terminate
        except_session: Session key to exclude from termination
        reason: Reason for termination
    """
    sessions = AuthSession.objects.filter(
        user=user,
        is_active=True
    )
    
    if except_session:
        sessions = sessions.exclude(session_key=except_session)
    
    sessions.update(
        is_active=False,
        terminated_at=timezone.now(),
        termination_reason=reason
    )
    
    # Also blacklist all active tokens
    # This would need to track JWTs with session IDs