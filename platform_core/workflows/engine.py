"""
Workflow Engine

Core workflow engine that manages workflow execution and integrates with modules.
"""

import logging
import importlib
from typing import Dict, List, Optional, Type, Any
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import (
    WorkflowDefinition, WorkflowInstance, WorkflowTask,
    WorkflowTransition, WorkflowTemplate
)
from .base import ModuleWorkflow
from .exceptions import (
    WorkflowError, WorkflowNotFoundError, WorkflowPermissionError,
    WorkflowExecutionError
)


logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Central workflow engine that manages workflow lifecycle.
    """
    
    def __init__(self):
        self._workflow_registry = {}
        self._loaded_definitions = {}
        self._template_cache = {}
    
    def register_workflow(self, workflow_class: Type[ModuleWorkflow]):
        """Register a workflow class"""
        if not workflow_class.workflow_id:
            raise ValueError("Workflow must have a workflow_id")
        
        self._workflow_registry[workflow_class.workflow_id] = workflow_class
        logger.info(f"Registered workflow: {workflow_class.workflow_id}")
    
    def unregister_workflow(self, workflow_id: str):
        """Unregister a workflow"""
        if workflow_id in self._workflow_registry:
            del self._workflow_registry[workflow_id]
            logger.info(f"Unregistered workflow: {workflow_id}")
    
    def get_workflow_class(self, workflow_id: str) -> Type[ModuleWorkflow]:
        """Get a workflow class by ID"""
        # Check registry first
        if workflow_id in self._workflow_registry:
            return self._workflow_registry[workflow_id]
        
        # Try to load from definition
        try:
            definition = WorkflowDefinition.objects.get(workflow_id=workflow_id)
            return self._load_workflow_class(definition)
        except WorkflowDefinition.DoesNotExist:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
    
    def _load_workflow_class(self, definition: WorkflowDefinition) -> Type[ModuleWorkflow]:
        """Load a workflow class from its definition"""
        if definition.workflow_id in self._loaded_definitions:
            return self._loaded_definitions[definition.workflow_id]
        
        try:
            # Parse module and class name
            module_path, class_name = definition.flow_class.rsplit('.', 1)
            
            # Import module
            module = importlib.import_module(module_path)
            
            # Get class
            workflow_class = getattr(module, class_name)
            
            # Validate it's a workflow
            if not issubclass(workflow_class, ModuleWorkflow):
                raise ValueError(f"{definition.flow_class} is not a ModuleWorkflow")
            
            # Cache it
            self._loaded_definitions[definition.workflow_id] = workflow_class
            
            return workflow_class
            
        except Exception as e:
            logger.error(f"Failed to load workflow {definition.workflow_id}: {e}")
            raise WorkflowError(f"Failed to load workflow: {e}")
    
    def list_available_workflows(self, user, module_id=None) -> List[WorkflowDefinition]:
        """List workflows available to a user"""
        queryset = WorkflowDefinition.objects.filter(
            is_active=True,
            group=user.group
        )
        
        if module_id:
            queryset = queryset.filter(module__module_id=module_id)
        
        # Filter by permissions
        workflows = []
        for definition in queryset:
            if self.can_start_workflow(user, definition):
                workflows.append(definition)
        
        return workflows
    
    def can_start_workflow(self, user, definition: WorkflowDefinition) -> bool:
        """Check if user can start a workflow"""
        if not definition.start_permission:
            return True
        
        return user.has_perm(definition.start_permission)
    
    def can_view_workflow(self, user, definition: WorkflowDefinition) -> bool:
        """Check if user can view a workflow"""
        if not definition.view_permission:
            return True
        
        return user.has_perm(definition.view_permission)
    
    def start_workflow(self, workflow_id: str, user, title=None, **context) -> WorkflowInstance:
        """
        Start a new workflow instance.
        
        Args:
            workflow_id: Workflow identifier
            user: User starting the workflow
            title: Optional instance title
            **context: Initial context data
        
        Returns:
            WorkflowInstance
        """
        # Get workflow definition
        try:
            definition = WorkflowDefinition.objects.get(
                workflow_id=workflow_id,
                is_active=True
            )
        except WorkflowDefinition.DoesNotExist:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
        
        # Check permissions
        if not self.can_start_workflow(user, definition):
            raise WorkflowPermissionError("User cannot start this workflow")
        
        # Get workflow class
        workflow_class = self.get_workflow_class(workflow_id)
        
        # Create workflow instance
        workflow = workflow_class()
        
        with transaction.atomic():
            instance = workflow.start_workflow(user, title=title, **context)
            
            # Log workflow start
            logger.info(
                f"Started workflow {workflow_id} - Instance: {instance.instance_id}",
                extra={
                    'workflow_id': workflow_id,
                    'instance_id': instance.instance_id,
                    'user_id': user.id
                }
            )
            
            return instance
    
    def get_workflow_instance(self, instance_id: str, user=None) -> WorkflowInstance:
        """Get a workflow instance"""
        try:
            instance = WorkflowInstance.objects.select_related(
                'definition', 'started_by'
            ).get(instance_id=instance_id)
        except WorkflowInstance.DoesNotExist:
            raise WorkflowNotFoundError(f"Workflow instance {instance_id} not found")
        
        # Check permissions
        if user and not self.can_view_instance(user, instance):
            raise WorkflowPermissionError("User cannot view this workflow")
        
        return instance
    
    def can_view_instance(self, user, instance: WorkflowInstance) -> bool:
        """Check if user can view a workflow instance"""
        # User can view if they started it, are assigned, or are a participant
        if (user == instance.started_by or 
            user == instance.current_assignee or
            instance.participants.filter(id=user.id).exists()):
            return True
        
        # Check view permission
        return self.can_view_workflow(user, instance.definition)
    
    def get_user_tasks(self, user, status=None, workflow_id=None) -> List[WorkflowTask]:
        """Get tasks assigned to a user"""
        queryset = WorkflowTask.objects.filter(
            assigned_to=user
        ).select_related('workflow', 'workflow__definition')
        
        if status:
            if isinstance(status, list):
                queryset = queryset.filter(status__in=status)
            else:
                queryset = queryset.filter(status=status)
        
        if workflow_id:
            queryset = queryset.filter(workflow__definition__workflow_id=workflow_id)
        
        return list(queryset.order_by('-created_at'))
    
    def execute_task(self, task_id: str, user, action: str, data: Dict = None):
        """
        Execute an action on a task.
        
        Args:
            task_id: Task ID
            user: User executing the action
            action: Action to perform (start, complete, fail, skip)
            data: Optional action data
        
        Returns:
            Updated WorkflowTask
        """
        try:
            task = WorkflowTask.objects.select_related(
                'workflow', 'workflow__definition'
            ).get(id=task_id)
        except WorkflowTask.DoesNotExist:
            raise WorkflowNotFoundError(f"Task {task_id} not found")
        
        # Check permissions
        if not self._can_execute_task(user, task):
            raise WorkflowPermissionError("User cannot execute this task")
        
        # Execute action
        with transaction.atomic():
            if action == 'start':
                task.start(user=user)
            elif action == 'complete':
                task.complete(user=user, output_data=data)
                self._handle_task_completion(task)
            elif action == 'fail':
                error_message = data.get('error_message') if data else None
                task.fail(error_message=error_message)
            elif action == 'skip':
                reason = data.get('reason') if data else None
                task.skip(reason=reason)
                self._handle_task_completion(task)
            else:
                raise ValueError(f"Invalid action: {action}")
            
            task.save()
            
            logger.info(
                f"Executed task action - Task: {task_id}, Action: {action}",
                extra={
                    'task_id': task_id,
                    'action': action,
                    'user_id': user.id,
                    'workflow_instance_id': task.workflow.instance_id
                }
            )
            
            return task
    
    def _can_execute_task(self, user, task: WorkflowTask) -> bool:
        """Check if user can execute a task"""
        # User can execute if assigned or has workflow permission
        if task.assigned_to == user:
            return True
        
        # Check role-based assignment
        if task.assigned_role and user.groups.filter(name=task.assigned_role).exists():
            return True
        
        # Check workflow permission
        return self.can_view_instance(user, task.workflow)
    
    def _handle_task_completion(self, task: WorkflowTask):
        """Handle task completion and activate next tasks"""
        # Find transitions from this task
        transitions = WorkflowTransition.objects.filter(
            from_task=task
        ).select_related('to_task')
        
        for transition in transitions:
            # Check if transition condition is met
            if self._evaluate_transition_condition(transition, task):
                # Mark transition as executed
                transition.executed_at = timezone.now()
                transition.executed_by = task.completed_by
                transition.save()
                
                # Check if target task can start
                target_task = transition.to_task
                if target_task.can_start():
                    # Activate the task
                    target_task.status = 'assigned'
                    target_task.save()
                    
                    # Auto-start system tasks
                    if target_task.task_type == 'system':
                        self._execute_system_task(target_task)
        
        # Check if workflow is complete
        self._check_workflow_completion(task.workflow)
    
    def _evaluate_transition_condition(self, transition: WorkflowTransition, 
                                     task: WorkflowTask) -> bool:
        """Evaluate a transition condition"""
        if not transition.condition:
            return True
        
        # Simple condition evaluation
        # In production, use a proper expression evaluator
        try:
            context = {
                'task': task,
                'workflow': task.workflow,
                'output': task.output_data
            }
            
            # WARNING: eval is dangerous! Use a safe evaluator in production
            # This is just for demonstration
            return eval(transition.condition, {"__builtins__": {}}, context)
        except Exception as e:
            logger.error(f"Failed to evaluate condition: {e}")
            return False
    
    def _execute_system_task(self, task: WorkflowTask):
        """Execute a system task automatically"""
        try:
            # Get workflow class
            workflow_class = self.get_workflow_class(
                task.workflow.definition.workflow_id
            )
            
            # Check if workflow has a handler for this task
            handler_name = f"_handle_{task.task_id}"
            if hasattr(workflow_class, handler_name):
                handler = getattr(workflow_class, handler_name)
                result = handler(task)
                
                # Complete the task
                task.complete(output_data={'result': result})
                task.save()
            else:
                # Default system task completion
                task.complete()
                task.save()
                
        except Exception as e:
            logger.error(f"System task execution failed: {e}")
            task.fail(error_message=str(e))
            task.save()
    
    def _check_workflow_completion(self, workflow: WorkflowInstance):
        """Check if workflow is complete"""
        # Check if all tasks are complete
        pending_tasks = WorkflowTask.objects.filter(
            workflow=workflow,
            status__in=['created', 'assigned', 'started']
        ).exists()
        
        if not pending_tasks:
            # Check if any tasks failed
            failed_tasks = WorkflowTask.objects.filter(
                workflow=workflow,
                status='failed'
            ).exists()
            
            if failed_tasks:
                workflow.fail(error_message="One or more tasks failed")
            else:
                workflow.complete()
            
            workflow.save()
    
    # Template Management
    
    def list_templates(self, category=None) -> List[WorkflowTemplate]:
        """List available workflow templates"""
        queryset = WorkflowTemplate.objects.filter(
            is_active=True
        ).select_related('definition')
        
        if category:
            queryset = queryset.filter(category=category)
        
        return list(queryset)
    
    def create_from_template(self, template_id: str, user, title: str, 
                           **customizations) -> WorkflowInstance:
        """Create a workflow instance from a template"""
        try:
            template = WorkflowTemplate.objects.select_related(
                'definition'
            ).get(template_id=template_id, is_active=True)
        except WorkflowTemplate.DoesNotExist:
            raise WorkflowNotFoundError(f"Template {template_id} not found")
        
        # Check permissions
        if not self.can_start_workflow(user, template.definition):
            raise WorkflowPermissionError("User cannot start this workflow")
        
        # Create instance from template
        instance = template.create_instance(
            title=title,
            user=user,
            **customizations
        )
        
        # Get workflow class and initialize
        workflow_class = self.get_workflow_class(
            template.definition.workflow_id
        )
        workflow = workflow_class()
        workflow._instance = instance
        workflow._definition = template.definition
        
        # Create initial tasks
        workflow._create_initial_tasks()
        
        # Start the workflow
        instance.start(user)
        instance.save()
        
        return instance


# Global workflow engine instance
workflow_engine = WorkflowEngine()