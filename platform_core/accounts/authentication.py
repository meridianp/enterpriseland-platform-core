"""
Custom JWT authentication backend that reads tokens from httpOnly cookies
"""
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework.authentication import CSRFCheck
from rest_framework import exceptions


class CookieJWTAuthentication(JWTAuthentication):
    """
    JWT authentication using httpOnly cookies instead of Authorization header
    """
    
    def authenticate(self, request):
        # Get access token from cookie
        raw_token = request.COOKIES.get('access_token')
        if raw_token is None:
            return None
            
        # Validate the token
        validated_token = self.get_validated_token(raw_token)
        
        # For cookie-based auth, we need to enforce CSRF protection
        self.enforce_csrf(request)
        
        # Get the user from the token
        return self.get_user(validated_token), validated_token
    
    def enforce_csrf(self, request):
        """
        Enforce CSRF validation for cookie-based authentication
        """
        # Skip CSRF check for safe methods
        if request.method in ['GET', 'HEAD', 'OPTIONS', 'TRACE']:
            return
            
        # Check CSRF token
        check = CSRFCheck()
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f'CSRF Failed: {reason}')