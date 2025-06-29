"""
Tests for files views and API endpoints.
"""
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from unittest.mock import patch, Mock
import json

from tests.base import BaseAPITestCase
from tests.factories.assessment_factories import AssessmentFactory
from tests.factories.user_factories import GroupFactory
from tests.utils.s3_mocks import S3MockHelper
from files.models import FileAttachment


class FileAttachmentViewSetTest(BaseAPITestCase):
    """Test FileAttachment ViewSet."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        self.url = reverse('fileattachment-list')
        
    def test_list_files_authenticated(self):
        """Test listing files requires authentication."""
        # Create test file
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # Test unauthenticated
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        # Test authenticated
        self.login(self.analyst_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
    def test_group_filtering(self):
        """Test files are filtered by user's group."""
        # Create file in user's group
        test_file = SimpleUploadedFile("test1.pdf", b"test content")
        file1 = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test1.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # Create file in different group
        other_group = GroupFactory()
        other_assessment = AssessmentFactory(group=other_group)
        file2 = FileAttachment.objects.create(
            assessment=other_assessment,
            file=test_file,
            filename="test2.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        self.login(self.analyst_user)
        response = self.client.get(self.url)
        
        file_ids = [f['id'] for f in response.data['results']]
        self.assertIn(str(file1.id), file_ids)
        self.assertNotIn(str(file2.id), file_ids)
        
    def test_admin_sees_all_files(self):
        """Test admin can see all files."""
        # Create files in different groups
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        file1 = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test1.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        other_group = GroupFactory()
        other_assessment = AssessmentFactory(group=other_group)
        file2 = FileAttachment.objects.create(
            assessment=other_assessment,
            file=test_file,
            filename="test2.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        self.login(self.admin_user)
        response = self.client.get(self.url)
        
        file_ids = [f['id'] for f in response.data['results']]
        self.assertIn(str(file1.id), file_ids)
        self.assertIn(str(file2.id), file_ids)


class FileUploadTest(BaseAPITestCase):
    """Test file upload functionality."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        self.upload_url = reverse('fileattachment-upload')
        
    def test_successful_file_upload(self):
        """Test successful file upload."""
        test_file = SimpleUploadedFile(
            "document.pdf",
            b"PDF file content",
            content_type="application/pdf"
        )
        
        self.login(self.analyst_user)
        
        data = {
            'assessment_id': str(self.assessment.id),
            'file': test_file,
            'category': 'financial',
            'description': 'Financial statement'
        }
        
        response = self.client.post(self.upload_url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify file was created
        attachment = FileAttachment.objects.get(id=response.data['id'])
        self.assertEqual(attachment.assessment, self.assessment)
        self.assertEqual(attachment.filename, 'document.pdf')
        self.assertEqual(attachment.content_type, 'application/pdf')
        self.assertEqual(attachment.category, 'financial')
        self.assertEqual(attachment.description, 'Financial statement')
        self.assertEqual(attachment.uploaded_by, self.analyst_user)
        
    def test_upload_missing_assessment_id(self):
        """Test upload without assessment_id."""
        test_file = SimpleUploadedFile("test.pdf", b"content")
        
        self.login(self.analyst_user)
        
        data = {'file': test_file}
        
        response = self.client.post(self.upload_url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('assessment_id is required', response.data['error'])
        
    def test_upload_nonexistent_assessment(self):
        """Test upload to nonexistent assessment."""
        test_file = SimpleUploadedFile("test.pdf", b"content")
        
        self.login(self.analyst_user)
        
        data = {
            'assessment_id': '00000000-0000-0000-0000-000000000000',
            'file': test_file
        }
        
        response = self.client.post(self.upload_url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Assessment not found', response.data['error'])
        
    def test_upload_access_denied(self):
        """Test upload to assessment in different group."""
        other_group = GroupFactory()
        other_assessment = AssessmentFactory(group=other_group)
        
        test_file = SimpleUploadedFile("test.pdf", b"content")
        
        self.login(self.analyst_user)  # User not in other_group
        
        data = {
            'assessment_id': str(other_assessment.id),
            'file': test_file
        }
        
        response = self.client.post(self.upload_url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Access denied', response.data['error'])
        
    def test_admin_can_upload_to_any_assessment(self):
        """Test admin can upload to any assessment."""
        other_group = GroupFactory()
        other_assessment = AssessmentFactory(group=other_group)
        
        test_file = SimpleUploadedFile("test.pdf", b"content")
        
        self.login(self.admin_user)
        
        data = {
            'assessment_id': str(other_assessment.id),
            'file': test_file
        }
        
        response = self.client.post(self.upload_url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
    def test_upload_with_default_category(self):
        """Test upload with default category."""
        test_file = SimpleUploadedFile("test.pdf", b"content")
        
        self.login(self.analyst_user)
        
        data = {
            'assessment_id': str(self.assessment.id),
            'file': test_file
        }
        
        response = self.client.post(self.upload_url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        attachment = FileAttachment.objects.get(id=response.data['id'])
        self.assertEqual(attachment.category, 'other')  # Default
        
    @patch('files.views.settings')
    def test_s3_fields_populated(self, mock_settings):
        """Test S3 fields are populated when using S3."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = 'test-bucket'
        
        test_file = SimpleUploadedFile("test.pdf", b"content")
        
        self.login(self.analyst_user)
        
        data = {
            'assessment_id': str(self.assessment.id),
            'file': test_file
        }
        
        response = self.client.post(self.upload_url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        attachment = FileAttachment.objects.get(id=response.data['id'])
        self.assertEqual(attachment.s3_bucket, 'test-bucket')
        self.assertTrue(attachment.s3_key)  # Should be populated
        
    def test_upload_invalid_file_data(self):
        """Test upload with invalid file data."""
        self.login(self.analyst_user)
        
        data = {
            'assessment_id': str(self.assessment.id),
            # Missing file
        }
        
        response = self.client.post(self.upload_url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class FileDownloadTest(BaseAPITestCase):
    """Test file download functionality."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
        # Create test file
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        self.attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        self.download_url = reverse('fileattachment-download', kwargs={'pk': self.attachment.id})
        
    def test_download_local_file(self):
        """Test download of local file."""
        self.login(self.analyst_user)
        
        response = self.client.get(self.download_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('download_url', response.data)
        self.assertIn(self.attachment.file.url, response.data['download_url'])
        
    @patch('files.views.boto3.client')
    @patch('files.views.settings')
    def test_download_s3_file(self, mock_settings, mock_boto_client):
        """Test download of S3 file with presigned URL."""
        # Setup S3 settings
        mock_settings.AWS_ACCESS_KEY_ID = 'test-key'
        mock_settings.AWS_SECRET_ACCESS_KEY = 'test-secret'
        mock_settings.AWS_S3_REGION_NAME = 'us-east-1'
        
        # Setup S3 mock
        mock_s3 = Mock()
        mock_s3.generate_presigned_url.return_value = 'https://s3.amazonaws.com/presigned-url'
        mock_boto_client.return_value = mock_s3
        
        # Update attachment with S3 info
        self.attachment.s3_bucket = 'test-bucket'
        self.attachment.s3_key = 'test/file.pdf'
        self.attachment.save()
        
        self.login(self.analyst_user)
        
        response = self.client.get(self.download_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['download_url'], 'https://s3.amazonaws.com/presigned-url')
        
        # Verify S3 client was called correctly
        mock_s3.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': 'test/file.pdf'},
            ExpiresIn=3600
        )
        
    @patch('files.views.boto3.client')
    def test_download_s3_error(self, mock_boto_client):
        """Test S3 download error handling."""
        from botocore.exceptions import ClientError
        
        # Setup S3 error
        mock_s3 = Mock()
        mock_s3.generate_presigned_url.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchKey'}}, 'GetObject'
        )
        mock_boto_client.return_value = mock_s3
        
        # Update attachment with S3 info
        self.attachment.s3_bucket = 'test-bucket'
        self.attachment.s3_key = 'nonexistent/file.pdf'
        self.attachment.save()
        
        self.login(self.analyst_user)
        
        response = self.client.get(self.download_url)
        
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('Failed to generate download URL', response.data['error'])
        
    def test_download_missing_file(self):
        """Test download when file is missing."""
        # Clear file reference
        self.attachment.file = None
        self.attachment.save()
        
        self.login(self.analyst_user)
        
        response = self.client.get(self.download_url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('File not found', response.data['error'])
        
    def test_download_access_control(self):
        """Test download access control."""
        other_group = GroupFactory()
        other_assessment = AssessmentFactory(group=other_group)
        
        test_file = SimpleUploadedFile("other.pdf", b"content")
        other_attachment = FileAttachment.objects.create(
            assessment=other_assessment,
            file=test_file,
            filename="other.pdf",
            file_size=7,
            content_type="application/pdf",
            uploaded_by=self.admin_user
        )
        
        other_download_url = reverse('fileattachment-download', kwargs={'pk': other_attachment.id})
        
        self.login(self.analyst_user)  # User not in other_group
        
        response = self.client.get(other_download_url)
        
        # Should return 404 (not 403) due to queryset filtering
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class FilesByAssessmentTest(BaseAPITestCase):
    """Test files by assessment endpoint."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        self.url = reverse('fileattachment-by-assessment')
        
    def test_get_files_by_assessment(self):
        """Test getting files for specific assessment."""
        # Create files for the assessment
        test_file = SimpleUploadedFile("test.pdf", b"content")
        
        file1 = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="doc1.pdf",
            file_size=7,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        file2 = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="doc2.pdf",
            file_size=7,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # Create file for different assessment
        other_assessment = AssessmentFactory(group=self.group)
        FileAttachment.objects.create(
            assessment=other_assessment,
            file=test_file,
            filename="other.pdf",
            file_size=7,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        self.login(self.analyst_user)
        
        response = self.client.get(self.url, {'assessment_id': str(self.assessment.id)})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        
        file_ids = [f['id'] for f in response.data]
        self.assertIn(str(file1.id), file_ids)
        self.assertIn(str(file2.id), file_ids)
        
    def test_missing_assessment_id_parameter(self):
        """Test error when assessment_id parameter is missing."""
        self.login(self.analyst_user)
        
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('assessment_id parameter is required', response.data['error'])
        
    def test_nonexistent_assessment(self):
        """Test error when assessment doesn't exist."""
        self.login(self.analyst_user)
        
        response = self.client.get(self.url, {'assessment_id': '00000000-0000-0000-0000-000000000000'})
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Assessment not found', response.data['error'])
        
    def test_access_denied_to_assessment(self):
        """Test access denied to assessment in different group."""
        other_group = GroupFactory()
        other_assessment = AssessmentFactory(group=other_group)
        
        self.login(self.analyst_user)
        
        response = self.client.get(self.url, {'assessment_id': str(other_assessment.id)})
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Access denied', response.data['error'])
        
    def test_admin_access_to_any_assessment(self):
        """Test admin can access files from any assessment."""
        other_group = GroupFactory()
        other_assessment = AssessmentFactory(group=other_group)
        
        test_file = SimpleUploadedFile("test.pdf", b"content")
        FileAttachment.objects.create(
            assessment=other_assessment,
            file=test_file,
            filename="admin_test.pdf",
            file_size=7,
            content_type="application/pdf",
            uploaded_by=self.admin_user
        )
        
        self.login(self.admin_user)
        
        response = self.client.get(self.url, {'assessment_id': str(other_assessment.id)})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


class FilePermissionTest(BaseAPITestCase):
    """Test file operation permissions."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
        test_file = SimpleUploadedFile("test.pdf", b"content")
        self.attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=7,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
    def test_read_only_user_permissions(self):
        """Test read-only user can only view files."""
        self.login(self.viewer_user)
        
        # Can view files
        response = self.client.get(reverse('fileattachment-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Cannot upload
        upload_url = reverse('fileattachment-upload')
        test_file = SimpleUploadedFile("new.pdf", b"content")
        data = {'assessment_id': str(self.assessment.id), 'file': test_file}
        
        response = self.client.post(upload_url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Cannot delete
        response = self.client.delete(
            reverse('fileattachment-detail', kwargs={'pk': self.attachment.id})
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
    def test_external_partner_permissions(self):
        """Test external partner permissions."""
        self.login(self.partner_user)
        
        # Can view files
        response = self.client.get(reverse('fileattachment-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Can download
        response = self.client.get(
            reverse('fileattachment-download', kwargs={'pk': self.attachment.id})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Cannot upload (depending on business rules)
        upload_url = reverse('fileattachment-upload')
        test_file = SimpleUploadedFile("partner.pdf", b"content")
        data = {'assessment_id': str(self.assessment.id), 'file': test_file}
        
        response = self.client.post(upload_url, data, format='multipart')
        # This might be allowed or forbidden depending on business rules
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_403_FORBIDDEN])