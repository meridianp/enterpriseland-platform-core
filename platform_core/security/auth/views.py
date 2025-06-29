"""
Authentication Views

Enhanced authentication views with MFA and session management.
"""

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken

from platform_core.core.views import PlatformViewSet
from .models import MFADevice, AuthSession, OAuth2Client, BlacklistedToken
from .serializers import (
    EnhancedTokenObtainPairSerializer, EnhancedTokenRefreshSerializer,
    MFADeviceSerializer, SetupTOTPSerializer, VerifyTOTPSerializer,
    AuthSessionSerializer, OAuth2ClientSerializer
)
from .authentication import blacklist_token, terminate_user_sessions


User = get_user_model()


class EnhancedTokenObtainPairView(TokenObtainPairView):
    """
    Enhanced login view with MFA support.
    
    Returns JWT tokens after validating credentials and MFA.
    """
    serializer_class = EnhancedTokenObtainPairSerializer


class EnhancedTokenRefreshView(TokenRefreshView):
    """
    Enhanced token refresh with rotation.
    
    Implements refresh token rotation for enhanced security.
    """
    serializer_class = EnhancedTokenRefreshSerializer


class LogoutView(APIView):
    """
    Logout view that blacklists tokens.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Logout user and blacklist tokens"""
        try:
            # Get refresh token from request
            refresh_token = request.data.get('refresh')
            if refresh_token:
                # Blacklist refresh token
                blacklist_token(refresh_token, request.user, 'logout')
            
            # Get access token from auth header
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Bearer '):
                access_token = auth_header.split(' ')[1]
                blacklist_token(access_token, request.user, 'logout')
            
            # Terminate session if tracked
            session_id = getattr(request.auth, 'payload', {}).get('session_id')
            if session_id:
                try:
                    session = AuthSession.objects.get(
                        session_key=session_id,
                        user=request.user,
                        is_active=True
                    )
                    session.terminate('logout')
                except AuthSession.DoesNotExist:
                    pass
            
            return Response(
                {'detail': _('Successfully logged out')},
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class MFADeviceViewSet(PlatformViewSet):
    """
    ViewSet for managing MFA devices.
    """
    serializer_class = MFADeviceSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Get user's MFA devices"""
        return MFADevice.objects.filter(
            user=self.request.user
        ).order_by('-is_primary', '-created_at')
    
    @action(detail=False, methods=['post'])
    def setup_totp(self, request):
        """Setup TOTP device"""
        serializer = SetupTOTPSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        
        return Response(result, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['post'])
    def verify_totp(self, request):
        """Verify and activate TOTP device"""
        serializer = VerifyTOTPSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.validated_data
        
        return Response(
            MFADeviceSerializer(result['device']).data,
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['post'])
    def set_primary(self, request, pk=None):
        """Set device as primary"""
        device = self.get_object()
        
        # Remove primary from other devices
        MFADevice.objects.filter(
            user=request.user,
            is_primary=True
        ).exclude(id=device.id).update(is_primary=False)
        
        # Set this as primary
        device.is_primary = True
        device.save()
        
        return Response(
            MFADeviceSerializer(device).data,
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['post'])
    def regenerate_backup_codes(self, request, pk=None):
        """Regenerate backup codes"""
        device = self.get_object()
        
        if device.device_type != 'backup':
            return Response(
                {'error': _('Only backup devices can regenerate codes')},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        codes = device.generate_backup_codes()
        
        return Response(
            {'backup_codes': codes},
            status=status.HTTP_200_OK
        )
    
    def destroy(self, request, *args, **kwargs):
        """Delete MFA device with safety check"""
        device = self.get_object()
        
        # Check if this is the last active device
        other_devices = MFADevice.objects.filter(
            user=request.user,
            is_active=True
        ).exclude(id=device.id).exists()
        
        if not other_devices and device.is_active:
            return Response(
                {'error': _('Cannot delete the last active MFA device')},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return super().destroy(request, *args, **kwargs)


class AuthSessionViewSet(PlatformViewSet):
    """
    ViewSet for managing authentication sessions.
    """
    serializer_class = AuthSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Get user's sessions"""
        return AuthSession.objects.filter(
            user=self.request.user
        ).order_by('-last_activity')
    
    @action(detail=True, methods=['post'])
    def terminate(self, request, pk=None):
        """Terminate a session"""
        session = self.get_object()
        
        # Check if terminating current session
        current_session_id = getattr(request.auth, 'payload', {}).get('session_id')
        if session.session_key == current_session_id:
            return Response(
                {'error': _('Cannot terminate current session. Use logout instead.')},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        session.terminate('user')
        
        return Response(
            {'detail': _('Session terminated')},
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=['post'])
    def terminate_all(self, request):
        """Terminate all other sessions"""
        current_session_id = getattr(request.auth, 'payload', {}).get('session_id')
        
        terminate_user_sessions(
            request.user,
            except_session=current_session_id,
            reason='user'
        )
        
        return Response(
            {'detail': _('All other sessions terminated')},
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=['get'])
    def current(self, request):
        """Get current session info"""
        session_id = getattr(request.auth, 'payload', {}).get('session_id')
        
        if not session_id:
            return Response(
                {'error': _('No session information available')},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            session = AuthSession.objects.get(
                session_key=session_id,
                user=request.user,
                is_active=True
            )
            return Response(
                AuthSessionSerializer(session).data,
                status=status.HTTP_200_OK
            )
        except AuthSession.DoesNotExist:
            return Response(
                {'error': _('Session not found')},
                status=status.HTTP_404_NOT_FOUND
            )


class OAuth2ClientViewSet(PlatformViewSet):
    """
    ViewSet for managing OAuth2 clients.
    """
    serializer_class = OAuth2ClientSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Get OAuth2 clients"""
        queryset = OAuth2Client.objects.all()
        
        # Filter by user's group if not admin
        if not self.request.user.is_staff:
            if hasattr(self.request.user, 'group'):
                queryset = queryset.filter(group=self.request.user.group)
            else:
                queryset = queryset.none()
        
        return queryset.order_by('-created_at')
    
    def create(self, request, *args, **kwargs):
        """Create OAuth2 client"""
        # Check permission
        if not request.user.has_perm('security.add_oauth2client'):
            return Response(
                {'error': _('Permission denied')},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().create(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    def regenerate_secret(self, request, pk=None):
        """Regenerate client secret"""
        import secrets
        
        client = self.get_object()
        
        # Check permission
        if not request.user.has_perm('security.change_oauth2client'):
            return Response(
                {'error': _('Permission denied')},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Generate new secret
        new_secret = secrets.token_urlsafe(32)
        client.client_secret = new_secret  # In production, encrypt this
        client.save()
        
        return Response(
            {'client_secret': new_secret},
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        """Revoke OAuth2 client"""
        client = self.get_object()
        
        # Check permission
        if not request.user.has_perm('security.change_oauth2client'):
            return Response(
                {'error': _('Permission denied')},
                status=status.HTTP_403_FORBIDDEN
            )
        
        client.is_active = False
        client.save()
        
        # TODO: Revoke all active tokens for this client
        
        return Response(
            {'detail': _('Client revoked')},
            status=status.HTTP_200_OK
        )