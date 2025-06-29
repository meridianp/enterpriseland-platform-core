# Migration to move assessment audit logs to the new comprehensive audit system

from django.db import migrations
from django.contrib.contenttypes.models import ContentType
import json


def migrate_audit_logs(apps, schema_editor):
    """Migrate existing assessment audit logs to the new comprehensive audit system"""
    # Get model classes
    AssessmentAuditLog_Legacy = apps.get_model('assessments', 'AssessmentAuditLog_Legacy')
    AuditLog = apps.get_model('core', 'AuditLog')
    AuditLogEntry = apps.get_model('core', 'AuditLogEntry')
    
    # Process each legacy audit log
    for legacy_log in AssessmentAuditLog_Legacy.objects.all():
        try:
            # Map legacy action to new action
            action_mapping = {
                'CREATE': AuditLog.Action.CREATE,
                'UPDATE': AuditLog.Action.UPDATE,
                'DELETE': AuditLog.Action.DELETE,
            }
            
            # Create new audit log
            new_log = AuditLog.objects.create(
                action=action_mapping.get(legacy_log.action, AuditLog.Action.UPDATE),
                user=legacy_log.user,
                model_name=legacy_log.table_name,
                object_id=str(legacy_log.record_id),
                timestamp=legacy_log.timestamp,
                ip_address=legacy_log.ip_address,
                user_agent=legacy_log.user_agent,
                success=True,  # Assume all legacy logs were successful
                changes={}  # Will be populated below
            )
            
            # Process changes if any
            if legacy_log.old_values or legacy_log.new_values:
                changes = {}
                
                # Get all fields mentioned in old or new values
                old_values = legacy_log.old_values or {}
                new_values = legacy_log.new_values or {}
                all_fields = set(old_values.keys()) | set(new_values.keys())
                
                # Create field-level entries
                for field_name in all_fields:
                    old_val = old_values.get(field_name)
                    new_val = new_values.get(field_name)
                    
                    # Skip if no actual change
                    if old_val == new_val:
                        continue
                    
                    # Add to changes dict
                    changes[field_name] = {
                        'old': old_val,
                        'new': new_val,
                        'type': 'Unknown'  # Legacy logs don't track field types
                    }
                    
                    # Create AuditLogEntry for detailed tracking
                    AuditLogEntry.objects.create(
                        audit_log=new_log,
                        field_name=field_name,
                        field_type='Unknown',
                        old_value=json.dumps(old_val) if old_val is not None else None,
                        new_value=json.dumps(new_val) if new_val is not None else None,
                        is_sensitive=any(sensitive in field_name.lower() 
                                       for sensitive in ['password', 'token', 'secret', 'key'])
                    )
                
                # Update the audit log with changes
                new_log.changes = changes
                new_log.save()
                
        except Exception as e:
            print(f"Error migrating audit log {legacy_log.id}: {e}")
            continue


def reverse_migration(apps, schema_editor):
    """Reverse the migration by deleting migrated logs"""
    # This is destructive and should be used carefully
    # Only delete logs that were migrated (you might want to track these with metadata)
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0002_initial'),
        ('assessments', '0002_assessmentauditlog_legacy_delete_auditlog_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_audit_logs, reverse_migration),
    ]