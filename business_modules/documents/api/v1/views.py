"""API views for document management."""

import os
import zipfile
import tempfile
from typing import List
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

from ...models import (
    Document, DocumentVersion, Folder,
    DocumentPermission, FolderPermission,
    SharedLink, DocumentTemplate, DocumentAudit
)
from ...services import (
    DocumentService, PermissionService, SearchService,
    PreviewService, OCRService, TemplateService
)
from .serializers import (
    DocumentSerializer, DocumentUploadSerializer, DocumentVersionSerializer,
    FolderSerializer, DocumentPermissionSerializer, FolderPermissionSerializer,
    SharedLinkSerializer, DocumentTemplateSerializer, TemplateUseSerializer,
    DocumentAuditSerializer, BulkOperationSerializer, SearchSerializer
)
from .permissions import DocumentPermission as DocumentPerm
from .filters import DocumentFilter, FolderFilter


class FolderViewSet(viewsets.ModelViewSet):
    """ViewSet for folder management."""
    
    serializer_class = FolderSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = FolderFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['name']
    
    def get_queryset(self):
        """Get folders accessible to user."""
        queryset = Folder.objects.filter(group=self.request.user.group)
        
        # Filter by parent
        parent_id = self.request.query_params.get('parent_id')
        if parent_id:
            if parent_id == 'root':
                queryset = queryset.filter(parent__isnull=True)
            else:
                queryset = queryset.filter(parent_id=parent_id)
        
        return queryset
    
    def perform_create(self, serializer):
        """Create folder with user tracking."""
        serializer.save(
            created_by=self.request.user,
            modified_by=self.request.user,
            group=self.request.user.group
        )
    
    def perform_update(self, serializer):
        """Update folder with user tracking."""
        serializer.save(modified_by=self.request.user)
    
    def perform_destroy(self, instance):
        """Delete folder with validation."""
        if not instance.can_delete():
            raise ValidationError("Cannot delete folder that contains documents or is a system folder")
        
        # Log deletion
        DocumentAudit.log(
            action='folder_deleted',
            user=self.request.user,
            folder=instance
        )
        
        instance.delete()
    
    @action(detail=True, methods=['get'])
    def tree(self, request, pk=None):
        """Get folder tree structure."""
        folder = self.get_object()
        
        def build_tree(folder):
            children = []
            for child in folder.get_children():
                children.append(build_tree(child))
            
            return {
                'id': str(folder.id),
                'name': folder.name,
                'path': folder.path,
                'document_count': folder.document_count,
                'children': children
            }
        
        tree_data = build_tree(folder)
        return Response(tree_data)
    
    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        """Move folder to new parent."""
        folder = self.get_object()
        new_parent_id = request.data.get('parent_id')
        
        if new_parent_id:
            new_parent = get_object_or_404(Folder, id=new_parent_id)
            folder.move_to(new_parent)
        else:
            folder.move_to(None)
        
        # Log move
        DocumentAudit.log(
            action='folder_moved',
            user=request.user,
            folder=folder,
            details={'new_parent': new_parent.name if new_parent_id else 'Root'}
        )
        
        serializer = self.get_serializer(folder)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def permissions(self, request, pk=None):
        """Get folder permissions."""
        folder = self.get_object()
        permission_service = PermissionService()
        
        # Check if user can manage permissions
        if not permission_service.has_folder_permission(request.user, folder, 'manage'):
            return Response(
                {'error': 'You do not have permission to view folder permissions'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        permissions = FolderPermission.objects.filter(folder=folder)
        serializer = FolderPermissionSerializer(permissions, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def grant_permission(self, request, pk=None):
        """Grant permission on folder."""
        folder = self.get_object()
        serializer = FolderPermissionSerializer(data=request.data)
        
        if serializer.is_valid():
            permission_service = PermissionService()
            
            try:
                permission = permission_service.grant_folder_permission(
                    folder=folder,
                    permission=serializer.validated_data['permission'],
                    granted_by=request.user,
                    user=serializer.validated_data.get('user'),
                    group=serializer.validated_data.get('group'),
                    expires_at=serializer.validated_data.get('expires_at'),
                    apply_to_subfolders=serializer.validated_data.get('apply_to_subfolders', True),
                    apply_to_documents=serializer.validated_data.get('apply_to_documents', True),
                    notes=serializer.validated_data.get('notes', '')
                )
                
                return Response(
                    FolderPermissionSerializer(permission).data,
                    status=status.HTTP_201_CREATED
                )
            except PermissionError as e:
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DocumentViewSet(viewsets.ModelViewSet):
    """ViewSet for document management."""
    
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated, DocumentPerm]
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DocumentFilter
    search_fields = ['name', 'description', 'tags']
    ordering_fields = ['name', 'size', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get documents accessible to user."""
        permission_service = PermissionService()
        accessible_ids = permission_service.get_accessible_document_ids(self.request.user)
        
        queryset = Document.objects.filter(
            id__in=accessible_ids,
            is_deleted=False
        )
        
        # Filter by folder
        folder_id = self.request.query_params.get('folder_id')
        if folder_id:
            queryset = queryset.filter(folder_id=folder_id)
        
        return queryset
    
    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def upload(self, request):
        """Upload a new document."""
        serializer = DocumentUploadSerializer(data=request.data)
        
        if serializer.is_valid():
            document_service = DocumentService()
            
            try:
                document = document_service.create_document(
                    file=serializer.validated_data['file'],
                    name=serializer.validated_data.get('name') or serializer.validated_data['file'].name,
                    user=request.user,
                    folder=Folder.objects.get(id=serializer.validated_data['folder_id']) if serializer.validated_data.get('folder_id') else None,
                    description=serializer.validated_data.get('description', ''),
                    tags=serializer.validated_data.get('tags', []),
                    category=serializer.validated_data.get('category', ''),
                    encrypt=serializer.validated_data.get('encrypt', True)
                )
                
                return Response(
                    DocumentSerializer(document, context={'request': request}).data,
                    status=status.HTTP_201_CREATED
                )
            except Exception as e:
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download document."""
        document = self.get_object()
        document_service = DocumentService()
        
        try:
            file_data = document_service.get_document_for_download(document, request.user)
            
            response = HttpResponse(
                file_data['content'],
                content_type=file_data['content_type']
            )
            response['Content-Disposition'] = f'attachment; filename="{file_data["filename"]}"'
            response['Content-Length'] = file_data['size']
            
            return response
        except PermissionError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
    
    @action(detail=True, methods=['get'])
    def preview(self, request, pk=None):
        """Get document preview."""
        document = self.get_object()
        
        if not document.preview_generated:
            # Generate preview on demand
            preview_service = PreviewService()
            preview_service.generate_preview(document)
        
        if document.preview_path:
            # Serve preview file
            storage_service = document_service.storage_service
            preview_url = storage_service.generate_presigned_url(
                document.preview_path,
                expiration=3600
            )
            
            return Response({'preview_url': preview_url})
        
        return Response(
            {'error': 'Preview not available'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        """Lock document for editing."""
        document = self.get_object()
        
        try:
            document.lock(request.user)
            return Response({'message': 'Document locked successfully'})
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        """Unlock document."""
        document = self.get_object()
        
        try:
            document.unlock(request.user)
            return Response({'message': 'Document unlocked successfully'})
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """Get document versions."""
        document = self.get_object()
        versions = document.versions.all()
        serializer = DocumentVersionSerializer(
            versions,
            many=True,
            context={'request': request}
        )
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser])
    def create_version(self, request, pk=None):
        """Create new document version."""
        document = self.get_object()
        file = request.FILES.get('file')
        
        if not file:
            return Response(
                {'error': 'File is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        document_service = DocumentService()
        
        try:
            version = document_service.create_version(
                document=document,
                file=file,
                user=request.user,
                comment=request.data.get('comment', ''),
                is_major_version=request.data.get('is_major_version', False)
            )
            
            return Response(
                DocumentVersionSerializer(version, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'], url_path='versions/(?P<version_id>[^/.]+)/restore')
    def restore_version(self, request, pk=None, version_id=None):
        """Restore document version."""
        document = self.get_object()
        version = get_object_or_404(DocumentVersion, id=version_id, document=document)
        
        try:
            restored_version = version.restore()
            return Response(
                DocumentVersionSerializer(restored_version, context={'request': request}).data
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        """Create shared link for document."""
        document = self.get_object()
        
        # Check permission
        permission_service = PermissionService()
        if not permission_service.has_document_permission(request.user, document, 'share'):
            return Response(
                {'error': 'You do not have permission to share this document'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = SharedLinkSerializer(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            shared_link = SharedLink.create_for_document(
                document=document,
                user=request.user,
                days=request.data.get('expiry_days', 30),
                **serializer.validated_data
            )
            
            return Response(
                SharedLinkSerializer(shared_link, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def ocr(self, request, pk=None):
        """Extract text from document using OCR."""
        document = self.get_object()
        ocr_service = OCRService()
        
        language = request.data.get('language', 'eng')
        
        try:
            text = ocr_service.extract_text(document, language)
            
            if text:
                return Response({
                    'success': True,
                    'text': text,
                    'word_count': len(text.split()),
                    'language': language
                })
            else:
                return Response({
                    'success': False,
                    'message': 'No text could be extracted'
                })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def search(self, request):
        """Search documents."""
        serializer = SearchSerializer(data=request.data)
        
        if serializer.is_valid():
            document_service = DocumentService()
            
            # Build filters
            filters = {}
            for field in ['category', 'file_extension', 'tags', 'created_after', 
                         'created_before', 'size_min', 'size_max']:
                if field in serializer.validated_data:
                    filters[field] = serializer.validated_data[field]
            
            # Add folder filter
            if 'folder_id' in serializer.validated_data:
                folder = Folder.objects.get(id=serializer.validated_data['folder_id'])
                if serializer.validated_data.get('include_subfolders', True):
                    folder_ids = [folder.id] + list(folder.get_descendants().values_list('id', flat=True))
                    filters['folder_id__in'] = folder_ids
                else:
                    filters['folder_id'] = folder.id
            
            # Perform search
            results = document_service.search_documents(
                query=serializer.validated_data['query'],
                user=request.user,
                filters=filters,
                limit=request.query_params.get('limit', 100),
                offset=request.query_params.get('offset', 0)
            )
            
            # Serialize results
            documents = Document.objects.filter(
                id__in=[doc['id'] for doc in results['documents']]
            )
            
            return Response({
                'total': results['total'],
                'documents': DocumentSerializer(
                    documents,
                    many=True,
                    context={'request': request}
                ).data,
                'limit': results['limit'],
                'offset': results['offset']
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'])
    def bulk(self, request):
        """Perform bulk operations on documents."""
        serializer = BulkOperationSerializer(data=request.data)
        
        if serializer.is_valid():
            operation = serializer.validated_data['operation']
            document_ids = serializer.validated_data.get('document_ids', [])
            
            # Get documents
            documents = Document.objects.filter(id__in=document_ids)
            
            # Check permissions
            permission_service = PermissionService()
            permitted_documents = []
            
            for doc in documents:
                if operation == 'download' and permission_service.has_document_permission(request.user, doc, 'download'):
                    permitted_documents.append(doc)
                elif operation == 'delete' and permission_service.has_document_permission(request.user, doc, 'delete'):
                    permitted_documents.append(doc)
                elif operation in ['move', 'tag'] and permission_service.has_document_permission(request.user, doc, 'edit'):
                    permitted_documents.append(doc)
            
            if not permitted_documents:
                return Response(
                    {'error': 'No documents with required permissions'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Perform operation
            if operation == 'download':
                return self._bulk_download(permitted_documents)
            elif operation == 'delete':
                return self._bulk_delete(
                    permitted_documents,
                    request.user,
                    serializer.validated_data.get('permanent', False)
                )
            elif operation == 'move':
                return self._bulk_move(
                    permitted_documents,
                    request.user,
                    serializer.validated_data.get('target_folder_id')
                )
            elif operation == 'tag':
                return self._bulk_tag(
                    permitted_documents,
                    request.user,
                    serializer.validated_data.get('tags', [])
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def _bulk_download(self, documents: List[Document]):
        """Create zip file for bulk download."""
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_zip:
            with zipfile.ZipFile(tmp_zip.name, 'w') as zip_file:
                for doc in documents:
                    try:
                        file_data = DocumentService().get_document_for_download(doc, self.request.user)
                        zip_file.writestr(doc.file_name, file_data['content'])
                    except Exception:
                        continue
            
            # Serve zip file
            with open(tmp_zip.name, 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/zip')
                response['Content-Disposition'] = 'attachment; filename="documents.zip"'
            
            # Clean up
            os.unlink(tmp_zip.name)
            
            return response
    
    def _bulk_delete(self, documents: List[Document], user, permanent: bool):
        """Bulk delete documents."""
        document_service = DocumentService()
        deleted_count = 0
        
        for doc in documents:
            try:
                document_service.delete_document(doc, user, permanent)
                deleted_count += 1
            except Exception:
                continue
        
        return Response({
            'deleted': deleted_count,
            'total': len(documents)
        })
    
    def _bulk_move(self, documents: List[Document], user, target_folder_id):
        """Bulk move documents."""
        if not target_folder_id:
            return Response(
                {'error': 'target_folder_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        target_folder = get_object_or_404(Folder, id=target_folder_id)
        document_service = DocumentService()
        
        moved_documents = document_service.move_documents(documents, target_folder, user)
        
        return Response({
            'moved': len(moved_documents),
            'total': len(documents)
        })
    
    def _bulk_tag(self, documents: List[Document], user, tags: List[str]):
        """Bulk add tags to documents."""
        tagged_count = 0
        
        for doc in documents:
            # Add new tags
            existing_tags = set(doc.tags)
            new_tags = existing_tags.union(set(tags))
            doc.tags = list(new_tags)
            doc.modified_by = user
            doc.save()
            tagged_count += 1
        
        return Response({
            'tagged': tagged_count,
            'total': len(documents),
            'tags': tags
        })


class DocumentTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for document templates."""
    
    serializer_class = DocumentTemplateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description', 'category']
    ordering_fields = ['name', 'category', 'usage_count', 'created_at']
    ordering = ['category', 'name']
    
    def get_queryset(self):
        """Get templates accessible to user."""
        queryset = DocumentTemplate.objects.filter(
            Q(is_public=True) |
            Q(allowed_users=self.request.user) |
            Q(allowed_groups__in=self.request.user.groups.all())
        ).distinct()
        
        # Filter by active
        if self.request.query_params.get('active_only', 'true').lower() == 'true':
            queryset = queryset.filter(is_active=True)
        
        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def use(self, request, pk=None):
        """Use template to create document."""
        template = self.get_object()
        
        if not template.can_use(request.user):
            return Response(
                {'error': 'You do not have permission to use this template'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = TemplateUseSerializer(data=request.data)
        
        if serializer.is_valid():
            template_service = TemplateService()
            
            try:
                document = template_service.create_document_from_template(
                    template=template,
                    user=request.user,
                    data=serializer.validated_data['data'],
                    folder=Folder.objects.get(id=serializer.validated_data['folder_id']) if serializer.validated_data.get('folder_id') else None,
                    name=serializer.validated_data.get('name')
                )
                
                return Response(
                    DocumentSerializer(document, context={'request': request}).data,
                    status=status.HTTP_201_CREATED
                )
            except Exception as e:
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        """Preview template with sample data."""
        template = self.get_object()
        template_service = TemplateService()
        
        sample_data = request.data.get('data', {})
        
        result = template_service.preview_template(template, sample_data)
        
        if result['success']:
            return Response(result)
        else:
            return Response(
                {'error': result['error']},
                status=status.HTTP_400_BAD_REQUEST
            )


class SharedLinkViewSet(viewsets.ModelViewSet):
    """ViewSet for shared links."""
    
    serializer_class = SharedLinkSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get shared links created by user."""
        return SharedLink.objects.filter(
            created_by=self.request.user,
            is_active=True
        )
    
    def perform_create(self, serializer):
        """Create shared link."""
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        """Revoke shared link."""
        shared_link = self.get_object()
        reason = request.data.get('reason', '')
        
        shared_link.revoke(request.user, reason)
        
        return Response({'message': 'Shared link revoked successfully'})


class DocumentAuditViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for document audit logs."""
    
    serializer_class = DocumentAuditSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get audit logs for accessible documents."""
        permission_service = PermissionService()
        accessible_doc_ids = permission_service.get_accessible_document_ids(self.request.user)
        
        queryset = DocumentAudit.objects.filter(
            Q(document_id__in=accessible_doc_ids) |
            Q(user=self.request.user)
        )
        
        # Filter by document
        document_id = self.request.query_params.get('document_id')
        if document_id:
            queryset = queryset.filter(document_id=document_id)
        
        # Filter by action
        action = self.request.query_params.get('action')
        if action:
            queryset = queryset.filter(action=action)
        
        # Filter by user
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        return queryset