"""Custom permissions for document management API."""

from rest_framework import permissions
from ...services import PermissionService


class DocumentPermission(permissions.BasePermission):
    """Custom permission class for document operations."""
    
    def has_permission(self, request, view):
        """Check if user has permission to access documents."""
        # All authenticated users can access document endpoints
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        """Check if user has permission for specific document."""
        permission_service = PermissionService()
        
        # Map HTTP methods to permission types
        if request.method in permissions.SAFE_METHODS:
            # GET, HEAD, OPTIONS
            return permission_service.has_document_permission(
                request.user, obj, 'view'
            )
        elif request.method in ['PUT', 'PATCH']:
            # Update operations
            return permission_service.has_document_permission(
                request.user, obj, 'edit'
            )
        elif request.method == 'DELETE':
            return permission_service.has_document_permission(
                request.user, obj, 'delete'
            )
        
        # For custom actions, check in the view
        return True


class FolderPermission(permissions.BasePermission):
    """Custom permission class for folder operations."""
    
    def has_permission(self, request, view):
        """Check if user has permission to access folders."""
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        """Check if user has permission for specific folder."""
        permission_service = PermissionService()
        
        # Map HTTP methods to permission types
        if request.method in permissions.SAFE_METHODS:
            return permission_service.has_folder_permission(
                request.user, obj, 'view'
            )
        elif request.method in ['PUT', 'PATCH']:
            return permission_service.has_folder_permission(
                request.user, obj, 'edit'
            )
        elif request.method == 'DELETE':
            return permission_service.has_folder_permission(
                request.user, obj, 'delete'
            )
        
        return True


class TemplatePermission(permissions.BasePermission):
    """Custom permission class for template operations."""
    
    def has_permission(self, request, view):
        """Check if user has permission to access templates."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check for template management permission
        if request.method not in permissions.SAFE_METHODS:
            return request.user.has_perm('documents.manage_templates')
        
        return True
    
    def has_object_permission(self, request, view, obj):
        """Check if user has permission for specific template."""
        # System templates can't be modified
        if obj.is_system and request.method not in permissions.SAFE_METHODS:
            return False
        
        # Check if user can use the template
        if request.method in permissions.SAFE_METHODS:
            return obj.can_use(request.user)
        
        # Only template managers can modify
        return request.user.has_perm('documents.manage_templates')