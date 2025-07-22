"""Permission service for document access control."""

from typing import List, Optional, Set
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from django.core.cache import cache

from ..models import Document, Folder, DocumentPermission, FolderPermission

User = get_user_model()


class PermissionService:
    """Service for managing document and folder permissions."""
    
    CACHE_TIMEOUT = 300  # 5 minutes
    
    def has_document_permission(
        self,
        user: User,
        document: Document,
        permission: str
    ) -> bool:
        """Check if user has specific permission on a document."""
        if not user or not user.is_authenticated:
            return False
        
        # Superusers have all permissions
        if user.is_superuser:
            return True
        
        # Document owner has all permissions
        if document.created_by == user:
            return True
        
        # Check cached permissions
        cache_key = f"doc_perm:{user.id}:{document.id}:{permission}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Check direct document permissions
        has_permission = self._check_document_permission(user, document, permission)
        
        # If not found, check folder permissions
        if not has_permission and document.folder:
            has_permission = self._check_folder_permission_recursive(
                user, document.folder, permission, check_documents=True
            )
        
        # Cache result
        cache.set(cache_key, has_permission, self.CACHE_TIMEOUT)
        
        return has_permission
    
    def has_folder_permission(
        self,
        user: User,
        folder: Folder,
        permission: str
    ) -> bool:
        """Check if user has specific permission on a folder."""
        if not user or not user.is_authenticated:
            return False
        
        # Superusers have all permissions
        if user.is_superuser:
            return True
        
        # Folder creator has all permissions
        if folder.created_by == user:
            return True
        
        # Check cached permissions
        cache_key = f"folder_perm:{user.id}:{folder.id}:{permission}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Check folder permissions recursively
        has_permission = self._check_folder_permission_recursive(
            user, folder, permission, check_documents=False
        )
        
        # Cache result
        cache.set(cache_key, has_permission, self.CACHE_TIMEOUT)
        
        return has_permission
    
    def _check_document_permission(
        self,
        user: User,
        document: Document,
        permission: str
    ) -> bool:
        """Check direct document permissions."""
        now = timezone.now()
        
        # Check user permissions
        user_perms = DocumentPermission.objects.filter(
            document=document,
            user=user,
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
        
        for perm in user_perms:
            if perm.has_permission(permission):
                return True
        
        # Check group permissions
        user_groups = user.groups.all()
        group_perms = DocumentPermission.objects.filter(
            document=document,
            group__in=user_groups,
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
        
        for perm in group_perms:
            if perm.has_permission(permission):
                return True
        
        return False
    
    def _check_folder_permission_recursive(
        self,
        user: User,
        folder: Folder,
        permission: str,
        check_documents: bool
    ) -> bool:
        """Check folder permissions recursively up the tree."""
        current_folder = folder
        
        while current_folder:
            # Check direct folder permissions
            if self._check_folder_permission(user, current_folder, permission, check_documents):
                return True
            
            # Move up the tree if permissions are inherited
            if current_folder.inherit_permissions and current_folder.parent:
                current_folder = current_folder.parent
            else:
                break
        
        return False
    
    def _check_folder_permission(
        self,
        user: User,
        folder: Folder,
        permission: str,
        check_documents: bool
    ) -> bool:
        """Check direct folder permissions."""
        now = timezone.now()
        
        # Check user permissions
        user_perms = FolderPermission.objects.filter(
            folder=folder,
            user=user,
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
        
        if check_documents:
            user_perms = user_perms.filter(apply_to_documents=True)
        
        for perm in user_perms:
            if perm.has_permission(permission):
                return True
        
        # Check group permissions
        user_groups = user.groups.all()
        group_perms = FolderPermission.objects.filter(
            folder=folder,
            group__in=user_groups,
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
        
        if check_documents:
            group_perms = group_perms.filter(apply_to_documents=True)
        
        for perm in group_perms:
            if perm.has_permission(permission):
                return True
        
        return False
    
    def get_accessible_document_ids(self, user: User) -> List[str]:
        """Get all document IDs the user can access."""
        if not user or not user.is_authenticated:
            return []
        
        if user.is_superuser:
            return list(Document.objects.values_list('id', flat=True))
        
        # Cache key for user's accessible documents
        cache_key = f"accessible_docs:{user.id}"
        cached_ids = cache.get(cache_key)
        if cached_ids is not None:
            return cached_ids
        
        accessible_ids = set()
        now = timezone.now()
        
        # Documents created by user
        accessible_ids.update(
            Document.objects.filter(
                created_by=user,
                is_deleted=False
            ).values_list('id', flat=True)
        )
        
        # Documents with direct user permissions
        accessible_ids.update(
            DocumentPermission.objects.filter(
                user=user,
                Q(expires_at__isnull=True) | Q(expires_at__gt=now)
            ).values_list('document_id', flat=True)
        )
        
        # Documents with group permissions
        user_groups = user.groups.all()
        accessible_ids.update(
            DocumentPermission.objects.filter(
                group__in=user_groups,
                Q(expires_at__isnull=True) | Q(expires_at__gt=now)
            ).values_list('document_id', flat=True)
        )
        
        # Documents in folders with permissions
        accessible_folders = self._get_accessible_folders(user)
        for folder_id in accessible_folders:
            accessible_ids.update(
                Document.objects.filter(
                    folder_id=folder_id,
                    is_deleted=False
                ).values_list('id', flat=True)
            )
        
        # Convert to list
        document_ids = list(accessible_ids)
        
        # Cache result
        cache.set(cache_key, document_ids, self.CACHE_TIMEOUT)
        
        return document_ids
    
    def _get_accessible_folders(self, user: User) -> Set[str]:
        """Get all folder IDs the user can access."""
        accessible_folders = set()
        now = timezone.now()
        
        # Folders created by user
        accessible_folders.update(
            Folder.objects.filter(
                created_by=user
            ).values_list('id', flat=True)
        )
        
        # Folders with direct user permissions
        folder_perms = FolderPermission.objects.filter(
            user=user,
            apply_to_documents=True,
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        ).select_related('folder')
        
        for perm in folder_perms:
            accessible_folders.add(perm.folder_id)
            if perm.apply_to_subfolders:
                # Add all descendant folders
                accessible_folders.update(
                    perm.folder.get_descendants().values_list('id', flat=True)
                )
        
        # Folders with group permissions
        user_groups = user.groups.all()
        group_folder_perms = FolderPermission.objects.filter(
            group__in=user_groups,
            apply_to_documents=True,
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        ).select_related('folder')
        
        for perm in group_folder_perms:
            accessible_folders.add(perm.folder_id)
            if perm.apply_to_subfolders:
                # Add all descendant folders
                accessible_folders.update(
                    perm.folder.get_descendants().values_list('id', flat=True)
                )
        
        return accessible_folders
    
    def grant_document_permission(
        self,
        document: Document,
        permission: str,
        granted_by: User,
        user: Optional[User] = None,
        group: Optional[Group] = None,
        expires_at: Optional[datetime] = None,
        notes: str = ''
    ) -> DocumentPermission:
        """Grant permission on a document."""
        if not user and not group:
            raise ValueError("Either user or group must be specified")
        
        if user and group:
            raise ValueError("Cannot specify both user and group")
        
        # Check if granter has manage permission
        if not self.has_document_permission(granted_by, document, 'manage'):
            raise PermissionError("You don't have permission to manage document permissions")
        
        # Create or update permission
        perm, created = DocumentPermission.objects.update_or_create(
            document=document,
            user=user,
            group=group,
            permission=permission,
            defaults={
                'granted_by': granted_by,
                'expires_at': expires_at,
                'notes': notes,
                'is_inherited': False
            }
        )
        
        # Clear cache
        if user:
            cache_pattern = f"doc_perm:{user.id}:{document.id}:*"
            cache.delete_pattern(cache_pattern)
        
        # Log permission grant
        from ..models import DocumentAudit
        DocumentAudit.log_permission_change(
            permission=perm,
            action='permission_granted'
        )
        
        return perm
    
    def grant_folder_permission(
        self,
        folder: Folder,
        permission: str,
        granted_by: User,
        user: Optional[User] = None,
        group: Optional[Group] = None,
        expires_at: Optional[datetime] = None,
        apply_to_subfolders: bool = True,
        apply_to_documents: bool = True,
        notes: str = ''
    ) -> FolderPermission:
        """Grant permission on a folder."""
        if not user and not group:
            raise ValueError("Either user or group must be specified")
        
        if user and group:
            raise ValueError("Cannot specify both user and group")
        
        # Check if granter has manage permission
        if not self.has_folder_permission(granted_by, folder, 'manage'):
            raise PermissionError("You don't have permission to manage folder permissions")
        
        # Create or update permission
        perm, created = FolderPermission.objects.update_or_create(
            folder=folder,
            user=user,
            group=group,
            permission=permission,
            defaults={
                'granted_by': granted_by,
                'expires_at': expires_at,
                'apply_to_subfolders': apply_to_subfolders,
                'apply_to_documents': apply_to_documents,
                'notes': notes,
                'is_inherited': False
            }
        )
        
        # Propagate to children if requested
        if created or perm.apply_to_subfolders or perm.apply_to_documents:
            perm.propagate_to_children()
        
        # Clear cache
        if user:
            cache_pattern = f"folder_perm:{user.id}:{folder.id}:*"
            cache.delete_pattern(cache_pattern)
            cache.delete(f"accessible_docs:{user.id}")
        
        # Log permission grant
        from ..models import DocumentAudit
        DocumentAudit.log_permission_change(
            permission=perm,
            action='permission_granted'
        )
        
        return perm
    
    def revoke_permission(self, permission, revoked_by: User) -> None:
        """Revoke a permission."""
        # Check if user can revoke
        if hasattr(permission, 'document'):
            if not self.has_document_permission(revoked_by, permission.document, 'manage'):
                raise PermissionError("You don't have permission to manage document permissions")
        else:
            if not self.has_folder_permission(revoked_by, permission.folder, 'manage'):
                raise PermissionError("You don't have permission to manage folder permissions")
        
        # Log revocation
        from ..models import DocumentAudit
        DocumentAudit.log_permission_change(
            permission=permission,
            action='permission_revoked'
        )
        
        # Clear cache
        if permission.user:
            cache.delete_pattern(f"*:{permission.user.id}:*")
        
        # Delete permission
        permission.delete()
    
    def get_document_permissions(self, document: Document) -> List[Dict]:
        """Get all permissions for a document."""
        permissions = []
        
        # Direct permissions
        for perm in document.permissions.select_related('user', 'group', 'granted_by'):
            permissions.append({
                'type': 'direct',
                'user': perm.user,
                'group': perm.group,
                'permission': perm.permission,
                'granted_by': perm.granted_by,
                'expires_at': perm.expires_at,
                'is_inherited': False
            })
        
        # Inherited permissions from folders
        if document.folder:
            folder = document.folder
            while folder:
                for perm in folder.permissions.filter(apply_to_documents=True).select_related('user', 'group', 'granted_by'):
                    permissions.append({
                        'type': 'inherited',
                        'source': folder,
                        'user': perm.user,
                        'group': perm.group,
                        'permission': perm.permission,
                        'granted_by': perm.granted_by,
                        'expires_at': perm.expires_at,
                        'is_inherited': True
                    })
                
                if folder.inherit_permissions and folder.parent:
                    folder = folder.parent
                else:
                    break
        
        return permissions