"""
Consolidated authentication views with JWT/Cookie hybrid approach
"""
from django.conf import settings
from django.middleware import csrf
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .models import User
from .serializers import UserSerializer, LoginSerializer
from .services import auth_service


class AuthenticationThrottle(AnonRateThrottle):
    """Strict rate limiting for authentication endpoints"""
    rate = '10/hour'


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthenticationThrottle])
def login_view(request):
    """
    Login endpoint supporting both JWT and cookie-based authentication
    
    POST /api/auth/login/
    {
        "email": "user@example.com",
        "password": "password",
        "use_cookies": true  // Optional, defaults to false
    }
    """
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    email = serializer.validated_data['email']
    password = serializer.validated_data['password']
    use_cookies = request.data.get('use_cookies', False)
    
    try:
        # Authenticate user
        user, tokens = auth_service.authenticate_user(email, password, request)
        
        # Check if MFA is required
        if isinstance(tokens, dict) and tokens.get('mfa_required'):
            return Response({
                'mfa_required': True,
                'user_id': tokens['user_id'],
                'methods': tokens['methods'],
            }, status=status.HTTP_200_OK)
        
        # Check for suspicious activity
        if auth_service.check_suspicious_activity(user, request):
            # Could implement additional verification here
            pass
        
        # Prepare response
        response_data = {
            'user': UserSerializer(user).data,
            'access_expires_at': tokens['access_expires_at'],
            'refresh_expires_at': tokens['refresh_expires_at'],
        }
        
        # Include tokens in response body for JWT mode
        if not use_cookies:
            response_data['access'] = tokens['access']
            response_data['refresh'] = tokens['refresh']
        
        response = Response(response_data, status=status.HTTP_200_OK)
        
        # Set httpOnly cookies if requested
        if use_cookies:
            # Access token cookie
            response.set_cookie(
                key='access_token',
                value=tokens['access'],
                max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
                httponly=True,
                secure=not settings.DEBUG,  # HTTPS only in production
                samesite='Lax' if settings.DEBUG else 'Strict',
                path='/api/'
            )
            
            # Refresh token cookie
            response.set_cookie(
                key='refresh_token',
                value=tokens['refresh'],
                max_age=settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds(),
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax' if settings.DEBUG else 'Strict',
                path='/api/auth/'  # More restrictive path for refresh
            )
            
            # Set CSRF token
            csrf_token = auth_service.get_csrf_token(request)
            response.set_cookie(
                key='csrftoken',
                value=csrf_token,
                max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
                httponly=False,  # Frontend needs to read this
                secure=not settings.DEBUG,
                samesite='Lax' if settings.DEBUG else 'Strict',
                path='/'
            )
            response['X-CSRF-Token'] = csrf_token
        
        return response
        
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_401_UNAUTHORIZED
        )
    except Exception as e:
        return Response(
            {'error': 'Authentication failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_view(request):
    """
    Refresh access token
    
    POST /api/auth/refresh/
    {
        "refresh": "refresh_token"  // For JWT mode
    }
    
    Or with cookies: token read from httpOnly cookie
    """
    # Try to get refresh token from cookie first
    refresh_token = request.COOKIES.get('refresh_token')
    use_cookies = bool(refresh_token)
    
    # Fall back to request body
    if not refresh_token:
        refresh_token = request.data.get('refresh')
    
    if not refresh_token:
        return Response(
            {'error': 'Refresh token required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        tokens = auth_service.refresh_tokens(refresh_token, request)
        
        response_data = {
            'access_expires_at': tokens['access_expires_at'],
        }
        
        # Include access token in response for JWT mode
        if not use_cookies:
            response_data['access'] = tokens['access']
            if 'refresh' in tokens:  # New refresh token if rotation is enabled
                response_data['refresh'] = tokens['refresh']
        
        response = Response(response_data, status=status.HTTP_200_OK)
        
        # Update cookies if using cookie mode
        if use_cookies:
            response.set_cookie(
                key='access_token',
                value=tokens['access'],
                max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax' if settings.DEBUG else 'Strict',
                path='/api/'
            )
            
            # Update refresh token if rotated
            if 'refresh' in tokens:
                response.set_cookie(
                    key='refresh_token',
                    value=tokens['refresh'],
                    max_age=settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds(),
                    httponly=True,
                    secure=not settings.DEBUG,
                    samesite='Lax' if settings.DEBUG else 'Strict',
                    path='/api/auth/'
                )
            
            # Update CSRF token
            csrf_token = auth_service.get_csrf_token(request)
            response.set_cookie(
                key='csrftoken',
                value=csrf_token,
                max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
                httponly=False,
                secure=not settings.DEBUG,
                samesite='Lax' if settings.DEBUG else 'Strict',
                path='/'
            )
            response['X-CSRF-Token'] = csrf_token
        
        return response
        
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    Logout user and invalidate tokens
    
    POST /api/auth/logout/
    {
        "refresh": "refresh_token"  // Optional for JWT mode
    }
    """
    # Get tokens
    access_token = request.COOKIES.get('access_token') or request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '')
    refresh_token = request.COOKIES.get('refresh_token') or request.data.get('refresh')
    
    # Logout user
    auth_service.logout_user(
        request.user,
        {'access': access_token, 'refresh': refresh_token},
        request
    )
    
    response = Response(
        {'message': 'Successfully logged out'},
        status=status.HTTP_200_OK
    )
    
    # Clear cookies if they exist
    if 'access_token' in request.COOKIES:
        response.delete_cookie('access_token', path='/api/')
    if 'refresh_token' in request.COOKIES:
        response.delete_cookie('refresh_token', path='/api/auth/')
    if 'csrftoken' in request.COOKIES:
        response.delete_cookie('csrftoken', path='/')
    
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_view(request):
    """
    Get current user profile
    
    GET /api/auth/me/
    """
    return Response(UserSerializer(request.user).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def csrf_token_view(request):
    """
    Get CSRF token for cookie-based authentication
    
    GET /api/auth/csrf/
    """
    csrf_token = csrf.get_token(request)
    
    response = Response({'csrf_token': csrf_token})
    
    # Also set as cookie
    response.set_cookie(
        key='csrftoken',
        value=csrf_token,
        max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
        httponly=False,  # Frontend needs to read this
        secure=not settings.DEBUG,
        samesite='Lax' if settings.DEBUG else 'Strict',
        path='/'
    )
    
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verify_token_view(request):
    """
    Verify if current token is valid
    
    GET /api/auth/verify/
    """
    # Token is valid if we get here (IsAuthenticated permission)
    return Response({
        'valid': True,
        'user': UserSerializer(request.user).data
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def complete_mfa_login_view(request):
    """
    Complete login after MFA verification
    
    POST /api/auth/mfa/complete/
    {
        "user_id": "uuid",
        "session_token": "token_from_mfa_verify",
        "use_cookies": true  // Optional
    }
    """
    user_id = request.data.get('user_id')
    session_token = request.data.get('session_token')
    use_cookies = request.data.get('use_cookies', False)
    
    if not user_id or not session_token:
        return Response(
            {'error': 'User ID and session token are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Complete MFA login
        user, tokens = auth_service.complete_mfa_login(user_id, session_token, request)
        
        # Prepare response
        response_data = {
            'user': UserSerializer(user).data,
            'access_expires_at': tokens['access_expires_at'],
            'refresh_expires_at': tokens['refresh_expires_at'],
        }
        
        # Include tokens in response body for JWT mode
        if not use_cookies:
            response_data['access'] = tokens['access']
            response_data['refresh'] = tokens['refresh']
        
        response = Response(response_data, status=status.HTTP_200_OK)
        
        # Set httpOnly cookies if requested
        if use_cookies:
            # Access token cookie
            response.set_cookie(
                key='access_token',
                value=tokens['access'],
                max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax' if settings.DEBUG else 'Strict',
                path='/api/'
            )
            
            # Refresh token cookie
            response.set_cookie(
                key='refresh_token',
                value=tokens['refresh'],
                max_age=settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds(),
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax' if settings.DEBUG else 'Strict',
                path='/api/auth/'
            )
            
            # Set CSRF token
            csrf_token = auth_service.get_csrf_token(request)
            response.set_cookie(
                key='csrftoken',
                value=csrf_token,
                max_age=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(),
                httponly=False,
                secure=not settings.DEBUG,
                samesite='Lax' if settings.DEBUG else 'Strict',
                path='/'
            )
            response['X-CSRF-Token'] = csrf_token
        
        return response
        
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_401_UNAUTHORIZED
        )
    except Exception as e:
        return Response(
            {'error': 'Authentication failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )