"""Tests for document models."""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta

from ..models import (
    Document, DocumentVersion, Folder,
    DocumentPermission, FolderPermission,
    SharedLink, DocumentTemplate
)

User = get_user_model()


class FolderModelTest(TestCase):
    """Test folder model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
    
    def test_folder_creation(self):
        """Test creating a folder."""
        folder = Folder.objects.create(
            name='Test Folder',
            description='Test description',
            group=self.group,
            created_by=self.user
        )
        
        self.assertEqual(folder.name, 'Test Folder')
        self.assertEqual(folder.path, '/Test Folder')
        self.assertEqual(folder.document_count, 0)
        self.assertEqual(folder.total_size, 0)
    
    def test_nested_folders(self):
        """Test creating nested folders."""
        parent = Folder.objects.create(
            name='Parent',
            group=self.group,
            created_by=self.user
        )
        
        child = Folder.objects.create(
            name='Child',
            parent=parent,
            group=self.group,
            created_by=self.user
        )
        
        self.assertEqual(child.path, '/Parent/Child')
        self.assertEqual(child.get_ancestors_with_self().count(), 2)
        self.assertEqual(parent.get_children().count(), 1)
    
    def test_folder_uniqueness(self):
        """Test folder name uniqueness in same parent."""
        parent = Folder.objects.create(
            name='Parent',
            group=self.group,
            created_by=self.user
        )
        
        Folder.objects.create(
            name='Child',
            parent=parent,
            group=self.group,
            created_by=self.user
        )
        
        # Try to create duplicate
        with self.assertRaises(ValidationError):
            folder = Folder(
                name='Child',
                parent=parent,
                group=self.group,
                created_by=self.user
            )
            folder.clean()
    
    def test_folder_move(self):
        """Test moving folder to new parent."""
        parent1 = Folder.objects.create(
            name='Parent1',
            group=self.group,
            created_by=self.user
        )
        
        parent2 = Folder.objects.create(
            name='Parent2',
            group=self.group,
            created_by=self.user
        )
        
        child = Folder.objects.create(
            name='Child',
            parent=parent1,
            group=self.group,
            created_by=self.user
        )
        
        # Move to parent2
        child.move_to(parent2)
        
        self.assertEqual(child.parent, parent2)
        self.assertEqual(child.path, '/Parent2/Child')
    
    def test_system_folder(self):
        """Test system folder protection."""
        folder = Folder.objects.create(
            name='System',
            is_system=True,
            group=self.group,
            created_by=self.user
        )
        
        self.assertFalse(folder.can_delete())


class DocumentModelTest(TestCase):
    """Test document model."""
    
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
    
    def test_document_creation(self):
        """Test creating a document."""
        document = Document.objects.create(
            name='Test Document',
            description='Test description',
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
        
        self.assertEqual(document.name, 'Test Document')
        self.assertEqual(document.status, 'active')
        self.assertFalse(document.is_deleted)
        self.assertEqual(document.version_number, 1)
    
    def test_document_soft_delete(self):
        """Test soft deleting a document."""
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
        document.soft_delete(self.user)
        
        self.assertTrue(document.is_deleted)
        self.assertEqual(document.status, 'deleted')
        self.assertIsNotNone(document.deleted_at)
        
        # Document still exists in database
        self.assertTrue(Document.objects.filter(id=document.id).exists())
    
    def test_document_locking(self):
        """Test document locking."""
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
        
        # Lock document
        document.lock(self.user)
        
        self.assertTrue(document.is_locked)
        self.assertEqual(document.locked_by, self.user)
        self.assertIsNotNone(document.locked_at)
        
        # Try to lock by another user
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass'
        )
        
        with self.assertRaises(ValueError):
            document.lock(other_user)
        
        # Unlock
        document.unlock(self.user)
        
        self.assertFalse(document.is_locked)
        self.assertIsNone(document.locked_by)
        self.assertIsNone(document.locked_at)
    
    def test_document_tags(self):
        """Test document tags."""
        document = Document.objects.create(
            name='Test Document',
            folder=self.folder,
            file_path='/documents/test.pdf',
            file_name='test.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            tags=['important', 'reviewed', 'final'],
            group=self.group,
            created_by=self.user
        )
        
        self.assertEqual(len(document.tags), 3)
        self.assertIn('important', document.tags)
        
        # Query by tag
        tagged_docs = Document.objects.filter(tags__contains=['important'])
        self.assertEqual(tagged_docs.count(), 1)
    
    def test_document_retention(self):
        """Test document retention."""
        retention_date = datetime.now().date() + timedelta(days=365)
        
        document = Document.objects.create(
            name='Test Document',
            folder=self.folder,
            file_path='/documents/test.pdf',
            file_name='test.pdf',
            file_extension='pdf',
            mime_type='application/pdf',
            size=1024,
            checksum='abc123',
            retention_date=retention_date,
            group=self.group,
            created_by=self.user
        )
        
        self.assertEqual(document.retention_date, retention_date)


class DocumentVersionTest(TestCase):
    """Test document versioning."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
        
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
    
    def test_version_creation(self):
        """Test creating document versions."""
        # Create version
        version = DocumentVersion.objects.create(
            document=self.document,
            version_number=1,
            file_path='/documents/test_v1.pdf',
            size=1024,
            checksum='abc123',
            created_by=self.user,
            comment='Initial version'
        )
        
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.comment, 'Initial version')
        self.assertFalse(version.is_major_version)
    
    def test_version_uniqueness(self):
        """Test version number uniqueness."""
        DocumentVersion.objects.create(
            document=self.document,
            version_number=1,
            file_path='/documents/test_v1.pdf',
            size=1024,
            checksum='abc123',
            created_by=self.user
        )
        
        # Try to create duplicate version number
        with self.assertRaises(Exception):
            DocumentVersion.objects.create(
                document=self.document,
                version_number=1,
                file_path='/documents/test_v1_dup.pdf',
                size=1024,
                checksum='xyz789',
                created_by=self.user
            )


class PermissionTest(TestCase):
    """Test document and folder permissions."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
        
        self.folder = Folder.objects.create(
            name='Test Folder',
            group=self.group,
            created_by=self.user
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
            created_by=self.user
        )
    
    def test_document_permission(self):
        """Test document permissions."""
        # Grant permission
        permission = DocumentPermission.objects.create(
            document=self.document,
            user=self.other_user,
            permission='view',
            granted_by=self.user
        )
        
        self.assertTrue(permission.is_active())
        self.assertTrue(permission.has_permission('view'))
        self.assertFalse(permission.has_permission('edit'))
    
    def test_folder_permission(self):
        """Test folder permissions."""
        # Grant permission with inheritance
        permission = FolderPermission.objects.create(
            folder=self.folder,
            user=self.other_user,
            permission='edit',
            granted_by=self.user,
            apply_to_subfolders=True,
            apply_to_documents=True
        )
        
        self.assertTrue(permission.is_active())
        self.assertTrue(permission.has_permission('view'))
        self.assertTrue(permission.has_permission('edit'))
        self.assertFalse(permission.has_permission('delete'))
    
    def test_permission_expiry(self):
        """Test permission expiration."""
        from django.utils import timezone
        
        # Create expired permission
        permission = DocumentPermission.objects.create(
            document=self.document,
            user=self.other_user,
            permission='view',
            granted_by=self.user,
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        self.assertFalse(permission.is_active())


class SharedLinkTest(TestCase):
    """Test shared links."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.group = self.user.groups.first()
        
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
    
    def test_shared_link_creation(self):
        """Test creating shared link."""
        link = SharedLink.create_for_document(
            document=self.document,
            user=self.user,
            days=7,
            allow_view=True,
            allow_download=True
        )
        
        self.assertIsNotNone(link.token)
        self.assertEqual(len(link.token), 64)
        self.assertTrue(link.is_active)
        self.assertTrue(link.is_valid())
        self.assertEqual(link.view_count, 0)
        self.assertEqual(link.download_count, 0)
    
    def test_shared_link_access(self):
        """Test shared link access control."""
        link = SharedLink.create_for_document(
            document=self.document,
            user=self.user,
            days=7,
            require_authentication=True,
            allowed_emails=['allowed@example.com']
        )
        
        # Test unauthenticated access
        self.assertFalse(link.can_access())
        
        # Test with allowed email
        allowed_user = User.objects.create_user(
            username='allowed',
            email='allowed@example.com',
            password='testpass'
        )
        self.assertTrue(link.can_access(allowed_user))
        
        # Test with disallowed email
        other_user = User.objects.create_user(
            username='other',
            email='other@example.com',
            password='testpass'
        )
        self.assertFalse(link.can_access(other_user))
    
    def test_shared_link_limits(self):
        """Test shared link access limits."""
        link = SharedLink.create_for_document(
            document=self.document,
            user=self.user,
            max_views=2,
            max_downloads=1
        )
        
        # First access
        link.record_access(is_download=False)
        self.assertEqual(link.view_count, 1)
        self.assertTrue(link.is_valid())
        
        # Second access
        link.record_access(is_download=False)
        self.assertEqual(link.view_count, 2)
        self.assertFalse(link.is_valid())  # Reached max views
    
    def test_shared_link_revoke(self):
        """Test revoking shared link."""
        link = SharedLink.create_for_document(
            document=self.document,
            user=self.user
        )
        
        self.assertTrue(link.is_active)
        
        # Revoke link
        link.revoke(self.user, 'No longer needed')
        
        self.assertFalse(link.is_active)
        self.assertIsNotNone(link.revoked_at)
        self.assertEqual(link.revoked_by, self.user)
        self.assertEqual(link.revoke_reason, 'No longer needed')
        self.assertFalse(link.is_valid())