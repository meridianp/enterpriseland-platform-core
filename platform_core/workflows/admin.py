"""
Workflow Admin Configuration
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from .models import (
    WorkflowDefinition, WorkflowInstance, WorkflowTask,
    WorkflowTransition, WorkflowTemplate
)


@admin.register(WorkflowDefinition)
class WorkflowDefinitionAdmin(admin.ModelAdmin):
    list_display = [
        'workflow_id', 'name', 'version', 'workflow_type',
        'module_link', 'is_active', 'times_used', 'last_used_at'
    ]
    list_filter = ['workflow_type', 'is_active', 'is_template', 'created_at']
    search_fields = ['workflow_id', 'name', 'description']
    readonly_fields = [
        'times_used', 'last_used_at', 'created_at', 'updated_at'
    ]
    
    fieldsets = (
        (None, {
            'fields': (
                'workflow_id', 'name', 'description', 'version',
                'workflow_type', 'module', 'flow_class'
            )
        }),
        ('Configuration', {
            'fields': (
                'config_schema', 'default_config', 'tags'
            )
        }),
        ('Permissions', {
            'fields': (
                'start_permission', 'view_permission'
            )
        }),
        ('Status', {
            'fields': (
                'is_active', 'is_template', 'times_used', 'last_used_at'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def module_link(self, obj):
        if obj.module:
            url = reverse('admin:modules_modulemanifest_change', args=[obj.module.id])
            return format_html('<a href="{}">{}</a>', url, obj.module.name)
        return '-'
    module_link.short_description = 'Module'


@admin.register(WorkflowInstance)
class WorkflowInstanceAdmin(admin.ModelAdmin):
    list_display = [
        'instance_id', 'title', 'definition_link', 'status',
        'started_by', 'progress_bar', 'started_at', 'completed_at'
    ]
    list_filter = ['status', 'created_at', 'definition']
    search_fields = ['instance_id', 'title', 'started_by__username']
    readonly_fields = [
        'instance_id', 'task_count', 'completed_task_count',
        'execution_time', 'created_at', 'updated_at'
    ]
    raw_id_fields = ['started_by', 'current_assignee', 'parent_workflow']
    filter_horizontal = ['participants']
    
    fieldsets = (
        (None, {
            'fields': (
                'instance_id', 'title', 'definition', 'status'
            )
        }),
        ('Assignment', {
            'fields': (
                'started_by', 'current_assignee', 'participants'
            )
        }),
        ('Dates', {
            'fields': (
                'started_at', 'completed_at', 'due_date', 'execution_time'
            )
        }),
        ('Data', {
            'fields': (
                'context_data', 'configuration'
            ),
            'classes': ('collapse',)
        }),
        ('Progress', {
            'fields': (
                'task_count', 'completed_task_count'
            )
        }),
        ('Error Information', {
            'fields': (
                'error_message', 'error_details', 'retry_count'
            ),
            'classes': ('collapse',)
        }),
        ('Relationships', {
            'fields': (
                'parent_workflow', 'related_object_type', 'related_object_id'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def definition_link(self, obj):
        url = reverse('admin:workflows_workflowdefinition_change', args=[obj.definition.id])
        return format_html('<a href="{}">{}</a>', url, obj.definition.name)
    definition_link.short_description = 'Definition'
    
    def progress_bar(self, obj):
        percentage = obj.get_progress_percentage()
        return format_html(
            '<div style="width: 100px; background-color: #f0f0f0; border: 1px solid #ccc;">'
            '<div style="width: {}px; background-color: #4CAF50; height: 20px;"></div>'
            '</div> {}%',
            percentage, percentage
        )
    progress_bar.short_description = 'Progress'


@admin.register(WorkflowTask)
class WorkflowTaskAdmin(admin.ModelAdmin):
    list_display = [
        'task_id', 'name', 'workflow_link', 'task_type', 'status',
        'assigned_to', 'priority', 'is_overdue', 'created_at'
    ]
    list_filter = ['task_type', 'status', 'priority', 'created_at']
    search_fields = ['task_id', 'name', 'assigned_to__username']
    readonly_fields = [
        'started_at', 'completed_at', 'execution_time',
        'completed_by', 'created_at', 'updated_at'
    ]
    raw_id_fields = ['workflow', 'assigned_to', 'completed_by']
    filter_horizontal = ['depends_on']
    
    fieldsets = (
        (None, {
            'fields': (
                'workflow', 'task_id', 'name', 'description',
                'task_type', 'status'
            )
        }),
        ('Assignment', {
            'fields': (
                'assigned_to', 'assigned_role', 'completed_by'
            )
        }),
        ('Timing', {
            'fields': (
                'due_date', 'started_at', 'completed_at', 'execution_time'
            )
        }),
        ('Data', {
            'fields': (
                'input_data', 'output_data', 'form_data'
            ),
            'classes': ('collapse',)
        }),
        ('Execution', {
            'fields': (
                'priority', 'sequence_order', 'depends_on',
                'error_message', 'retry_count', 'max_retries'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def workflow_link(self, obj):
        url = reverse('admin:workflows_workflowinstance_change', args=[obj.workflow.id])
        return format_html('<a href="{}">{}</a>', url, obj.workflow.title)
    workflow_link.short_description = 'Workflow'


@admin.register(WorkflowTransition)
class WorkflowTransitionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'workflow_link', 'from_task', 'to_task',
        'transition_type', 'executed_at', 'executed_by'
    ]
    list_filter = ['transition_type', 'created_at']
    search_fields = ['workflow__instance_id', 'condition']
    readonly_fields = ['executed_at', 'executed_by', 'created_at']
    raw_id_fields = ['workflow', 'from_task', 'to_task', 'executed_by']
    
    def workflow_link(self, obj):
        url = reverse('admin:workflows_workflowinstance_change', args=[obj.workflow.id])
        return format_html('<a href="{}">{}</a>', url, obj.workflow.instance_id)
    workflow_link.short_description = 'Workflow'


@admin.register(WorkflowTemplate)
class WorkflowTemplateAdmin(admin.ModelAdmin):
    list_display = [
        'template_id', 'name', 'category', 'definition_link',
        'is_featured', 'is_active', 'times_used'
    ]
    list_filter = ['category', 'is_featured', 'is_active', 'created_at']
    search_fields = ['template_id', 'name', 'description']
    readonly_fields = ['times_used', 'created_at', 'updated_at']
    raw_id_fields = ['definition']
    
    fieldsets = (
        (None, {
            'fields': (
                'template_id', 'name', 'description', 'category',
                'definition'
            )
        }),
        ('Customization', {
            'fields': (
                'customizable_fields', 'default_values'
            )
        }),
        ('Display', {
            'fields': (
                'preview_image', 'estimated_duration',
                'is_featured', 'is_active'
            )
        }),
        ('Usage', {
            'fields': ('times_used',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def definition_link(self, obj):
        url = reverse('admin:workflows_workflowdefinition_change', args=[obj.definition.id])
        return format_html('<a href="{}">{}</a>', url, obj.definition.name)
    definition_link.short_description = 'Definition'