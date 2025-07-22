"""Celery tasks for document management."""

from celery import shared_task
from django.utils import timezone
from datetime import timedelta

from .models import Document, DocumentVersion, DocumentMetadata
from .services import (
    MetadataService, PreviewService, OCRService,
    SearchService, DocumentService
)


@shared_task
def extract_document_metadata(document_id):
    """Extract metadata from document."""
    try:
        document = Document.objects.get(id=document_id)
        metadata_service = MetadataService()
        
        metadata = metadata_service.extract_metadata(document)
        
        return {
            'success': True,
            'document_id': str(document_id),
            'metadata': metadata
        }
    except Document.DoesNotExist:
        return {
            'success': False,
            'error': f'Document {document_id} not found'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def generate_document_preview(document_id, size='medium'):
    """Generate preview for document."""
    try:
        document = Document.objects.get(id=document_id)
        preview_service = PreviewService()
        
        preview_path = preview_service.generate_preview(document, size)
        
        return {
            'success': True,
            'document_id': str(document_id),
            'preview_path': preview_path
        }
    except Document.DoesNotExist:
        return {
            'success': False,
            'error': f'Document {document_id} not found'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def extract_document_text(document_id):
    """Extract text from document for search indexing."""
    try:
        document = Document.objects.get(id=document_id)
        
        # Try OCR first if applicable
        ocr_service = OCRService()
        text = ''
        
        if document.file_extension in ['jpg', 'jpeg', 'png', 'pdf']:
            text = ocr_service.extract_text(document) or ''
        
        # Index in search
        search_service = SearchService()
        search_service.index_document(document, text)
        
        return {
            'success': True,
            'document_id': str(document_id),
            'text_length': len(text)
        }
    except Document.DoesNotExist:
        return {
            'success': False,
            'error': f'Document {document_id} not found'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def analyze_version_changes(new_version_id, old_version_id):
    """Analyze changes between document versions."""
    try:
        new_version = DocumentVersion.objects.get(id=new_version_id)
        old_version = DocumentVersion.objects.get(id=old_version_id)
        
        # This would implement diff analysis
        # For now, just record basic changes
        changes = {
            'size_change': new_version.size - old_version.size,
            'size_change_percent': ((new_version.size - old_version.size) / old_version.size * 100) if old_version.size > 0 else 0
        }
        
        new_version.changes_summary = changes
        new_version.save(update_fields=['changes_summary'])
        
        return {
            'success': True,
            'version_id': str(new_version_id),
            'changes': changes
        }
    except DocumentVersion.DoesNotExist:
        return {
            'success': False,
            'error': 'Version not found'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def cleanup_expired_links():
    """Clean up expired shared links."""
    from .models import SharedLink
    
    expired_links = SharedLink.objects.filter(
        expires_at__lt=timezone.now(),
        is_active=True
    )
    
    count = 0
    for link in expired_links:
        link.is_active = False
        link.save(update_fields=['is_active'])
        count += 1
    
    return {
        'success': True,
        'expired_count': count
    }


@shared_task
def cleanup_deleted_documents(days=30):
    """Permanently delete old soft-deleted documents."""
    document_service = DocumentService()
    
    count = document_service.cleanup_old_documents(days)
    
    return {
        'success': True,
        'deleted_count': count
    }


@shared_task
def update_folder_statistics():
    """Update document count and size for all folders."""
    from .models import Folder
    
    folders = Folder.objects.all()
    
    for folder in folders:
        folder.update_statistics()
    
    return {
        'success': True,
        'folders_updated': folders.count()
    }


@shared_task
def process_retention_policies():
    """Process document retention policies."""
    # Find documents past retention date
    documents = Document.objects.filter(
        retention_date__lt=timezone.now().date(),
        is_deleted=False
    )
    
    count = 0
    for document in documents:
        document.soft_delete()
        count += 1
    
    return {
        'success': True,
        'retained_count': count
    }


@shared_task
def reindex_search(batch_size=100):
    """Reindex all documents for search."""
    search_service = SearchService()
    
    count = search_service.reindex_all(batch_size)
    
    return {
        'success': True,
        'indexed_count': count
    }


@shared_task
def scan_document_batch(document_ids):
    """Scan a batch of documents for viruses."""
    from .services import VirusScanService
    
    virus_service = VirusScanService()
    results = {
        'scanned': 0,
        'clean': 0,
        'infected': 0,
        'errors': 0
    }
    
    for doc_id in document_ids:
        try:
            document = Document.objects.get(id=doc_id)
            
            # Skip if already scanned
            if document.virus_scanned:
                continue
            
            # Download and scan
            from .services import StorageService
            storage_service = StorageService()
            content = storage_service.download_file(document.file_path)
            
            scan_result = virus_service.scan_file(content)
            
            document.virus_scanned = True
            document.virus_scan_result = scan_result['status']
            document.save(update_fields=['virus_scanned', 'virus_scan_result'])
            
            results['scanned'] += 1
            if scan_result['status'] == 'clean':
                results['clean'] += 1
            elif scan_result['status'] == 'infected':
                results['infected'] += 1
                
                # Quarantine infected file
                virus_service.quarantine_file(
                    document.file_path,
                    scan_result.get('virus_name', 'Unknown virus')
                )
        
        except Exception:
            results['errors'] += 1
    
    return results


# Periodic tasks
@shared_task
def hourly_maintenance():
    """Run hourly maintenance tasks."""
    cleanup_expired_links.delay()
    process_retention_policies.delay()


@shared_task
def daily_maintenance():
    """Run daily maintenance tasks."""
    cleanup_deleted_documents.delay(days=30)
    update_folder_statistics.delay()
    
    # Update virus definitions
    from .services import VirusScanService
    virus_service = VirusScanService()
    virus_service.update_definitions()