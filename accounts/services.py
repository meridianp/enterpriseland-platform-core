"""
Authentication services for unified auth handling
"""
import secrets
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework.request import Request

from .models import User, UserDevice, LoginAttempt, SecurityEvent

logger = logging.getLogger(__name__)


class DeviceTracker:
    """Track user devices for security monitoring"""
    
    @staticmethod
    def get_device_id(request: Request) -> str:
        """Generate a unique device ID from request metadata"""
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        accept_lang = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
        ip = request.META.get('REMOTE_ADDR', '')
        
        # Create a hash of device characteristics
        device_string = f"{user_agent}:{accept_lang}:{ip}"
        return hashlib.sha256(device_string.encode()).hexdigest()[:16]
    
    @staticmethod
    def track_device(user_id: str, device_id: str, request: Request) -> UserDevice:
        """Track device information for a user"""
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        ip_address = request.META.get('REMOTE_ADDR', '')
        
        # Extract device type from user agent
        device_type = 'desktop'
        if 'Mobile' in user_agent:
            device_type = 'mobile'
        elif 'Tablet' in user_agent:
            device_type = 'tablet'
        
        # Get or create device
        device, created = UserDevice.objects.get_or_create(
            user_id=user_id,
            device_id=device_id,
            defaults={
                'user_agent': user_agent,
                'ip_address': ip_address,
                'device_type': device_type,
                'country': request.META.get('HTTP_CF_IPCOUNTRY', ''),
                'city': request.META.get('HTTP_CF_IPCITY', ''),
            }
        )
        
        if not created:
            # Update device info
            device.last_seen = timezone.now()
            device.login_count += 1
            device.ip_address = ip_address
            device.user_agent = user_agent
            device.save(update_fields=['last_seen', 'login_count', 'ip_address', 'user_agent'])
        
        return device
    
    @staticmethod
    def get_user_devices(user_id: str) -> list:
        """Get all devices for a user"""
        return list(UserDevice.objects.filter(user_id=user_id, is_blocked=False).order_by('-last_seen'))


class TokenBlacklistService:
    """Service for managing token blacklist"""
    
    @staticmethod
    def blacklist_token(token: str, token_type: str = 'access') -> None:
        """Add a token to the blacklist using Django's token blacklist"""
        try:
            if token_type == 'refresh':
                refresh = RefreshToken(token)
                # This will automatically blacklist the token
                refresh.blacklist()
                logger.info(f"Refresh token blacklisted")
            else:
                # For access tokens, we still use cache-based blacklisting
                access = AccessToken(token)
                jti = access.payload.get('jti')
                exp = access.payload.get('exp')
                
                if jti and exp:
                    ttl = exp - int(timezone.now().timestamp())
                    if ttl > 0:
                        cache_key = f"blacklist:{jti}"
                        cache.set(cache_key, True, timeout=ttl)
                        logger.info(f"Access token {jti} blacklisted for {ttl} seconds")
        except TokenError as e:
            logger.error(f"Failed to blacklist token: {e}")
    
    @staticmethod
    def is_blacklisted(jti: str) -> bool:
        """Check if a token is blacklisted"""
        # Check cache first (for access tokens)
        cache_key = f"blacklist:{jti}"
        if cache.get(cache_key, False):
            return True
        
        # Check database (for refresh tokens)
        try:
            return BlacklistedToken.objects.filter(token__jti=jti).exists()
        except:
            return False


class AuthenticationService:
    """Unified authentication service"""
    
    def __init__(self):
        self.device_tracker = DeviceTracker()
        self.blacklist_service = TokenBlacklistService()
    
    def authenticate_user(self, email: str, password: str, request: Request) -> Tuple[User, Dict[str, str]]:
        """
        Authenticate user and return tokens
        
        Returns:
            Tuple of (user, tokens_dict)
        """
        user = authenticate(request=request, username=email, password=password)
        
        # Log login attempt
        if not user:
            LoginAttempt.objects.create(
                email=email,
                ip_address=request.META.get('REMOTE_ADDR', ''),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                success=False,
                failure_reason='Invalid credentials'
            )
            raise ValueError("Invalid credentials")
        
        if not user.is_active:
            LoginAttempt.objects.create(
                email=email,
                ip_address=request.META.get('REMOTE_ADDR', ''),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                success=False,
                failure_reason='Account disabled',
                user=user
            )
            raise ValueError("User account is disabled")
        
        # Check if user has MFA enabled
        mfa_required = MFAMethod.objects.filter(user=user, is_active=True).exists()
        
        if mfa_required:
            # Don't complete login yet - require MFA verification
            # Store temporary session
            session_key = f"pending_login:{user.id}"
            cache.set(session_key, {
                'user_id': str(user.id),
                'timestamp': timezone.now().isoformat(),
                'ip': request.META.get('REMOTE_ADDR', ''),
            }, timeout=300)  # 5 minutes
            
            return user, {
                'mfa_required': True,
                'user_id': str(user.id),
                'methods': list(MFAMethod.objects.filter(user=user, is_active=True).values_list('method', flat=True)),
            }
        
        # Track device
        device_id = self.device_tracker.get_device_id(request)
        self.device_tracker.track_device(str(user.id), device_id, request)
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        # Add custom claims
        refresh['device_id'] = device_id
        refresh['role'] = user.role
        refresh['group_ids'] = [str(g.id) for g in user.groups.all()]
        
        # Update last login
        user.last_login_at = timezone.now()
        user.save(update_fields=['last_login_at'])
        
        # Log authentication attempt
        LoginAttempt.objects.create(
            email=email,
            ip_address=request.META.get('REMOTE_ADDR', ''),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            success=True,
            user=user,
            device_id=device_id
        )
        
        # Log security event
        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEvent.EventType.LOGIN_SUCCESS,
            description=f"Successful login from device {device_id}",
            ip_address=request.META.get('REMOTE_ADDR', ''),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            device_id=device_id
        )
        
        logger.info(f"User {user.email} authenticated from device {device_id}")
        
        return user, {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'access_expires_at': (timezone.now() + settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']).isoformat(),
            'refresh_expires_at': (timezone.now() + settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']).isoformat(),
        }
    
    def refresh_tokens(self, refresh_token: str, request: Request) -> Dict[str, str]:
        """Refresh access token"""
        try:
            refresh = RefreshToken(refresh_token)
            
            # Check if refresh token is blacklisted
            if self.blacklist_service.is_blacklisted(refresh.payload.get('jti')):
                raise TokenError("Token has been revoked")
            
            # Rotate refresh token
            if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', True):
                refresh.set_jti()
                refresh.set_exp()
                
                # Blacklist old refresh token
                if settings.SIMPLE_JWT.get('BLACKLIST_AFTER_ROTATION', True):
                    self.blacklist_service.blacklist_token(refresh_token, 'refresh')
            
            # Track device activity
            user_id = refresh.payload.get('user_id')
            device_id = self.device_tracker.get_device_id(request)
            if user_id:
                self.device_tracker.track_device(str(user_id), device_id, request)
            
            return {
                'access': str(refresh.access_token),
                'refresh': str(refresh) if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', True) else refresh_token,
                'access_expires_at': (timezone.now() + settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']).isoformat(),
            }
        except TokenError as e:
            logger.error(f"Token refresh failed: {e}")
            raise ValueError("Invalid or expired refresh token")
    
    def logout_user(self, user: User, tokens: Dict[str, Optional[str]], request: Request) -> None:
        """Logout user and invalidate tokens"""
        # Blacklist tokens
        if tokens.get('access'):
            self.blacklist_service.blacklist_token(tokens['access'], 'access')
        
        if tokens.get('refresh'):
            self.blacklist_service.blacklist_token(tokens['refresh'], 'refresh')
        
        # Log logout event
        device_id = self.device_tracker.get_device_id(request)
        
        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEvent.EventType.LOGOUT,
            description="User logged out",
            ip_address=request.META.get('REMOTE_ADDR', ''),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            device_id=device_id
        )
        
        logger.info(f"User {user.email} logged out from device {device_id}")
    
    def validate_token(self, token: str) -> bool:
        """Validate if a token is valid and not blacklisted"""
        try:
            access = AccessToken(token)
            jti = access.payload.get('jti')
            
            # Check blacklist
            if jti and self.blacklist_service.is_blacklisted(jti):
                return False
            
            # Token is valid if we get here
            return True
        except TokenError:
            return False
    
    def check_suspicious_activity(self, user: User, request: Request) -> bool:
        """Check for suspicious authentication activity"""
        # Check for rapid login attempts in last hour
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_attempts = LoginAttempt.objects.filter(
            email=user.email,
            created_at__gte=one_hour_ago
        ).count()
        
        if recent_attempts > 5:
            SecurityEvent.objects.create(
                user=user,
                event_type=SecurityEvent.EventType.SUSPICIOUS_ACTIVITY,
                description=f"Multiple login attempts detected: {recent_attempts} in last hour",
                ip_address=request.META.get('REMOTE_ADDR', ''),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                metadata={'attempts': recent_attempts}
            )
            logger.warning(f"Suspicious activity detected for user {user.email}: {recent_attempts} login attempts")
            return True
        
        # Check for new device
        device_id = self.device_tracker.get_device_id(request)
        is_new_device = not UserDevice.objects.filter(
            user=user,
            device_id=device_id
        ).exists()
        
        if is_new_device:
            SecurityEvent.objects.create(
                user=user,
                event_type=SecurityEvent.EventType.LOGIN_SUCCESS,
                description="Login from new device",
                ip_address=request.META.get('REMOTE_ADDR', ''),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                device_id=device_id,
                metadata={'new_device': True}
            )
            logger.info(f"New device login for user {user.email}")
        
        return False
    
    def get_csrf_token(self, request: Request) -> str:
        """Generate a new CSRF token"""
        csrf_token = secrets.token_urlsafe(32)
        request.session['csrf_token'] = csrf_token
        return csrf_token
    
    def complete_mfa_login(self, user_id: str, session_token: str, request: Request) -> Tuple[User, Dict[str, str]]:
        """Complete login after successful MFA verification"""
        # Verify session token
        cache_key = f"mfa_verified:{user_id}"
        stored_token = cache.get(cache_key)
        
        if not stored_token or stored_token != session_token:
            raise ValueError("Invalid or expired MFA session")
        
        # Get user
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise ValueError("Invalid user")
        
        # Clear MFA session
        cache.delete(cache_key)
        cache.delete(f"pending_login:{user_id}")
        
        # Track device
        device_id = self.device_tracker.get_device_id(request)
        self.device_tracker.track_device(str(user.id), device_id, request)
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        # Add custom claims
        refresh['device_id'] = device_id
        refresh['role'] = user.role
        refresh['group_ids'] = [str(g.id) for g in user.groups.all()]
        refresh['mfa_verified'] = True
        
        # Update last login
        user.last_login_at = timezone.now()
        user.save(update_fields=['last_login_at'])
        
        # Log successful MFA login
        LoginAttempt.objects.create(
            email=user.email,
            ip_address=request.META.get('REMOTE_ADDR', ''),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            success=True,
            user=user,
            device_id=device_id
        )
        
        SecurityEvent.objects.create(
            user=user,
            event_type=SecurityEvent.EventType.LOGIN_SUCCESS,
            description=f"Successful login with MFA from device {device_id}",
            ip_address=request.META.get('REMOTE_ADDR', ''),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            device_id=device_id,
            metadata={'mfa_verified': True}
        )
        
        return user, {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'access_expires_at': (timezone.now() + settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']).isoformat(),
            'refresh_expires_at': (timezone.now() + settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']).isoformat(),
        }


# Global instance
auth_service = AuthenticationService()