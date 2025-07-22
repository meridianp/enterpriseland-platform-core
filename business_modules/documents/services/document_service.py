"""Document service for core document operations."""

import os
import shutil
import mimetypes
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, BinaryIO
from django.db import transaction
from django.db.models import Q, F
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings

from ..models import Document, DocumentVersion, Folder, DocumentAudit, DocumentMetadata
from .storage_service import StorageService
from .permission_service import PermissionService
from .virus_scan_service import VirusScanService
from .encryption_service import EncryptionService
from .metadata_service import MetadataService
from .search_service import SearchService


class DocumentService:
    """Service for managing documents."""
    
    def __init__(self):
        self.storage_service = StorageService()
        self.permission_service = PermissionService()
        self.virus_scan_service = VirusScanService()
        self.encryption_service = EncryptionService()
        self.metadata_service = MetadataService()
        self.search_service = SearchService()
    
    @transaction.atomic
    def create_document(
        self, 
        file: BinaryIO,
        name: str,
        user,
        folder: Optional[Folder] = None,
        description: str = '',
        tags: List[str] = None,
        category: str = '',
        encrypt: bool = True,
        **kwargs
    ) -> Document:
        """Create a new document."""
        # Read file content
        file_content = file.read()
        file.seek(0)  # Reset for other operations
        
        # Extract file info
        file_name = getattr(file, 'name', name)
        _, file_extension = os.path.splitext(file_name)
        file_extension = file_extension.lower().lstrip('.')
        
        # Validate file extension
        allowed_extensions = getattr(
            settings, 
            'DOCUMENTS_ALLOWED_EXTENSIONS',
            ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'jpg', 'png']
        )
        if file_extension not in allowed_extensions:
            raise ValidationError(f"File type '.{file_extension}' is not allowed")
        
        # Check file size
        max_size = getattr(settings, 'DOCUMENTS_MAX_FILE_SIZE', 52428800)  # 50MB
        if len(file_content) > max_size:
            raise ValidationError(f"File size exceeds maximum allowed size of {max_size} bytes")
        
        # Scan for viruses
        if getattr(settings, 'DOCUMENTS_VIRUS_SCAN_ENABLED', True):
            scan_result = self.virus_scan_service.scan_file(file_content)
            if scan_result['status'] == 'infected':
                raise ValidationError(f"File is infected with virus: {scan_result.get('virus_name', 'Unknown')}")
        
        # Encrypt if requested
        encryption_key_id = None
        if encrypt and getattr(settings, 'DOCUMENTS_ENCRYPTION_ENABLED', True):
            encrypted_data = self.encryption_service.encrypt_file(file_content)
            file_content = encrypted_data['encrypted_content']
            encryption_key_id = encrypted_data['key_id']
        
        # Generate storage path
        storage_path = self.storage_service.generate_path(
            file_name=file_name,
            folder=folder,
            user=user
        )
        
        # Upload to storage
        upload_result = self.storage_service.upload_file(
            file_content=file_content,
            path=storage_path,
            content_type=mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
        )
        
        # Create document record
        document = Document(
            name=name,
            description=description,
            folder=folder,
            file_path=upload_result['path'],
            file_name=file_name,
            file_extension=file_extension,
            mime_type=upload_result['content_type'],
            size=len(file_content),
            checksum=document.calculate_checksum(file_content),
            tags=tags or [],
            category=category,
            group=user.group,
            created_by=user,
            modified_by=user,
            is_encrypted=encrypt,
            encryption_key_id=encryption_key_id,
            virus_scanned=True,
            virus_scan_result='clean',
            **kwargs
        )
        document.save()
        
        # Create metadata record
        DocumentMetadata.objects.create(document=document)
        
        # Extract metadata asynchronously
        from ..tasks import extract_document_metadata
        extract_document_metadata.delay(document.id)
        
        # Generate preview asynchronously
        if getattr(settings, 'DOCUMENTS_PREVIEW_ENABLED', True):
            from ..tasks import generate_document_preview
            generate_document_preview.delay(document.id)
        
        # Extract text for search
        from ..tasks import extract_document_text
        extract_document_text.delay(document.id)
        
        # Log creation
        DocumentAudit.log(
            action='created',
            user=user,
            document=document,
            details={
                'file_name': file_name,
                'size': document.size,
                'folder': folder.name if folder else 'Root'
            }
        )
        
        # Update folder statistics
        if folder:
            folder.update_statistics()
        
        return document
    
    def get_document(self, document_id: str, user) -> Document:
        """Get a document by ID with permission check."""
        document = Document.objects.get(id=document_id)
        
        if not self.permission_service.has_document_permission(user, document, 'view'):
            raise PermissionError("You don't have permission to view this document")
        
        return document
    
    def update_document(
        self,
        document: Document,
        user,
        name: Optional[str] = None,
        description: Optional[str] = None,
        folder: Optional[Folder] = None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        **kwargs
    ) -> Document:
        """Update document metadata."""
        if not self.permission_service.has_document_permission(user, document, 'edit'):
            raise PermissionError("You don't have permission to edit this document")
        
        # Track changes
        old_values = {}
        new_values = {}
        
        if name and name != document.name:
            old_values['name'] = document.name
            new_values['name'] = name
            document.name = name
        
        if description is not None and description != document.description:
            old_values['description'] = document.description
            new_values['description'] = description
            document.description = description
        
        if folder is not None and folder != document.folder:
            old_values['folder'] = document.folder.name if document.folder else 'Root'
            new_values['folder'] = folder.name if folder else 'Root'
            
            # Update folder statistics
            old_folder = document.folder
            document.folder = folder
            
            if old_folder:
                old_folder.update_statistics()
            if folder:
                folder.update_statistics()
        
        if tags is not None:
            old_values['tags'] = document.tags
            new_values['tags'] = tags
            document.tags = tags
        
        if category is not None:
            old_values['category'] = document.category
            new_values['category'] = category
            document.category = category
        
        # Update other fields
        for key, value in kwargs.items():
            if hasattr(document, key):
                setattr(document, key, value)
        
        document.modified_by = user
        document.save()
        
        # Log update
        if old_values:
            DocumentAudit.log(
                action='updated',
                user=user,
                document=document,
                old_values=old_values,
                new_values=new_values
            )
        
        return document
    
    @transaction.atomic
    def create_version(
        self,
        document: Document,
        file: BinaryIO,
        user,
        comment: str = '',
        is_major_version: bool = False
    ) -> DocumentVersion:
        """Create a new version of a document."""
        if not self.permission_service.has_document_permission(user, document, 'edit'):
            raise PermissionError("You don't have permission to edit this document")
        
        if document.is_locked and document.locked_by != user:
            raise ValidationError(f"Document is locked by {document.locked_by}")
        
        # Read file content
        file_content = file.read()
        
        # Validate file type matches
        file_name = getattr(file, 'name', document.file_name)
        _, file_extension = os.path.splitext(file_name)
        if file_extension.lower().lstrip('.') != document.file_extension:
            raise ValidationError("File type must match the original document")
        
        # Scan for viruses
        if getattr(settings, 'DOCUMENTS_VIRUS_SCAN_ENABLED', True):
            scan_result = self.virus_scan_service.scan_file(file_content)
            if scan_result['status'] == 'infected':
                raise ValidationError(f"File is infected with virus: {scan_result.get('virus_name', 'Unknown')}")
        
        # Encrypt if document is encrypted
        if document.is_encrypted:
            encrypted_data = self.encryption_service.encrypt_file(file_content)
            file_content = encrypted_data['encrypted_content']
        
        # Generate version path
        version_path = self.storage_service.generate_version_path(
            document=document,
            version_number=document.version_number + 1
        )
        
        # Upload version file
        upload_result = self.storage_service.upload_file(
            file_content=file_content,
            path=version_path,
            content_type=document.mime_type
        )
        
        # Create version record for current document state
        current_version = DocumentVersion.objects.create(
            document=document,
            version_number=document.version_number,
            file_path=document.file_path,
            size=document.size,
            checksum=document.checksum,
            created_by=document.modified_by or document.created_by,
            comment="Previous version",
            is_major_version=False
        )
        
        # Update document with new version
        document.version_number += 1
        document.file_path = upload_result['path']
        document.size = len(file_content)
        document.checksum = document.calculate_checksum(file_content)
        document.modified_by = user
        document.save()
        
        # Create version record for new version
        new_version = DocumentVersion.objects.create(
            document=document,
            version_number=document.version_number,
            file_path=upload_result['path'],
            size=len(file_content),
            checksum=document.checksum,
            created_by=user,
            comment=comment,
            is_major_version=is_major_version
        )
        
        # Extract changes
        if document.version_number > 1:
            # Compare with previous version
            from ..tasks import analyze_version_changes
            analyze_version_changes.delay(new_version.id, current_version.id)
        
        # Update search index
        from ..tasks import extract_document_text
        extract_document_text.delay(document.id)
        
        # Log version creation
        DocumentAudit.log(
            action='version_created',
            user=user,
            document=document,
            details={
                'version_number': new_version.version_number,
                'comment': comment,
                'is_major': is_major_version
            }
        )
        
        return new_version
    
    def delete_document(self, document: Document, user, permanent: bool = False) -> None:
        """Delete a document (soft or permanent)."""
        if not self.permission_service.has_document_permission(user, document, 'delete'):
            raise PermissionError("You don't have permission to delete this document")
        
        if permanent:
            # Permanent deletion
            # Delete all versions from storage
            for version in document.versions.all():
                self.storage_service.delete_file(version.file_path)
            
            # Delete main file from storage
            self.storage_service.delete_file(document.file_path)
            
            # Delete preview if exists
            if document.preview_path:
                self.storage_service.delete_file(document.preview_path)
            
            # Log deletion
            DocumentAudit.log(
                action='deleted',
                user=user,
                document=None,  # Document will be gone
                details={
                    'document_name': document.name,
                    'document_id': str(document.id),
                    'permanent': True
                }
            )
            
            # Delete document record
            document.delete()
        else:
            # Soft delete
            document.soft_delete(user)
            
            # Log soft deletion
            DocumentAudit.log(
                action='deleted',
                user=user,
                document=document,
                details={'permanent': False}
            )
    
    def restore_document(self, document: Document, user) -> Document:
        """Restore a soft-deleted document."""
        if not self.permission_service.has_document_permission(user, document, 'delete'):
            raise PermissionError("You don't have permission to restore this document")
        
        if not document.is_deleted:
            raise ValidationError("Document is not deleted")
        
        document.restore(user)
        
        # Log restoration
        DocumentAudit.log(
            action='restored',
            user=user,
            document=document
        )
        
        return document
    
    def move_documents(
        self,
        documents: List[Document],
        target_folder: Optional[Folder],
        user
    ) -> List[Document]:
        """Move multiple documents to a folder."""
        moved_documents = []
        
        for document in documents:
            if not self.permission_service.has_document_permission(user, document, 'edit'):
                continue
            
            old_folder = document.folder
            document.folder = target_folder
            document.modified_by = user
            document.save()
            
            # Update folder statistics
            if old_folder:
                old_folder.update_statistics()
            if target_folder:
                target_folder.update_statistics()
            
            moved_documents.append(document)
        
        # Log bulk move
        if moved_documents:
            DocumentAudit.log_bulk_operation(
                action='bulk_move',
                user=user,
                documents=moved_documents,
                details={
                    'target_folder': target_folder.name if target_folder else 'Root',
                    'count': len(moved_documents)
                }
            )
        
        return moved_documents
    
    def search_documents(
        self,
        query: str,
        user,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Search documents with permissions."""
        # Get accessible document IDs
        accessible_ids = self.permission_service.get_accessible_document_ids(user)
        
        # Perform search
        results = self.search_service.search_documents(
            query=query,
            document_ids=accessible_ids,
            filters=filters,
            limit=limit,
            offset=offset
        )
        
        # Log search
        DocumentAudit.log(
            action='searched',
            user=user,
            details={
                'query': query,
                'filters': filters,
                'results_count': results['total']
            }
        )
        
        return results
    
    def get_document_for_download(self, document: Document, user) -> Dict[str, Any]:
        """Get document content for download."""
        if not self.permission_service.has_document_permission(user, document, 'download'):
            raise PermissionError("You don't have permission to download this document")
        
        # Get file content from storage
        file_content = self.storage_service.download_file(document.file_path)
        
        # Decrypt if necessary
        if document.is_encrypted:
            file_content = self.encryption_service.decrypt_file(
                file_content,
                document.encryption_key_id
            )
        
        # Increment download count
        document.increment_download_count()
        
        # Log download
        DocumentAudit.log_document_access(
            document=document,
            user=user,
            action='downloaded'
        )
        
        return {
            'content': file_content,
            'filename': document.file_name,
            'content_type': document.mime_type,
            'size': document.size
        }
    
    def cleanup_old_documents(self, days: int = 365) -> int:
        """Clean up old deleted documents."""
        cutoff_date = timezone.now() - timedelta(days=days)
        
        old_documents = Document.objects.filter(
            is_deleted=True,
            deleted_at__lt=cutoff_date
        )
        
        count = 0
        for document in old_documents:
            try:
                self.delete_document(document, user=None, permanent=True)
                count += 1
            except Exception as e:
                # Log error but continue
                print(f"Error deleting document {document.id}: {e}")
        
        return count