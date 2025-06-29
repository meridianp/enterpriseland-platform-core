"""
Workflow Celery Tasks

Async tasks for workflow operations.
"""

import logging
from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist

from .models import WorkflowInstance
from .engine import workflow_engine


logger = logging.getLogger(__name__)


@shared_task
def retry_automated_workflow(instance_id):
    """
    Retry a failed automated workflow.
    
    Args:
        instance_id: ID of the workflow instance to retry
    """
    try:
        instance = WorkflowInstance.objects.get(id=instance_id)
        
        # Get workflow class
        workflow_class = workflow_engine.get_workflow_class(
            instance.definition.workflow_id
        )
        
        # Create workflow instance
        workflow = workflow_class()
        workflow._instance = instance
        workflow._definition = instance.definition
        
        # Execute
        workflow.execute()
        
        logger.info(f"Retried automated workflow: {instance.instance_id}")
        
    except ObjectDoesNotExist:
        logger.error(f"Workflow instance {instance_id} not found")
    except Exception as e:
        logger.error(f"Failed to retry workflow {instance_id}: {e}")


@shared_task
def process_overdue_workflows():
    """
    Process overdue workflows and send notifications.
    """
    from django.utils import timezone
    from notifications.models import Notification
    
    overdue_instances = WorkflowInstance.objects.filter(
        due_date__lt=timezone.now(),
        status__in=['created', 'started']
    ).select_related('definition', 'started_by', 'current_assignee')
    
    for instance in overdue_instances:
        # Send notification to assignee
        if instance.current_assignee:
            Notification.objects.create(
                recipient=instance.current_assignee,
                title=f"Workflow Overdue: {instance.title}",
                message=f"The workflow '{instance.title}' is overdue. Please take action.",
                notification_type='workflow_overdue',
                related_object=instance
            )
        
        # Send notification to starter
        if instance.started_by and instance.started_by != instance.current_assignee:
            Notification.objects.create(
                recipient=instance.started_by,
                title=f"Workflow Overdue: {instance.title}",
                message=f"A workflow you started '{instance.title}' is overdue.",
                notification_type='workflow_overdue',
                related_object=instance
            )
        
        logger.info(f"Processed overdue workflow: {instance.instance_id}")


@shared_task
def process_overdue_tasks():
    """
    Process overdue tasks and send notifications.
    """
    from django.utils import timezone
    from notifications.models import Notification
    from .models import WorkflowTask
    
    overdue_tasks = WorkflowTask.objects.filter(
        due_date__lt=timezone.now(),
        status__in=['created', 'assigned', 'started']
    ).select_related('workflow', 'assigned_to')
    
    for task in overdue_tasks:
        # Send notification to assignee
        if task.assigned_to:
            Notification.objects.create(
                recipient=task.assigned_to,
                title=f"Task Overdue: {task.name}",
                message=f"Your task '{task.name}' in workflow '{task.workflow.title}' is overdue.",
                notification_type='task_overdue',
                related_object=task
            )
        
        # Send notification to workflow starter
        if task.workflow.started_by and task.workflow.started_by != task.assigned_to:
            Notification.objects.create(
                recipient=task.workflow.started_by,
                title=f"Task Overdue: {task.name}",
                message=f"A task '{task.name}' in your workflow '{task.workflow.title}' is overdue.",
                notification_type='task_overdue',
                related_object=task
            )
        
        logger.info(f"Processed overdue task: {task.task_id}")


@shared_task
def cleanup_old_workflows():
    """
    Clean up old completed workflows based on retention policy.
    """
    from django.utils import timezone
    from datetime import timedelta
    
    # Get retention period from settings (default 90 days)
    from django.conf import settings
    retention_days = getattr(settings, 'WORKFLOW_RETENTION_DAYS', 90)
    
    cutoff_date = timezone.now() - timedelta(days=retention_days)
    
    # Find old completed workflows
    old_workflows = WorkflowInstance.objects.filter(
        status__in=['completed', 'cancelled'],
        completed_at__lt=cutoff_date
    )
    
    count = old_workflows.count()
    
    # Delete old workflows
    old_workflows.delete()
    
    logger.info(f"Cleaned up {count} old workflows")


@shared_task
def generate_workflow_report(user_id, start_date, end_date, report_type='summary'):
    """
    Generate a workflow report for a user.
    
    Args:
        user_id: ID of the user requesting the report
        start_date: Start date for the report
        end_date: End date for the report
        report_type: Type of report to generate
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Count, Avg, Q, F
    from notifications.models import Notification
    
    User = get_user_model()
    
    try:
        user = User.objects.get(id=user_id)
        
        # Get workflow instances for the period
        instances = WorkflowInstance.objects.filter(
            Q(started_by=user) | Q(participants=user),
            created_at__gte=start_date,
            created_at__lte=end_date
        ).distinct()
        
        # Generate report data
        report_data = {
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            },
            'summary': {
                'total_workflows': instances.count(),
                'completed': instances.filter(status='completed').count(),
                'in_progress': instances.filter(status__in=['created', 'started']).count(),
                'failed': instances.filter(status='failed').count(),
                'cancelled': instances.filter(status='cancelled').count()
            },
            'performance': {
                'average_completion_time': instances.filter(
                    status='completed',
                    execution_time__isnull=False
                ).aggregate(avg_time=Avg('execution_time'))['avg_time'],
                'on_time_completion_rate': calculate_on_time_rate(instances)
            },
            'by_workflow_type': list(
                instances.values('definition__name').annotate(
                    count=Count('id')
                ).order_by('-count')
            )
        }
        
        if report_type == 'detailed':
            # Add detailed workflow list
            report_data['workflows'] = list(
                instances.values(
                    'instance_id', 'title', 'status',
                    'started_at', 'completed_at', 'execution_time'
                ).order_by('-created_at')
            )
        
        # Send notification with report
        Notification.objects.create(
            recipient=user,
            title="Workflow Report Generated",
            message=f"Your workflow report for {start_date.date()} to {end_date.date()} is ready.",
            notification_type='report_ready',
            data={'report': report_data}
        )
        
        logger.info(f"Generated workflow report for user {user_id}")
        
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found")
    except Exception as e:
        logger.error(f"Failed to generate report for user {user_id}: {e}")


def calculate_on_time_rate(instances):
    """
    Calculate on-time completion rate for workflow instances.
    """
    completed_instances = instances.filter(status='completed', due_date__isnull=False)
    
    if not completed_instances.exists():
        return 0.0
    
    on_time_count = completed_instances.filter(
        completed_at__lte=F('due_date')
    ).count()
    
    total_count = completed_instances.count()
    
    return (on_time_count / total_count) * 100 if total_count > 0 else 0.0


@shared_task
def execute_scheduled_workflow(workflow_id, user_id, title=None, **context):
    """
    Execute a scheduled workflow.
    
    Args:
        workflow_id: Workflow definition ID
        user_id: User ID who scheduled the workflow
        title: Optional workflow title
        **context: Workflow context data
    """
    from django.contrib.auth import get_user_model
    
    User = get_user_model()
    
    try:
        user = User.objects.get(id=user_id)
        
        # Start the workflow
        instance = workflow_engine.start_workflow(
            workflow_id=workflow_id,
            user=user,
            title=title,
            **context
        )
        
        logger.info(f"Executed scheduled workflow: {instance.instance_id}")
        
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found")
    except Exception as e:
        logger.error(f"Failed to execute scheduled workflow {workflow_id}: {e}")