
from rest_framework import viewsets
from platform_core.core.views import PlatformViewSet, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.http import Http404
from django.conf import settings
import boto3
from botocore.exceptions import ClientError

from accounts.permissions import RoleBasedPermission, GroupAccessPermission
from assessments.models import Assessment
from .models import FileAttachment
from .serializers import FileAttachmentSerializer, FileUploadSerializer
from core.mixins import FileUploadThrottleMixin

class FileAttachmentViewSet(FileUploadThrottleMixin, PlatformViewSet):
    """ViewSet for file attachments with upload rate limiting"""
    queryset = FileAttachment.objects.all()
    serializer_class = FileAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission, GroupAccessPermission]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        """Filter by user's groups"""
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return FileAttachment.objects.select_related('assessment', 'uploaded_by')
        
        user_groups = user.groups.all()
        return FileAttachment.objects.filter(
            assessment__group__in=user_groups
        ).select_related('assessment', 'uploaded_by')
    
    @action(detail=False, methods=['post'])
    def upload(self, request):
        """Upload file to assessment"""
        assessment_id = request.data.get('assessment_id')
        
        if not assessment_id:
            return Response(
                {'error': 'assessment_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            
            # Check if user has access to this assessment
            user_groups = request.user.groups.all()
            if request.user.role != request.user.Role.ADMIN and assessment.group not in user_groups:
                return Response(
                    {'error': 'Access denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            serializer = FileUploadSerializer(data=request.data)
            if serializer.is_valid():
                file_obj = serializer.validated_data['file']
                category = serializer.validated_data.get('category', 'other')
                description = serializer.validated_data.get('description', '')
                
                # Create file attachment
                attachment = FileAttachment.objects.create(
                    assessment=assessment,
                    file=file_obj,
                    filename=file_obj.name,
                    file_size=file_obj.size,
                    content_type=file_obj.content_type,
                    category=category,
                    description=description,
                    uploaded_by=request.user
                )
                
                # If using S3, update S3 fields
                if hasattr(settings, 'AWS_STORAGE_BUCKET_NAME') and settings.AWS_STORAGE_BUCKET_NAME:
                    attachment.s3_bucket = settings.AWS_STORAGE_BUCKET_NAME
                    attachment.s3_key = attachment.file.name
                    attachment.save()
                
                response_serializer = FileAttachmentSerializer(attachment, context={'request': request})
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        except Assessment.DoesNotExist:
            return Response(
                {'error': 'Assessment not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Generate download URL for file"""
        attachment = self.get_object()
        
        # If using S3, generate presigned URL
        if attachment.s3_bucket and attachment.s3_key:
            try:
                s3_client = boto3.client(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_S3_REGION_NAME
                )
                
                url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': attachment.s3_bucket, 'Key': attachment.s3_key},
                    ExpiresIn=3600  # 1 hour
                )
                
                return Response({'download_url': url})
            
            except ClientError as e:
                return Response(
                    {'error': 'Failed to generate download URL'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        # For local files, return the file URL
        if attachment.file:
            return Response({
                'download_url': request.build_absolute_uri(attachment.file.url)
            })
        
        return Response(
            {'error': 'File not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    @action(detail=False, methods=['get'])
    def by_assessment(self, request):
        """Get files for specific assessment"""
        assessment_id = request.query_params.get('assessment_id')
        
        if not assessment_id:
            return Response(
                {'error': 'assessment_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            assessment = Assessment.objects.get(id=assessment_id)
            
            # Check access
            user_groups = request.user.groups.all()
            if request.user.role != request.user.Role.ADMIN and assessment.group not in user_groups:
                return Response(
                    {'error': 'Access denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            files = FileAttachment.objects.filter(assessment=assessment)
            serializer = FileAttachmentSerializer(files, many=True, context={'request': request})
            return Response(serializer.data)
        
        except Assessment.DoesNotExist:
            return Response(
                {'error': 'Assessment not found'},
                status=status.HTTP_404_NOT_FOUND
            )
