# Document Management Module

A comprehensive document management system for the EnterpriseLand platform, providing hierarchical folder structures, document versioning, full-text search, granular permissions, and collaboration features.

## Features

### Core Features
- **Hierarchical Folder Structure**: Organize documents in nested folders with path-based navigation
- **Document Versioning**: Track all document versions with diff tracking and restoration capabilities
- **Full-Text Search**: Search document contents using PostgreSQL or Elasticsearch
- **Granular Permissions**: Document and folder-level permissions with inheritance
- **Document Sharing**: Create expiring share links with customizable permissions
- **Audit Trail**: Complete audit log of all document operations

### Advanced Features
- **Document Preview**: Generate previews for PDFs, images, and office documents
- **OCR Support**: Extract text from scanned documents and images
- **Virus Scanning**: Scan documents on upload using ClamAV or VirusTotal
- **Encryption**: Encrypt documents at rest with AES-256
- **Document Templates**: Create and use document templates with variable substitution
- **Bulk Operations**: Perform bulk downloads, moves, deletes, and tagging
- **Metadata Extraction**: Automatically extract and index document metadata
- **Retention Policies**: Automated document retention and cleanup

## Installation

### Requirements
- Python 3.8+
- Django 4.2+
- PostgreSQL 12+ (required for full-text search and array fields)
- Redis (for caching and Celery)
- Optional: Elasticsearch 7+ (for enhanced search)
- Optional: LibreOffice (for document preview)
- Optional: Tesseract (for OCR)
- Optional: ClamAV (for virus scanning)

### Python Dependencies
```bash
pip install -r requirements.txt
```

Key dependencies:
- `django-mptt`: For hierarchical folder structure
- `boto3`: For S3 storage
- `elasticsearch`: For search functionality
- `pdf2image`: For PDF preview generation
- `pytesseract`: For OCR
- `python-magic`: For file type detection
- `cryptography`: For document encryption

### Module Installation
1. Add the module to your Django settings:
```python
INSTALLED_APPS = [
    # ...
    'business_modules.documents',
    'mptt',  # Required for folder hierarchy
    # ...
]
```

2. Configure module settings:
```python
# Storage configuration
DOCUMENTS_STORAGE_BACKEND = 's3'  # or 'local'
AWS_ACCESS_KEY_ID = 'your-key'
AWS_SECRET_ACCESS_KEY = 'your-secret'
AWS_STORAGE_BUCKET_NAME = 'your-bucket'
AWS_S3_REGION_NAME = 'us-east-1'

# Feature toggles
DOCUMENTS_PREVIEW_ENABLED = True
DOCUMENTS_OCR_ENABLED = True
DOCUMENTS_VIRUS_SCAN_ENABLED = True
DOCUMENTS_ENCRYPTION_ENABLED = True
DOCUMENTS_ELASTICSEARCH_ENABLED = True

# Limits
DOCUMENTS_MAX_FILE_SIZE = 52428800  # 50MB
DOCUMENTS_ALLOWED_EXTENSIONS = [
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'jpg', 'jpeg', 'png', 'csv', 'zip'
]

# Elasticsearch configuration
ELASTICSEARCH_HOSTS = ['localhost:9200']

# Virus scanning
VIRUS_SCAN_METHOD = 'clamav'  # or 'virustotal'
VIRUSTOTAL_API_KEY = 'your-api-key'  # if using VirusTotal

# Encryption
DOCUMENTS_MASTER_KEY = 'base64-encoded-master-key'
```

3. Run migrations:
```bash
python manage.py migrate documents
```

4. Include URLs:
```python
urlpatterns = [
    # ...
    path('documents/', include('business_modules.documents.urls')),
    # ...
]
```

## Usage

### Basic Document Operations

#### Upload a Document
```python
from business_modules.documents.services import DocumentService

service = DocumentService()
with open('example.pdf', 'rb') as f:
    document = service.create_document(
        file=f,
        name='Example Document',
        user=request.user,
        folder=folder,
        description='An example PDF',
        tags=['example', 'pdf'],
        category='documentation'
    )
```

#### Search Documents
```python
from business_modules.documents.services import DocumentService

service = DocumentService()
results = service.search_documents(
    query='invoice 2024',
    user=request.user,
    filters={
        'category': 'financial',
        'created_after': '2024-01-01',
        'file_extension': 'pdf'
    }
)
```

### Folder Management

#### Create Folder Structure
```python
from business_modules.documents.models import Folder

# Create root folder
root = Folder.objects.create(
    name='Company Documents',
    group=user.group,
    created_by=user
)

# Create subfolder
contracts = Folder.objects.create(
    name='Contracts',
    parent=root,
    group=user.group,
    created_by=user,
    default_retention_days=365
)
```

### Permission Management

#### Grant Document Permission
```python
from business_modules.documents.services import PermissionService

service = PermissionService()
permission = service.grant_document_permission(
    document=document,
    permission='view',
    granted_by=admin_user,
    user=viewer_user,
    expires_at=datetime.now() + timedelta(days=30)
)
```

#### Grant Folder Permission with Inheritance
```python
permission = service.grant_folder_permission(
    folder=folder,
    permission='edit',
    granted_by=admin_user,
    group=editors_group,
    apply_to_subfolders=True,
    apply_to_documents=True
)
```

### Document Sharing

#### Create Share Link
```python
from business_modules.documents.models import SharedLink

link = SharedLink.create_for_document(
    document=document,
    user=user,
    days=7,
    allow_view=True,
    allow_download=True,
    require_authentication=False,
    max_downloads=10
)

share_url = f"https://example.com/shared/{link.token}"
```

### Document Templates

#### Create and Use Template
```python
from business_modules.documents.models import DocumentTemplate
from business_modules.documents.services import TemplateService

# Create template
template = DocumentTemplate.objects.create(
    name='Invoice Template',
    category='financial',
    file_path='/templates/invoice.docx',
    file_type='docx',
    is_public=True
)

# Use template
service = TemplateService()
document = service.create_document_from_template(
    template=template,
    user=user,
    data={
        'company_name': 'Acme Corp',
        'invoice_number': 'INV-2024-001',
        'amount': '$1,000.00',
        'date': '2024-01-15'
    }
)
```

## API Reference

### Endpoints

#### Documents
- `GET /api/v1/documents/` - List documents
- `POST /api/v1/documents/upload/` - Upload document
- `GET /api/v1/documents/{id}/` - Get document details
- `PATCH /api/v1/documents/{id}/` - Update document
- `DELETE /api/v1/documents/{id}/` - Delete document
- `GET /api/v1/documents/{id}/download/` - Download document
- `GET /api/v1/documents/{id}/preview/` - Get document preview
- `POST /api/v1/documents/{id}/lock/` - Lock document
- `POST /api/v1/documents/{id}/unlock/` - Unlock document
- `GET /api/v1/documents/{id}/versions/` - List versions
- `POST /api/v1/documents/{id}/create_version/` - Create new version
- `POST /api/v1/documents/{id}/share/` - Create share link
- `POST /api/v1/documents/{id}/ocr/` - Extract text with OCR
- `POST /api/v1/documents/search/` - Search documents
- `POST /api/v1/documents/bulk/` - Bulk operations

#### Folders
- `GET /api/v1/folders/` - List folders
- `POST /api/v1/folders/` - Create folder
- `GET /api/v1/folders/{id}/` - Get folder details
- `PATCH /api/v1/folders/{id}/` - Update folder
- `DELETE /api/v1/folders/{id}/` - Delete folder
- `GET /api/v1/folders/{id}/tree/` - Get folder tree
- `POST /api/v1/folders/{id}/move/` - Move folder
- `GET /api/v1/folders/{id}/permissions/` - List permissions
- `POST /api/v1/folders/{id}/grant_permission/` - Grant permission

#### Templates
- `GET /api/v1/templates/` - List templates
- `GET /api/v1/templates/{id}/` - Get template details
- `POST /api/v1/templates/{id}/use/` - Use template
- `POST /api/v1/templates/{id}/preview/` - Preview template

#### Shared Links
- `GET /api/v1/shared-links/` - List your shared links
- `POST /api/v1/shared-links/` - Create shared link
- `POST /api/v1/shared-links/{id}/revoke/` - Revoke link

#### Audit
- `GET /api/v1/audit/` - List audit logs

### Request/Response Examples

#### Upload Document
```http
POST /api/v1/documents/upload/
Content-Type: multipart/form-data

file: (binary)
name: "Q4 Report"
description: "Quarterly financial report"
folder_id: "123e4567-e89b-12d3-a456-426614174000"
tags: ["financial", "report", "q4"]
category: "financial"
```

Response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Q4 Report",
  "file_name": "q4_report.pdf",
  "size": 2048576,
  "mime_type": "application/pdf",
  "created_at": "2024-01-15T10:30:00Z",
  "folder": {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "name": "Financial Reports",
    "path": "/Company/Financial Reports"
  },
  "permissions": ["view", "download", "edit", "delete", "share", "manage"]
}
```

#### Search Documents
```http
POST /api/v1/documents/search/
Content-Type: application/json

{
  "query": "contract renewal",
  "category": "legal",
  "tags": ["active"],
  "created_after": "2024-01-01T00:00:00Z",
  "folder_id": "123e4567-e89b-12d3-a456-426614174000",
  "include_subfolders": true
}
```

## Architecture

### Models

#### Core Models
- **Document**: Main document entity with metadata, status, and relationships
- **DocumentVersion**: Version tracking for documents
- **Folder**: Hierarchical folder structure using MPTT
- **DocumentMetadata**: Extended metadata extracted from documents

#### Permission Models
- **DocumentPermission**: Document-level access control
- **FolderPermission**: Folder-level access control with inheritance
- **SharedLink**: Temporary share links with customizable permissions

#### Supporting Models
- **DocumentTag**: Predefined tags for categorization
- **DocumentTemplate**: Reusable document templates
- **DocumentAudit**: Comprehensive audit trail

### Services

#### Core Services
- **DocumentService**: Document CRUD operations, versioning, search
- **StorageService**: File storage abstraction (S3/local)
- **PermissionService**: Permission checking and management
- **SearchService**: Full-text search with PostgreSQL/Elasticsearch

#### Processing Services
- **PreviewService**: Generate document previews
- **OCRService**: Extract text from images and scanned documents
- **VirusScanService**: Scan documents for malware
- **EncryptionService**: Encrypt/decrypt documents at rest
- **MetadataService**: Extract document metadata
- **TemplateService**: Process document templates

### Background Tasks

The module uses Celery for asynchronous processing:

- **extract_document_metadata**: Extract metadata after upload
- **generate_document_preview**: Generate preview images
- **extract_document_text**: OCR and text extraction for search
- **cleanup_expired_links**: Remove expired share links
- **cleanup_deleted_documents**: Permanently delete old soft-deleted documents
- **process_retention_policies**: Apply document retention rules
- **scan_document_batch**: Batch virus scanning

## Security

### Access Control
- Row-level security through Django's permission system
- Group-based multi-tenancy
- Granular permissions (view, download, edit, delete, share, manage)
- Permission inheritance from folders to documents
- Time-based permission expiry

### Data Protection
- AES-256 encryption for documents at rest
- Secure key management with master key derivation
- Virus scanning on upload
- Secure file deletion with overwriting
- Audit trail for compliance

### API Security
- JWT authentication required
- Permission checks on all operations
- Rate limiting on search and bulk operations
- Input validation and sanitization

## Performance Considerations

### Optimization Strategies
- Cursor-based pagination for large datasets
- Database indexes on frequently queried fields
- Caching of permission checks
- Asynchronous processing for heavy operations
- CDN integration for document delivery

### Scalability
- Horizontal scaling with multiple workers
- S3 for unlimited storage capacity
- Elasticsearch for scalable search
- Redis for distributed caching
- Background job queuing with Celery

## Monitoring

### Health Checks
- Storage backend connectivity
- Elasticsearch cluster health
- Virus scanner availability
- Preview service dependencies

### Metrics
- Documents created/downloaded
- Storage usage
- Search query performance
- OCR processing success rate
- Virus detection statistics

## Troubleshooting

### Common Issues

#### Upload Failures
- Check file size limits
- Verify allowed file extensions
- Check virus scan results
- Verify storage backend connectivity

#### Search Not Working
- Check Elasticsearch connection
- Verify documents are indexed
- Run reindex task if needed
- Check PostgreSQL full-text search setup

#### Preview Generation Failures
- Verify LibreOffice installation
- Check poppler-utils for PDF preview
- Verify sufficient disk space
- Check preview service logs

#### Permission Denied
- Verify user has required permission
- Check folder inheritance settings
- Verify permission hasn't expired
- Check group membership

## License

This module is part of the EnterpriseLand platform and follows the same licensing terms.