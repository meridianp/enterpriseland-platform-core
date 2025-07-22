"""Health checks for document management module."""

from django.conf import settings
from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import HealthCheckException

from .services import StorageService, SearchService, VirusScanService


class StorageHealthCheck(BaseHealthCheckBackend):
    """Check storage backend connectivity."""
    
    critical_service = True
    
    def check_status(self):
        """Check if storage backend is accessible."""
        try:
            storage_service = StorageService()
            
            # Try to check if base path exists
            test_path = f"{storage_service.base_path}/.health_check"
            
            if storage_service.backend == 's3':
                # Check S3 bucket access
                storage_service.s3_client.head_bucket(Bucket=storage_service.bucket_name)
            else:
                # Check local storage
                import os
                base_dir = settings.MEDIA_ROOT
                if not os.path.exists(base_dir):
                    raise HealthCheckException("Media root does not exist")
        
        except Exception as e:
            raise HealthCheckException(f"Storage backend error: {str(e)}")


class ElasticsearchHealthCheck(BaseHealthCheckBackend):
    """Check Elasticsearch connectivity."""
    
    critical_service = False
    
    def check_status(self):
        """Check if Elasticsearch is accessible."""
        if not getattr(settings, 'DOCUMENTS_ELASTICSEARCH_ENABLED', True):
            return
        
        try:
            search_service = SearchService()
            if search_service.use_elasticsearch:
                # Check cluster health
                health = search_service.es_client.cluster.health()
                
                if health['status'] == 'red':
                    raise HealthCheckException("Elasticsearch cluster status is RED")
        
        except Exception as e:
            raise HealthCheckException(f"Elasticsearch error: {str(e)}")


class VirusScannerHealthCheck(BaseHealthCheckBackend):
    """Check virus scanner availability."""
    
    critical_service = False
    
    def check_status(self):
        """Check if virus scanner is available."""
        if not getattr(settings, 'DOCUMENTS_VIRUS_SCAN_ENABLED', True):
            return
        
        try:
            virus_service = VirusScanService()
            info = virus_service.get_scanner_info()
            
            if not info['available']:
                raise HealthCheckException(f"Virus scanner '{info['method']}' is not available")
        
        except Exception as e:
            raise HealthCheckException(f"Virus scanner error: {str(e)}")


class PreviewServiceHealthCheck(BaseHealthCheckBackend):
    """Check preview service dependencies."""
    
    critical_service = False
    
    def check_status(self):
        """Check if preview service dependencies are available."""
        if not getattr(settings, 'DOCUMENTS_PREVIEW_ENABLED', True):
            return
        
        try:
            # Check if required libraries are available
            import pdf2image
            import PIL
            
            # Check if poppler is installed (required for PDF preview)
            import subprocess
            result = subprocess.run(['which', 'pdftocairo'], capture_output=True)
            
            if result.returncode != 0:
                raise HealthCheckException("Poppler utils not installed (required for PDF preview)")
        
        except ImportError as e:
            raise HealthCheckException(f"Missing preview dependency: {str(e)}")
        except Exception as e:
            raise HealthCheckException(f"Preview service error: {str(e)}")


def register_health_checks():
    """Register all health checks for the documents module."""
    from health_check.plugins import plugin_dir
    
    plugin_dir.register(StorageHealthCheck)
    plugin_dir.register(ElasticsearchHealthCheck)
    plugin_dir.register(VirusScannerHealthCheck)
    plugin_dir.register(PreviewServiceHealthCheck)