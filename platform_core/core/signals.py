"""
Django signals for comprehensive audit logging.

Automatically captures model changes, authentication events,
and system activities with detailed change tracking.
"""

import json
import logging
from typing import Dict, Any, Optional, Set, List
from django.db.models.signals import (
    pre_save, post_save, pre_delete, post_delete, m2m_changed
)
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed
)
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.apps import apps

from accounts.models import Group
from platform_core.core.models import AuditLog, AuditLogEntry
from platform_core.core.middleware.audit import get_audit_context, get_current_user

User = get_user_model()
logger = logging.getLogger(__name__)


# Configuration
AUDIT_ENABLED = True  # Can be controlled via settings
SENSITIVE_FIELDS = {
    'password', 'token', 'secret', 'key', 'auth', 'api_key',
    'ssn', 'social_security', 'credit_card', 'bank_account',
    'private_key', 'certificate', 'hash'
}

# Models to exclude from audit logging
EXCLUDED_MODELS = {
    'AuditLog', 'AuditLogEntry', 'SystemMetrics',
    'Session', 'ContentType', 'Permission', 'LogEntry'
}

# Fields to exclude from change tracking
EXCLUDED_FIELDS = {
    'password', 'last_login', 'date_joined', 'created_at', 'updated_at',
    'modified', 'timestamp', 'id', 'uuid'
}


def should_audit_model(model_class: type) -> bool:
    """
    Determine if a model should be audited.
    
    Args:
        model_class: Django model class
        
    Returns:
        True if model should be audited
    """
    if not AUDIT_ENABLED:
        return False
    
    model_name = model_class.__name__
    
    # Skip excluded models
    if model_name in EXCLUDED_MODELS:
        return False
    
    # Skip abstract models
    if getattr(model_class._meta, 'abstract', False):
        return False
    
    # Skip proxy models (audit the concrete model instead)
    if getattr(model_class._meta, 'proxy', False):
        return False
    
    return True


def is_sensitive_field(field_name: str) -> bool:
    """
    Check if a field contains sensitive data.
    
    Args:
        field_name: Name of the field
        
    Returns:
        True if field is sensitive
    """
    field_lower = field_name.lower()
    return any(sensitive in field_lower for sensitive in SENSITIVE_FIELDS)


def get_field_value(instance: models.Model, field_name: str) -> Any:
    """
    Get the value of a field from a model instance.
    
    Args:
        instance: Model instance
        field_name: Name of the field
        
    Returns:
        Field value (JSON serializable)
    """
    try:
        value = getattr(instance, field_name)
        
        # Handle different field types
        if hasattr(value, 'pk'):
            # Foreign key - return primary key
            return value.pk
        elif hasattr(value, 'all'):
            # Many-to-many - return list of primary keys
            return list(value.values_list('pk', flat=True))
        elif isinstance(value, (dict, list)):
            # JSON fields
            return value
        else:
            # Convert to string for JSON serialization
            return str(value) if value is not None else None
    except Exception as e:
        logger.warning(f"Error getting field value for {field_name}: {e}")
        return None


def get_model_changes(instance: models.Model, original_data: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Get changes made to a model instance.
    
    Args:
        instance: Current model instance
        original_data: Original field values before changes
        
    Returns:
        Dictionary of changes with old/new values
    """
    changes = {}
    
    if not original_data:
        # For new instances, all fields are "new"
        for field in instance._meta.fields:
            if field.name not in EXCLUDED_FIELDS:
                value = get_field_value(instance, field.name)
                if value is not None:
                    changes[field.name] = {
                        'old': None,
                        'new': value,
                        'type': field.__class__.__name__
                    }
    else:
        # Compare current values with original
        for field in instance._meta.fields:
            if field.name not in EXCLUDED_FIELDS:
                current_value = get_field_value(instance, field.name)
                original_value = original_data.get(field.name)
                
                if current_value != original_value:
                    changes[field.name] = {
                        'old': original_value,
                        'new': current_value,
                        'type': field.__class__.__name__
                    }
    
    return changes


def create_audit_log_entry(
    action: str,
    instance: models.Model,
    changes: Optional[Dict[str, Any]] = None,
    user: Optional[User] = None,
    success: bool = True,
    error_message: Optional[str] = None
) -> Optional[AuditLog]:
    """
    Create an audit log entry for a model instance.
    
    Args:
        action: Action performed (CREATE, UPDATE, DELETE)
        instance: Model instance
        changes: Dictionary of changes made
        user: User who performed the action
        success: Whether the action was successful
        error_message: Error message if action failed
        
    Returns:
        Created AuditLog instance or None
    """
    try:
        context = get_audit_context()
        
        # Get user and context information
        if not user:
            user = get_current_user()
        
        # Get group from instance, user, or context
        group = None
        if hasattr(instance, 'group'):
            group = instance.group
        elif context:
            group = context.group
        elif user and hasattr(user, 'groups') and user.groups.exists():
            group = user.groups.first()
        
        # Create audit log
        audit_log = AuditLog.objects.create_log(
            action=action,
            user=user,
            content_object=instance,
            changes=changes or {},
            ip_address=context.ip_address if context else None,
            user_agent=context.user_agent if context else None,
            group=group,
            success=success,
            error_message=error_message
        )
        
        # Create detailed field entries if there are changes
        if changes and audit_log:
            for field_name, change_data in changes.items():
                if isinstance(change_data, dict) and 'old' in change_data and 'new' in change_data:
                    AuditLogEntry.objects.create(
                        audit_log=audit_log,
                        field_name=field_name,
                        field_type=change_data.get('type', 'Unknown'),
                        old_value=json.dumps(change_data['old'], cls=DjangoJSONEncoder),
                        new_value=json.dumps(change_data['new'], cls=DjangoJSONEncoder),
                        is_sensitive=is_sensitive_field(field_name)
                    )
        
        return audit_log
        
    except Exception as e:
        logger.error(f"Error creating audit log entry: {e}")
        return None


# Store original data before save
_original_data = {}


@receiver(pre_save)
def capture_pre_save_data(sender, instance, **kwargs):
    """Capture original data before save for change tracking."""
    if not should_audit_model(sender):
        return
    
    if instance.pk:
        try:
            # Get original instance from database
            original = sender.objects.get(pk=instance.pk)
            original_data = {}
            
            for field in sender._meta.fields:
                if field.name not in EXCLUDED_FIELDS:
                    original_data[field.name] = get_field_value(original, field.name)
            
            # Store original data using instance memory address as key
            _original_data[id(instance)] = original_data
            
        except sender.DoesNotExist:
            # Instance doesn't exist yet (shouldn't happen in pre_save for existing objects)
            pass
        except Exception as e:
            logger.warning(f"Error capturing pre-save data: {e}")


@receiver(post_save)
def log_model_save(sender, instance, created, **kwargs):
    """Log model create/update operations."""
    if not should_audit_model(sender):
        return
    
    try:
        # Determine action
        action = AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE
        
        # Get changes
        changes = {}
        if created:
            # For new instances, capture all non-excluded fields
            changes = get_model_changes(instance)
        else:
            # For updates, compare with original data
            original_data = _original_data.get(id(instance))
            if original_data:
                changes = get_model_changes(instance, original_data)
        
        # Only log if there are changes or it's a creation
        if changes or created:
            create_audit_log_entry(
                action=action,
                instance=instance,
                changes=changes
            )
        
        # Clean up original data
        if id(instance) in _original_data:
            del _original_data[id(instance)]
            
    except Exception as e:
        logger.error(f"Error logging model save: {e}")


@receiver(pre_delete)
def capture_pre_delete_data(sender, instance, **kwargs):
    """Capture data before deletion for audit logging."""
    if not should_audit_model(sender):
        return
    
    try:
        # Capture all field values before deletion
        deletion_data = {}
        for field in sender._meta.fields:
            if field.name not in EXCLUDED_FIELDS:
                deletion_data[field.name] = get_field_value(instance, field.name)
        
        # Store for post_delete signal
        _original_data[id(instance)] = deletion_data
        
    except Exception as e:
        logger.warning(f"Error capturing pre-delete data: {e}")


@receiver(post_delete)
def log_model_delete(sender, instance, **kwargs):
    """Log model deletion operations."""
    if not should_audit_model(sender):
        return
    
    try:
        # Get the data that was deleted
        deleted_data = _original_data.get(id(instance), {})
        
        # Create audit log for deletion
        create_audit_log_entry(
            action=AuditLog.Action.DELETE,
            instance=instance,
            changes={'deleted_data': deleted_data}
        )
        
        # Clean up
        if id(instance) in _original_data:
            del _original_data[id(instance)]
            
    except Exception as e:
        logger.error(f"Error logging model delete: {e}")


@receiver(m2m_changed)
def log_m2m_changes(sender, instance, action, pk_set, **kwargs):
    """Log many-to-many field changes."""
    # Only log for certain M2M actions
    if action not in ['post_add', 'post_remove', 'post_clear']:
        return
    
    if not should_audit_model(instance.__class__):
        return
    
    try:
        # Get the field name from the sender (through table)
        field_name = None
        for field in instance._meta.many_to_many:
            if field.remote_field.through == sender:
                field_name = field.name
                break
        
        if not field_name:
            return
        
        # Prepare change data
        changes = {
            field_name: {
                'action': action,
                'objects': list(pk_set) if pk_set else [],
                'type': 'ManyToManyField'
            }
        }
        
        # Map action to audit action
        audit_action = AuditLog.Action.UPDATE
        if action == 'post_clear':
            changes[field_name]['action'] = 'cleared'
        elif action == 'post_add':
            changes[field_name]['action'] = 'added'
        elif action == 'post_remove':
            changes[field_name]['action'] = 'removed'
        
        create_audit_log_entry(
            action=audit_action,
            instance=instance,
            changes=changes
        )
        
    except Exception as e:
        logger.error(f"Error logging M2M changes: {e}")


# Authentication signals are handled in middleware, but we can add additional logging here
@receiver(user_logged_in)
def log_user_login_signal(sender, request, user, **kwargs):
    """Additional logging for user login via signal."""
    try:
        # This will be caught by middleware, but we can add additional context here
        logger.info(f"User {user.email} logged in from {request.META.get('REMOTE_ADDR')}")
    except Exception as e:
        logger.error(f"Error in login signal handler: {e}")


@receiver(user_logged_out)
def log_user_logout_signal(sender, request, user, **kwargs):
    """Additional logging for user logout via signal."""
    try:
        # This will be caught by middleware, but we can add additional context here
        logger.info(f"User {user.email if user else 'Anonymous'} logged out")
    except Exception as e:
        logger.error(f"Error in logout signal handler: {e}")


@receiver(user_login_failed)
def log_user_login_failed_signal(sender, credentials, request, **kwargs):
    """Additional logging for failed login attempts via signal."""
    try:
        username = credentials.get('username', credentials.get('email', 'Unknown'))
        ip_address = request.META.get('REMOTE_ADDR', 'Unknown')
        logger.warning(f"Failed login attempt for {username} from {ip_address}")
    except Exception as e:
        logger.error(f"Error in login failed signal handler: {e}")


def bulk_create_audit_logs(instances: List[models.Model], action: str) -> List[AuditLog]:
    """
    Create audit logs for bulk operations.
    
    Args:
        instances: List of model instances
        action: Action performed (BULK_CREATE, BULK_UPDATE, BULK_DELETE)
        
    Returns:
        List of created AuditLog instances
    """
    audit_logs = []
    
    if not instances:
        return audit_logs
    
    try:
        context = get_audit_context()
        user = get_current_user()
        
        for instance in instances:
            if should_audit_model(instance.__class__):
                audit_log = create_audit_log_entry(
                    action=action,
                    instance=instance,
                    user=user
                )
                if audit_log:
                    audit_logs.append(audit_log)
        
        logger.info(f"Created {len(audit_logs)} audit logs for bulk {action}")
        
    except Exception as e:
        logger.error(f"Error creating bulk audit logs: {e}")
    
    return audit_logs


def log_custom_action(
    action: str,
    instance: Optional[models.Model] = None,
    changes: Optional[Dict[str, Any]] = None,
    user: Optional[User] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    **metadata
) -> Optional[AuditLog]:
    """
    Log a custom action that doesn't fit standard CRUD operations.
    
    Args:
        action: Custom action name
        instance: Related model instance (optional)
        changes: Changes or data related to the action
        user: User who performed the action
        success: Whether the action was successful
        error_message: Error message if action failed
        **metadata: Additional metadata
        
    Returns:
        Created AuditLog instance or None
    """
    try:
        context = get_audit_context()
        
        # Get user and context information
        if not user:
            user = get_current_user()
        
        # Get group
        group = None
        if instance and hasattr(instance, 'group'):
            group = instance.group
        elif context:
            group = context.group
        elif user and hasattr(user, 'groups') and user.groups.exists():
            group = user.groups.first()
        
        # Merge metadata with context
        full_metadata = {}
        if context:
            full_metadata.update(context.metadata)
        full_metadata.update(metadata)
        
        return AuditLog.objects.create_log(
            action=action,
            user=user,
            content_object=instance,
            changes=changes or {},
            ip_address=context.ip_address if context else None,
            user_agent=context.user_agent if context else None,
            group=group,
            success=success,
            error_message=error_message,
            metadata=full_metadata
        )
        
    except Exception as e:
        logger.error(f"Error logging custom action: {e}")
        return None


# Utility functions for common audit operations
def log_data_export(
    export_type: str,
    record_count: int,
    file_format: str,
    user: Optional[User] = None,
    **metadata
) -> Optional[AuditLog]:
    """Log data export operations."""
    return log_custom_action(
        action=AuditLog.Action.EXPORT,
        user=user,
        changes={
            'export_type': export_type,
            'record_count': record_count,
            'file_format': file_format
        },
        **metadata
    )


def log_data_import(
    import_type: str,
    record_count: int,
    file_name: str,
    user: Optional[User] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    **metadata
) -> Optional[AuditLog]:
    """Log data import operations."""
    return log_custom_action(
        action=AuditLog.Action.IMPORT,
        user=user,
        changes={
            'import_type': import_type,
            'record_count': record_count,
            'file_name': file_name
        },
        success=success,
        error_message=error_message,
        **metadata
    )


def log_permission_change(
    target_user: User,
    permission_changes: Dict[str, Any],
    user: Optional[User] = None,
    **metadata
) -> Optional[AuditLog]:
    """Log permission changes."""
    return log_custom_action(
        action=AuditLog.Action.PERMISSION_CHANGE,
        instance=target_user,
        changes=permission_changes,
        user=user,
        **metadata
    )


def log_settings_change(
    setting_changes: Dict[str, Any],
    user: Optional[User] = None,
    **metadata
) -> Optional[AuditLog]:
    """Log system settings changes."""
    return log_custom_action(
        action=AuditLog.Action.SETTINGS_CHANGE,
        changes=setting_changes,
        user=user,
        **metadata
    )