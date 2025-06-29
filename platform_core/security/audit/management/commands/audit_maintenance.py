"""
Audit Log Maintenance Command

Management command for audit log maintenance tasks.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count, Q
from datetime import timedelta

from platform_core.security.audit.models import (
    AuditLog, APIAccessLog, DataAccessLog, SecurityEvent
)
from platform_core.security.audit.utils import export_audit_logs, get_audit_statistics


class Command(BaseCommand):
    help = 'Perform audit log maintenance tasks'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Clean up old audit logs based on retention policy'
        )
        parser.add_argument(
            '--archive',
            action='store_true',
            help='Archive old audit logs to file'
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Display audit log statistics'
        )
        parser.add_argument(
            '--check-anomalies',
            action='store_true',
            help='Check for anomalies in recent logs'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to process (default: 30)'
        )
        parser.add_argument(
            '--output',
            type=str,
            help='Output file for archive'
        )
    
    def handle(self, *args, **options):
        if options['cleanup']:
            self.cleanup_old_logs()
        
        if options['archive']:
            self.archive_logs(options['days'], options['output'])
        
        if options['stats']:
            self.display_statistics(options['days'])
        
        if options['check_anomalies']:
            self.check_anomalies(options['days'])
    
    def cleanup_old_logs(self):
        """Clean up logs past retention date"""
        self.stdout.write("Cleaning up old audit logs...")
        
        # Clean AuditLog
        audit_deleted = AuditLog.objects.filter(
            retention_date__lt=timezone.now().date()
        ).delete()
        
        # Clean APIAccessLog (keep for 90 days)
        api_cutoff = timezone.now() - timedelta(days=90)
        api_deleted = APIAccessLog.objects.filter(
            timestamp__lt=api_cutoff
        ).delete()
        
        # Clean DataAccessLog (keep based on classification)
        data_deleted = 0
        for days, classification in [(90, 'public'), (180, 'internal')]:
            cutoff = timezone.now() - timedelta(days=days)
            deleted = DataAccessLog.objects.filter(
                timestamp__lt=cutoff,
                data_classification=classification
            ).delete()
            data_deleted += deleted[0]
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted: {audit_deleted[0]} audit logs, "
                f"{api_deleted[0]} API logs, {data_deleted} data access logs"
            )
        )
    
    def archive_logs(self, days: int, output_file: str = None):
        """Archive old logs to file"""
        self.stdout.write(f"Archiving logs older than {days} days...")
        
        cutoff = timezone.now() - timedelta(days=days)
        logs = AuditLog.objects.filter(timestamp__lt=cutoff)
        
        if not logs.exists():
            self.stdout.write("No logs to archive")
            return
        
        # Export logs
        if not output_file:
            output_file = f"audit_archive_{timezone.now().date()}.json"
        
        export_data = export_audit_logs(logs, format='json', anonymize=True)
        
        with open(output_file, 'w') as f:
            f.write(export_data)
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Archived {logs.count()} logs to {output_file}"
            )
        )
    
    def display_statistics(self, days: int):
        """Display audit log statistics"""
        self.stdout.write(f"\nAudit Log Statistics (last {days} days)")
        self.stdout.write("=" * 50)
        
        stats = get_audit_statistics(days)
        
        # Audit logs
        self.stdout.write(f"\nAudit Logs: {stats['audit_logs']['total']:,}")
        self.stdout.write("Top event types:")
        for event, count in list(stats['audit_logs']['by_type'].items())[:5]:
            self.stdout.write(f"  - {event}: {count:,}")
        
        # API access
        self.stdout.write(f"\nAPI Access: {stats['api_access']['total']:,}")
        self.stdout.write(f"  - Errors: {stats['api_access']['errors']:,}")
        self.stdout.write(f"  - Slow requests: {stats['api_access']['slow_requests']:,}")
        
        # Security events
        self.stdout.write(f"\nSecurity Events: {stats['security_events']['total']:,}")
        self.stdout.write(f"  - Unhandled: {stats['security_events']['unhandled']:,}")
        
        severity_map = {
            'critical': self.style.ERROR,
            'high': self.style.WARNING,
            'medium': self.style.WARNING,
            'low': self.style.SUCCESS,
            'info': self.style.SUCCESS
        }
        
        for severity, count in stats['security_events']['by_severity'].items():
            style = severity_map.get(severity, self.style.SUCCESS)
            self.stdout.write(style(f"  - {severity}: {count}"))
    
    def check_anomalies(self, days: int):
        """Check for anomalies in recent logs"""
        self.stdout.write(f"\nChecking for anomalies (last {days} days)...")
        
        since = timezone.now() - timedelta(days=days)
        
        # Check for users with high activity
        high_activity_users = AuditLog.objects.filter(
            timestamp__gte=since
        ).values('user__username').annotate(
            count=Count('id')
        ).filter(count__gt=1000).order_by('-count')
        
        if high_activity_users:
            self.stdout.write(self.style.WARNING("\nHigh activity users:"))
            for user in high_activity_users[:5]:
                self.stdout.write(
                    f"  - {user['user__username']}: {user['count']:,} actions"
                )
        
        # Check for failed login attempts
        failed_logins = AuditLog.objects.filter(
            event_type='login_failed',
            timestamp__gte=since
        ).values('ip_address').annotate(
            count=Count('id')
        ).filter(count__gte=10).order_by('-count')
        
        if failed_logins:
            self.stdout.write(self.style.WARNING("\nMultiple failed login attempts:"))
            for attempt in failed_logins[:5]:
                self.stdout.write(
                    f"  - {attempt['ip_address']}: {attempt['count']} attempts"
                )
        
        # Check for large exports
        large_exports = AuditLog.objects.filter(
            event_type='export',
            timestamp__gte=since,
            metadata__count__gt=5000
        ).select_related('user')
        
        if large_exports:
            self.stdout.write(self.style.WARNING("\nLarge data exports:"))
            for export in large_exports[:5]:
                count = export.metadata.get('count', 'Unknown')
                self.stdout.write(
                    f"  - {export.user}: exported {count} records of {export.object_repr}"
                )
        
        # Check unhandled security events
        unhandled = SecurityEvent.objects.filter(
            handled=False,
            severity__in=['high', 'critical']
        )
        
        if unhandled:
            self.stdout.write(
                self.style.ERROR(
                    f"\nWARNING: {unhandled.count()} unhandled high/critical security events!"
                )
            )