"""
Authentication middleware for token validation
"""
from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from .services import auth_service


class TokenBlacklistMiddleware(MiddlewareMixin):
    """
    Middleware to check if JWT tokens are blacklisted
    """
    
    def process_request(self, request):
        # Skip for paths that don't require authentication
        if request.path.startswith('/admin/') or request.path.startswith('/static/'):
            return None
        
        # Check Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            if not self._is_token_valid(token):
                # Invalid token, remove from request
                request.META.pop('HTTP_AUTHORIZATION', None)
        
        # Check cookie-based token
        access_token = request.COOKIES.get('access_token')
        if access_token and not self._is_token_valid(access_token):
            # Invalid token in cookie
            request._invalid_cookie_token = True
        
        return None
    
    def _is_token_valid(self, token: str) -> bool:
        """Check if token is valid and not blacklisted"""
        try:
            access = AccessToken(token)
            jti = access.payload.get('jti')
            
            # Check blacklist
            if jti and auth_service.blacklist_service.is_blacklisted(jti):
                return False
            
            return True
        except TokenError:
            return False