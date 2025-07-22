"""
Permission classes for API Key authentication.

Provides scope-based permissions that work with DRF permission system.
"""

from rest_framework import permissions
from rest_framework.request import Request

from .models import APIKey


class HasAPIKeyScope(permissions.BasePermission):
    """
    Base permission class that checks for API key scopes.
    
    Usage:
        class MyViewSet(viewsets.ModelViewSet):
            permission_classes = [HasAPIKeyScope]
            required_scopes = ['read', 'assessments:read']
    """
    
    def has_permission(self, request: Request, view) -> bool:
        """Check if the request has the required API key scopes."""
        # If not authenticated via API key, defer to other auth methods
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True  # Let other permission classes handle it
        
        # Get required scopes from the view
        required_scopes = getattr(view, 'required_scopes', [])
        if not required_scopes:
            # If no scopes required, any valid API key is sufficient
            return True
        
        api_key = request.auth
        
        # Check if the API key has any of the required scopes
        return api_key.has_any_scope(required_scopes)
    
    def has_object_permission(self, request: Request, view, obj) -> bool:
        """Check object-level permissions."""
        # For API keys, object permissions are the same as view permissions
        return self.has_permission(request, view)


class ReadOnlyAPIKey(HasAPIKeyScope):
    """Permission that allows read-only access for API keys."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check for read permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        # Allow safe methods with read scope
        if request.method in permissions.SAFE_METHODS:
            return request.auth.has_scope('read')
        
        # Deny write operations
        return False


class WriteAPIKey(HasAPIKeyScope):
    """Permission that requires write scope for API keys."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check for write permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        api_key = request.auth
        
        # Safe methods only need read scope
        if request.method in permissions.SAFE_METHODS:
            return api_key.has_scope('read')
        
        # Write methods need write scope
        return api_key.has_scope('write')


class AdminAPIKey(HasAPIKeyScope):
    """Permission that requires admin scope for API keys."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check for admin permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        # Admin scope required for all operations
        return request.auth.has_scope('admin')


# Resource-specific permission classes
class AssessmentsAPIKeyPermission(HasAPIKeyScope):
    """Permission for assessments API endpoints."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check assessments permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        api_key = request.auth
        
        if request.method in permissions.SAFE_METHODS:
            return api_key.has_any_scope(['read', 'assessments:read', 'admin'])
        else:
            return api_key.has_any_scope(['write', 'assessments:write', 'admin'])


class LeadsAPIKeyPermission(HasAPIKeyScope):
    """Permission for leads API endpoints."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check leads permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        api_key = request.auth
        
        if request.method in permissions.SAFE_METHODS:
            return api_key.has_any_scope(['read', 'leads:read', 'admin'])
        else:
            return api_key.has_any_scope(['write', 'leads:write', 'admin'])


class MarketIntelAPIKeyPermission(HasAPIKeyScope):
    """Permission for market intelligence API endpoints."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check market intelligence permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        api_key = request.auth
        
        if request.method in permissions.SAFE_METHODS:
            return api_key.has_any_scope(['read', 'market_intel:read', 'admin'])
        else:
            return api_key.has_any_scope(['write', 'market_intel:write', 'admin'])


class DealsAPIKeyPermission(HasAPIKeyScope):
    """Permission for deals API endpoints."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check deals permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        api_key = request.auth
        
        if request.method in permissions.SAFE_METHODS:
            return api_key.has_any_scope(['read', 'deals:read', 'admin'])
        else:
            return api_key.has_any_scope(['write', 'deals:write', 'admin'])


class ContactsAPIKeyPermission(HasAPIKeyScope):
    """Permission for contacts API endpoints."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check contacts permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        api_key = request.auth
        
        if request.method in permissions.SAFE_METHODS:
            return api_key.has_any_scope(['read', 'contacts:read', 'admin'])
        else:
            return api_key.has_any_scope(['write', 'contacts:write', 'admin'])


class FilesAPIKeyPermission(HasAPIKeyScope):
    """Permission for files API endpoints."""
    
    def has_permission(self, request: Request, view) -> bool:
        """Check files permissions."""
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return True
        
        api_key = request.auth
        
        if request.method in permissions.SAFE_METHODS:
            return api_key.has_any_scope(['read', 'files:read', 'admin'])
        elif request.method == 'DELETE':
            return api_key.has_any_scope(['delete', 'files:delete', 'admin'])
        else:
            return api_key.has_any_scope(['write', 'files:write', 'admin'])


# Utility function to get permission class for resource
def get_permission_class_for_resource(resource_name: str):
    """
    Get the appropriate permission class for a resource.
    
    Args:
        resource_name: Name of the resource (e.g., 'assessments', 'leads')
    
    Returns:
        Permission class for the resource
    """
    permission_map = {
        'assessments': AssessmentsAPIKeyPermission,
        'leads': LeadsAPIKeyPermission,
        'market_intel': MarketIntelAPIKeyPermission,
        'deals': DealsAPIKeyPermission,
        'contacts': ContactsAPIKeyPermission,
        'files': FilesAPIKeyPermission,
    }
    
    return permission_map.get(resource_name, HasAPIKeyScope)