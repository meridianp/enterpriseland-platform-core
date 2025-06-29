"""
Audit Logging Mixins

Mixins for models and views to enable audit logging.
"""

import json
from typing import Dict, Any, List, Optional
from django.db import models
from django.db.models.signals import pre_save, post_save, pre_delete
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from django.forms.models import model_to_dict
from django.core.serializers.json import DjangoJSONEncoder

from .models import AuditLog
from .utils import get_audit_context, should_audit_model


class AuditMixin:
    """
    Mixin for models to enable automatic audit logging.
    
    Usage:
        class MyModel(AuditMixin, models.Model):
            audit_enabled = True
            audit_exclude_fields = ['last_login', 'password']
            ...
    """
    
    # Override these in your model
    audit_enabled = True
    audit_exclude_fields = []
    audit_include_fields = None  # If set, only these fields are audited
    audit_data_classification = 'internal'
    
    def get_audit_fields(self) -> List[str]:
        """Get list of fields to audit"""
        all_fields = [f.name for f in self._meta.fields]
        
        if self.audit_include_fields:
            return [f for f in all_fields if f in self.audit_include_fields]
        else:
            return [f for f in all_fields if f not in self.audit_exclude_fields]
    
    def get_audit_data(self) -> Dict[str, Any]:
        """Get model data for auditing"""
        fields = self.get_audit_fields()
        data = {}
        
        for field in fields:
            value = getattr(self, field)
            
            # Handle special field types
            if isinstance(value, models.Model):
                value = str(value.pk)
            elif hasattr(value, 'all'):  # ManyToMany
                value = list(value.values_list('pk', flat=True))
            
            # Mask sensitive fields
            if field in ['password', 'secret', 'token', 'key']:
                value = '***'
            
            data[field] = value
        
        return data
    
    def create_audit_log(self, event_type: str, changes: Dict[str, List] = None):
        """Create an audit log entry for this instance"""
        if not self.audit_enabled:
            return None
        
        context = get_audit_context()
        
        # Get content type
        ct = ContentType.objects.get_for_model(self.__class__)
        
        # Create audit log
        audit_log = AuditLog.objects.create(
            event_type=event_type,
            user=context.get('user'),
            ip_address=context.get('ip_address'),
            user_agent=context.get('user_agent', ''),
            content_type=ct,
            object_id=str(self.pk),
            object_repr=str(self),
            changes=changes or {},
            metadata={
                'model': self.__class__.__name__,
                'app': self._meta.app_label,
            },
            request_id=context.get('request_id'),
            session_key=context.get('session_key'),
            data_classification=self.audit_data_classification,
            group=getattr(self, 'group', None)
        )
        
        return audit_log
    
    @classmethod
    def setup_audit_signals(cls):
        """Set up signals for automatic audit logging"""
        
        @receiver(pre_save, sender=cls)
        def audit_pre_save(sender, instance, **kwargs):
            """Track changes before save"""
            if not instance.audit_enabled:
                return
            
            if instance.pk:
                # Get old instance
                try:
                    old_instance = sender.objects.get(pk=instance.pk)
                    old_data = old_instance.get_audit_data()
                    instance._audit_old_data = old_data
                except sender.DoesNotExist:
                    instance._audit_old_data = None
            else:
                instance._audit_old_data = None
        
        @receiver(post_save, sender=cls)
        def audit_post_save(sender, instance, created, **kwargs):
            """Log changes after save"""
            if not instance.audit_enabled:
                return
            
            if created:
                instance.create_audit_log('create')
            else:
                # Calculate changes
                old_data = getattr(instance, '_audit_old_data', {})
                new_data = instance.get_audit_data()
                
                changes = {}
                for field in new_data:
                    if field in old_data and old_data[field] != new_data[field]:
                        changes[field] = [old_data[field], new_data[field]]
                
                if changes:
                    instance.create_audit_log('update', changes)
        
        @receiver(pre_delete, sender=cls)
        def audit_pre_delete(sender, instance, **kwargs):
            """Log deletion"""
            if instance.audit_enabled:
                instance.create_audit_log('delete')


class BulkAuditMixin:
    """
    Mixin for QuerySets to audit bulk operations.
    """
    
    def bulk_create(self, objs, **kwargs):
        """Audit bulk create operations"""
        result = super().bulk_create(objs, **kwargs)
        
        # Create audit log for bulk operation
        if objs and hasattr(objs[0], 'audit_enabled') and objs[0].audit_enabled:
            context = get_audit_context()
            ct = ContentType.objects.get_for_model(objs[0].__class__)
            
            AuditLog.objects.create(
                event_type='bulk_create',
                user=context.get('user'),
                ip_address=context.get('ip_address'),
                content_type=ct,
                metadata={
                    'count': len(objs),
                    'model': objs[0].__class__.__name__,
                },
                request_id=context.get('request_id'),
                group=getattr(objs[0], 'group', None) if objs else None
            )
        
        return result
    
    def bulk_update(self, objs, fields, **kwargs):
        """Audit bulk update operations"""
        # Track which objects are being updated
        obj_ids = [str(obj.pk) for obj in objs]
        
        result = super().bulk_update(objs, fields, **kwargs)
        
        # Create audit log
        if objs and hasattr(objs[0], 'audit_enabled') and objs[0].audit_enabled:
            context = get_audit_context()
            ct = ContentType.objects.get_for_model(objs[0].__class__)
            
            AuditLog.objects.create(
                event_type='bulk_update',
                user=context.get('user'),
                ip_address=context.get('ip_address'),
                content_type=ct,
                metadata={
                    'count': len(objs),
                    'fields': fields,
                    'object_ids': obj_ids[:100],  # Limit to prevent huge logs
                },
                request_id=context.get('request_id'),
                group=getattr(objs[0], 'group', None) if objs else None
            )
        
        return result
    
    def delete(self):
        """Audit bulk delete operations"""
        # Get info before deletion
        model = self.model
        count = self.count()
        
        # Get sample of IDs being deleted (for audit trail)
        deleted_ids = list(self.values_list('pk', flat=True)[:100])
        
        result = super().delete()
        
        # Create audit log
        if should_audit_model(model):
            context = get_audit_context()
            ct = ContentType.objects.get_for_model(model)
            
            AuditLog.objects.create(
                event_type='bulk_delete',
                user=context.get('user'),
                ip_address=context.get('ip_address'),
                content_type=ct,
                metadata={
                    'count': count,
                    'deleted_ids': deleted_ids,
                },
                request_id=context.get('request_id')
            )
        
        return result


class ViewAuditMixin:
    """
    Mixin for views to enable audit logging of data access.
    """
    
    audit_enabled = True
    audit_access_type = 'view'
    
    def get_object(self):
        """Override to audit object access"""
        obj = super().get_object()
        
        if self.audit_enabled and hasattr(obj, 'audit_enabled') and obj.audit_enabled:
            # Log data access
            from .models import DataAccessLog
            
            context = get_audit_context()
            
            DataAccessLog.objects.create(
                user=context.get('user'),
                model_name=obj.__class__.__name__,
                record_id=str(obj.pk),
                fields_accessed=obj.get_audit_fields() if hasattr(obj, 'get_audit_fields') else [],
                access_type=self.audit_access_type,
                ip_address=context.get('ip_address'),
                group=getattr(obj, 'group', None)
            )
        
        return obj
    
    def get_queryset(self):
        """Override to audit list access"""
        queryset = super().get_queryset()
        
        if self.audit_enabled and queryset.model:
            # Log query access (simplified - in production, be more selective)
            from .models import DataAccessLog
            
            context = get_audit_context()
            
            # Only log if accessing sensitive models
            if should_audit_model(queryset.model):
                DataAccessLog.objects.create(
                    user=context.get('user'),
                    model_name=queryset.model.__name__,
                    record_id='multiple',
                    access_type='list',
                    ip_address=context.get('ip_address'),
                    metadata={
                        'query': str(queryset.query)[:1000],  # Truncate long queries
                        'count': queryset.count()
                    }
                )
        
        return queryset


class ExportAuditMixin:
    """
    Mixin for views that export data.
    """
    
    def export_data(self, queryset, format='csv'):
        """Audit data export operations"""
        # Log export operation
        from .models import AuditLog
        
        context = get_audit_context()
        ct = ContentType.objects.get_for_model(queryset.model)
        
        # Get export details
        count = queryset.count()
        sample_ids = list(queryset.values_list('pk', flat=True)[:10])
        
        AuditLog.objects.create(
            event_type='export',
            user=context.get('user'),
            ip_address=context.get('ip_address'),
            content_type=ct,
            metadata={
                'format': format,
                'count': count,
                'sample_ids': sample_ids,
                'filters': self.request.GET.dict() if hasattr(self, 'request') else {}
            },
            request_id=context.get('request_id'),
            data_classification='confidential'  # Exports often contain sensitive data
        )
        
        # Perform actual export
        return super().export_data(queryset, format)