"""Storage service for managing file storage backend."""

import os
import uuid
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, BinaryIO
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import boto3
from botocore.exceptions import ClientError


class StorageService:
    """Service for managing document storage."""
    
    def __init__(self):
        self.backend = getattr(settings, 'DOCUMENTS_STORAGE_BACKEND', 's3')
        
        if self.backend == 's3':
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=getattr(settings, 'AWS_S3_REGION_NAME', 'us-east-1')
            )
            self.bucket_name = settings.AWS_STORAGE_BUCKET_NAME
            self.base_path = getattr(settings, 'DOCUMENTS_S3_BASE_PATH', 'documents/')
        else:
            # Local filesystem storage
            self.base_path = getattr(settings, 'DOCUMENTS_LOCAL_BASE_PATH', 'documents/')
    
    def generate_path(
        self,
        file_name: str,
        folder: Optional['Folder'] = None,
        user: Optional['User'] = None
    ) -> str:
        """Generate a unique storage path for a file."""
        # Extract extension
        _, ext = os.path.splitext(file_name)
        
        # Generate unique filename
        unique_id = uuid.uuid4().hex
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Build path components
        path_parts = [self.base_path.rstrip('/')]
        
        # Add year/month for organization
        now = datetime.now()
        path_parts.extend([str(now.year), f"{now.month:02d}"])
        
        # Add folder path if provided
        if folder:
            folder_path = folder.path.strip('/').replace('/', '_')
            path_parts.append(folder_path)
        elif user:
            path_parts.append(f"user_{user.id}")
        
        # Add filename
        safe_name = f"{timestamp}_{unique_id}{ext}"
        path_parts.append(safe_name)
        
        return '/'.join(path_parts)
    
    def generate_version_path(self, document: 'Document', version_number: int) -> str:
        """Generate path for document version."""
        base_path = os.path.dirname(document.file_path)
        file_name = os.path.basename(document.file_path)
        name, ext = os.path.splitext(file_name)
        
        version_name = f"{name}_v{version_number}{ext}"
        return os.path.join(base_path, 'versions', version_name)
    
    def upload_file(
        self,
        file_content: bytes,
        path: str,
        content_type: str = 'application/octet-stream',
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Upload file to storage backend."""
        if self.backend == 's3':
            return self._upload_to_s3(file_content, path, content_type, metadata)
        else:
            return self._upload_to_local(file_content, path, content_type, metadata)
    
    def _upload_to_s3(
        self,
        file_content: bytes,
        path: str,
        content_type: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Upload file to S3."""
        try:
            # Prepare upload parameters
            put_params = {
                'Bucket': self.bucket_name,
                'Key': path,
                'Body': file_content,
                'ContentType': content_type,
            }
            
            # Add metadata if provided
            if metadata:
                put_params['Metadata'] = metadata
            
            # Add server-side encryption
            if getattr(settings, 'AWS_S3_ENCRYPTION', True):
                put_params['ServerSideEncryption'] = 'AES256'
            
            # Upload file
            response = self.s3_client.put_object(**put_params)
            
            # Generate URL
            url = self._generate_s3_url(path)
            
            return {
                'path': path,
                'url': url,
                'etag': response.get('ETag', '').strip('"'),
                'content_type': content_type,
                'size': len(file_content)
            }
            
        except ClientError as e:
            raise Exception(f"Failed to upload file to S3: {str(e)}")
    
    def _upload_to_local(
        self,
        file_content: bytes,
        path: str,
        content_type: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Upload file to local storage."""
        try:
            # Save file using Django's storage
            file_name = default_storage.save(path, ContentFile(file_content))
            
            # Get file URL
            url = default_storage.url(file_name)
            
            return {
                'path': file_name,
                'url': url,
                'content_type': content_type,
                'size': len(file_content)
            }
            
        except Exception as e:
            raise Exception(f"Failed to upload file to local storage: {str(e)}")
    
    def download_file(self, path: str) -> bytes:
        """Download file from storage backend."""
        if self.backend == 's3':
            return self._download_from_s3(path)
        else:
            return self._download_from_local(path)
    
    def _download_from_s3(self, path: str) -> bytes:
        """Download file from S3."""
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=path
            )
            return response['Body'].read()
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                raise FileNotFoundError(f"File not found: {path}")
            raise Exception(f"Failed to download file from S3: {str(e)}")
    
    def _download_from_local(self, path: str) -> bytes:
        """Download file from local storage."""
        try:
            with default_storage.open(path, 'rb') as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")
        except Exception as e:
            raise Exception(f"Failed to download file from local storage: {str(e)}")
    
    def delete_file(self, path: str) -> bool:
        """Delete file from storage backend."""
        if self.backend == 's3':
            return self._delete_from_s3(path)
        else:
            return self._delete_from_local(path)
    
    def _delete_from_s3(self, path: str) -> bool:
        """Delete file from S3."""
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=path
            )
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                return True  # Already deleted
            raise Exception(f"Failed to delete file from S3: {str(e)}")
    
    def _delete_from_local(self, path: str) -> bool:
        """Delete file from local storage."""
        try:
            default_storage.delete(path)
            return True
        except Exception:
            return False
    
    def file_exists(self, path: str) -> bool:
        """Check if file exists in storage."""
        if self.backend == 's3':
            return self._exists_in_s3(path)
        else:
            return default_storage.exists(path)
    
    def _exists_in_s3(self, path: str) -> bool:
        """Check if file exists in S3."""
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=path
            )
            return True
        except ClientError:
            return False
    
    def get_file_info(self, path: str) -> Dict[str, Any]:
        """Get file information from storage."""
        if self.backend == 's3':
            return self._get_s3_info(path)
        else:
            return self._get_local_info(path)
    
    def _get_s3_info(self, path: str) -> Dict[str, Any]:
        """Get file info from S3."""
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=path
            )
            
            return {
                'size': response['ContentLength'],
                'content_type': response.get('ContentType', 'application/octet-stream'),
                'last_modified': response['LastModified'],
                'etag': response.get('ETag', '').strip('"'),
                'metadata': response.get('Metadata', {})
            }
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise FileNotFoundError(f"File not found: {path}")
            raise Exception(f"Failed to get file info from S3: {str(e)}")
    
    def _get_local_info(self, path: str) -> Dict[str, Any]:
        """Get file info from local storage."""
        try:
            size = default_storage.size(path)
            modified_time = default_storage.get_modified_time(path)
            
            return {
                'size': size,
                'last_modified': modified_time,
                'content_type': 'application/octet-stream'
            }
        except Exception as e:
            raise Exception(f"Failed to get file info: {str(e)}")
    
    def generate_presigned_url(
        self,
        path: str,
        expiration: int = 3600,
        response_content_type: Optional[str] = None
    ) -> str:
        """Generate a presigned URL for temporary access."""
        if self.backend != 's3':
            # For local storage, return the regular URL
            return default_storage.url(path)
        
        try:
            params = {
                'Bucket': self.bucket_name,
                'Key': path
            }
            
            if response_content_type:
                params['ResponseContentType'] = response_content_type
            
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expiration
            )
            
            return url
        except ClientError as e:
            raise Exception(f"Failed to generate presigned URL: {str(e)}")
    
    def copy_file(self, source_path: str, dest_path: str) -> Dict[str, Any]:
        """Copy a file within storage."""
        if self.backend == 's3':
            return self._copy_in_s3(source_path, dest_path)
        else:
            return self._copy_in_local(source_path, dest_path)
    
    def _copy_in_s3(self, source_path: str, dest_path: str) -> Dict[str, Any]:
        """Copy file in S3."""
        try:
            copy_source = {'Bucket': self.bucket_name, 'Key': source_path}
            
            self.s3_client.copy_object(
                CopySource=copy_source,
                Bucket=self.bucket_name,
                Key=dest_path
            )
            
            return {
                'path': dest_path,
                'url': self._generate_s3_url(dest_path)
            }
        except ClientError as e:
            raise Exception(f"Failed to copy file in S3: {str(e)}")
    
    def _copy_in_local(self, source_path: str, dest_path: str) -> Dict[str, Any]:
        """Copy file in local storage."""
        try:
            # Read source file
            with default_storage.open(source_path, 'rb') as f:
                content = f.read()
            
            # Write to destination
            dest_name = default_storage.save(dest_path, ContentFile(content))
            
            return {
                'path': dest_name,
                'url': default_storage.url(dest_name)
            }
        except Exception as e:
            raise Exception(f"Failed to copy file: {str(e)}")
    
    def _generate_s3_url(self, path: str) -> str:
        """Generate S3 URL for a file."""
        if getattr(settings, 'AWS_S3_CUSTOM_DOMAIN', None):
            return f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/{path}"
        else:
            region = getattr(settings, 'AWS_S3_REGION_NAME', 'us-east-1')
            return f"https://{self.bucket_name}.s3.{region}.amazonaws.com/{path}"
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        if self.backend == 's3':
            return self._get_s3_stats()
        else:
            return self._get_local_stats()
    
    def _get_s3_stats(self) -> Dict[str, Any]:
        """Get S3 storage statistics."""
        try:
            # Get bucket size
            total_size = 0
            total_objects = 0
            
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=self.base_path
            )
            
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        total_size += obj['Size']
                        total_objects += 1
            
            return {
                'total_size': total_size,
                'total_objects': total_objects,
                'backend': 's3',
                'bucket': self.bucket_name
            }
        except ClientError as e:
            raise Exception(f"Failed to get S3 stats: {str(e)}")
    
    def _get_local_stats(self) -> Dict[str, Any]:
        """Get local storage statistics."""
        # Simple implementation - could be enhanced
        return {
            'backend': 'local',
            'base_path': self.base_path
        }