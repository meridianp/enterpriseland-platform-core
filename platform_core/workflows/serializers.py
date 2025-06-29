"""
Workflow Serializers
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import (
    WorkflowDefinition, WorkflowInstance, WorkflowTask,
    WorkflowTransition, WorkflowTemplate
)

User = get_user_model()


class WorkflowDefinitionSerializer(serializers.ModelSerializer):
    """Serializer for workflow definitions"""
    
    module_name = serializers.CharField(
        source='module.name',
        read_only=True
    )
    can_start = serializers.SerializerMethodField()
    
    class Meta:
        model = WorkflowDefinition
        fields = [
            'id', 'workflow_id', 'name', 'description', 'version',
            'workflow_type', 'module', 'module_name', 'config_schema',
            'default_config', 'start_permission', 'view_permission',
            'tags', 'is_active', 'is_template', 'times_used',
            'last_used_at', 'created_at', 'updated_at', 'can_start'
        ]
        read_only_fields = [
            'id', 'times_used', 'last_used_at', 'created_at', 'updated_at'
        ]
    
    def get_can_start(self, obj):
        """Check if current user can start this workflow"""
        request = self.context.get('request')
        if not request or not request.user:
            return False
        
        if not obj.start_permission:
            return True
        
        return request.user.has_perm(obj.start_permission)


class WorkflowInstanceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for workflow instance lists"""
    
    definition_name = serializers.CharField(
        source='definition.name',
        read_only=True
    )
    started_by_name = serializers.CharField(
        source='started_by.get_full_name',
        read_only=True
    )
    progress = serializers.IntegerField(
        source='get_progress_percentage',
        read_only=True
    )
    
    class Meta:
        model = WorkflowInstance
        fields = [
            'id', 'instance_id', 'title', 'definition', 'definition_name',
            'status', 'started_by', 'started_by_name', 'started_at',
            'completed_at', 'due_date', 'progress', 'task_count',
            'completed_task_count'
        ]
        read_only_fields = fields


class WorkflowInstanceDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for workflow instances"""
    
    definition = WorkflowDefinitionSerializer(read_only=True)
    started_by = serializers.SerializerMethodField()
    current_assignee = serializers.SerializerMethodField()
    participants = serializers.SerializerMethodField()
    tasks = serializers.SerializerMethodField()
    progress = serializers.IntegerField(
        source='get_progress_percentage',
        read_only=True
    )
    can_edit = serializers.SerializerMethodField()
    
    class Meta:
        model = WorkflowInstance
        fields = [
            'id', 'instance_id', 'title', 'definition', 'status',
            'started_by', 'current_assignee', 'participants',
            'context_data', 'configuration', 'started_at',
            'completed_at', 'due_date', 'execution_time',
            'task_count', 'completed_task_count', 'progress',
            'error_message', 'error_details', 'retry_count',
            'parent_workflow', 'sub_workflows', 'related_object_type',
            'related_object_id', 'tasks', 'can_edit', 'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id', 'instance_id', 'started_at', 'completed_at',
            'execution_time', 'task_count', 'completed_task_count',
            'created_at', 'updated_at'
        ]
    
    def get_started_by(self, obj):
        """Get starter user details"""
        if not obj.started_by:
            return None
        
        return {
            'id': obj.started_by.id,
            'username': obj.started_by.username,
            'full_name': obj.started_by.get_full_name(),
            'email': obj.started_by.email
        }
    
    def get_current_assignee(self, obj):
        """Get current assignee details"""
        if not obj.current_assignee:
            return None
        
        return {
            'id': obj.current_assignee.id,
            'username': obj.current_assignee.username,
            'full_name': obj.current_assignee.get_full_name()
        }
    
    def get_participants(self, obj):
        """Get participant list"""
        return obj.participants.values('id', 'username', 'email')
    
    def get_tasks(self, obj):
        """Get workflow tasks"""
        tasks = obj.tasks.all().order_by('sequence_order')
        return WorkflowTaskSerializer(tasks, many=True).data
    
    def get_can_edit(self, obj):
        """Check if current user can edit"""
        request = self.context.get('request')
        if not request or not request.user:
            return False
        
        return obj.can_edit(request.user)


class WorkflowTaskSerializer(serializers.ModelSerializer):
    """Serializer for workflow tasks"""
    
    workflow_title = serializers.CharField(
        source='workflow.title',
        read_only=True
    )
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name',
        read_only=True
    )
    completed_by_name = serializers.CharField(
        source='completed_by.get_full_name',
        read_only=True
    )
    is_overdue = serializers.BooleanField(read_only=True)
    can_start = serializers.BooleanField(read_only=True)
    dependencies = serializers.SerializerMethodField()
    
    class Meta:
        model = WorkflowTask
        fields = [
            'id', 'workflow', 'workflow_title', 'task_id', 'name',
            'description', 'task_type', 'status', 'assigned_to',
            'assigned_to_name', 'assigned_role', 'completed_by',
            'completed_by_name', 'input_data', 'output_data',
            'form_data', 'due_date', 'started_at', 'completed_at',
            'execution_time', 'priority', 'sequence_order',
            'error_message', 'retry_count', 'max_retries',
            'is_overdue', 'can_start', 'dependencies',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'started_at', 'completed_at', 'execution_time',
            'completed_by', 'created_at', 'updated_at'
        ]
    
    def get_dependencies(self, obj):
        """Get task dependencies"""
        deps = obj.depends_on.all()
        return [
            {
                'id': dep.id,
                'task_id': dep.task_id,
                'name': dep.name,
                'status': dep.status
            }
            for dep in deps
        ]


class WorkflowTransitionSerializer(serializers.ModelSerializer):
    """Serializer for workflow transitions"""
    
    from_task_name = serializers.CharField(
        source='from_task.name',
        read_only=True
    )
    to_task_name = serializers.CharField(
        source='to_task.name',
        read_only=True
    )
    executed_by_name = serializers.CharField(
        source='executed_by.get_full_name',
        read_only=True
    )
    
    class Meta:
        model = WorkflowTransition
        fields = [
            'id', 'workflow', 'from_task', 'from_task_name',
            'to_task', 'to_task_name', 'transition_type',
            'condition', 'executed_at', 'executed_by',
            'executed_by_name', 'created_at'
        ]
        read_only_fields = ['id', 'executed_at', 'created_at']


class WorkflowTemplateSerializer(serializers.ModelSerializer):
    """Serializer for workflow templates"""
    
    definition = WorkflowDefinitionSerializer(read_only=True)
    definition_id = serializers.PrimaryKeyRelatedField(
        queryset=WorkflowDefinition.objects.all(),
        source='definition',
        write_only=True
    )
    
    class Meta:
        model = WorkflowTemplate
        fields = [
            'id', 'template_id', 'name', 'description', 'category',
            'definition', 'definition_id', 'customizable_fields',
            'default_values', 'times_used', 'is_featured',
            'is_active', 'preview_image', 'estimated_duration',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'times_used', 'created_at', 'updated_at'
        ]


class StartWorkflowSerializer(serializers.Serializer):
    """Serializer for starting a workflow"""
    
    workflow_id = serializers.CharField()
    title = serializers.CharField(required=False)
    context_data = serializers.JSONField(required=False, default=dict)
    
    def validate_workflow_id(self, value):
        """Validate workflow exists and is active"""
        try:
            WorkflowDefinition.objects.get(
                workflow_id=value,
                is_active=True
            )
        except WorkflowDefinition.DoesNotExist:
            raise serializers.ValidationError(
                f"Workflow {value} not found or inactive"
            )
        return value


class ExecuteTaskSerializer(serializers.Serializer):
    """Serializer for executing task actions"""
    
    action = serializers.ChoiceField(
        choices=['start', 'complete', 'fail', 'skip']
    )
    data = serializers.JSONField(required=False, default=dict)


class CreateFromTemplateSerializer(serializers.Serializer):
    """Serializer for creating workflow from template"""
    
    template_id = serializers.CharField()
    title = serializers.CharField()
    customizations = serializers.JSONField(required=False, default=dict)
    
    def validate_template_id(self, value):
        """Validate template exists and is active"""
        try:
            WorkflowTemplate.objects.get(
                template_id=value,
                is_active=True
            )
        except WorkflowTemplate.DoesNotExist:
            raise serializers.ValidationError(
                f"Template {value} not found or inactive"
            )
        return value


class WorkflowStatisticsSerializer(serializers.Serializer):
    """Serializer for workflow statistics"""
    
    total_definitions = serializers.IntegerField()
    active_definitions = serializers.IntegerField()
    total_instances = serializers.IntegerField()
    active_instances = serializers.IntegerField()
    completed_instances = serializers.IntegerField()
    failed_instances = serializers.IntegerField()
    average_completion_time = serializers.DurationField()
    most_used_workflows = serializers.ListField(
        child=serializers.DictField()
    )
    task_statistics = serializers.DictField()