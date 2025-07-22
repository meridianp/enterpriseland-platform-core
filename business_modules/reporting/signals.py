"""Signal handlers for the reporting module."""

from django.db.models.signals import post_save, pre_delete, m2m_changed
from django.dispatch import receiver
from django.core.cache import cache
from django.utils import timezone

from .models import (
    Report, Dashboard, Widget, ReportExecution,
    Metric, MetricCalculation, Alert, DataSource
)


@receiver(post_save, sender=Report)
def handle_report_save(sender, instance, created, **kwargs):
    """Handle report save signal."""
    if not created:
        # Clear cache for updated report
        cache_pattern = f"report_data:{instance.id}:*"
        cache.delete_pattern(cache_pattern)
        
        # Update version if status changed to published
        if instance.status == 'published' and 'status' in instance.get_dirty_fields():
            instance.version += 1
            instance.save(update_fields=['version'])


@receiver(post_save, sender=Dashboard)
def handle_dashboard_save(sender, instance, created, **kwargs):
    """Handle dashboard save signal."""
    if not created:
        # Clear cache for dashboard widgets
        for widget in instance.widgets.all():
            cache_key = f"widget_data:{widget.id}"
            cache.delete(cache_key)


@receiver(m2m_changed, sender=Report.data_sources.through)
def handle_report_data_sources_change(sender, instance, action, **kwargs):
    """Handle changes to report data sources."""
    if action in ['post_add', 'post_remove', 'post_clear']:
        # Clear report cache when data sources change
        cache_pattern = f"report_data:{instance.id}:*"
        cache.delete_pattern(cache_pattern)


@receiver(post_save, sender=Widget)
def handle_widget_save(sender, instance, created, **kwargs):
    """Handle widget save signal."""
    if not created:
        # Clear widget cache
        cache_key = f"widget_data:{instance.id}"
        cache.delete(cache_key)
        
    # Reorder widgets if position changed
    if not created and 'position' in instance.get_dirty_fields():
        _reorder_widgets(instance.dashboard)


@receiver(pre_delete, sender=Widget)
def handle_widget_delete(sender, instance, **kwargs):
    """Handle widget deletion."""
    dashboard = instance.dashboard
    
    # Reorder remaining widgets after deletion
    Widget.objects.filter(
        dashboard=dashboard,
        position__gt=instance.position
    ).update(position=models.F('position') - 1)


@receiver(post_save, sender=ReportExecution)
def handle_report_execution_save(sender, instance, created, **kwargs):
    """Handle report execution save."""
    if instance.status == 'completed' and instance.schedule:
        # Update schedule last run time
        schedule = instance.schedule
        schedule.last_run = instance.completed_at
        schedule.run_count += 1
        schedule.save(update_fields=['last_run', 'run_count'])
        
        # Calculate next run time
        from .services import SchedulingService
        service = SchedulingService()
        service.update_next_run(schedule)


@receiver(post_save, sender=MetricCalculation)
def handle_metric_calculation_save(sender, instance, created, **kwargs):
    """Handle metric calculation save."""
    if created:
        # Check alerts for this metric
        alerts = Alert.objects.filter(
            metric=instance.metric,
            status='active'
        )
        
        for alert in alerts:
            _check_alert_conditions(alert, instance)


@receiver(post_save, sender=DataSource)
def handle_data_source_save(sender, instance, created, **kwargs):
    """Handle data source save."""
    if not created and instance.status == 'error':
        # Notify owner of data source error
        from .services import NotificationService
        notification_service = NotificationService()
        
        notification_service.send_notification(
            user=instance.owner,
            subject=f"Data Source Error: {instance.name}",
            message=f"The data source '{instance.name}' encountered an error: {instance.last_error}",
            notification_type='error'
        )


def _reorder_widgets(dashboard):
    """Reorder dashboard widgets to ensure continuous positions."""
    widgets = Widget.objects.filter(dashboard=dashboard).order_by('position')
    
    for index, widget in enumerate(widgets):
        if widget.position != index:
            widget.position = index
            widget.save(update_fields=['position'])


def _check_alert_conditions(alert, calculation):
    """Check if alert conditions are met."""
    from .services import AlertMonitor
    
    monitor = AlertMonitor()
    triggered = monitor.check_conditions(alert, calculation)
    
    if triggered:
        # Update alert status
        alert.status = 'triggered'
        alert.last_triggered = timezone.now()
        alert.trigger_count += 1
        alert.save(update_fields=['status', 'last_triggered', 'trigger_count'])
        
        # Send notifications
        monitor.send_alert_notifications(alert, calculation)