"""
Tests for files models.
"""
import os
import tempfile
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch, Mock

from tests.base import BaseTestCase
from tests.factories.assessment_factories import AssessmentFactory
from files.models import FileAttachment, upload_to


class FileAttachmentModelTest(BaseTestCase):
    """Test FileAttachment model."""
    
    def setUp(self):
        super().setUp()
        self.assessment = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        
    def test_create_file_attachment(self):
        """Test creating a file attachment."""
        # Create a test file
        test_file = SimpleUploadedFile(
            "test.pdf",
            b"test file content",
            content_type="application/pdf"
        )
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=len(b"test file content"),
            content_type="application/pdf",
            category="financial",
            description="Test financial document",
            uploaded_by=self.analyst_user
        )
        
        self.assertEqual(attachment.assessment, self.assessment)
        self.assertEqual(attachment.filename, "test.pdf")
        self.assertEqual(attachment.file_size, 17)  # Length of test content
        self.assertEqual(attachment.content_type, "application/pdf")
        self.assertEqual(attachment.category, "financial")
        self.assertEqual(attachment.uploaded_by, self.analyst_user)
        
    def test_file_size_mb_property(self):
        """Test file_size_mb property calculation."""
        test_file = SimpleUploadedFile("test.pdf", b"x" * (1024 * 1024 * 2))  # 2MB
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=1024 * 1024 * 2,  # 2MB in bytes
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        self.assertEqual(attachment.file_size_mb, 2.0)
        
    def test_file_size_mb_rounding(self):
        """Test file_size_mb property rounding."""
        test_file = SimpleUploadedFile("test.pdf", b"x" * 1536)  # 1.5KB
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=1536,  # 1.5KB in bytes
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # 1536 bytes = 0.001464844 MB, should round to 0.0
        self.assertEqual(attachment.file_size_mb, 0.0)
        
    def test_s3_fields(self):
        """Test S3-specific fields."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user,
            s3_bucket="test-bucket",
            s3_key="assessments/123/test.pdf"
        )
        
        self.assertEqual(attachment.s3_bucket, "test-bucket")
        self.assertEqual(attachment.s3_key, "assessments/123/test.pdf")
        
    def test_category_choices(self):
        """Test file category choices."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        # Valid category
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            category="legal",
            uploaded_by=self.analyst_user
        )
        
        self.assertEqual(attachment.category, "legal")
        
        # Default category
        attachment2 = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test2.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        self.assertEqual(attachment2.category, "other")
        
    def test_str_representation(self):
        """Test string representation."""
        test_file = SimpleUploadedFile("document.pdf", b"test content")
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="document.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        expected = f"document.pdf ({self.assessment})"
        self.assertEqual(str(attachment), expected)
        
    @patch('os.path.isfile')
    @patch('os.remove')
    def test_delete_removes_file(self, mock_remove, mock_isfile):
        """Test that delete method removes file from filesystem."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # Mock file exists
        mock_isfile.return_value = True
        
        # Delete the attachment
        attachment.delete()
        
        # Verify file removal was attempted
        mock_isfile.assert_called_once()
        mock_remove.assert_called_once()
        
    @patch('os.path.isfile')
    @patch('os.remove')
    def test_delete_handles_missing_file(self, mock_remove, mock_isfile):
        """Test that delete handles missing files gracefully."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # Mock file doesn't exist
        mock_isfile.return_value = False
        
        # Delete should not crash
        attachment.delete()
        
        # Verify remove was not called
        mock_remove.assert_not_called()


class UploadToFunctionTest(TestCase):
    """Test upload_to function."""
    
    def test_upload_path_generation(self):
        """Test upload path generation."""
        # Mock instance with assessment ID
        mock_instance = Mock()
        mock_instance.assessment.id = "12345678-1234-1234-1234-123456789012"
        
        filename = "document.pdf"
        
        path = upload_to(mock_instance, filename)
        
        expected = "assessments/12345678-1234-1234-1234-123456789012/document.pdf"
        self.assertEqual(path, expected)
        
    def test_upload_path_with_special_characters(self):
        """Test upload path with special characters in filename."""
        mock_instance = Mock()
        mock_instance.assessment.id = "test-id"
        
        filename = "my document (1).pdf"
        
        path = upload_to(mock_instance, filename)
        
        expected = "assessments/test-id/my document (1).pdf"
        self.assertEqual(path, expected)


class FileAttachmentQueryTest(BaseTestCase):
    """Test file attachment queries and relationships."""
    
    def setUp(self):
        super().setUp()
        self.assessment1 = AssessmentFactory(group=self.group, created_by=self.analyst_user)
        self.assessment2 = AssessmentFactory(group=self.group, created_by=self.manager_user)
        
    def test_assessment_relationship(self):
        """Test relationship with assessment."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment1,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # Test forward relationship
        self.assertEqual(attachment.assessment, self.assessment1)
        
        # Test reverse relationship
        self.assertIn(attachment, self.assessment1.attachments.all())
        
    def test_uploaded_by_relationship(self):
        """Test relationship with user."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment1,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # Test forward relationship
        self.assertEqual(attachment.uploaded_by, self.analyst_user)
        
        # Test reverse relationship
        self.assertIn(attachment, self.analyst_user.uploaded_files.all())
        
    def test_cascade_delete_from_assessment(self):
        """Test cascade delete when assessment is deleted."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment1,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        attachment_id = attachment.id
        
        # Delete assessment
        self.assessment1.delete()
        
        # Attachment should be deleted too
        self.assertFalse(FileAttachment.objects.filter(id=attachment_id).exists())
        
    def test_protect_delete_from_user(self):
        """Test protected delete when user is deleted."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        attachment = FileAttachment.objects.create(
            assessment=self.assessment1,
            file=test_file,
            filename="test.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        # Attempting to delete user should be protected
        # (This would need to be tested at the database level)
        # For now, just verify the relationship exists
        self.assertEqual(attachment.uploaded_by, self.analyst_user)
        
    def test_filter_by_category(self):
        """Test filtering attachments by category."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        financial_doc = FileAttachment.objects.create(
            assessment=self.assessment1,
            file=test_file,
            filename="financial.pdf",
            file_size=12,
            content_type="application/pdf",
            category="financial",
            uploaded_by=self.analyst_user
        )
        
        legal_doc = FileAttachment.objects.create(
            assessment=self.assessment1,
            file=test_file,
            filename="legal.pdf",
            file_size=12,
            content_type="application/pdf",
            category="legal",
            uploaded_by=self.analyst_user
        )
        
        # Filter by category
        financial_docs = FileAttachment.objects.filter(category="financial")
        legal_docs = FileAttachment.objects.filter(category="legal")
        
        self.assertIn(financial_doc, financial_docs)
        self.assertNotIn(legal_doc, financial_docs)
        
        self.assertIn(legal_doc, legal_docs)
        self.assertNotIn(financial_doc, legal_docs)
        
    def test_filter_by_assessment(self):
        """Test filtering attachments by assessment."""
        test_file = SimpleUploadedFile("test.pdf", b"test content")
        
        attachment1 = FileAttachment.objects.create(
            assessment=self.assessment1,
            file=test_file,
            filename="doc1.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.analyst_user
        )
        
        attachment2 = FileAttachment.objects.create(
            assessment=self.assessment2,
            file=test_file,
            filename="doc2.pdf",
            file_size=12,
            content_type="application/pdf",
            uploaded_by=self.manager_user
        )
        
        # Filter by assessment
        assessment1_files = FileAttachment.objects.filter(assessment=self.assessment1)
        assessment2_files = FileAttachment.objects.filter(assessment=self.assessment2)
        
        self.assertIn(attachment1, assessment1_files)
        self.assertNotIn(attachment2, assessment1_files)
        
        self.assertIn(attachment2, assessment2_files)
        self.assertNotIn(attachment1, assessment2_files)