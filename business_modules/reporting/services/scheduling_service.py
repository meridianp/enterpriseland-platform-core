"""Scheduling service for automated report generation."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from croniter import croniter
from django.utils import timezone
from celery import shared_task

from ..models import ReportSchedule, ReportExecution
from .report_service import ReportService, ReportExecutor
from .export_service import ExportService
from .notification_service import NotificationService

logger = logging.getLogger(__name__)


class SchedulingService:
    """Service for managing report schedules."""
    
    def __init__(self):
        self.report_service = ReportService()
        self.export_service = ExportService()
        self.notification_service = NotificationService()
    
    def update_next_run(self, schedule: ReportSchedule):
        """Update the next run time for a schedule."""
        if not schedule.is_active:
            schedule.next_run = None
            schedule.save()
            return
        
        now = timezone.now()
        
        if schedule.frequency == 'once':
            # One-time schedule
            if not schedule.last_run:
                schedule.next_run = schedule.start_date
            else:
                schedule.next_run = None
                schedule.is_active = False
        
        elif schedule.frequency == 'custom' and schedule.cron_expression:
            # Cron-based schedule
            try:
                cron = croniter(schedule.cron_expression, now)
                schedule.next_run = timezone.make_aware(
                    datetime.fromtimestamp(cron.get_next())
                )
            except Exception as e:
                logger.error(f"Invalid cron expression: {schedule.cron_expression}")
                schedule.next_run = None
        
        else:
            # Standard frequencies
            if schedule.last_run:
                base_time = schedule.last_run
            else:
                base_time = max(schedule.start_date, now)
            
            if schedule.frequency == 'daily':
                schedule.next_run = base_time + timedelta(days=1)
            elif schedule.frequency == 'weekly':
                schedule.next_run = base_time + timedelta(weeks=1)
            elif schedule.frequency == 'monthly':
                # Add one month (approximate)
                schedule.next_run = base_time + timedelta(days=30)
            elif schedule.frequency == 'quarterly':
                # Add three months (approximate)
                schedule.next_run = base_time + timedelta(days=90)
            elif schedule.frequency == 'yearly':
                # Add one year (approximate)
                schedule.next_run = base_time + timedelta(days=365)
        
        # Check end date
        if schedule.end_date and schedule.next_run and schedule.next_run > schedule.end_date:
            schedule.next_run = None
            schedule.is_active = False
        
        schedule.save()
    
    def get_due_schedules(self) -> List[ReportSchedule]:
        """Get all schedules that are due to run."""
        now = timezone.now()
        
        return ReportSchedule.objects.filter(
            is_active=True,
            next_run__lte=now
        ).select_related('report')
    
    def execute_schedule(self, schedule_id: str):
        """Execute a scheduled report."""
        try:
            schedule = ReportSchedule.objects.get(id=schedule_id)
            
            if not schedule.is_active:
                logger.warning(f"Attempted to execute inactive schedule: {schedule_id}")
                return
            
            # Execute the report
            executor = ReportExecutor()
            execution = ReportExecution.objects.create(
                report=schedule.report,
                schedule=schedule,
                status='running',
                started_at=timezone.now(),
                parameters={}
            )
            
            try:
                # Execute report
                report_data = executor.execute_report(schedule.report, {})
                
                # Update execution
                execution.status = 'completed'
                execution.completed_at = timezone.now()
                execution.duration = (execution.completed_at - execution.started_at).total_seconds()
                execution.result_data = report_data
                execution.save()
                
                # Handle delivery
                self._deliver_scheduled_report(schedule, report_data)
                
                # Update schedule
                schedule.last_run = timezone.now()
                schedule.run_count += 1
                self.update_next_run(schedule)
                
            except Exception as e:
                logger.error(f"Schedule execution failed: {str(e)}")
                execution.status = 'failed'
                execution.completed_at = timezone.now()
                execution.error_message = str(e)
                execution.save()
                raise
                
        except Exception as e:
            logger.error(f"Failed to execute schedule {schedule_id}: {str(e)}")
            raise
    
    def _deliver_scheduled_report(self, schedule: ReportSchedule, report_data: Dict):
        """Deliver the scheduled report based on delivery method."""
        if schedule.delivery_method == 'email':
            self._deliver_via_email(schedule, report_data)
        elif schedule.delivery_method == 'webhook':
            self._deliver_via_webhook(schedule, report_data)
        elif schedule.delivery_method == 'storage':
            self._deliver_to_storage(schedule, report_data)
        elif schedule.delivery_method == 'dashboard':
            self._deliver_to_dashboard(schedule, report_data)
    
    def _deliver_via_email(self, schedule: ReportSchedule, report_data: Dict):
        """Deliver report via email."""
        recipients = schedule.delivery_config.get('recipients', [])
        
        if not recipients:
            logger.warning(f"No recipients configured for schedule {schedule.id}")
            return
        
        # Export report if format specified
        if schedule.export_format != 'none':
            export_result = self.export_service.export(
                data=report_data,
                format=schedule.export_format,
                options={'include_visualizations': True}
            )
            
            # TODO: Attach file to email
            attachment_url = export_result.get('download_url')
        else:
            attachment_url = None
        
        # Send email
        self.notification_service.send_report_email(
            report_data=report_data,
            recipients=recipients,
            subject=f"Scheduled Report: {schedule.report.name}"
        )
    
    def _deliver_via_webhook(self, schedule: ReportSchedule, report_data: Dict):
        """Deliver report via webhook."""
        webhook_url = schedule.delivery_config.get('webhook_url')
        
        if not webhook_url:
            logger.warning(f"No webhook URL configured for schedule {schedule.id}")
            return
        
        import requests
        
        payload = {
            'schedule_id': str(schedule.id),
            'report_id': str(schedule.report.id),
            'report_name': schedule.report.name,
            'generated_at': report_data.get('report', {}).get('generated_at'),
            'data': report_data
        }
        
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Webhook delivery failed: {str(e)}")
            raise
    
    def _deliver_to_storage(self, schedule: ReportSchedule, report_data: Dict):
        """Save report to storage."""
        # Export report
        export_result = self.export_service.export(
            data=report_data,
            format=schedule.export_format or 'json',
            options={'include_visualizations': True}
        )
        
        # The file is already saved by the export service
        logger.info(f"Report saved to storage: {export_result.get('file_path')}")
    
    def _deliver_to_dashboard(self, schedule: ReportSchedule, report_data: Dict):
        """Update dashboard with report data."""
        # This would update dashboard widgets with the latest data
        # Implementation depends on your dashboard update mechanism
        pass


class ReportScheduler:
    """Celery task scheduler for reports."""
    
    @staticmethod
    @shared_task
    def check_schedules():
        """Check and execute due schedules."""
        service = SchedulingService()
        due_schedules = service.get_due_schedules()
        
        for schedule in due_schedules:
            # Delegate to separate task for parallel execution
            execute_scheduled_report.delay(str(schedule.id))
    
    @staticmethod
    @shared_task
    def execute_scheduled_report(schedule_id: str):
        """Execute a single scheduled report."""
        service = SchedulingService()
        service.execute_schedule(schedule_id)


# Celery beat schedule
from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    'check-report-schedules': {
        'task': 'business_modules.reporting.services.scheduling_service.check_schedules',
        'schedule': crontab(minute='*/5'),  # Check every 5 minutes
    },
}