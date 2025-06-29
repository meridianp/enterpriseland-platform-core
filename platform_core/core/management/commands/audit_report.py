"""
Django management command for generating audit reports.

Provides comprehensive audit reporting with filtering, export options,
and compliance report generation.
"""

import json
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder

from accounts.models import Group
from platform_core.core.models import AuditLog

User = get_user_model()


class Command(BaseCommand):
    help = 'Generate comprehensive audit reports with filtering and export options'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--report-type',
            choices=['all', 'security', 'data_changes', 'errors', 'user_activity', 'compliance'],
            default='all',
            help='Type of audit report to generate'
        )
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date for the report (YYYY-MM-DD format)'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date for the report (YYYY-MM-DD format)'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days back from today (if start/end dates not provided)'
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Filter by user email'
        )
        parser.add_argument(
            '--group',
            type=str,
            help='Filter by group name'
        )
        parser.add_argument(
            '--action',
            type=str,
            help='Filter by specific action'
        )
        parser.add_argument(
            '--model',
            type=str,
            help='Filter by model name'
        )
        parser.add_argument(
            '--ip-address',
            type=str,
            help='Filter by IP address'
        )
        parser.add_argument(
            '--success',
            choices=['true', 'false'],
            help='Filter by success status'
        )
        parser.add_argument(
            '--format',
            choices=['json', 'csv', 'table', 'summary'],
            default='table',
            help='Output format'
        )
        parser.add_argument(
            '--output',
            type=str,
            help='Output file path (default: stdout)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=1000,
            help='Maximum number of records to include'
        )
        parser.add_argument(
            '--include-sensitive',
            action='store_true',
            help='Include sensitive data in the output (use with caution)'
        )
        parser.add_argument(
            '--group-by',
            choices=['user', 'action', 'model', 'date', 'ip'],
            help='Group results by specified field'
        )
    
    def handle(self, *args, **options):
        try:
            # Parse date range
            start_date, end_date = self._parse_date_range(options)
            
            # Build the query
            queryset = self._build_queryset(options, start_date, end_date)
            
            # Generate the report
            if options['group_by']:
                report_data = self._generate_grouped_report(queryset, options)
            else:
                report_data = self._generate_detailed_report(queryset, options)
            
            # Format and output the report
            self._output_report(report_data, options)
            
            self.stdout.write(
                self.style.SUCCESS(f"Audit report generated successfully")
            )
        
        except Exception as e:
            raise CommandError(f"Error generating audit report: {e}")
    
    def _parse_date_range(self, options):
        """Parse start and end dates from options."""
        if options['start_date'] and options['end_date']:
            try:
                start_date = datetime.strptime(options['start_date'], '%Y-%m-%d')
                end_date = datetime.strptime(options['end_date'], '%Y-%m-%d')
                
                # Make end_date inclusive by setting time to end of day
                end_date = end_date.replace(hour=23, minute=59, second=59)
                
                # Convert to timezone-aware datetimes
                start_date = timezone.make_aware(start_date)
                end_date = timezone.make_aware(end_date)
                
            except ValueError as e:
                raise CommandError(f"Invalid date format: {e}")
        else:
            # Use days parameter
            end_date = timezone.now()
            start_date = end_date - timedelta(days=options['days'])
        
        return start_date, end_date
    
    def _build_queryset(self, options, start_date, end_date):
        """Build the audit log queryset based on filters."""
        queryset = AuditLog.objects.filter(
            timestamp__gte=start_date,
            timestamp__lte=end_date
        )
        
        # Apply report type filters
        report_type = options['report_type']
        if report_type == 'security':
            queryset = queryset.filter(
                action__in=[
                    AuditLog.Action.LOGIN_FAILED,
                    AuditLog.Action.PERMISSION_CHANGE,
                    AuditLog.Action.PASSWORD_CHANGE,
                    AuditLog.Action.DELETE,
                    AuditLog.Action.ADMIN_ACCESS,
                    AuditLog.Action.USER_DEACTIVATION
                ]
            )
        elif report_type == 'data_changes':
            queryset = queryset.filter(
                action__in=[
                    AuditLog.Action.CREATE,
                    AuditLog.Action.UPDATE,
                    AuditLog.Action.DELETE,
                    AuditLog.Action.BULK_CREATE,
                    AuditLog.Action.BULK_UPDATE,
                    AuditLog.Action.BULK_DELETE
                ]
            ).exclude(changes={})
        elif report_type == 'errors':
            queryset = queryset.filter(success=False)
        elif report_type == 'user_activity':
            queryset = queryset.filter(
                action__in=[
                    AuditLog.Action.LOGIN,
                    AuditLog.Action.LOGOUT,
                    AuditLog.Action.CREATE,
                    AuditLog.Action.UPDATE,
                    AuditLog.Action.DELETE,
                    AuditLog.Action.EXPORT,
                    AuditLog.Action.IMPORT
                ]
            ).exclude(user__isnull=True)
        elif report_type == 'compliance':
            # Include all critical actions for compliance reporting
            queryset = queryset.filter(
                action__in=[
                    AuditLog.Action.CREATE,
                    AuditLog.Action.UPDATE,
                    AuditLog.Action.DELETE,
                    AuditLog.Action.PERMISSION_CHANGE,
                    AuditLog.Action.EXPORT,
                    AuditLog.Action.IMPORT,
                    AuditLog.Action.LOGIN_FAILED
                ]
            )
        
        # Apply additional filters
        if options['user']:
            try:
                user = User.objects.get(email=options['user'])
                queryset = queryset.filter(user=user)
            except User.DoesNotExist:
                raise CommandError(f"User not found: {options['user']}")
        
        if options['group']:
            try:
                group = Group.objects.get(name=options['group'])
                queryset = queryset.filter(group=group)
            except Group.DoesNotExist:
                raise CommandError(f"Group not found: {options['group']}")
        
        if options['action']:
            queryset = queryset.filter(action=options['action'])
        
        if options['model']:
            queryset = queryset.filter(model_name=options['model'])
        
        if options['ip_address']:
            queryset = queryset.filter(ip_address=options['ip_address'])
        
        if options['success'] is not None:
            success = options['success'].lower() == 'true'
            queryset = queryset.filter(success=success)
        
        return queryset.select_related('user', 'group', 'content_type').order_by('-timestamp')
    
    def _generate_detailed_report(self, queryset, options):
        """Generate detailed audit report."""
        # Limit the results
        limited_queryset = queryset[:options['limit']]
        
        report_data = {
            'report_type': options['report_type'],
            'generated_at': timezone.now().isoformat(),
            'total_records': queryset.count(),
            'included_records': len(limited_queryset),
            'records': []
        }
        
        for log in limited_queryset:
            record = {
                'id': str(log.id),
                'timestamp': log.timestamp.isoformat(),
                'action': log.action,
                'user': log.user.email if log.user else None,
                'group': log.group.name if log.group else None,
                'model_name': log.model_name,
                'object_id': log.object_id,
                'ip_address': log.ip_address,
                'user_agent': log.user_agent,
                'success': log.success,
                'error_message': log.error_message,
                'metadata': log.metadata
            }
            
            # Handle sensitive data
            if options['include_sensitive']:
                record['changes'] = log.changes
            else:
                record['changes'] = log.mask_sensitive_data()
            
            report_data['records'].append(record)
        
        return report_data
    
    def _generate_grouped_report(self, queryset, options):
        """Generate grouped audit report."""
        from django.db.models import Count, Q
        from collections import defaultdict
        
        group_by = options['group_by']
        report_data = {
            'report_type': options['report_type'],
            'grouped_by': group_by,
            'generated_at': timezone.now().isoformat(),
            'total_records': queryset.count(),
            'groups': defaultdict(lambda: {
                'count': 0,
                'success_count': 0,
                'error_count': 0,
                'actions': defaultdict(int),
                'latest_timestamp': None
            })
        }
        
        # Process the queryset
        for log in queryset:
            # Determine the group key
            if group_by == 'user':
                group_key = log.user.email if log.user else 'Anonymous'
            elif group_by == 'action':
                group_key = log.action
            elif group_by == 'model':
                group_key = log.model_name or 'System'
            elif group_by == 'date':
                group_key = log.timestamp.date().isoformat()
            elif group_by == 'ip':
                group_key = log.ip_address or 'Unknown'
            else:
                group_key = 'Other'
            
            # Update group statistics
            group_stats = report_data['groups'][group_key]
            group_stats['count'] += 1
            
            if log.success:
                group_stats['success_count'] += 1
            else:
                group_stats['error_count'] += 1
            
            group_stats['actions'][log.action] += 1
            
            if (group_stats['latest_timestamp'] is None or 
                log.timestamp > datetime.fromisoformat(group_stats['latest_timestamp'].replace('Z', '+00:00'))):
                group_stats['latest_timestamp'] = log.timestamp.isoformat()
        
        # Convert defaultdict to regular dict for JSON serialization
        report_data['groups'] = dict(report_data['groups'])
        for group_key, group_stats in report_data['groups'].items():
            group_stats['actions'] = dict(group_stats['actions'])
        
        return report_data
    
    def _output_report(self, report_data, options):
        """Output the report in the specified format."""
        output_format = options['format']
        output_file = options.get('output')
        
        if output_format == 'json':
            content = json.dumps(report_data, indent=2, cls=DjangoJSONEncoder)
        elif output_format == 'csv':
            content = self._format_csv(report_data)
        elif output_format == 'table':
            content = self._format_table(report_data)
        elif output_format == 'summary':
            content = self._format_summary(report_data)
        else:
            content = str(report_data)
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(content)
            self.stdout.write(f"Report saved to: {output_file}")
        else:
            self.stdout.write(content)
    
    def _format_csv(self, report_data):
        """Format report data as CSV."""
        import csv
        import io
        
        output = io.StringIO()
        
        if 'records' in report_data:
            # Detailed report
            if not report_data['records']:
                return "No records found\n"
            
            fieldnames = report_data['records'][0].keys()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for record in report_data['records']:
                # Flatten complex fields
                flattened_record = {}
                for key, value in record.items():
                    if isinstance(value, (dict, list)):
                        flattened_record[key] = json.dumps(value)
                    else:
                        flattened_record[key] = value
                writer.writerow(flattened_record)
        else:
            # Grouped report
            writer = csv.writer(output)
            writer.writerow(['Group', 'Count', 'Success Count', 'Error Count', 'Latest Activity'])
            
            for group_key, group_stats in report_data['groups'].items():
                writer.writerow([
                    group_key,
                    group_stats['count'],
                    group_stats['success_count'],
                    group_stats['error_count'],
                    group_stats['latest_timestamp']
                ])
        
        return output.getvalue()
    
    def _format_table(self, report_data):
        """Format report data as a table."""
        from django.utils.text import Truncator
        
        lines = []
        lines.append(f"Audit Report - {report_data['report_type'].upper()}")
        lines.append(f"Generated: {report_data['generated_at']}")
        lines.append(f"Total Records: {report_data['total_records']}")
        lines.append("-" * 80)
        
        if 'records' in report_data:
            # Detailed report
            if not report_data['records']:
                lines.append("No records found")
                return "\n".join(lines)
            
            lines.append(f"{'Timestamp':<20} {'Action':<15} {'User':<25} {'Model':<15} {'Success':<8}")
            lines.append("-" * 80)
            
            for record in report_data['records']:
                timestamp = record['timestamp'][:19].replace('T', ' ')
                action = Truncator(record['action']).chars(14)
                user = Truncator(record['user'] or 'Anonymous').chars(24)
                model = Truncator(record['model_name'] or 'System').chars(14)
                success = '✓' if record['success'] else '✗'
                
                lines.append(f"{timestamp:<20} {action:<15} {user:<25} {model:<15} {success:<8}")
        else:
            # Grouped report
            lines.append(f"{'Group':<30} {'Count':<8} {'Success':<8} {'Errors':<8} {'Latest':<20}")
            lines.append("-" * 80)
            
            for group_key, group_stats in report_data['groups'].items():
                group_name = Truncator(group_key).chars(29)
                latest = group_stats['latest_timestamp'][:19].replace('T', ' ') if group_stats['latest_timestamp'] else 'N/A'
                
                lines.append(
                    f"{group_name:<30} {group_stats['count']:<8} "
                    f"{group_stats['success_count']:<8} {group_stats['error_count']:<8} {latest:<20}"
                )
        
        return "\n".join(lines)
    
    def _format_summary(self, report_data):
        """Format report data as a summary."""
        lines = []
        lines.append(f"AUDIT REPORT SUMMARY")
        lines.append(f"Report Type: {report_data['report_type'].upper()}")
        lines.append(f"Generated: {report_data['generated_at']}")
        lines.append(f"Total Records: {report_data['total_records']}")
        lines.append("")
        
        if 'records' in report_data:
            # Detailed report summary
            if not report_data['records']:
                lines.append("No records found")
                return "\n".join(lines)
            
            # Calculate statistics
            total_records = len(report_data['records'])
            success_count = sum(1 for r in report_data['records'] if r['success'])
            error_count = total_records - success_count
            
            # Count by action
            action_counts = {}
            for record in report_data['records']:
                action = record['action']
                action_counts[action] = action_counts.get(action, 0) + 1
            
            lines.append(f"Success Rate: {success_count}/{total_records} ({success_count/total_records*100:.1f}%)")
            lines.append(f"Error Count: {error_count}")
            lines.append("")
            lines.append("Actions:")
            for action, count in sorted(action_counts.items()):
                lines.append(f"  {action}: {count}")
        else:
            # Grouped report summary
            total_groups = len(report_data['groups'])
            total_records = sum(stats['count'] for stats in report_data['groups'].values())
            total_errors = sum(stats['error_count'] for stats in report_data['groups'].values())
            
            lines.append(f"Total Groups: {total_groups}")
            lines.append(f"Total Records: {total_records}")
            lines.append(f"Total Errors: {total_errors}")
            lines.append("")
            lines.append("Top Groups:")
            
            sorted_groups = sorted(
                report_data['groups'].items(),
                key=lambda x: x[1]['count'],
                reverse=True
            )[:10]
            
            for group_key, group_stats in sorted_groups:
                lines.append(f"  {group_key}: {group_stats['count']} records")
        
        return "\n".join(lines)