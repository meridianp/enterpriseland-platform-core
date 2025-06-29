"""
Audit Logging Utilities

Utility functions for audit logging.
"""

import threading
from typing import Dict, Any, Optional, List
from django.conf import settings
from django.db import models
from django.core.serializers import serialize
from django.utils import timezone
from datetime import timedelta
import hashlib
import json


# Thread-local storage for audit context
_thread_locals = threading.local()


def set_audit_context(context: Dict[str, Any]):
    """Set audit context for current thread"""
    _thread_locals.audit_context = context


def get_audit_context() -> Dict[str, Any]:
    """Get audit context for current thread"""
    return getattr(_thread_locals, 'audit_context', {})


def clear_audit_context():
    """Clear audit context for current thread"""
    if hasattr(_thread_locals, 'audit_context'):
        del _thread_locals.audit_context


def should_audit_model(model: type) -> bool:
    """Check if a model should be audited"""
    # Check if model has audit settings
    if hasattr(model, 'audit_enabled'):
        return model.audit_enabled
    
    # Check global settings
    audit_models = getattr(settings, 'AUDIT_MODELS', [])
    exclude_models = getattr(settings, 'AUDIT_EXCLUDE_MODELS', [])
    
    model_name = f"{model._meta.app_label}.{model.__name__}"
    
    if model_name in exclude_models:
        return False
    
    if audit_models:
        return model_name in audit_models
    
    # Default to auditing all models except system models
    system_apps = ['contenttypes', 'sessions', 'admin', 'auth']
    return model._meta.app_label not in system_apps


def mask_sensitive_data(data: Dict[str, Any], fields: List[str] = None) -> Dict[str, Any]:
    """Mask sensitive fields in data"""
    if fields is None:
        fields = getattr(
            settings, 
            'AUDIT_SENSITIVE_FIELDS',
            ['password', 'secret', 'token', 'key', 'ssn', 'credit_card']
        )
    
    masked_data = data.copy()
    
    for field in fields:
        if field in masked_data:
            # Keep first and last char for reference
            value = str(masked_data[field])
            if len(value) > 2:
                masked_data[field] = f"{value[0]}***{value[-1]}"
            else:
                masked_data[field] = "***"
    
    return masked_data


def anonymize_user_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Anonymize user data for compliance"""
    anonymized = data.copy()
    
    # Hash identifiable fields
    identifiable_fields = ['email', 'username', 'first_name', 'last_name', 'phone']
    
    for field in identifiable_fields:
        if field in anonymized and anonymized[field]:
            # Create consistent hash for the same value
            value = str(anonymized[field])
            hash_value = hashlib.sha256(value.encode()).hexdigest()[:8]
            anonymized[field] = f"anon_{hash_value}"
    
    return anonymized


def calculate_retention_date(classification: str = 'internal') -> timezone.datetime:
    """Calculate retention date based on data classification"""
    retention_periods = getattr(settings, 'AUDIT_RETENTION_PERIODS', {
        'public': 365,        # 1 year
        'internal': 730,      # 2 years  
        'confidential': 1095, # 3 years
        'restricted': 2555,   # 7 years
    })
    
    days = retention_periods.get(classification, 730)
    return timezone.now().date() + timedelta(days=days)


def export_audit_logs(
    queryset,
    format: str = 'json',
    anonymize: bool = False
) -> str:
    """Export audit logs in specified format"""
    if format == 'json':
        data = []
        for log in queryset:
            log_data = {
                'id': str(log.id),
                'event_type': log.event_type,
                'timestamp': log.timestamp.isoformat(),
                'user': str(log.user.id) if log.user else None,
                'ip_address': log.ip_address,
                'object_type': log.content_type.model if log.content_type else None,
                'object_id': log.object_id,
                'object_repr': log.object_repr,
                'changes': log.changes,
                'metadata': log.metadata,
            }
            
            if anonymize:
                log_data = anonymize_user_data(log_data)
                log_data['ip_address'] = anonymize_ip(log_data['ip_address'])
            
            data.append(log_data)
        
        return json.dumps(data, indent=2, default=str)
    
    elif format == 'csv':
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'ID', 'Event Type', 'Timestamp', 'User', 'IP Address',
            'Object Type', 'Object ID', 'Object', 'Changes'
        ])
        
        # Data
        for log in queryset:
            ip = anonymize_ip(log.ip_address) if anonymize else log.ip_address
            user = f"anon_{log.user.id}" if anonymize and log.user else str(log.user)
            
            writer.writerow([
                str(log.id),
                log.event_type,
                log.timestamp.isoformat(),
                user,
                ip,
                log.content_type.model if log.content_type else '',
                log.object_id or '',
                log.object_repr,
                json.dumps(log.changes) if log.changes else ''
            ])
        
        return output.getvalue()
    
    else:
        raise ValueError(f"Unsupported format: {format}")


def anonymize_ip(ip_address: str) -> str:
    """Anonymize IP address for privacy"""
    if not ip_address:
        return ''
    
    parts = ip_address.split('.')
    if len(parts) == 4:
        # IPv4 - zero out last octet
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
    else:
        # IPv6 - zero out last segments
        parts = ip_address.split(':')
        if len(parts) > 4:
            return ':'.join(parts[:4] + ['0'] * (len(parts) - 4))
    
    return ip_address


def get_audit_statistics(days: int = 30) -> Dict[str, Any]:
    """Get audit log statistics for monitoring"""
    from .models import AuditLog, APIAccessLog, SecurityEvent
    
    since = timezone.now() - timedelta(days=days)
    
    # Audit log stats
    audit_logs = AuditLog.objects.filter(timestamp__gte=since)
    audit_stats = {
        'total': audit_logs.count(),
        'by_type': dict(
            audit_logs.values_list('event_type').annotate(
                count=models.Count('id')
            ).order_by('-count')[:10]
        ),
        'by_user': dict(
            audit_logs.exclude(user=None).values_list(
                'user__username'
            ).annotate(
                count=models.Count('id')
            ).order_by('-count')[:10]
        ),
    }
    
    # API access stats
    api_logs = APIAccessLog.objects.filter(timestamp__gte=since)
    api_stats = {
        'total': api_logs.count(),
        'errors': api_logs.filter(status_code__gte=400).count(),
        'slow_requests': api_logs.filter(response_time_ms__gt=1000).count(),
        'by_endpoint': dict(
            api_logs.values_list('path').annotate(
                count=models.Count('id')
            ).order_by('-count')[:10]
        ),
    }
    
    # Security events
    security_events = SecurityEvent.objects.filter(detected_at__gte=since)
    security_stats = {
        'total': security_events.count(),
        'unhandled': security_events.filter(handled=False).count(),
        'by_severity': dict(
            security_events.values_list('severity').annotate(
                count=models.Count('id')
            )
        ),
    }
    
    return {
        'period_days': days,
        'audit_logs': audit_stats,
        'api_access': api_stats,
        'security_events': security_stats,
    }


def detect_anomalies(user, action: str, metadata: Dict[str, Any] = None) -> Optional[str]:
    """
    Simple anomaly detection for security monitoring.
    
    Returns anomaly type if detected, None otherwise.
    """
    from .models import AuditLog, APIAccessLog
    
    # Check for unusual activity patterns
    last_hour = timezone.now() - timedelta(hours=1)
    
    # High frequency of actions
    recent_actions = AuditLog.objects.filter(
        user=user,
        timestamp__gte=last_hour
    ).count()
    
    if recent_actions > 100:
        return 'high_frequency_activity'
    
    # Multiple failed logins
    if action == 'login_failed':
        failed_logins = AuditLog.objects.filter(
            user=user,
            event_type='login_failed',
            timestamp__gte=last_hour
        ).count()
        
        if failed_logins >= 5:
            return 'brute_force_attempt'
    
    # Unusual access patterns
    if action in ['export', 'bulk_delete']:
        # Check if user normally performs these actions
        historical = AuditLog.objects.filter(
            user=user,
            event_type=action,
            timestamp__lt=last_hour
        ).exists()
        
        if not historical:
            return 'unusual_activity'
    
    # Large data access
    if metadata and metadata.get('count', 0) > 10000:
        return 'large_data_access'
    
    return None