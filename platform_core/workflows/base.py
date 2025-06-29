"""
Base Workflow Classes

Provides base classes for creating workflows that integrate with the module system.
"""

import logging
from typing import Dict, Any, Optional, List, Type
from django.db import transaction
from django.utils import timezone
from viewflow import This
from viewflow.workflow import flow, Node
from viewflow.workflow.flow import FlowMeta

from .models import WorkflowDefinition, WorkflowInstance, WorkflowTask, WorkflowTransition


logger = logging.getLogger(__name__)


class ModuleWorkflowMeta(FlowMeta):
    """
    Metaclass for module workflows that automatically registers them.
    """
    
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        
        # Register workflow if it's not the base class
        if name != 'ModuleWorkflow' and hasattr(cls, 'workflow_id'):
            cls._register_workflow()
        
        return cls


class ModuleWorkflow(flow.Flow, metaclass=ModuleWorkflowMeta):
    """
    Base class for workflows provided by modules.
    
    Integrates with the platform's workflow system and provides
    additional features like audit logging, permissions, and monitoring.
    """
    
    # Workflow metadata (override in subclasses)
    workflow_id = None  # e.g., 'com.company.approval'
    workflow_name = "Module Workflow"
    workflow_description = ""
    workflow_version = "1.0.0"
    workflow_type = "custom"
    
    # Permissions
    start_permission = None
    view_permission = None
    
    # Configuration schema
    config_schema = {}
    default_config = {}
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._instance = None
        self._definition = None
    
    @classmethod
    def _register_workflow(cls):
        """Register this workflow with the platform"""
        if not cls.workflow_id:
            return
        
        try:
            # Get or create workflow definition
            definition, created = WorkflowDefinition.objects.get_or_create(
                workflow_id=cls.workflow_id,
                defaults={
                    'name': cls.workflow_name,
                    'description': cls.workflow_description,
                    'version': cls.workflow_version,
                    'workflow_type': cls.workflow_type,
                    'flow_class': f"{cls.__module__}.{cls.__name__}",
                    'config_schema': cls.config_schema,
                    'default_config': cls.default_config,
                    'start_permission': cls.start_permission,
                    'view_permission': cls.view_permission,
                }
            )
            
            if created:
                logger.info(f"Registered workflow: {cls.workflow_id}")
            else:
                # Update version if changed
                if definition.version != cls.workflow_version:
                    definition.version = cls.workflow_version
                    definition.save(update_fields=['version'])
                    logger.info(f"Updated workflow version: {cls.workflow_id} -> {cls.workflow_version}")
                    
        except Exception as e:
            logger.error(f"Failed to register workflow {cls.workflow_id}: {e}")
    
    def start_workflow(self, user, title=None, **kwargs):
        """
        Start a new workflow instance.
        
        Args:
            user: User starting the workflow
            title: Optional title for the instance
            **kwargs: Additional context data
        
        Returns:
            WorkflowInstance
        """
        with transaction.atomic():
            # Get workflow definition
            self._definition = WorkflowDefinition.objects.get(
                workflow_id=self.workflow_id
            )
            
            # Create instance
            self._instance = WorkflowInstance.objects.create(
                definition=self._definition,
                instance_id=f"{self.workflow_id}_{timezone.now().timestamp()}",
                title=title or f"{self.workflow_name} - {timezone.now().strftime('%Y-%m-%d %H:%M')}",
                started_by=user,
                context_data=kwargs,
                group=user.group
            )
            
            # Start the workflow
            self._instance.start(user)
            self._instance.save()
            
            # Create initial tasks
            self._create_initial_tasks()
            
            return self._instance
    
    def _create_initial_tasks(self):
        """Create initial workflow tasks"""
        # This should be overridden by subclasses to create
        # the initial tasks based on the workflow definition
        pass
    
    def create_task(self, task_id, name, task_type='user', **kwargs):
        """
        Create a workflow task.
        
        Args:
            task_id: Unique task identifier
            name: Task name
            task_type: Type of task
            **kwargs: Additional task fields
        
        Returns:
            WorkflowTask
        """
        if not self._instance:
            raise ValueError("No workflow instance available")
        
        task = WorkflowTask.objects.create(
            workflow=self._instance,
            task_id=task_id,
            name=name,
            task_type=task_type,
            group=self._instance.group,
            **kwargs
        )
        
        # Update task count
        self._instance.task_count += 1
        self._instance.save(update_fields=['task_count'])
        
        return task
    
    def create_transition(self, from_task, to_task, transition_type='sequence', condition=None):
        """
        Create a transition between tasks.
        
        Args:
            from_task: Source task (can be None for start)
            to_task: Target task
            transition_type: Type of transition
            condition: Optional condition expression
        
        Returns:
            WorkflowTransition
        """
        if not self._instance:
            raise ValueError("No workflow instance available")
        
        return WorkflowTransition.objects.create(
            workflow=self._instance,
            from_task=from_task,
            to_task=to_task,
            transition_type=transition_type,
            condition=condition
        )
    
    def get_context(self, key=None, default=None):
        """Get workflow context data"""
        if not self._instance:
            return default
        
        if key:
            return self._instance.context_data.get(key, default)
        return self._instance.context_data
    
    def set_context(self, key, value):
        """Set workflow context data"""
        if not self._instance:
            raise ValueError("No workflow instance available")
        
        self._instance.context_data[key] = value
        self._instance.save(update_fields=['context_data'])
    
    def update_context(self, data):
        """Update workflow context with multiple values"""
        if not self._instance:
            raise ValueError("No workflow instance available")
        
        self._instance.context_data.update(data)
        self._instance.save(update_fields=['context_data'])


class BaseApprovalWorkflow(ModuleWorkflow):
    """
    Base class for approval workflows.
    
    Provides common approval patterns and utilities.
    """
    
    workflow_type = "approval"
    
    # Approval configuration
    approval_levels = 1  # Number of approval levels
    auto_approve_conditions = []  # Conditions for auto-approval
    rejection_allowed = True  # Whether rejection is allowed
    
    def _create_initial_tasks(self):
        """Create approval tasks"""
        # Create submission task
        submission_task = self.create_task(
            task_id='submit',
            name='Submit for Approval',
            task_type='user',
            description='Submit the item for approval'
        )
        
        # Create approval tasks for each level
        previous_task = submission_task
        for level in range(1, self.approval_levels + 1):
            approval_task = self.create_task(
                task_id=f'approve_level_{level}',
                name=f'Level {level} Approval',
                task_type='approval',
                description=f'Approval by level {level} approver'
            )
            
            # Create transition
            self.create_transition(
                from_task=previous_task,
                to_task=approval_task,
                transition_type='sequence'
            )
            
            previous_task = approval_task
        
        # Create completion task
        completion_task = self.create_task(
            task_id='complete',
            name='Complete Approval',
            task_type='system',
            description='Finalize the approval process'
        )
        
        self.create_transition(
            from_task=previous_task,
            to_task=completion_task,
            transition_type='sequence'
        )
    
    def approve_task(self, task_id, user, comments=None):
        """Approve a task"""
        task = WorkflowTask.objects.get(
            workflow=self._instance,
            task_id=task_id
        )
        
        if task.task_type != 'approval':
            raise ValueError("Task is not an approval task")
        
        # Complete the task
        output_data = {
            'approved': True,
            'approved_by': user.id,
            'approved_at': timezone.now().isoformat(),
            'comments': comments
        }
        
        task.complete(user=user, output_data=output_data)
        task.save()
        
        # Check if workflow should complete
        self._check_workflow_completion()
    
    def reject_task(self, task_id, user, reason=None):
        """Reject a task"""
        if not self.rejection_allowed:
            raise ValueError("Rejection not allowed for this workflow")
        
        task = WorkflowTask.objects.get(
            workflow=self._instance,
            task_id=task_id
        )
        
        if task.task_type != 'approval':
            raise ValueError("Task is not an approval task")
        
        # Complete the task with rejection
        output_data = {
            'approved': False,
            'rejected_by': user.id,
            'rejected_at': timezone.now().isoformat(),
            'rejection_reason': reason
        }
        
        task.complete(user=user, output_data=output_data)
        task.save()
        
        # Mark workflow as failed
        self._instance.fail(error_message=f"Rejected by {user.get_full_name()}: {reason}")
        self._instance.save()
    
    def _check_workflow_completion(self):
        """Check if all approval tasks are completed"""
        pending_approvals = WorkflowTask.objects.filter(
            workflow=self._instance,
            task_type='approval',
            status__in=['created', 'assigned', 'started']
        ).exists()
        
        if not pending_approvals:
            # Complete the workflow
            self._instance.complete()
            self._instance.save()


class BaseProcessWorkflow(ModuleWorkflow):
    """
    Base class for process workflows.
    
    Provides common patterns for multi-step processes.
    """
    
    workflow_type = "sequential"
    
    # Process configuration
    process_steps = []  # List of (step_id, step_name, step_type) tuples
    allow_skip = False  # Whether steps can be skipped
    parallel_execution = False  # Whether steps can run in parallel
    
    def _create_initial_tasks(self):
        """Create process tasks"""
        if not self.process_steps:
            raise ValueError("No process steps defined")
        
        previous_task = None
        parallel_tasks = []
        
        for step_id, step_name, step_type in self.process_steps:
            task = self.create_task(
                task_id=step_id,
                name=step_name,
                task_type=step_type or 'user'
            )
            
            if self.parallel_execution:
                parallel_tasks.append(task)
            else:
                if previous_task:
                    self.create_transition(
                        from_task=previous_task,
                        to_task=task,
                        transition_type='sequence'
                    )
                previous_task = task
        
        # If parallel execution, create merge task
        if self.parallel_execution and parallel_tasks:
            merge_task = self.create_task(
                task_id='merge',
                name='Merge Results',
                task_type='system',
                description='Merge results from parallel tasks'
            )
            
            for task in parallel_tasks:
                self.create_transition(
                    from_task=task,
                    to_task=merge_task,
                    transition_type='merge'
                )
    
    def skip_step(self, step_id, user, reason=None):
        """Skip a process step"""
        if not self.allow_skip:
            raise ValueError("Step skipping not allowed")
        
        task = WorkflowTask.objects.get(
            workflow=self._instance,
            task_id=step_id
        )
        
        task.skip(reason=reason)
        task.save()
        
        # Move to next task
        self._activate_next_tasks(task)
    
    def _activate_next_tasks(self, completed_task):
        """Activate tasks that depend on the completed task"""
        transitions = WorkflowTransition.objects.filter(
            from_task=completed_task
        )
        
        for transition in transitions:
            next_task = transition.to_task
            if next_task.can_start():
                next_task.status = 'assigned'
                next_task.save()


class BaseAutomatedWorkflow(ModuleWorkflow):
    """
    Base class for automated workflows.
    
    Provides patterns for fully automated processes.
    """
    
    workflow_type = "automated"
    
    # Automation configuration
    retry_on_failure = True
    max_retries = 3
    retry_delay = 60  # seconds
    
    def execute(self):
        """Execute the automated workflow"""
        try:
            # Start workflow
            self._instance.status = 'active'
            self._instance.save()
            
            # Execute automation logic
            result = self._execute_automation()
            
            # Update context with results
            self.update_context({'result': result})
            
            # Complete workflow
            self._instance.complete()
            self._instance.save()
            
            return result
            
        except Exception as e:
            logger.error(f"Automated workflow failed: {e}")
            
            if self.retry_on_failure and self._instance.retry_count < self.max_retries:
                # Schedule retry
                self._instance.retry_count += 1
                self._instance.save()
                self._schedule_retry()
            else:
                # Mark as failed
                self._instance.fail(error_message=str(e))
                self._instance.save()
            
            raise
    
    def _execute_automation(self):
        """Execute the automation logic (override in subclasses)"""
        raise NotImplementedError("Subclasses must implement _execute_automation")
    
    def _schedule_retry(self):
        """Schedule a retry of the workflow"""
        from celery import current_app
        from .tasks import retry_automated_workflow
        
        current_app.send_task(
            'platform_core.workflows.tasks.retry_automated_workflow',
            args=[self._instance.id],
            countdown=self.retry_delay
        )