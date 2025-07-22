"""Serializers for document management API."""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from ...models import (
    Document, DocumentVersion, DocumentTag,
    Folder, DocumentPermission, FolderPermission,
    SharedLink, DocumentTemplate, TemplateField,
    DocumentAudit, DocumentMetadata
)

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user references."""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'full_name']
        read_only_fields = fields


class GroupSerializer(serializers.ModelSerializer):
    """Serializer for group references."""
    
    class Meta:
        model = Group
        fields = ['id', 'name']
        read_only_fields = fields


class FolderSerializer(serializers.ModelSerializer):
    """Serializer for folder management."""
    
    created_by = UserSerializer(read_only=True)
    modified_by = UserSerializer(read_only=True)
    parent_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    parent = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()
    document_count_recursive = serializers.SerializerMethodField()
    total_size_recursive = serializers.SerializerMethodField()
    breadcrumb = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    
    class Meta:
        model = Folder
        fields = [
            'id', 'name', 'description', 'parent', 'parent_id', 'path',
            'is_system', 'color', 'icon', 'document_count', 'total_size',
            'inherit_permissions', 'default_retention_days',
            'children_count', 'document_count_recursive', 'total_size_recursive',
            'breadcrumb', 'can_delete', 'created_by', 'modified_by',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'path', 'document_count', 'total_size',
            'created_by', 'modified_by', 'created_at', 'updated_at'
        ]
    
    def get_parent(self, obj):
        """Get parent folder info."""
        if obj.parent:
            return {
                'id': str(obj.parent.id),
                'name': obj.parent.name,
                'path': obj.parent.path
            }
        return None
    
    def get_children_count(self, obj):
        """Get number of direct children."""
        return obj.get_children().count()
    
    def get_document_count_recursive(self, obj):
        """Get total document count including subfolders."""
        return obj.get_document_count_recursive()
    
    def get_total_size_recursive(self, obj):
        """Get total size including subfolders."""
        return obj.get_total_size_recursive()
    
    def get_breadcrumb(self, obj):
        """Get folder breadcrumb path."""
        ancestors = obj.get_ancestors_with_self()
        return [
            {
                'id': str(folder.id),
                'name': folder.name,
                'path': folder.path
            }
            for folder in ancestors
        ]
    
    def get_can_delete(self, obj):
        """Check if folder can be deleted."""
        return obj.can_delete()
    
    def create(self, validated_data):
        """Create folder with parent reference."""
        parent_id = validated_data.pop('parent_id', None)
        if parent_id:
            validated_data['parent'] = Folder.objects.get(id=parent_id)
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Update folder with parent reference."""
        parent_id = validated_data.pop('parent_id', None)
        if parent_id is not None:
            if parent_id:
                validated_data['parent'] = Folder.objects.get(id=parent_id)
            else:
                validated_data['parent'] = None
        
        return super().update(instance, validated_data)


class DocumentTagSerializer(serializers.ModelSerializer):
    """Serializer for document tags."""
    
    class Meta:
        model = DocumentTag
        fields = ['id', 'name', 'description', 'color', 'is_active', 'usage_count']
        read_only_fields = ['id', 'usage_count']


class DocumentMetadataSerializer(serializers.ModelSerializer):
    """Serializer for document metadata."""
    
    display_metadata = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentMetadata
        fields = [
            'id', 'title', 'author', 'subject', 'keywords',
            'creation_date', 'modification_date', 'page_count',
            'word_count', 'character_count', 'width', 'height',
            'duration', 'latitude', 'longitude', 'location_name',
            'producer', 'creator_tool', 'custom_fields',
            'extraction_status', 'extracted_at', 'display_metadata'
        ]
        read_only_fields = ['id', 'extraction_status', 'extracted_at']
    
    def get_display_metadata(self, obj):
        """Get formatted metadata for display."""
        return obj.get_display_metadata()


class DocumentVersionSerializer(serializers.ModelSerializer):
    """Serializer for document versions."""
    
    created_by = UserSerializer(read_only=True)
    restore_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentVersion
        fields = [
            'id', 'version_number', 'size', 'checksum', 'created_by',
            'comment', 'changes_summary', 'is_major_version',
            'created_at', 'restore_url', 'download_url'
        ]
        read_only_fields = ['id', 'version_number', 'size', 'checksum', 'created_by', 'created_at']
    
    def get_restore_url(self, obj):
        """Get URL to restore this version."""
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(
                f'/api/v1/documents/{obj.document.id}/versions/{obj.id}/restore/'
            )
        return None
    
    def get_download_url(self, obj):
        """Get URL to download this version."""
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(
                f'/api/v1/documents/{obj.document.id}/versions/{obj.id}/download/'
            )
        return None


class DocumentSerializer(serializers.ModelSerializer):
    """Serializer for documents."""
    
    created_by = UserSerializer(read_only=True)
    modified_by = UserSerializer(read_only=True)
    locked_by = UserSerializer(read_only=True)
    folder_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    folder = FolderSerializer(read_only=True)
    metadata = DocumentMetadataSerializer(read_only=True)
    latest_version = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id', 'name', 'description', 'folder', 'folder_id',
            'file_name', 'file_extension', 'mime_type', 'size',
            'checksum', 'status', 'is_deleted', 'deleted_at',
            'version_number', 'is_locked', 'locked_by', 'locked_at',
            'tags', 'category', 'language', 'content_extracted',
            'is_encrypted', 'virus_scanned', 'virus_scan_result',
            'preview_generated', 'ocr_processed', 'retention_date',
            'download_count', 'view_count', 'last_accessed',
            'created_by', 'modified_by', 'created_at', 'updated_at',
            'metadata', 'latest_version', 'permissions',
            'download_url', 'preview_url', 'share_url'
        ]
        read_only_fields = [
            'id', 'file_name', 'file_extension', 'mime_type', 'size',
            'checksum', 'is_deleted', 'deleted_at', 'version_number',
            'is_locked', 'locked_by', 'locked_at', 'content_extracted',
            'is_encrypted', 'virus_scanned', 'virus_scan_result',
            'preview_generated', 'ocr_processed', 'download_count',
            'view_count', 'last_accessed', 'created_by', 'modified_by',
            'created_at', 'updated_at'
        ]
    
    def get_latest_version(self, obj):
        """Get latest version info."""
        latest = obj.versions.first()
        if latest:
            return {
                'version_number': latest.version_number,
                'created_at': latest.created_at,
                'created_by': latest.created_by.get_full_name() if latest.created_by else None
            }
        return None
    
    def get_permissions(self, obj):
        """Get user's permissions on this document."""
        request = self.context.get('request')
        if request and request.user:
            from ...services import PermissionService
            permission_service = PermissionService()
            
            permissions = []
            for perm in ['view', 'download', 'edit', 'delete', 'share', 'manage']:
                if permission_service.has_document_permission(request.user, obj, perm):
                    permissions.append(perm)
            
            return permissions
        return []
    
    def get_download_url(self, obj):
        """Get document download URL."""
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(
                f'/api/v1/documents/{obj.id}/download/'
            )
        return None
    
    def get_preview_url(self, obj):
        """Get document preview URL."""
        request = self.context.get('request')
        if request and obj.preview_generated:
            return request.build_absolute_uri(
                f'/api/v1/documents/{obj.id}/preview/'
            )
        return None
    
    def get_share_url(self, obj):
        """Get document sharing URL."""
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(
                f'/api/v1/documents/{obj.id}/share/'
            )
        return None
    
    def create(self, validated_data):
        """Create document with folder reference."""
        folder_id = validated_data.pop('folder_id', None)
        if folder_id:
            validated_data['folder'] = Folder.objects.get(id=folder_id)
        
        return super().create(validated_data)


class DocumentUploadSerializer(serializers.Serializer):
    """Serializer for document upload."""
    
    file = serializers.FileField(required=True)
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    folder_id = serializers.UUIDField(required=False, allow_null=True)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list
    )
    category = serializers.CharField(max_length=50, required=False, allow_blank=True)
    encrypt = serializers.BooleanField(default=True)


class DocumentPermissionSerializer(serializers.ModelSerializer):
    """Serializer for document permissions."""
    
    user = UserSerializer(read_only=True)
    group = GroupSerializer(read_only=True)
    granted_by = UserSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    group_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = DocumentPermission
        fields = [
            'id', 'document', 'user', 'user_id', 'group', 'group_id',
            'permission', 'granted_by', 'expires_at', 'is_inherited',
            'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'document', 'granted_by', 'is_inherited', 'created_at', 'updated_at']
    
    def validate(self, attrs):
        """Validate permission data."""
        if not attrs.get('user_id') and not attrs.get('group_id'):
            raise serializers.ValidationError("Either user_id or group_id must be provided")
        
        if attrs.get('user_id') and attrs.get('group_id'):
            raise serializers.ValidationError("Cannot specify both user_id and group_id")
        
        return attrs
    
    def create(self, validated_data):
        """Create permission with user/group reference."""
        user_id = validated_data.pop('user_id', None)
        group_id = validated_data.pop('group_id', None)
        
        if user_id:
            validated_data['user'] = User.objects.get(id=user_id)
        elif group_id:
            validated_data['group'] = Group.objects.get(id=group_id)
        
        return super().create(validated_data)


class FolderPermissionSerializer(serializers.ModelSerializer):
    """Serializer for folder permissions."""
    
    user = UserSerializer(read_only=True)
    group = GroupSerializer(read_only=True)
    granted_by = UserSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    group_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = FolderPermission
        fields = [
            'id', 'folder', 'user', 'user_id', 'group', 'group_id',
            'permission', 'granted_by', 'expires_at', 'is_inherited',
            'apply_to_subfolders', 'apply_to_documents', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'folder', 'granted_by', 'is_inherited', 'created_at', 'updated_at']
    
    def validate(self, attrs):
        """Validate permission data."""
        if not attrs.get('user_id') and not attrs.get('group_id'):
            raise serializers.ValidationError("Either user_id or group_id must be provided")
        
        if attrs.get('user_id') and attrs.get('group_id'):
            raise serializers.ValidationError("Cannot specify both user_id and group_id")
        
        return attrs
    
    def create(self, validated_data):
        """Create permission with user/group reference."""
        user_id = validated_data.pop('user_id', None)
        group_id = validated_data.pop('group_id', None)
        
        if user_id:
            validated_data['user'] = User.objects.get(id=user_id)
        elif group_id:
            validated_data['group'] = Group.objects.get(id=group_id)
        
        return super().create(validated_data)


class SharedLinkSerializer(serializers.ModelSerializer):
    """Serializer for shared links."""
    
    created_by = UserSerializer(read_only=True)
    document = DocumentSerializer(read_only=True)
    folder = FolderSerializer(read_only=True)
    document_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    folder_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    public_url = serializers.SerializerMethodField()
    is_valid = serializers.SerializerMethodField()
    
    class Meta:
        model = SharedLink
        fields = [
            'id', 'token', 'document', 'document_id', 'folder', 'folder_id',
            'created_by', 'title', 'message', 'allow_view', 'allow_download',
            'allow_edit', 'require_authentication', 'allowed_emails',
            'password', 'max_downloads', 'max_views', 'expires_at',
            'view_count', 'download_count', 'last_accessed', 'is_active',
            'created_at', 'updated_at', 'public_url', 'is_valid'
        ]
        read_only_fields = [
            'id', 'token', 'created_by', 'view_count', 'download_count',
            'last_accessed', 'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'password': {'write_only': True}
        }
    
    def get_public_url(self, obj):
        """Get public URL for the shared link."""
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/shared/{obj.token}/')
        return None
    
    def get_is_valid(self, obj):
        """Check if link is still valid."""
        return obj.is_valid()
    
    def validate(self, attrs):
        """Validate shared link data."""
        if not attrs.get('document_id') and not attrs.get('folder_id'):
            raise serializers.ValidationError("Either document_id or folder_id must be provided")
        
        if attrs.get('document_id') and attrs.get('folder_id'):
            raise serializers.ValidationError("Cannot share both document and folder")
        
        if attrs.get('allow_edit') and not attrs.get('require_authentication'):
            raise serializers.ValidationError("Edit permission requires authentication")
        
        return attrs
    
    def create(self, validated_data):
        """Create shared link with document/folder reference."""
        document_id = validated_data.pop('document_id', None)
        folder_id = validated_data.pop('folder_id', None)
        
        if document_id:
            validated_data['document'] = Document.objects.get(id=document_id)
        elif folder_id:
            validated_data['folder'] = Folder.objects.get(id=folder_id)
        
        # Hash password if provided
        password = validated_data.get('password')
        if password:
            from django.contrib.auth.hashers import make_password
            validated_data['password'] = make_password(password)
        
        return super().create(validated_data)


class TemplateFieldSerializer(serializers.ModelSerializer):
    """Serializer for template fields."""
    
    class Meta:
        model = TemplateField
        fields = [
            'id', 'name', 'label', 'description', 'field_type',
            'is_required', 'is_active', 'default_value',
            'validation_rules', 'choices', 'order', 'placeholder',
            'document_property', 'template_variable'
        ]
        read_only_fields = ['id']


class DocumentTemplateSerializer(serializers.ModelSerializer):
    """Serializer for document templates."""
    
    created_by = UserSerializer(read_only=True)
    modified_by = UserSerializer(read_only=True)
    fields = TemplateFieldSerializer(many=True, read_only=True)
    can_use = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentTemplate
        fields = [
            'id', 'name', 'description', 'category', 'file_type',
            'is_active', 'is_system', 'usage_count', 'last_used',
            'preview_image', 'tags', 'is_public', 'created_by',
            'modified_by', 'created_at', 'updated_at', 'fields', 'can_use'
        ]
        read_only_fields = [
            'id', 'is_system', 'usage_count', 'last_used',
            'created_by', 'modified_by', 'created_at', 'updated_at'
        ]
    
    def get_can_use(self, obj):
        """Check if current user can use this template."""
        request = self.context.get('request')
        if request and request.user:
            return obj.can_use(request.user)
        return False


class TemplateUseSerializer(serializers.Serializer):
    """Serializer for using a template."""
    
    template_id = serializers.UUIDField(required=True)
    folder_id = serializers.UUIDField(required=False, allow_null=True)
    name = serializers.CharField(max_length=255, required=False)
    data = serializers.DictField(required=True)


class DocumentAuditSerializer(serializers.ModelSerializer):
    """Serializer for document audit logs."""
    
    user = UserSerializer(read_only=True)
    document = serializers.SerializerMethodField()
    folder = serializers.SerializerMethodField()
    changes = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentAudit
        fields = [
            'id', 'document', 'folder', 'action', 'user',
            'ip_address', 'session_id', 'details', 'old_values',
            'new_values', 'status', 'error_message', 'duration_ms',
            'batch_id', 'created_at', 'changes'
        ]
        read_only_fields = fields
    
    def get_document(self, obj):
        """Get document info if available."""
        if obj.document:
            return {
                'id': str(obj.document.id),
                'name': obj.document.name
            }
        return None
    
    def get_folder(self, obj):
        """Get folder info if available."""
        if obj.folder:
            return {
                'id': str(obj.folder.id),
                'name': obj.folder.name,
                'path': obj.folder.path
            }
        return None
    
    def get_changes(self, obj):
        """Get formatted changes."""
        return obj.get_changes()


class BulkOperationSerializer(serializers.Serializer):
    """Serializer for bulk operations."""
    
    document_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list
    )
    folder_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list
    )
    operation = serializers.ChoiceField(
        choices=['download', 'delete', 'move', 'tag', 'share'],
        required=True
    )
    target_folder_id = serializers.UUIDField(required=False, allow_null=True)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False
    )
    permanent = serializers.BooleanField(default=False)


class SearchSerializer(serializers.Serializer):
    """Serializer for document search."""
    
    query = serializers.CharField(required=True, min_length=2)
    category = serializers.CharField(required=False)
    file_extension = serializers.CharField(required=False)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False
    )
    created_after = serializers.DateTimeField(required=False)
    created_before = serializers.DateTimeField(required=False)
    size_min = serializers.IntegerField(required=False, min_value=0)
    size_max = serializers.IntegerField(required=False, min_value=0)
    folder_id = serializers.UUIDField(required=False)
    include_subfolders = serializers.BooleanField(default=True)