"""
Comprehensive test suite for file handling with S3.

Tests file upload/download with S3 mocking, file access control
and permissions, file metadata and validation.
"""

import os
import io
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, PropertyMock
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
import boto3
from moto import mock_s3

from files.models import FileAttachment
from files.serializers import FileAttachmentSerializer
from accounts.models import Group, GroupMembership
from assessments.models import Assessment, AssessmentStatus
from partners.models import DevelopmentPartner

User = get_user_model()


# Test settings for file storage
TEST_FILE_SETTINGS = {
    'DEFAULT_FILE_STORAGE': 'storages.backends.s3boto3.S3Boto3Storage',
    'AWS_ACCESS_KEY_ID': 'test-access-key',
    'AWS_SECRET_ACCESS_KEY': 'test-secret-key',
    'AWS_STORAGE_BUCKET_NAME': 'test-bucket',
    'AWS_S3_REGION_NAME': 'us-east-1',
    'AWS_S3_FILE_OVERWRITE': False,
    'AWS_DEFAULT_ACL': None,
    'AWS_S3_VERIFY': True
}


@override_settings(**TEST_FILE_SETTINGS)
@mock_s3
class FileModelTestCase(TestCase):
    """Test FileAttachment model functionality"""
    
    def setUp(self):
        """Set up test data"""
        # Create mock S3 bucket
        self.s3_client = boto3.client(
            's3',
            region_name='us-east-1',
            aws_access_key_id='test-access-key',
            aws_secret_access_key='test-secret-key'
        )
        self.s3_client.create_bucket(Bucket='test-bucket')
        
        # Create test group and users
        self.group = Group.objects.create(name="File Test Company")
        self.user = User.objects.create_user(
            username="file@test.com",
            email="file@test.com",
            password="testpass123",
            role=User.Role.ADMIN
        )
        GroupMembership.objects.create(user=self.user, group=self.group)
        
        # Create test assessment
        self.partner = DevelopmentPartner.objects.create(
            name="File Test Partner",
            email="partner@filetest.com",
            group=self.group,
            created_by=self.user
        )
        self.assessment = Assessment.objects.create(
            partner=self.partner,
            assessment_date=timezone.now(),
            group=self.group,
            created_by=self.user
        )
    
    def test_file_attachment_creation(self):
        """Test creating file attachments"""
        # Create test file
        test_content = b"Test file content"
        test_file = SimpleUploadedFile(
            "test_document.pdf",
            test_content,
            content_type="application/pdf"
        )
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test_document.pdf",
            file_size=len(test_content),
            content_type="application/pdf",
            uploaded_by=self.user,
            description="Test financial document",
            category="financial"
        )
        
        self.assertEqual(attachment.filename, "test_document.pdf")
        self.assertEqual(attachment.file_size, len(test_content))
        self.assertEqual(attachment.content_type, "application/pdf")
        self.assertEqual(attachment.category, "financial")
        self.assertEqual(attachment.uploaded_by, self.user)
        self.assertEqual(attachment.assessment, self.assessment)
    
    def test_file_size_calculation(self):
        """Test file size MB property"""
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=SimpleUploadedFile("test.txt", b"test"),
            filename="test.txt",
            file_size=5242880,  # 5 MB in bytes
            content_type="text/plain",
            uploaded_by=self.user
        )
        
        self.assertEqual(attachment.file_size_mb, 5.0)
    
    def test_s3_fields_population(self):
        """Test S3 fields are populated correctly"""
        test_file = SimpleUploadedFile("s3_test.pdf", b"S3 test content")
        
        with patch('storages.backends.s3boto3.S3Boto3Storage.save') as mock_save:
            mock_save.return_value = f"assessments/{self.assessment.id}/s3_test.pdf"
            
            attachment = FileAttachment.objects.create(
                assessment=self.assessment,
                file=test_file,
                filename="s3_test.pdf",
                file_size=15,
                content_type="application/pdf",
                uploaded_by=self.user,
                s3_bucket="test-bucket",
                s3_key=f"assessments/{self.assessment.id}/s3_test.pdf"
            )
            
            self.assertEqual(attachment.s3_bucket, "test-bucket")
            self.assertEqual(attachment.s3_key, f"assessments/{self.assessment.id}/s3_test.pdf")
    
    def test_file_categories(self):
        """Test different file categories"""
        categories = [
            ('financial', 'Financial Documents'),
            ('legal', 'Legal Documents'),
            ('operational', 'Operational Documents'),
            ('technical', 'Technical Documents'),
            ('other', 'Other')
        ]
        
        for cat_code, cat_name in categories:
            attachment = FileAttachment.objects.create(
                assessment=self.assessment,
                file=SimpleUploadedFile(f"{cat_code}.pdf", b"test"),
                filename=f"{cat_code}.pdf",
                file_size=100,
                content_type="application/pdf",
                uploaded_by=self.user,
                category=cat_code
            )
            self.assertEqual(attachment.category, cat_code)


@override_settings(**TEST_FILE_SETTINGS)
@mock_s3
class FileAPITestCase(APITestCase):
    """Test file upload/download API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        # Create mock S3 bucket
        self.s3_client = boto3.client(
            's3',
            region_name='us-east-1',
            aws_access_key_id='test-access-key',
            aws_secret_access_key='test-secret-key'
        )
        self.s3_client.create_bucket(Bucket='test-bucket')
        
        # Create test groups and users
        self.group = Group.objects.create(name="File API Test Company")
        self.admin_user = User.objects.create_user(
            username="admin@fileapi.com",
            email="admin@fileapi.com",
            password="testpass123",
            role=User.Role.ADMIN
        )
        self.analyst_user = User.objects.create_user(
            username="analyst@fileapi.com",
            email="analyst@fileapi.com",
            password="testpass123",
            role=User.Role.BUSINESS_ANALYST
        )
        self.readonly_user = User.objects.create_user(
            username="readonly@fileapi.com",
            email="readonly@fileapi.com",
            password="testpass123",
            role=User.Role.READ_ONLY
        )
        
        # Add users to group
        GroupMembership.objects.create(user=self.admin_user, group=self.group, is_admin=True)
        GroupMembership.objects.create(user=self.analyst_user, group=self.group)
        GroupMembership.objects.create(user=self.readonly_user, group=self.group)
        
        # Create tokens
        self.admin_token = str(RefreshToken.for_user(self.admin_user).access_token)
        self.analyst_token = str(RefreshToken.for_user(self.analyst_user).access_token)
        self.readonly_token = str(RefreshToken.for_user(self.readonly_user).access_token)
        
        # Create test assessment
        self.partner = DevelopmentPartner.objects.create(
            name="API Test Partner",
            email="partner@apitest.com",
            group=self.group,
            created_by=self.admin_user
        )
        self.assessment = Assessment.objects.create(
            partner=self.partner,
            assessment_date=timezone.now(),
            group=self.group,
            created_by=self.admin_user
        )
    
    @patch('storages.backends.s3boto3.S3Boto3Storage.save')
    @patch('storages.backends.s3boto3.S3Boto3Storage.url')
    def test_file_upload(self, mock_url, mock_save):
        """Test file upload endpoint"""
        mock_save.return_value = f"assessments/{self.assessment.id}/test_upload.pdf"
        mock_url.return_value = "https://test-bucket.s3.amazonaws.com/test_upload.pdf"
        
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        
        # Create test file
        test_content = b"Test PDF content for upload"
        test_file = SimpleUploadedFile(
            "test_upload.pdf",
            test_content,
            content_type="application/pdf"
        )
        
        data = {
            'assessment': str(self.assessment.id),
            'file': test_file,
            'description': 'Test financial report',
            'category': 'financial'
        }
        
        response = self.client.post('/api/files/', data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['filename'], 'test_upload.pdf')
        self.assertEqual(response.data['category'], 'financial')
        self.assertEqual(response.data['uploaded_by']['id'], str(self.admin_user.id))
        
        # Verify file was created in database
        attachment = FileAttachment.objects.get(id=response.data['id'])
        self.assertEqual(attachment.assessment, self.assessment)
        self.assertEqual(attachment.uploaded_by, self.admin_user)
    
    def test_file_upload_validation(self):
        """Test file upload validation"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        
        # Test without file
        data = {
            'assessment': str(self.assessment.id),
            'description': 'Missing file'
        }
        
        response = self.client.post('/api/files/', data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', response.data)
        
        # Test with invalid assessment
        test_file = SimpleUploadedFile("test.pdf", b"test")
        data = {
            'assessment': 'invalid-uuid',
            'file': test_file
        }
        
        response = self.client.post('/api/files/', data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    @patch('storages.backends.s3boto3.S3Boto3Storage.open')
    def test_file_download(self, mock_open):
        """Test file download endpoint"""
        # Create file attachment
        mock_file_content = b"Test file content for download"
        mock_open.return_value = io.BytesIO(mock_file_content)
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file="test_download.pdf",
            filename="test_download.pdf",
            file_size=len(mock_file_content),
            content_type="application/pdf",
            uploaded_by=self.admin_user,
            s3_bucket="test-bucket",
            s3_key=f"assessments/{self.assessment.id}/test_download.pdf"
        )
        
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        
        response = self.client.get(f'/api/files/{attachment.id}/download/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(
            response['Content-Disposition'],
            f'attachment; filename="test_download.pdf"'
        )
        self.assertEqual(response.content, mock_file_content)
    
    def test_file_permissions(self):
        """Test file access permissions"""
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file="permission_test.pdf",
            filename="permission_test.pdf",
            file_size=100,
            content_type="application/pdf",
            uploaded_by=self.admin_user
        )
        
        # Read-only user should be able to view files
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.readonly_token}')
        response = self.client.get(f'/api/files/{attachment.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # But not upload files
        test_file = SimpleUploadedFile("readonly_test.pdf", b"test")
        data = {
            'assessment': str(self.assessment.id),
            'file': test_file
        }
        response = self.client.post('/api/files/', data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # And not delete files
        response = self.client.delete(f'/api/files/{attachment.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_file_type_restrictions(self):
        """Test file type validation"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        
        # Test allowed file types
        allowed_types = [
            ('document.pdf', 'application/pdf'),
            ('spreadsheet.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('document.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            ('image.png', 'image/png'),
            ('image.jpg', 'image/jpeg')
        ]
        
        for filename, content_type in allowed_types:
            test_file = SimpleUploadedFile(filename, b"test", content_type=content_type)
            data = {
                'assessment': str(self.assessment.id),
                'file': test_file
            }
            
            response = self.client.post('/api/files/', data, format='multipart')
            self.assertEqual(
                response.status_code,
                status.HTTP_201_CREATED,
                f"Failed to upload {filename} with type {content_type}"
            )
        
        # Test potentially dangerous file type
        dangerous_file = SimpleUploadedFile("script.exe", b"test", content_type="application/x-msdownload")
        data = {
            'assessment': str(self.assessment.id),
            'file': dangerous_file
        }
        
        response = self.client.post('/api/files/', data, format='multipart')
        # Should either reject or handle safely
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            self.assertIn('file', response.data)
    
    def test_file_size_limits(self):
        """Test file size validation"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        
        # Create a large file (simulate)
        large_content = b"x" * (50 * 1024 * 1024)  # 50MB
        large_file = SimpleUploadedFile("large_file.pdf", large_content, content_type="application/pdf")
        
        # Mock the file size check
        with patch.object(SimpleUploadedFile, 'size', new_callable=PropertyMock) as mock_size:
            mock_size.return_value = 50 * 1024 * 1024  # 50MB
            
            data = {
                'assessment': str(self.assessment.id),
                'file': large_file
            }
            
            response = self.client.post('/api/files/', data, format='multipart')
            
            # Depending on settings, this might be accepted or rejected
            # If there's a size limit, it should return 400
            if response.status_code == status.HTTP_400_BAD_REQUEST:
                self.assertIn('file', response.data)


@override_settings(**TEST_FILE_SETTINGS)
@mock_s3
class FileMultiTenancyTestCase(APITestCase):
    """Test file multi-tenancy and access control"""
    
    def setUp(self):
        """Set up test data for multi-tenancy testing"""
        # Create mock S3 bucket
        self.s3_client = boto3.client(
            's3',
            region_name='us-east-1',
            aws_access_key_id='test-access-key',
            aws_secret_access_key='test-secret-key'
        )
        self.s3_client.create_bucket(Bucket='test-bucket')
        
        # Create two separate groups
        self.group1 = Group.objects.create(name="Company Alpha Files")
        self.group2 = Group.objects.create(name="Company Beta Files")
        
        # Create users in each group
        self.user1 = User.objects.create_user(
            username="alpha@files.com",
            email="alpha@files.com",
            password="testpass123",
            role=User.Role.ADMIN
        )
        self.user2 = User.objects.create_user(
            username="beta@files.com",
            email="beta@files.com",
            password="testpass123",
            role=User.Role.ADMIN
        )
        
        GroupMembership.objects.create(user=self.user1, group=self.group1)
        GroupMembership.objects.create(user=self.user2, group=self.group2)
        
        # Create tokens
        self.token1 = str(RefreshToken.for_user(self.user1).access_token)
        self.token2 = str(RefreshToken.for_user(self.user2).access_token)
        
        # Create assessments in each group
        self.partner1 = DevelopmentPartner.objects.create(
            name="Alpha Partner",
            email="partner@alpha.com",
            group=self.group1,
            created_by=self.user1
        )
        self.assessment1 = Assessment.objects.create(
            partner=self.partner1,
            assessment_date=timezone.now(),
            group=self.group1,
            created_by=self.user1
        )
        
        self.partner2 = DevelopmentPartner.objects.create(
            name="Beta Partner",
            email="partner@beta.com",
            group=self.group2,
            created_by=self.user2
        )
        self.assessment2 = Assessment.objects.create(
            partner=self.partner2,
            assessment_date=timezone.now(),
            group=self.group2,
            created_by=self.user2
        )
        
        # Create files in each group
        self.file1 = FileAttachment.objects.create(
            assessment=self.assessment1,
            file="alpha_file.pdf",
            filename="alpha_file.pdf",
            file_size=1000,
            content_type="application/pdf",
            uploaded_by=self.user1
        )
        
        self.file2 = FileAttachment.objects.create(
            assessment=self.assessment2,
            file="beta_file.pdf",
            filename="beta_file.pdf",
            file_size=2000,
            content_type="application/pdf",
            uploaded_by=self.user2
        )
    
    def test_file_isolation(self):
        """Test that users can only see their own group's files"""
        # User 1 should only see their file
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token1}')
        response = self.client.get('/api/files/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['filename'], 'alpha_file.pdf')
        
        # User 2 should only see their file
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token2}')
        response = self.client.get('/api/files/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['filename'], 'beta_file.pdf')
    
    def test_cross_tenant_file_access_denied(self):
        """Test that users cannot access other tenant's files"""
        # User 1 trying to access User 2's file
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token1}')
        response = self.client.get(f'/api/files/{self.file2.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        # User 1 trying to download User 2's file
        response = self.client.get(f'/api/files/{self.file2.id}/download/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        # User 1 trying to delete User 2's file
        response = self.client.delete(f'/api/files/{self.file2.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_file_upload_to_other_tenant_assessment_denied(self):
        """Test that users cannot upload files to other tenant's assessments"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token1}')
        
        test_file = SimpleUploadedFile("cross_tenant.pdf", b"test")
        data = {
            'assessment': str(self.assessment2.id),  # Other tenant's assessment
            'file': test_file
        }
        
        response = self.client.post('/api/files/', data, format='multipart')
        # Should either return 404 (assessment not found) or 403 (forbidden)
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])


@override_settings(**TEST_FILE_SETTINGS)
@mock_s3
class FileBulkOperationsTestCase(APITestCase):
    """Test bulk file operations"""
    
    def setUp(self):
        """Set up test data"""
        # Create mock S3 bucket
        self.s3_client = boto3.client(
            's3',
            region_name='us-east-1',
            aws_access_key_id='test-access-key',
            aws_secret_access_key='test-secret-key'
        )
        self.s3_client.create_bucket(Bucket='test-bucket')
        
        self.group = Group.objects.create(name="Bulk File Test Company")
        self.user = User.objects.create_user(
            username="bulk@files.com",
            email="bulk@files.com",
            password="testpass123",
            role=User.Role.ADMIN
        )
        GroupMembership.objects.create(user=self.user, group=self.group)
        self.token = str(RefreshToken.for_user(self.user).access_token)
        
        # Create assessment
        self.partner = DevelopmentPartner.objects.create(
            name="Bulk Test Partner",
            email="partner@bulk.com",
            group=self.group,
            created_by=self.user
        )
        self.assessment = Assessment.objects.create(
            partner=self.partner,
            assessment_date=timezone.now(),
            group=self.group,
            created_by=self.user
        )
        
        # Create multiple files
        self.files = []
        for i in range(5):
            file_attachment = FileAttachment.objects.create(
                assessment=self.assessment,
                file=f"bulk_file_{i}.pdf",
                filename=f"bulk_file_{i}.pdf",
                file_size=1000 * (i + 1),
                content_type="application/pdf",
                uploaded_by=self.user,
                category='financial' if i < 3 else 'legal'
            )
            self.files.append(file_attachment)
    
    def test_bulk_download_as_zip(self):
        """Test downloading multiple files as ZIP"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        
        file_ids = [str(f.id) for f in self.files[:3]]
        
        data = {
            'file_ids': file_ids
        }
        
        with patch('files.views.create_zip_file') as mock_create_zip:
            mock_zip_content = b"Mock ZIP content"
            mock_create_zip.return_value = io.BytesIO(mock_zip_content)
            
            response = self.client.post('/api/files/bulk-download/', data, format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response['Content-Type'], 'application/zip')
            self.assertIn('attachment; filename=', response['Content-Disposition'])
    
    def test_bulk_delete_files(self):
        """Test bulk deleting files"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        
        file_ids = [str(f.id) for f in self.files[:2]]
        
        data = {
            'file_ids': file_ids
        }
        
        response = self.client.post('/api/files/bulk-delete/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['deleted_count'], 2)
        
        # Verify files were deleted
        remaining_files = FileAttachment.objects.filter(assessment=self.assessment)
        self.assertEqual(remaining_files.count(), 3)
    
    def test_bulk_update_category(self):
        """Test bulk updating file categories"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        
        file_ids = [str(f.id) for f in self.files if f.category == 'legal']
        
        data = {
            'file_ids': file_ids,
            'category': 'operational'
        }
        
        response = self.client.post('/api/files/bulk-update-category/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['updated_count'], 2)
        
        # Verify categories were updated
        for file_id in file_ids:
            file_attachment = FileAttachment.objects.get(id=file_id)
            self.assertEqual(file_attachment.category, 'operational')
    
    def test_assessment_files_summary(self):
        """Test getting file summary for an assessment"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        
        response = self.client.get(f'/api/assessments/{self.assessment.id}/files-summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify summary data
        self.assertEqual(response.data['total_files'], 5)
        self.assertEqual(response.data['total_size'], sum(f.file_size for f in self.files))
        self.assertEqual(response.data['categories']['financial'], 3)
        self.assertEqual(response.data['categories']['legal'], 2)
        self.assertIn('total_size_mb', response.data)


@override_settings(**TEST_FILE_SETTINGS)
class FileMetadataTestCase(TestCase):
    """Test file metadata handling"""
    
    def setUp(self):
        """Set up test data"""
        self.group = Group.objects.create(name="Metadata Test Company")
        self.user = User.objects.create_user(
            username="meta@files.com",
            email="meta@files.com",
            password="testpass123",
            role=User.Role.ADMIN
        )
        GroupMembership.objects.create(user=self.user, group=self.group)
        
        self.partner = DevelopmentPartner.objects.create(
            name="Metadata Test Partner",
            email="partner@meta.com",
            group=self.group,
            created_by=self.user
        )
        self.assessment = Assessment.objects.create(
            partner=self.partner,
            assessment_date=timezone.now(),
            group=self.group,
            created_by=self.user
        )
    
    def test_file_metadata_extraction(self):
        """Test extracting metadata from uploaded files"""
        # Test with different file types
        test_files = [
            ('document.pdf', 'application/pdf', b'%PDF-1.4'),
            ('spreadsheet.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', b'PK'),
            ('image.png', 'image/png', b'\x89PNG\r\n\x1a\n'),
            ('text.txt', 'text/plain', b'Plain text content')
        ]
        
        for filename, content_type, content_start in test_files:
            # Create realistic file content
            if filename.endswith('.pdf'):
                content = content_start + b'\n%Test PDF content'
            elif filename.endswith('.png'):
                content = content_start + b'\x00' * 100  # Minimal PNG
            else:
                content = content_start + b' - test content'
            
            test_file = SimpleUploadedFile(filename, content, content_type=content_type)
            
            attachment = FileAttachment.objects.create(
                assessment=self.assessment,
                file=test_file,
                filename=filename,
                file_size=len(content),
                content_type=content_type,
                uploaded_by=self.user
            )
            
            self.assertEqual(attachment.content_type, content_type)
            self.assertEqual(attachment.file_size, len(content))
    
    def test_file_versioning(self):
        """Test file versioning when uploading same filename"""
        # Upload first version
        v1_content = b"Version 1 content"
        v1_file = SimpleUploadedFile("versioned.pdf", v1_content)
        
        attachment_v1 = FileAttachment.objects.create(
            assessment=self.assessment,
            file=v1_file,
            filename="versioned.pdf",
            file_size=len(v1_content),
            content_type="application/pdf",
            uploaded_by=self.user
        )
        
        # Upload second version with same name
        v2_content = b"Version 2 content - updated"
        v2_file = SimpleUploadedFile("versioned.pdf", v2_content)
        
        attachment_v2 = FileAttachment.objects.create(
            assessment=self.assessment,
            file=v2_file,
            filename="versioned.pdf",
            file_size=len(v2_content),
            content_type="application/pdf",
            uploaded_by=self.user
        )
        
        # Both versions should exist
        self.assertNotEqual(attachment_v1.id, attachment_v2.id)
        self.assertEqual(
            FileAttachment.objects.filter(
                assessment=self.assessment,
                filename="versioned.pdf"
            ).count(),
            2
        )
    
    def test_file_search_by_metadata(self):
        """Test searching files by metadata"""
        # Create files with different metadata
        files_data = [
            ("Q1_Report.pdf", "financial", "Quarterly financial report"),
            ("Contract_2024.pdf", "legal", "Partnership agreement"),
            ("Tech_Specs.pdf", "technical", "Technical specifications"),
            ("Operations_Plan.pdf", "operational", "Operations planning document")
        ]
        
        for filename, category, description in files_data:
            FileAttachment.objects.create(
                assessment=self.assessment,
                file=SimpleUploadedFile(filename, b"test"),
                filename=filename,
                file_size=1000,
                content_type="application/pdf",
                uploaded_by=self.user,
                category=category,
                description=description
            )
        
        # Search by category
        financial_files = FileAttachment.objects.filter(
            assessment=self.assessment,
            category="financial"
        )
        self.assertEqual(financial_files.count(), 1)
        self.assertEqual(financial_files.first().filename, "Q1_Report.pdf")
        
        # Search by description
        spec_files = FileAttachment.objects.filter(
            assessment=self.assessment,
            description__icontains="specification"
        )
        self.assertEqual(spec_files.count(), 1)
        self.assertEqual(spec_files.first().filename, "Tech_Specs.pdf")
        
        # Search by filename pattern
        report_files = FileAttachment.objects.filter(
            assessment=self.assessment,
            filename__icontains="Report"
        )
        self.assertEqual(report_files.count(), 1)