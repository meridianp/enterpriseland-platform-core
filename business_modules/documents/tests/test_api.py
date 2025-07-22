"""Tests for document management API."""

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from ..models import Document, Folder, DocumentTemplate, SharedLink

User = get_user_model()


class FolderAPITest(TestCase):
    """Test folder API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
        
        self.client.force_authenticate(user=self.user)
        
        # Create test folder
        self.folder = Folder.objects.create(
            name='Test Folder',
            description='Test description',
            group=self.group,
            created_by=self.user
        )
    
    def test_list_folders(self):
        """Test listing folders."""
        url = reverse('documents_api_v1:folder-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], 'Test Folder')
    
    def test_create_folder(self):
        """Test creating a folder."""
        url = reverse('documents_api_v1:folder-list')
        data = {
            'name': 'New Folder',
            'description': 'New folder description',
            'parent_id': str(self.folder.id)
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'New Folder')
        self.assertEqual(response.data['parent']['id'], str(self.folder.id))
        self.assertEqual(response.data['path'], '/Test Folder/New Folder')
    
    def test_update_folder(self):
        """Test updating a folder."""
        url = reverse('documents_api_v1:folder-detail', args=[self.folder.id])
        data = {
            'name': 'Updated Folder',
            'description': 'Updated description'
        }
        
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Updated Folder')
        self.assertEqual(response.data['description'], 'Updated description')
    
    def test_delete_folder(self):
        """Test deleting a folder."""
        # Create empty folder
        folder = Folder.objects.create(
            name='Delete Me',
            group=self.group,
            created_by=self.user
        )
        
        url = reverse('documents_api_v1:folder-detail', args=[folder.id])
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Folder.objects.filter(id=folder.id).exists())
    
    def test_folder_tree(self):
        """Test getting folder tree."""
        # Create subfolder
        subfolder = Folder.objects.create(
            name='Subfolder',
            parent=self.folder,
            group=self.group,
            created_by=self.user
        )
        
        url = reverse('documents_api_v1:folder-tree', args=[self.folder.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Test Folder')
        self.assertEqual(len(response.data['children']), 1)
        self.assertEqual(response.data['children'][0]['name'], 'Subfolder')
    
    def test_move_folder(self):
        """Test moving folder."""
        # Create folders
        source = Folder.objects.create(
            name='Source',
            group=self.group,
            created_by=self.user
        )
        target = Folder.objects.create(
            name='Target',
            group=self.group,
            created_by=self.user
        )
        
        url = reverse('documents_api_v1:folder-move', args=[source.id])
        data = {'parent_id': str(target.id)}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['parent']['id'], str(target.id))
        self.assertEqual(response.data['path'], '/Target/Source')


class DocumentAPITest(TestCase):
    """Test document API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
        
        self.client.force_authenticate(user=self.user)
        
        # Create test folder
        self.folder = Folder.objects.create(
            name='Test Folder',
            group=self.group,
            created_by=self.user
        )
        
        # Create test document
        self.document = Document.objects.create(
            name='Test Document',
            description='Test description',
            folder=self.folder,
            file_path='/documents/test.pdf',
            file_name='test.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            tags=['test', 'pdf'],
            group=self.group,
            created_by=self.user
        )
    
    def test_list_documents(self):
        """Test listing documents."""
        url = reverse('documents_api_v1:document-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], 'Test Document')
    
    @patch('business_modules.documents.services.storage_service.StorageService.upload_file')
    @patch('business_modules.documents.services.virus_scan_service.VirusScanService.scan_file')
    def test_upload_document(self, mock_scan, mock_upload):
        """Test uploading a document."""
        # Mock services
        mock_scan.return_value = {'status': 'clean'}
        mock_upload.return_value = {
            'path': '/documents/new.pdf',
            'url': 'https://example.com/new.pdf',
            'content_type': 'application/pdf'
        }
        
        url = reverse('documents_api_v1:document-upload')
        
        # Create test file
        file = SimpleUploadedFile('new.pdf', b'PDF content', content_type='application/pdf')
        
        data = {
            'file': file,
            'name': 'New Document',
            'description': 'New document description',
            'folder_id': str(self.folder.id),
            'tags': ['new', 'upload'],
            'category': 'test'
        }
        
        response = self.client.post(url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'New Document')
        self.assertEqual(response.data['folder']['id'], str(self.folder.id))
        self.assertEqual(response.data['tags'], ['new', 'upload'])
    
    def test_update_document(self):
        """Test updating a document."""
        url = reverse('documents_api_v1:document-detail', args=[self.document.id])
        data = {
            'name': 'Updated Document',
            'description': 'Updated description',
            'tags': ['updated', 'modified']
        }
        
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Updated Document')
        self.assertEqual(response.data['tags'], ['updated', 'modified'])
    
    @patch('business_modules.documents.services.storage_service.StorageService.download_file')
    def test_download_document(self, mock_download):
        """Test downloading a document."""
        # Mock download
        mock_download.return_value = b'PDF content'
        
        url = reverse('documents_api_v1:document-download', args=[self.document.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="test.pdf"')
        self.assertEqual(response.content, b'PDF content')
    
    def test_lock_unlock_document(self):
        """Test locking and unlocking document."""
        # Lock document
        url = reverse('documents_api_v1:document-lock', args=[self.document.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Refresh document
        self.document.refresh_from_db()
        self.assertTrue(self.document.is_locked)
        self.assertEqual(self.document.locked_by, self.user)
        
        # Unlock document
        url = reverse('documents_api_v1:document-unlock', args=[self.document.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Refresh document
        self.document.refresh_from_db()
        self.assertFalse(self.document.is_locked)
        self.assertIsNone(self.document.locked_by)
    
    def test_document_search(self):
        """Test document search."""
        url = reverse('documents_api_v1:document-search')
        data = {
            'query': 'Test',
            'category': 'test',
            'tags': ['pdf']
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('total', response.data)
        self.assertIn('documents', response.data)
        self.assertGreater(response.data['total'], 0)
    
    def test_share_document(self):
        """Test creating shared link."""
        url = reverse('documents_api_v1:document-share', args=[self.document.id])
        data = {
            'title': 'Shared Document',
            'allow_view': True,
            'allow_download': True,
            'expiry_days': 7
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertIn('public_url', response.data)
        self.assertTrue(response.data['allow_view'])
        self.assertTrue(response.data['allow_download'])
    
    def test_bulk_operations(self):
        """Test bulk operations."""
        # Create another document
        doc2 = Document.objects.create(
            name='Document 2',
            file_path='/documents/doc2.pdf',
            file_name='doc2.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=2048,
            checksum='xyz789',
            group=self.group,
            created_by=self.user
        )
        
        url = reverse('documents_api_v1:document-bulk')
        
        # Test bulk tagging
        data = {
            'operation': 'tag',
            'document_ids': [str(self.document.id), str(doc2.id)],
            'tags': ['bulk', 'tagged']
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['tagged'], 2)
        
        # Verify tags were added
        self.document.refresh_from_db()
        self.assertIn('bulk', self.document.tags)
        self.assertIn('tagged', self.document.tags)


class DocumentTemplateAPITest(TestCase):
    """Test document template API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
        
        self.client.force_authenticate(user=self.user)
        
        # Create test template
        self.template = DocumentTemplate.objects.create(
            name='Test Template',
            description='Template description',
            category='test',
            file_path='/templates/test.docx',
            file_type='docx',
            is_public=True,
            group=self.group,
            created_by=self.user
        )
    
    def test_list_templates(self):
        """Test listing templates."""
        url = reverse('documents_api_v1:template-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], 'Test Template')
        self.assertTrue(response.data['results'][0]['can_use'])
    
    @patch('business_modules.documents.services.template_service.TemplateService.create_document_from_template')
    def test_use_template(self, mock_create):
        """Test using a template."""
        # Mock template service
        mock_document = MagicMock()
        mock_document.id = 'doc123'
        mock_document.name = 'Generated Document'
        mock_create.return_value = mock_document
        
        url = reverse('documents_api_v1:template-use', args=[self.template.id])
        data = {
            'data': {
                'name': 'John Doe',
                'date': '2024-01-01',
                'amount': '1000'
            },
            'name': 'Generated from Template'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify template service was called
        mock_create.assert_called_once()
    
    def test_preview_template(self):
        """Test previewing template."""
        url = reverse('documents_api_v1:template-preview', args=[self.template.id])
        data = {
            'data': {
                'name': 'Preview Name',
                'value': 'Preview Value'
            }
        }
        
        with patch('business_modules.documents.services.template_service.TemplateService.preview_template') as mock_preview:
            mock_preview.return_value = {
                'success': True,
                'preview_html': '<p>Preview content</p>',
                'sample_data': data['data']
            }
            
            response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('preview_html', response.data)


class SharedLinkAPITest(TestCase):
    """Test shared link API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
        
        self.client.force_authenticate(user=self.user)
        
        # Create test document
        self.document = Document.objects.create(
            name='Test Document',
            file_path='/documents/test.pdf',
            file_name='test.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            group=self.group,
            created_by=self.user
        )
        
        # Create shared link
        self.shared_link = SharedLink.create_for_document(
            document=self.document,
            user=self.user,
            days=7,
            allow_view=True,
            allow_download=True
        )
    
    def test_list_shared_links(self):
        """Test listing shared links."""
        url = reverse('documents_api_v1:sharedlink-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['token'], self.shared_link.token)
    
    def test_revoke_shared_link(self):
        """Test revoking shared link."""
        url = reverse('documents_api_v1:sharedlink-revoke', args=[self.shared_link.id])
        data = {'reason': 'No longer needed'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify link was revoked
        self.shared_link.refresh_from_db()
        self.assertFalse(self.shared_link.is_active)
        self.assertEqual(self.shared_link.revoke_reason, 'No longer needed')


class PermissionAPITest(TestCase):
    """Test permission-related API functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
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
        self.group = self.owner.groups.first()
        
        # Create test document
        self.document = Document.objects.create(
            name='Protected Document',
            file_path='/documents/protected.pdf',
            file_name='protected.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            group=self.group,
            created_by=self.owner
        )
    
    def test_owner_access(self):
        """Test document owner has full access."""
        self.client.force_authenticate(user=self.owner)
        
        # List documents
        url = reverse('documents_api_v1:document-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        
        # Check permissions in response
        doc_data = response.data['results'][0]
        permissions = doc_data['permissions']
        
        self.assertIn('view', permissions)
        self.assertIn('download', permissions)
        self.assertIn('edit', permissions)
        self.assertIn('delete', permissions)
        self.assertIn('share', permissions)
        self.assertIn('manage', permissions)
    
    def test_no_permission_access(self):
        """Test user without permissions can't access document."""
        self.client.force_authenticate(user=self.viewer)
        
        # List documents - should be empty
        url = reverse('documents_api_v1:document-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)
        
        # Try to access document directly - should fail
        url = reverse('documents_api_v1:document-detail', args=[self.document.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)