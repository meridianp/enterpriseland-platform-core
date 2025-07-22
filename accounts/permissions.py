
from rest_framework import permissions
from .models import User

class IsOwnerOrReadOnly(permissions.BasePermission):
    """Custom permission to only allow owners of an object to edit it"""
    
    def has_object_permission(self, request, view, obj):
        # Read permissions for any request
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write permissions only to the owner
        return obj == request.user

class RoleBasedPermission(permissions.BasePermission):
    """Permission class based on user roles"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Admin can do everything
        if request.user.role == User.Role.ADMIN:
            return True
        
        # Define permissions by action and role
        action = getattr(view, 'action', None)
        user_role = request.user.role
        
        # Read permissions
        if action in ['list', 'retrieve']:
            return user_role in [
                User.Role.BUSINESS_ANALYST,
                User.Role.PORTFOLIO_MANAGER,
                User.Role.EXTERNAL_PARTNER,
                User.Role.AUDITOR,
                User.Role.READ_ONLY
            ]
        
        # Create permissions
        if action == 'create':
            return user_role in [
                User.Role.BUSINESS_ANALYST,
                User.Role.PORTFOLIO_MANAGER
            ]
        
        # Update permissions
        if action in ['update', 'partial_update']:
            return user_role in [
                User.Role.BUSINESS_ANALYST,
                User.Role.PORTFOLIO_MANAGER
            ]
        
        # Delete permissions
        if action == 'destroy':
            return user_role == User.Role.ADMIN
        
        # Approval permissions
        if action == 'approve':
            return user_role in [
                User.Role.PORTFOLIO_MANAGER
            ]
        
        return False

class GroupAccessPermission(permissions.BasePermission):
    """Permission to ensure users can only access data from their groups"""
    
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Admin can access everything
        if request.user.role == User.Role.ADMIN:
            return True
        
        # Check if object has group attribute
        if hasattr(obj, 'group'):
            user_groups = request.user.groups.all()
            return obj.group in user_groups
        
        # Check if object has group_id attribute
        if hasattr(obj, 'group_id'):
            user_group_ids = request.user.groups.values_list('id', flat=True)
            return obj.group_id in user_group_ids
        
        return True

class CanExportData(permissions.BasePermission):
    """Permission for data export functionality"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.can_export_data

class CanApproveAssessments(permissions.BasePermission):
    """Permission for assessment approval"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.can_approve_assessments

class IsAdminOrReadOnly(permissions.BasePermission):
    """Permission that allows read access to all authenticated users but write access only to admins"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if request.method in permissions.SAFE_METHODS:
            return True
        
        return request.user.role == User.Role.ADMIN

class IsManager(permissions.BasePermission):
    """Permission for manager-level users"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.role in [User.Role.PORTFOLIO_MANAGER, User.Role.ADMIN]

class IsAdmin(permissions.BasePermission):
    """Permission for admin users only"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.role == User.Role.ADMIN


class IsGroupMember(permissions.BasePermission):
    """Permission for users that are members of a group"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check if user has a group_id (for the custom user model)
        if hasattr(request.user, 'group_id'):
            return request.user.group_id is not None
        
        # Alternative: check if user is in any groups
        return request.user.groups.exists()
