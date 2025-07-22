"""
Views for the files app.
"""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, Http404
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from .models import File, FileAccessLog
from .serializers import (
    FileSerializer, FileUploadSerializer, FileAccessLogSerializer
)


class FilePermission(permissions.BasePermission):
    """Custom permission class for files."""
    
    def has_permission(self, request, view):
        # All authenticated users can upload files
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # Check if user has access to the file
        return obj.has_access(request.user)


class FileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for file management.
    
    Provides CRUD operations for files with access control.
    """
    
    serializer_class = FileSerializer
    permission_classes = [FilePermission]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        """Get files accessible to the current user."""
        user = self.request.user
        
        # Start with files uploaded by user or public files
        queryset = File.objects.filter(
            Q(uploaded_by=user) | 
            Q(is_public=True) |
            Q(allowed_users=user)
        ).distinct()
        
        # Filter by content object if provided
        content_type_name = self.request.query_params.get('content_type')
        object_id = self.request.query_params.get('object_id')
        
        if content_type_name and object_id:
            try:
                app_label, model = content_type_name.split('.')
                content_type = ContentType.objects.get(
                    app_label=app_label,
                    model=model
                )
                queryset = queryset.filter(
                    content_type=content_type,
                    object_id=object_id
                )
            except (ValueError, ContentType.DoesNotExist):
                queryset = queryset.none()
        
        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        # Filter by uploader
        uploader_id = self.request.query_params.get('uploaded_by')
        if uploader_id:
            queryset = queryset.filter(uploaded_by_id=uploader_id)
        
        return queryset.select_related('uploaded_by', 'content_type')
    
    def get_serializer_class(self):
        """Get appropriate serializer class."""
        if self.action == 'create':
            return FileUploadSerializer
        return FileSerializer
    
    def perform_create(self, serializer):
        """Create file and log access."""
        file = serializer.save()
        
        # Log upload action
        FileAccessLog.objects.create(
            file=file,
            user=self.request.user,
            action='upload',
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
            metadata={'source': 'api'}
        )
    
    def perform_destroy(self, instance):
        """Log deletion before destroying."""
        FileAccessLog.objects.create(
            file=instance,
            user=self.request.user,
            action='delete',
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
            metadata={'source': 'api'}
        )
        super().perform_destroy(instance)
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download a file."""
        file = self.get_object()
        
        # Log download
        FileAccessLog.objects.create(
            file=file,
            user=request.user,
            action='download',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            metadata={'source': 'api'}
        )
        
        # Serve file
        try:
            response = HttpResponse(
                file.file.read(),
                content_type=file.content_type
            )
            response['Content-Disposition'] = f'attachment; filename="{file.filename}"'
            response['Content-Length'] = file.file_size
            return response
        except Exception as e:
            raise Http404(f"File not found: {str(e)}")
    
    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        """Share a file with other users."""
        file = self.get_object()
        
        # Only uploader can share
        if file.uploaded_by != request.user:
            return Response(
                {'error': 'Only the uploader can share this file'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_ids = request.data.get('user_ids', [])
        if not user_ids:
            return Response(
                {'error': 'No users specified'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Add users to allowed_users
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        users = User.objects.filter(id__in=user_ids)
        file.allowed_users.add(*users)
        
        # Log share action
        FileAccessLog.objects.create(
            file=file,
            user=request.user,
            action='share',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            metadata={
                'source': 'api',
                'shared_with': list(users.values_list('email', flat=True))
            }
        )
        
        return Response({
            'message': f'File shared with {users.count()} users',
            'shared_with': list(users.values_list('email', flat=True))
        })
    
    @action(detail=True, methods=['post'])
    def create_version(self, request, pk=None):
        """Create a new version of a file."""
        original_file = self.get_object()
        
        # Only uploader can create versions
        if original_file.uploaded_by != request.user:
            return Response(
                {'error': 'Only the uploader can create new versions'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        new_file = request.FILES.get('file')
        if not new_file:
            return Response(
                {'error': 'No file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        description = request.data.get('description', '')
        
        # Create new version
        new_version = original_file.create_version(
            new_file=new_file,
            user=request.user,
            description=description
        )
        
        serializer = FileSerializer(new_version, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['get'])
    def access_logs(self, request, pk=None):
        """Get access logs for a file."""
        file = self.get_object()
        
        # Only uploader can view access logs
        if file.uploaded_by != request.user:
            return Response(
                {'error': 'Only the uploader can view access logs'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        logs = file.access_logs.all().select_related('user')
        serializer = FileAccessLogSerializer(logs, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get file statistics for the current user."""
        user = request.user
        
        # Get user's files
        user_files = File.objects.filter(uploaded_by=user)
        
        stats = {
            'total_files': user_files.count(),
            'total_size': sum(f.file_size for f in user_files),
            'by_category': {},
            'recent_uploads': []
        }
        
        # Files by category
        for category, label in File.Category.choices:
            count = user_files.filter(category=category).count()
            if count > 0:
                stats['by_category'][category] = {
                    'label': label,
                    'count': count
                }
        
        # Recent uploads
        recent = user_files.order_by('-created_at')[:5]
        stats['recent_uploads'] = FileSerializer(
            recent, many=True, context={'request': request}
        ).data
        
        return Response(stats)