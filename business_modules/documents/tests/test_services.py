"""Tests for document services."""

import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from ..models import Document, Folder, DocumentPermission, FolderPermission
from ..services import (
    DocumentService, StorageService, PermissionService,
    SearchService, PreviewService, OCRService,
    VirusScanService, EncryptionService, MetadataService
)

User = get_user_model()


class DocumentServiceTest(TestCase):
    """Test document service."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
        
        self.folder = Folder.objects.create(
            name='Test Folder',
            group=self.group,
            created_by=self.user
        )
        
        self.service = DocumentService()
    
    @patch('business_modules.documents.services.storage_service.StorageService.upload_file')
    @patch('business_modules.documents.services.virus_scan_service.VirusScanService.scan_file')
    def test_create_document(self, mock_scan, mock_upload):
        """Test creating a document."""
        # Mock virus scan
        mock_scan.return_value = {'status': 'clean'}
        
        # Mock upload
        mock_upload.return_value = {
            'path': '/documents/test.pdf',
            'url': 'https://example.com/test.pdf',
            'content_type': 'application/pdf'
        }
        
        # Create test file
        file_content = b'Test PDF content'
        file = SimpleUploadedFile('test.pdf', file_content, content_type='application/pdf')
        
        # Create document
        document = self.service.create_document(
            file=file,
            name='Test Document',
            user=self.user,
            folder=self.folder,
            description='Test description',
            tags=['test', 'pdf'],
            category='test',
            encrypt=False
        )
        
        self.assertEqual(document.name, 'Test Document')
        self.assertEqual(document.folder, self.folder)
        self.assertEqual(document.file_extension, 'pdf')
        self.assertEqual(document.mime_type, 'application/pdf')
        self.assertEqual(document.size, len(file_content))
        self.assertEqual(document.tags, ['test', 'pdf'])
        self.assertEqual(document.category, 'test')
        self.assertTrue(document.virus_scanned)
        self.assertEqual(document.virus_scan_result, 'clean')
        
        # Verify virus scan was called
        mock_scan.assert_called_once()
        
        # Verify upload was called
        mock_upload.assert_called_once()
    
    @patch('business_modules.documents.services.storage_service.StorageService.upload_file')
    @patch('business_modules.documents.services.virus_scan_service.VirusScanService.scan_file')
    def test_create_document_virus_detected(self, mock_scan, mock_upload):
        """Test creating document with virus detected."""
        # Mock virus detected
        mock_scan.return_value = {
            'status': 'infected',
            'virus_name': 'TestVirus'
        }
        
        # Create test file
        file_content = b'Infected content'
        file = SimpleUploadedFile('virus.exe', file_content)
        
        # Try to create document
        with self.assertRaises(Exception) as context:
            self.service.create_document(
                file=file,
                name='Virus File',
                user=self.user
            )
        
        self.assertIn('infected', str(context.exception))
        
        # Verify no document was created
        self.assertEqual(Document.objects.count(), 0)
    
    def test_update_document(self):
        """Test updating document."""
        # Create document
        document = Document.objects.create(
            name='Original Name',
            description='Original description',
            folder=self.folder,
            file_path='/documents/test.pdf',
            file_name='test.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            tags=['original'],
            category='original',
            group=self.group,
            created_by=self.user
        )
        
        # Update document
        updated = self.service.update_document(
            document=document,
            user=self.user,
            name='Updated Name',
            description='Updated description',
            tags=['updated', 'modified'],
            category='updated'
        )
        
        self.assertEqual(updated.name, 'Updated Name')
        self.assertEqual(updated.description, 'Updated description')
        self.assertEqual(updated.tags, ['updated', 'modified'])
        self.assertEqual(updated.category, 'updated')
        self.assertEqual(updated.modified_by, self.user)
    
    @patch('business_modules.documents.services.storage_service.StorageService.delete_file')
    def test_delete_document(self, mock_delete):
        """Test deleting document."""
        # Create document
        document = Document.objects.create(
            name='Test Document',
            folder=self.folder,
            file_path='/documents/test.pdf',
            file_name='test.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            group=self.group,
            created_by=self.user
        )
        
        # Soft delete
        self.service.delete_document(document, self.user, permanent=False)
        
        self.assertTrue(document.is_deleted)
        self.assertEqual(document.status, 'deleted')
        
        # Verify file was not deleted from storage
        mock_delete.assert_not_called()
        
        # Permanent delete
        self.service.delete_document(document, self.user, permanent=True)
        
        # Verify document is gone
        self.assertFalse(Document.objects.filter(id=document.id).exists())
        
        # Verify file was deleted from storage
        mock_delete.assert_called_with('/documents/test.pdf')


class PermissionServiceTest(TestCase):
    """Test permission service."""
    
    def setUp(self):
        """Set up test data."""
        self.owner = User.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='testpass'
        )
        self.viewer = User.objects.create_user(
            username='viewer',
            email='viewer@example.com',
            password='testpass'
        )
        self.editor = User.objects.create_user(
            username='editor',
            email='editor@example.com',
            password='testpass'
        )
        self.group = self.owner.groups.first()
        
        self.folder = Folder.objects.create(
            name='Test Folder',
            group=self.group,
            created_by=self.owner
        )
        
        self.document = Document.objects.create(
            name='Test Document',
            folder=self.folder,
            file_path='/documents/test.pdf',
            file_name='test.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            group=self.group,
            created_by=self.owner
        )
        
        self.service = PermissionService()
    
    def test_document_owner_permissions(self):
        """Test document owner has all permissions."""
        self.assertTrue(self.service.has_document_permission(self.owner, self.document, 'view'))
        self.assertTrue(self.service.has_document_permission(self.owner, self.document, 'download'))
        self.assertTrue(self.service.has_document_permission(self.owner, self.document, 'edit'))
        self.assertTrue(self.service.has_document_permission(self.owner, self.document, 'delete'))
        self.assertTrue(self.service.has_document_permission(self.owner, self.document, 'share'))
        self.assertTrue(self.service.has_document_permission(self.owner, self.document, 'manage'))
    
    def test_grant_document_permission(self):
        """Test granting document permissions."""
        # Grant view permission
        permission = self.service.grant_document_permission(
            document=self.document,
            permission='view',
            granted_by=self.owner,
            user=self.viewer
        )
        
        self.assertEqual(permission.document, self.document)
        self.assertEqual(permission.user, self.viewer)
        self.assertEqual(permission.permission, 'view')
        self.assertEqual(permission.granted_by, self.owner)
        
        # Verify permission works
        self.assertTrue(self.service.has_document_permission(self.viewer, self.document, 'view'))
        self.assertFalse(self.service.has_document_permission(self.viewer, self.document, 'edit'))
    
    def test_folder_permission_inheritance(self):
        """Test folder permission inheritance."""
        # Grant edit permission on folder
        self.service.grant_folder_permission(
            folder=self.folder,
            permission='edit',
            granted_by=self.owner,
            user=self.editor,
            apply_to_documents=True,
            apply_to_subfolders=True
        )
        
        # Check document permission is inherited
        self.assertTrue(self.service.has_document_permission(self.editor, self.document, 'view'))
        self.assertTrue(self.service.has_document_permission(self.editor, self.document, 'edit'))
        self.assertFalse(self.service.has_document_permission(self.editor, self.document, 'delete'))
        
        # Create subfolder
        subfolder = Folder.objects.create(
            name='Subfolder',
            parent=self.folder,
            group=self.group,
            created_by=self.owner
        )
        
        # Check subfolder permission is inherited
        self.assertTrue(self.service.has_folder_permission(self.editor, subfolder, 'edit'))
    
    def test_get_accessible_documents(self):
        """Test getting accessible document IDs."""
        # Create another document user can't access
        other_doc = Document.objects.create(
            name='Other Document',
            file_path='/documents/other.pdf',
            file_name='other.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='xyz789',
            group=self.group,
            created_by=self.owner
        )
        
        # Grant permission only to first document
        self.service.grant_document_permission(
            document=self.document,
            permission='view',
            granted_by=self.owner,
            user=self.viewer
        )
        
        # Get accessible documents
        accessible_ids = self.service.get_accessible_document_ids(self.viewer)
        
        self.assertIn(str(self.document.id), accessible_ids)
        self.assertNotIn(str(other_doc.id), accessible_ids)


class StorageServiceTest(TestCase):
    """Test storage service."""
    
    def setUp(self):
        """Set up test data."""
        self.service = StorageService()
    
    @override_settings(DOCUMENTS_STORAGE_BACKEND='local')
    def test_generate_path(self):
        """Test generating storage path."""
        user = User.objects.create_user(username='test', email='test@example.com')
        
        path = self.service.generate_path(
            file_name='test document.pdf',
            user=user
        )
        
        self.assertIn('documents/', path)
        self.assertIn(str(user.id), path)
        self.assertIn('.pdf', path)
        # Path should be unique
        self.assertNotEqual(path, self.service.generate_path('test document.pdf', user=user))
    
    @patch('boto3.client')
    @override_settings(
        DOCUMENTS_STORAGE_BACKEND='s3',
        AWS_ACCESS_KEY_ID='test',
        AWS_SECRET_ACCESS_KEY='test',
        AWS_STORAGE_BUCKET_NAME='test-bucket'
    )
    def test_s3_upload(self, mock_boto):
        """Test S3 file upload."""
        # Mock S3 client
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.put_object.return_value = {'ETag': 'abc123'}
        
        service = StorageService()
        
        # Upload file
        result = service.upload_file(
            file_content=b'Test content',
            path='documents/test.pdf',
            content_type='application/pdf'
        )
        
        self.assertEqual(result['path'], 'documents/test.pdf')
        self.assertIn('url', result)
        
        # Verify S3 was called
        mock_s3.put_object.assert_called_once()
        call_args = mock_s3.put_object.call_args[1]
        self.assertEqual(call_args['Bucket'], 'test-bucket')
        self.assertEqual(call_args['Key'], 'documents/test.pdf')
        self.assertEqual(call_args['ContentType'], 'application/pdf')


class SearchServiceTest(TestCase):
    """Test search service."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='test',
            email='test@example.com'
        )
        self.group = self.user.groups.first()
        
        # Create test documents
        self.doc1 = Document.objects.create(
            name='Python Programming Guide',
            description='A comprehensive guide to Python',
            file_path='/docs/python.pdf',
            file_name='python.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            tags=['python', 'programming'],
            category='tutorial',
            group=self.group,
            created_by=self.user
        )
        
        self.doc2 = Document.objects.create(
            name='Django Best Practices',
            description='Best practices for Django development',
            file_path='/docs/django.pdf',
            file_name='django.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=2048,
            checksum='xyz789',
            tags=['django', 'python', 'web'],
            category='guide',
            group=self.group,
            created_by=self.user
        )
        
        self.service = SearchService()
    
    @override_settings(DOCUMENTS_ELASTICSEARCH_ENABLED=False)
    def test_postgres_search(self):
        """Test PostgreSQL full-text search."""
        # Search for Python
        results = self.service.search_documents(
            query='Python',
            document_ids=[str(self.doc1.id), str(self.doc2.id)]
        )
        
        self.assertEqual(results['total'], 2)
        doc_ids = [doc['id'] for doc in results['documents']]
        self.assertIn(str(self.doc1.id), doc_ids)
        self.assertIn(str(self.doc2.id), doc_ids)
        
        # Search for Django
        results = self.service.search_documents(
            query='Django',
            document_ids=[str(self.doc1.id), str(self.doc2.id)]
        )
        
        self.assertEqual(results['total'], 1)
        self.assertEqual(results['documents'][0]['id'], str(self.doc2.id))
    
    @override_settings(DOCUMENTS_ELASTICSEARCH_ENABLED=False)
    def test_search_with_filters(self):
        """Test search with filters."""
        # Filter by category
        results = self.service.search_documents(
            query='',
            document_ids=[str(self.doc1.id), str(self.doc2.id)],
            filters={'category': 'tutorial'}
        )
        
        self.assertEqual(results['total'], 1)
        self.assertEqual(results['documents'][0]['id'], str(self.doc1.id))
        
        # Filter by tags
        results = self.service.search_documents(
            query='',
            document_ids=[str(self.doc1.id), str(self.doc2.id)],
            filters={'tags': ['web']}
        )
        
        self.assertEqual(results['total'], 1)
        self.assertEqual(results['documents'][0]['id'], str(self.doc2.id))
        
        # Filter by size
        results = self.service.search_documents(
            query='',
            document_ids=[str(self.doc1.id), str(self.doc2.id)],
            filters={'size_min': 1500}
        )
        
        self.assertEqual(results['total'], 1)
        self.assertEqual(results['documents'][0]['id'], str(self.doc2.id))


class EncryptionServiceTest(TestCase):
    """Test encryption service."""
    
    def setUp(self):
        """Set up test data."""
        self.service = EncryptionService()
    
    def test_encrypt_decrypt_file(self):
        """Test file encryption and decryption."""
        # Test data
        original_content = b'This is sensitive document content'
        
        # Encrypt
        result = self.service.encrypt_file(original_content)
        
        self.assertTrue(result['success'])
        self.assertIn('encrypted_content', result)
        self.assertIn('key_id', result)
        
        encrypted_content = result['encrypted_content']
        key_id = result['key_id']
        
        # Verify encrypted is different from original
        self.assertNotEqual(encrypted_content, original_content)
        self.assertGreater(len(encrypted_content), len(original_content))
        
        # Decrypt
        decrypted_content = self.service.decrypt_file(encrypted_content, key_id)
        
        # Verify decrypted matches original
        self.assertEqual(decrypted_content, original_content)
    
    def test_encrypt_metadata(self):
        """Test metadata encryption."""
        # Test metadata
        metadata = {
            'author': 'John Doe',
            'title': 'Confidential Report',
            'keywords': ['secret', 'confidential'],
            'created': '2024-01-01'
        }
        
        # Encrypt
        encrypted = self.service.encrypt_metadata(metadata)
        
        self.assertIsInstance(encrypted, str)
        self.assertIn(':', encrypted)  # Should have key_id:content format
        
        # Decrypt
        decrypted = self.service.decrypt_metadata(encrypted)
        
        self.assertEqual(decrypted, metadata)
    
    def test_filename_encryption(self):
        """Test filename encryption."""
        # Test filename
        original = 'confidential_report_2024.pdf'
        
        # Encrypt
        encrypted = self.service.encrypt_filename(original)
        
        # Should preserve extension
        self.assertTrue(encrypted.endswith('.pdf'))
        
        # Should be different from original
        self.assertNotEqual(encrypted, original)


class VirusScanServiceTest(TestCase):
    """Test virus scan service."""
    
    def setUp(self):
        """Set up test data."""
        self.service = VirusScanService()
    
    @patch('subprocess.run')
    @override_settings(VIRUS_SCAN_METHOD='clamav')
    def test_clamav_clean_file(self, mock_run):
        """Test ClamAV scan with clean file."""
        # Mock clean scan result
        mock_run.return_value = Mock(
            returncode=0,
            stdout='test.pdf: OK',
            stderr=''
        )
        
        result = self.service.scan_file(b'Clean file content')
        
        self.assertEqual(result['status'], 'clean')
        self.assertEqual(result['scanner'], 'clamav')
        
        # Verify clamscan was called
        mock_run.assert_called_once()
        self.assertIn('clamscan', mock_run.call_args[0][0])
    
    @patch('subprocess.run')
    @override_settings(VIRUS_SCAN_METHOD='clamav')
    def test_clamav_infected_file(self, mock_run):
        """Test ClamAV scan with infected file."""
        # Mock infected scan result
        mock_run.return_value = Mock(
            returncode=1,
            stdout='test.exe: Win.Test.EICAR-HDB-1 FOUND',
            stderr=''
        )
        
        result = self.service.scan_file(b'EICAR test string')
        
        self.assertEqual(result['status'], 'infected')
        self.assertEqual(result['scanner'], 'clamav')
        self.assertIn('virus_name', result)
    
    @override_settings(DOCUMENTS_VIRUS_SCAN_ENABLED=False)
    def test_scan_disabled(self):
        """Test when virus scanning is disabled."""
        result = self.service.scan_file(b'Any content')
        
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('disabled', result['message'])