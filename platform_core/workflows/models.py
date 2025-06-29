"""
Workflow Models

Provides workflow engine capabilities for the platform using Viewflow.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone
from django_fsm import FSMField, transition
from viewflow import jsonstore
from viewflow.workflow.models import Process as ViewflowProcess, Task as ViewflowTask

from platform_core.core.models import PlatformModel, GroupFilteredModel

User = get_user_model()


class WorkflowDefinition(GroupFilteredModel):
    """
    Defines a workflow template that can be instantiated.
    """
    
    WORKFLOW_TYPES = [
        ('sequential', 'Sequential'),
        ('parallel', 'Parallel'),
        ('conditional', 'Conditional'),
        ('approval', 'Approval'),
        ('automated', 'Automated'),
        ('custom', 'Custom'),
    ]
    
    # Basic Information
    workflow_id = models.CharField(
        max_length=200, 
        unique=True,
        help_text="Unique identifier for the workflow (e.g., com.company.approval)"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    version = models.CharField(max_length=20, default='1.0.0')
    
    # Workflow Configuration
    workflow_type = models.CharField(
        max_length=50,
        choices=WORKFLOW_TYPES,
        default='sequential'
    )
    flow_class = models.CharField(
        max_length=200,
        help_text="Python path to the flow class"
    )
    
    # Module Integration
    module = models.ForeignKey(
        'modules.ModuleManifest',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='workflows',
        help_text="Module that provides this workflow"
    )
    
    # Configuration
    config_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON schema for workflow configuration"
    )
    default_config = models.JSONField(
        default=dict,
        blank=True
    )
    
    # Permissions
    start_permission = models.CharField(
        max_length=200,
        blank=True,
        help_text="Permission required to start this workflow"
    )
    view_permission = models.CharField(
        max_length=200,
        blank=True,
        help_text="Permission required to view this workflow"
    )
    
    # Metadata
    tags = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True
    )
    is_active = models.BooleanField(default=True)
    is_template = models.BooleanField(
        default=False,
        help_text="If true, this is a template that can be customized"
    )
    
    # Usage Tracking
    times_used = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Workflow Definition'
        verbose_name_plural = 'Workflow Definitions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workflow_id']),
            models.Index(fields=['module', 'is_active']),
            models.Index(fields=['workflow_type', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.version})"
    
    def increment_usage(self):
        """Increment usage counter"""
        self.times_used += 1
        self.last_used_at = timezone.now()
        self.save(update_fields=['times_used', 'last_used_at'])


class WorkflowInstance(GroupFilteredModel):
    """
    An instance of a workflow in execution.
    Extends Viewflow's Process model with additional fields.
    """
    
    # Link to definition
    definition = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.PROTECT,
        related_name='instances'
    )
    
    # Instance Information
    instance_id = models.CharField(
        max_length=200,
        unique=True,
        help_text="Unique instance identifier"
    )
    title = models.CharField(
        max_length=200,
        help_text="Human-readable title for this instance"
    )
    
    # State Management
    status = FSMField(
        default='created',
        choices=[
            ('created', 'Created'),
            ('started', 'Started'),
            ('active', 'Active'),
            ('paused', 'Paused'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ]
    )
    
    # Participants
    started_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='started_workflows'
    )
    current_assignee = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_workflows'
    )
    participants = models.ManyToManyField(
        User,
        related_name='participating_workflows',
        blank=True
    )
    
    # Data Storage
    context_data = models.JSONField(
        default=dict,
        help_text="Workflow context data"
    )
    configuration = models.JSONField(
        default=dict,
        help_text="Workflow configuration overrides"
    )
    
    # Timing
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    
    # Metrics
    execution_time = models.DurationField(null=True, blank=True)
    task_count = models.PositiveIntegerField(default=0)
    completed_task_count = models.PositiveIntegerField(default=0)
    
    # Error Handling
    error_message = models.TextField(blank=True)
    error_details = models.JSONField(default=dict, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    
    # Parent/Child Relationships
    parent_workflow = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='sub_workflows'
    )
    
    # Integration
    related_object_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="Type of related object (e.g., 'assessment', 'deal')"
    )
    related_object_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="ID of related object"
    )
    
    class Meta:
        verbose_name = 'Workflow Instance'
        verbose_name_plural = 'Workflow Instances'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['instance_id']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['definition', 'status']),
            models.Index(fields=['started_by', 'status']),
            models.Index(fields=['due_date', 'status']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.status})"
    
    @transition(field=status, source='created', target='started')
    def start(self, user=None):
        """Start the workflow"""
        self.started_at = timezone.now()
        self.started_by = user
        self.definition.increment_usage()
    
    @transition(field=status, source=['started', 'active'], target='paused')
    def pause(self, reason=None):
        """Pause the workflow"""
        if reason:
            self.context_data['pause_reason'] = reason
    
    @transition(field=status, source='paused', target='active')
    def resume(self):
        """Resume the workflow"""
        self.context_data.pop('pause_reason', None)
    
    @transition(field=status, source=['started', 'active', 'paused'], target='completed')
    def complete(self):
        """Complete the workflow"""
        self.completed_at = timezone.now()
        if self.started_at:
            self.execution_time = self.completed_at - self.started_at
    
    @transition(field=status, source=['started', 'active', 'paused'], target='failed')
    def fail(self, error_message=None, error_details=None):
        """Mark workflow as failed"""
        if error_message:
            self.error_message = error_message
        if error_details:
            self.error_details = error_details
        self.completed_at = timezone.now()
    
    @transition(field=status, source=['started', 'active', 'paused'], target='cancelled')
    def cancel(self, user=None, reason=None):
        """Cancel the workflow"""
        self.completed_at = timezone.now()
        if reason:
            self.context_data['cancel_reason'] = reason
        if user:
            self.context_data['cancelled_by'] = user.id
    
    def can_edit(self, user):
        """Check if user can edit this workflow"""
        return (
            self.status in ['created', 'started', 'active'] and
            (user == self.started_by or user.is_staff)
        )
    
    def get_progress_percentage(self):
        """Calculate progress percentage"""
        if self.task_count == 0:
            return 0
        return int((self.completed_task_count / self.task_count) * 100)


class WorkflowTask(GroupFilteredModel):
    """
    A task within a workflow.
    Extends Viewflow's Task model with additional fields.
    """
    
    TASK_TYPES = [
        ('user', 'User Task'),
        ('system', 'System Task'),
        ('timer', 'Timer Task'),
        ('email', 'Email Task'),
        ('approval', 'Approval Task'),
        ('gateway', 'Gateway'),
        ('subprocess', 'Subprocess'),
    ]
    
    # Link to workflow
    workflow = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.CASCADE,
        related_name='tasks'
    )
    
    # Task Information
    task_id = models.CharField(max_length=200)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    task_type = models.CharField(
        max_length=50,
        choices=TASK_TYPES,
        default='user'
    )
    
    # State Management
    status = FSMField(
        default='created',
        choices=[
            ('created', 'Created'),
            ('assigned', 'Assigned'),
            ('started', 'Started'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
            ('skipped', 'Skipped'),
        ]
    )
    
    # Assignment
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks'
    )
    assigned_role = models.CharField(
        max_length=100,
        blank=True,
        help_text="Role required for this task"
    )
    completed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='completed_tasks'
    )
    
    # Task Data
    input_data = models.JSONField(default=dict)
    output_data = models.JSONField(default=dict)
    form_data = models.JSONField(
        default=dict,
        help_text="Form schema for user tasks"
    )
    
    # Timing
    due_date = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    execution_time = models.DurationField(null=True, blank=True)
    
    # Priority and Order
    priority = models.IntegerField(
        default=0,
        help_text="Higher values = higher priority"
    )
    sequence_order = models.IntegerField(default=0)
    
    # Dependencies
    depends_on = models.ManyToManyField(
        'self',
        symmetrical=False,
        related_name='dependent_tasks',
        blank=True
    )
    
    # Error Handling
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)
    
    class Meta:
        verbose_name = 'Workflow Task'
        verbose_name_plural = 'Workflow Tasks'
        ordering = ['workflow', 'sequence_order', '-priority']
        indexes = [
            models.Index(fields=['workflow', 'status']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['due_date', 'status']),
        ]
        unique_together = [
            ('workflow', 'task_id'),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.workflow.title})"
    
    @transition(field=status, source='created', target='assigned')
    def assign(self, user=None, role=None):
        """Assign the task"""
        if user:
            self.assigned_to = user
        if role:
            self.assigned_role = role
    
    @transition(field=status, source=['created', 'assigned'], target='started')
    def start(self, user=None):
        """Start the task"""
        self.started_at = timezone.now()
        if user and not self.assigned_to:
            self.assigned_to = user
    
    @transition(field=status, source=['started', 'assigned'], target='completed')
    def complete(self, user=None, output_data=None):
        """Complete the task"""
        self.completed_at = timezone.now()
        self.completed_by = user
        if output_data:
            self.output_data = output_data
        if self.started_at:
            self.execution_time = self.completed_at - self.started_at
        
        # Update workflow task count
        self.workflow.completed_task_count += 1
        self.workflow.save(update_fields=['completed_task_count'])
    
    @transition(field=status, source=['started', 'assigned'], target='failed')
    def fail(self, error_message=None):
        """Mark task as failed"""
        if error_message:
            self.error_message = error_message
        self.completed_at = timezone.now()
    
    @transition(field=status, source='*', target='cancelled')
    def cancel(self, reason=None):
        """Cancel the task"""
        if reason:
            self.output_data['cancel_reason'] = reason
        self.completed_at = timezone.now()
    
    @transition(field=status, source=['created', 'assigned'], target='skipped')
    def skip(self, reason=None):
        """Skip the task"""
        if reason:
            self.output_data['skip_reason'] = reason
        self.completed_at = timezone.now()
    
    def can_start(self):
        """Check if all dependencies are met"""
        return not self.depends_on.filter(
            status__in=['created', 'assigned', 'started']
        ).exists()
    
    def is_overdue(self):
        """Check if task is overdue"""
        if self.due_date and self.status not in ['completed', 'cancelled', 'skipped']:
            return timezone.now() > self.due_date
        return False


class WorkflowTransition(PlatformModel):
    """
    Tracks transitions between workflow tasks.
    """
    
    workflow = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.CASCADE,
        related_name='transitions'
    )
    
    from_task = models.ForeignKey(
        WorkflowTask,
        on_delete=models.CASCADE,
        related_name='outgoing_transitions',
        null=True,
        blank=True
    )
    to_task = models.ForeignKey(
        WorkflowTask,
        on_delete=models.CASCADE,
        related_name='incoming_transitions'
    )
    
    # Transition Information
    transition_type = models.CharField(
        max_length=50,
        choices=[
            ('sequence', 'Sequential'),
            ('conditional', 'Conditional'),
            ('parallel', 'Parallel'),
            ('merge', 'Merge'),
        ],
        default='sequence'
    )
    condition = models.TextField(
        blank=True,
        help_text="Condition expression for conditional transitions"
    )
    
    # Execution
    executed_at = models.DateTimeField(null=True, blank=True)
    executed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    class Meta:
        verbose_name = 'Workflow Transition'
        verbose_name_plural = 'Workflow Transitions'
        ordering = ['workflow', 'created_at']
    
    def __str__(self):
        from_name = self.from_task.name if self.from_task else "Start"
        return f"{from_name} → {self.to_task.name}"


class WorkflowTemplate(GroupFilteredModel):
    """
    Pre-built workflow templates that can be instantiated.
    """
    
    TEMPLATE_CATEGORIES = [
        ('approval', 'Approval Process'),
        ('onboarding', 'Onboarding'),
        ('assessment', 'Assessment'),
        ('procurement', 'Procurement'),
        ('hr', 'Human Resources'),
        ('finance', 'Finance'),
        ('it', 'IT Operations'),
        ('custom', 'Custom'),
    ]
    
    # Template Information
    template_id = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(
        max_length=50,
        choices=TEMPLATE_CATEGORIES,
        default='custom'
    )
    
    # Template Definition
    definition = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.CASCADE,
        related_name='templates'
    )
    
    # Customization
    customizable_fields = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text="Fields that can be customized when creating from template"
    )
    default_values = models.JSONField(
        default=dict,
        help_text="Default values for the template"
    )
    
    # Usage
    times_used = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    # Preview
    preview_image = models.ImageField(
        upload_to='workflow_templates/',
        null=True,
        blank=True
    )
    estimated_duration = models.DurationField(
        null=True,
        blank=True,
        help_text="Estimated time to complete workflow"
    )
    
    class Meta:
        verbose_name = 'Workflow Template'
        verbose_name_plural = 'Workflow Templates'
        ordering = ['-is_featured', 'category', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.category})"
    
    def create_instance(self, title, user, **kwargs):
        """Create a workflow instance from this template"""
        # Merge default values with provided kwargs
        context_data = self.default_values.copy()
        context_data.update(kwargs)
        
        # Create instance
        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            instance_id=f"{self.template_id}_{timezone.now().timestamp()}",
            title=title,
            started_by=user,
            context_data=context_data,
            group=user.group
        )
        
        # Increment usage
        self.times_used += 1
        self.save(update_fields=['times_used'])
        
        return instance