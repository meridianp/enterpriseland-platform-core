from django.apps import AppConfig
from django.db.models.signals import post_migrate


class DocumentsConfig(AppConfig):
    """Document Management module configuration."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business_modules.documents'
    verbose_name = 'Document Management'
    
    def ready(self):
        """Initialize the documents module."""
        # Import signal handlers
        from . import signals
        
        # Register health checks
        from .health import register_health_checks
        register_health_checks()
        
        # Register permissions
        post_migrate.connect(self.create_permissions, sender=self)
    
    def create_permissions(self, **kwargs):
        """Create default permissions for document management."""
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        
        # Define custom permissions beyond the default model permissions
        custom_permissions = [
            ('share_document', 'Can share documents'),
            ('manage_permissions', 'Can manage document permissions'),
            ('bulk_operations', 'Can perform bulk operations'),
            ('manage_templates', 'Can manage document templates'),
            ('restore_version', 'Can restore document versions'),
            ('view_audit', 'Can view document audit logs'),
            ('manage_retention', 'Can manage document retention policies'),
            ('export_documents', 'Can export documents'),
        ]
        
        try:
            content_type = ContentType.objects.get(
                app_label='documents',
                model='document'
            )
            
            for codename, name in custom_permissions:
                Permission.objects.get_or_create(
                    codename=codename,
                    name=name,
                    content_type=content_type
                )
        except ContentType.DoesNotExist:
            # Models not yet migrated
            pass