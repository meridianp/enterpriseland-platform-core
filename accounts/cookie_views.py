"""
Cookie-based JWT authentication views
"""
from django.conf import settings
from django.utils import timezone
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from datetime import datetime, timedelta

from .models import User
from .serializers import UserSerializer, LoginSerializer


def set_cookie_params():
    """Get cookie parameters based on environment"""
    is_production = not settings.DEBUG
    
    return {
        'httponly': True,
        'samesite': 'Strict' if is_production else 'Lax',
        'secure': is_production,  # Only use secure in production
        'path': '/',
    }


@api_view(['POST'])
@permission_classes([AllowAny])
def cookie_login(request):
    """Login endpoint that sets JWT tokens in httpOnly cookies"""
    serializer = LoginSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    user = serializer.validated_data['user']
    
    # Update last login
    user.last_login_at = timezone.now()
    user.save()
    
    # Generate tokens
    refresh = RefreshToken.for_user(user)
    access_token = refresh.access_token
    
    # Create response
    response = Response({
        'user': UserSerializer(user).data,
        'csrf_token': get_token(request),
    })
    
    # Set cookie parameters
    cookie_params = set_cookie_params()
    
    # Set access token cookie (short-lived)
    response.set_cookie(
        key='access_token',
        value=str(access_token),
        max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
        **cookie_params
    )
    
    # Set refresh token cookie (long-lived)
    response.set_cookie(
        key='refresh_token',
        value=str(refresh),
        max_age=settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds(),
        **cookie_params
    )
    
    return response


@api_view(['POST'])
@permission_classes([AllowAny])
def cookie_refresh(request):
    """Refresh endpoint that reads refresh token from cookie"""
    refresh_token = request.COOKIES.get('refresh_token')
    
    if not refresh_token:
        return Response(
            {'error': 'Refresh token not found'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    try:
        # Create refresh token object
        refresh = RefreshToken(refresh_token)
        
        # Get new access token
        access_token = refresh.access_token
        
        # Create response with CSRF token
        response = Response({
            'csrf_token': get_token(request),
        })
        
        # Set cookie parameters
        cookie_params = set_cookie_params()
        
        # Update access token cookie
        response.set_cookie(
            key='access_token',
            value=str(access_token),
            max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
            **cookie_params
        )
        
        # If rotation is enabled, also update refresh token
        if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False):
            new_refresh = RefreshToken.for_user(refresh.token.user)
            response.set_cookie(
                key='refresh_token',
                value=str(new_refresh),
                max_age=settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds(),
                **cookie_params
            )
            
            # Blacklist old refresh token if configured
            if settings.SIMPLE_JWT.get('BLACKLIST_AFTER_ROTATION', False):
                try:
                    refresh.blacklist()
                except AttributeError:
                    pass
        
        return response
        
    except TokenError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cookie_logout(request):
    """Logout endpoint that clears JWT cookies"""
    refresh_token = request.COOKIES.get('refresh_token')
    
    # Try to blacklist the refresh token
    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            pass
    
    # Create response
    response = Response({'message': 'Successfully logged out'})
    
    # Clear cookies
    response.delete_cookie('access_token', path='/')
    response.delete_cookie('refresh_token', path='/')
    
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_csrf_token(request):
    """Get CSRF token for authenticated requests"""
    return Response({
        'csrf_token': get_token(request)
    })