"""
Workflow API Views

Provides REST API endpoints for workflow management.
"""

from django.db.models import Q, Count, Avg, F
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from platform_core.core.views import PlatformViewSet
from .models import (
    WorkflowDefinition, WorkflowInstance, WorkflowTask,
    WorkflowTransition, WorkflowTemplate
)
from .serializers import (
    WorkflowDefinitionSerializer, WorkflowInstanceListSerializer,
    WorkflowInstanceDetailSerializer, WorkflowTaskSerializer,
    WorkflowTransitionSerializer, WorkflowTemplateSerializer,
    StartWorkflowSerializer, ExecuteTaskSerializer,
    CreateFromTemplateSerializer, WorkflowStatisticsSerializer
)
from .engine import workflow_engine
from .exceptions import (
    WorkflowError, WorkflowNotFoundError, WorkflowPermissionError
)


class WorkflowDefinitionViewSet(PlatformViewSet):
    """
    ViewSet for workflow definitions.
    
    Provides endpoints for managing workflow definitions and starting workflows.
    """
    
    queryset = WorkflowDefinition.objects.all()
    serializer_class = WorkflowDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter by user permissions"""
        queryset = super().get_queryset()
        
        # Filter by active status
        if self.action != 'retrieve':
            queryset = queryset.filter(is_active=True)
        
        # Filter by module if specified
        module_id = self.request.query_params.get('module')
        if module_id:
            queryset = queryset.filter(module__module_id=module_id)
        
        # Filter by workflow type
        workflow_type = self.request.query_params.get('type')
        if workflow_type:
            queryset = queryset.filter(workflow_type=workflow_type)
        
        # Filter by tag
        tag = self.request.query_params.get('tag')
        if tag:
            queryset = queryset.filter(tags__contains=[tag])
        
        # Filter by permissions
        available_only = self.request.query_params.get('available', 'false').lower() == 'true'
        if available_only:
            # Only show workflows user can start
            workflow_ids = []
            for definition in queryset:
                if workflow_engine.can_start_workflow(self.request.user, definition):
                    workflow_ids.append(definition.id)
            queryset = queryset.filter(id__in=workflow_ids)
        
        return queryset.order_by('-times_used', 'name')
    
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start a new workflow instance"""
        definition = self.get_object()
        
        # Check permissions
        if not workflow_engine.can_start_workflow(request.user, definition):
            raise PermissionDenied("You do not have permission to start this workflow")
        
        # Validate input
        serializer = StartWorkflowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Start workflow
            instance = workflow_engine.start_workflow(
                workflow_id=definition.workflow_id,
                user=request.user,
                title=serializer.validated_data.get('title'),
                **serializer.validated_data.get('context_data', {})
            )
            
            # Return instance details
            response_serializer = WorkflowInstanceDetailSerializer(
                instance,
                context={'request': request}
            )
            return Response(
                response_serializer.data,
                status=status.HTTP_201_CREATED
            )
            
        except WorkflowError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get workflow statistics"""
        # Get base queryset
        queryset = self.get_queryset()
        
        # Calculate statistics
        stats = {
            'total_definitions': queryset.count(),
            'active_definitions': queryset.filter(is_active=True).count(),
            'by_type': list(
                queryset.values('workflow_type').annotate(
                    count=Count('id')
                ).order_by('-count')
            ),
            'by_module': list(
                queryset.values('module__name').annotate(
                    count=Count('id')
                ).order_by('-count')
            ),
            'most_used': list(
                queryset.order_by('-times_used')[:5].values(
                    'workflow_id', 'name', 'times_used'
                )
            )
        }
        
        return Response(stats)


class WorkflowInstanceViewSet(PlatformViewSet):
    """
    ViewSet for workflow instances.
    
    Provides endpoints for managing workflow instances and their lifecycle.
    """
    
    queryset = WorkflowInstance.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return WorkflowInstanceListSerializer
        return WorkflowInstanceDetailSerializer
    
    def get_queryset(self):
        """Filter by user access"""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter by user involvement
        involvement = self.request.query_params.get('involvement', 'all')
        if involvement == 'started':
            queryset = queryset.filter(started_by=user)
        elif involvement == 'assigned':
            queryset = queryset.filter(current_assignee=user)
        elif involvement == 'participant':
            queryset = queryset.filter(participants=user)
        elif involvement == 'involved':
            queryset = queryset.filter(
                Q(started_by=user) |
                Q(current_assignee=user) |
                Q(participants=user)
            ).distinct()
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            if ',' in status_filter:
                statuses = status_filter.split(',')
                queryset = queryset.filter(status__in=statuses)
            else:
                queryset = queryset.filter(status=status_filter)
        
        # Filter by workflow
        workflow_id = self.request.query_params.get('workflow_id')
        if workflow_id:
            queryset = queryset.filter(definition__workflow_id=workflow_id)
        
        # Filter by date range
        started_after = self.request.query_params.get('started_after')
        started_before = self.request.query_params.get('started_before')
        if started_after:
            queryset = queryset.filter(started_at__gte=started_after)
        if started_before:
            queryset = queryset.filter(started_at__lte=started_before)
        
        # Filter by overdue
        overdue_only = self.request.query_params.get('overdue', 'false').lower() == 'true'
        if overdue_only:
            queryset = queryset.filter(
                due_date__lt=timezone.now(),
                status__in=['created', 'started']
            )
        
        return queryset.select_related(
            'definition', 'started_by'
        ).order_by('-created_at')
    
    def retrieve(self, request, *args, **kwargs):
        """Get instance details with permission check"""
        instance = self.get_object()
        
        # Check permissions
        if not workflow_engine.can_view_instance(request.user, instance):
            raise PermissionDenied("You do not have permission to view this workflow")
        
        return super().retrieve(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a workflow instance"""
        instance = self.get_object()
        
        # Check permissions
        if not instance.can_edit(request.user):
            raise PermissionDenied("You do not have permission to cancel this workflow")
        
        # Check if can be cancelled
        if instance.status not in ['created', 'started']:
            return Response(
                {'error': 'Workflow cannot be cancelled in current state'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Cancel the workflow
        reason = request.data.get('reason', 'Cancelled by user')
        instance.cancel(reason=reason)
        instance.save()
        
        return Response({'status': 'cancelled'})
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Retry a failed workflow"""
        instance = self.get_object()
        
        # Check permissions
        if not instance.can_edit(request.user):
            raise PermissionDenied("You do not have permission to retry this workflow")
        
        # Check if can be retried
        if instance.status != 'failed':
            return Response(
                {'error': 'Only failed workflows can be retried'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Reset and restart
        instance.status = 'started'
        instance.error_message = None
        instance.error_details = None
        instance.retry_count += 1
        instance.save()
        
        return Response({'status': 'retrying'})
    
    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        """Get workflow timeline"""
        instance = self.get_object()
        
        # Check permissions
        if not workflow_engine.can_view_instance(request.user, instance):
            raise PermissionDenied("You do not have permission to view this workflow")
        
        # Build timeline
        timeline = []
        
        # Add instance events
        timeline.append({
            'timestamp': instance.created_at,
            'event': 'created',
            'description': 'Workflow created',
            'user': instance.started_by.get_full_name() if instance.started_by else 'System'
        })
        
        if instance.started_at:
            timeline.append({
                'timestamp': instance.started_at,
                'event': 'started',
                'description': 'Workflow started',
                'user': instance.started_by.get_full_name() if instance.started_by else 'System'
            })
        
        # Add task events
        for task in instance.tasks.all():
            if task.created_at:
                timeline.append({
                    'timestamp': task.created_at,
                    'event': 'task_created',
                    'description': f'Task created: {task.name}',
                    'task_id': task.id,
                    'task_name': task.name
                })
            
            if task.started_at:
                timeline.append({
                    'timestamp': task.started_at,
                    'event': 'task_started',
                    'description': f'Task started: {task.name}',
                    'task_id': task.id,
                    'task_name': task.name,
                    'user': task.assigned_to.get_full_name() if task.assigned_to else 'System'
                })
            
            if task.completed_at:
                timeline.append({
                    'timestamp': task.completed_at,
                    'event': 'task_completed',
                    'description': f'Task completed: {task.name}',
                    'task_id': task.id,
                    'task_name': task.name,
                    'user': task.completed_by.get_full_name() if task.completed_by else 'System'
                })
        
        # Add transitions
        for transition in instance.transitions.filter(executed_at__isnull=False):
            timeline.append({
                'timestamp': transition.executed_at,
                'event': 'transition',
                'description': f'Transition: {transition.from_task.name if transition.from_task else "Start"} → {transition.to_task.name}',
                'from_task': transition.from_task.name if transition.from_task else None,
                'to_task': transition.to_task.name,
                'user': transition.executed_by.get_full_name() if transition.executed_by else 'System'
            })
        
        if instance.completed_at:
            timeline.append({
                'timestamp': instance.completed_at,
                'event': 'completed',
                'description': 'Workflow completed',
                'user': 'System'
            })
        
        # Sort by timestamp
        timeline.sort(key=lambda x: x['timestamp'])
        
        return Response(timeline)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get workflow instance statistics"""
        queryset = self.get_queryset()
        
        # Calculate statistics
        stats = {
            'total_instances': queryset.count(),
            'active_instances': queryset.filter(
                status__in=['created', 'started']
            ).count(),
            'completed_instances': queryset.filter(status='completed').count(),
            'failed_instances': queryset.filter(status='failed').count(),
            'cancelled_instances': queryset.filter(status='cancelled').count(),
            'average_completion_time': queryset.filter(
                status='completed',
                execution_time__isnull=False
            ).aggregate(
                avg_time=Avg('execution_time')
            )['avg_time'],
            'by_status': list(
                queryset.values('status').annotate(
                    count=Count('id')
                ).order_by('status')
            ),
            'by_workflow': list(
                queryset.values(
                    'definition__workflow_id',
                    'definition__name'
                ).annotate(
                    count=Count('id'),
                    avg_time=Avg('execution_time')
                ).order_by('-count')[:10]
            ),
            'overdue_count': queryset.filter(
                due_date__lt=timezone.now(),
                status__in=['created', 'started']
            ).count()
        }
        
        return Response(stats)


class WorkflowTaskViewSet(PlatformViewSet):
    """
    ViewSet for workflow tasks.
    
    Provides endpoints for managing and executing workflow tasks.
    """
    
    queryset = WorkflowTask.objects.all()
    serializer_class = WorkflowTaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter by user access"""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter by assignment
        assignment = self.request.query_params.get('assignment', 'all')
        if assignment == 'mine':
            queryset = queryset.filter(assigned_to=user)
        elif assignment == 'role':
            # Tasks assigned to user's roles
            user_roles = user.groups.values_list('name', flat=True)
            queryset = queryset.filter(assigned_role__in=user_roles)
        elif assignment == 'available':
            # Tasks user can execute
            queryset = queryset.filter(
                Q(assigned_to=user) |
                Q(assigned_role__in=user.groups.values_list('name', flat=True))
            )
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            if ',' in status_filter:
                statuses = status_filter.split(',')
                queryset = queryset.filter(status__in=statuses)
            else:
                queryset = queryset.filter(status=status_filter)
        
        # Filter by workflow
        workflow_instance = self.request.query_params.get('workflow_instance')
        if workflow_instance:
            queryset = queryset.filter(workflow__instance_id=workflow_instance)
        
        # Filter by type
        task_type = self.request.query_params.get('type')
        if task_type:
            queryset = queryset.filter(task_type=task_type)
        
        # Filter by priority
        priority = self.request.query_params.get('priority')
        if priority:
            queryset = queryset.filter(priority=priority)
        
        # Filter by overdue
        overdue_only = self.request.query_params.get('overdue', 'false').lower() == 'true'
        if overdue_only:
            queryset = queryset.filter(
                due_date__lt=timezone.now(),
                status__in=['created', 'assigned', 'started']
            )
        
        return queryset.select_related(
            'workflow', 'workflow__definition',
            'assigned_to', 'completed_by'
        ).prefetch_related('depends_on').order_by('-priority', 'due_date')
    
    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """Execute a task action"""
        task = self.get_object()
        
        # Validate input
        serializer = ExecuteTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Execute action
            updated_task = workflow_engine.execute_task(
                task_id=str(task.id),
                user=request.user,
                action=serializer.validated_data['action'],
                data=serializer.validated_data.get('data')
            )
            
            # Return updated task
            response_serializer = WorkflowTaskSerializer(
                updated_task,
                context={'request': request}
            )
            return Response(response_serializer.data)
            
        except WorkflowPermissionError as e:
            raise PermissionDenied(str(e))
        except WorkflowError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def reassign(self, request, pk=None):
        """Reassign a task to another user"""
        task = self.get_object()
        
        # Check permissions
        if not workflow_engine.can_view_instance(request.user, task.workflow):
            raise PermissionDenied("You do not have permission to reassign this task")
        
        # Get new assignee
        assignee_id = request.data.get('assignee_id')
        if not assignee_id:
            return Response(
                {'error': 'assignee_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            new_assignee = User.objects.get(id=assignee_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Reassign task
        task.assigned_to = new_assignee
        task.save()
        
        # Add to participants
        task.workflow.participants.add(new_assignee)
        
        return Response({'status': 'reassigned'})
    
    @action(detail=True, methods=['post'])
    def add_dependency(self, request, pk=None):
        """Add a dependency to the task"""
        task = self.get_object()
        
        # Check permissions
        if not workflow_engine.can_view_instance(request.user, task.workflow):
            raise PermissionDenied("You do not have permission to modify this task")
        
        # Get dependency task
        dependency_id = request.data.get('dependency_id')
        if not dependency_id:
            return Response(
                {'error': 'dependency_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            dependency = WorkflowTask.objects.get(
                id=dependency_id,
                workflow=task.workflow
            )
        except WorkflowTask.DoesNotExist:
            return Response(
                {'error': 'Dependency task not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check for circular dependencies
        if dependency == task or task in dependency.depends_on.all():
            return Response(
                {'error': 'Circular dependency detected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Add dependency
        task.depends_on.add(dependency)
        
        return Response({'status': 'dependency added'})


class WorkflowTemplateViewSet(PlatformViewSet):
    """
    ViewSet for workflow templates.
    
    Provides endpoints for managing and using workflow templates.
    """
    
    queryset = WorkflowTemplate.objects.all()
    serializer_class = WorkflowTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter templates"""
        queryset = super().get_queryset()
        
        # Only show active templates
        queryset = queryset.filter(is_active=True)
        
        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        # Filter by featured
        featured_only = self.request.query_params.get('featured', 'false').lower() == 'true'
        if featured_only:
            queryset = queryset.filter(is_featured=True)
        
        # Search by name/description
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search)
            )
        
        return queryset.select_related('definition').order_by(
            '-is_featured', '-times_used', 'name'
        )
    
    @action(detail=True, methods=['post'])
    def create_instance(self, request, pk=None):
        """Create a workflow instance from template"""
        template = self.get_object()
        
        # Validate input
        serializer = CreateFromTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Create instance from template
            instance = workflow_engine.create_from_template(
                template_id=template.template_id,
                user=request.user,
                title=serializer.validated_data['title'],
                **serializer.validated_data.get('customizations', {})
            )
            
            # Return instance details
            response_serializer = WorkflowInstanceDetailSerializer(
                instance,
                context={'request': request}
            )
            return Response(
                response_serializer.data,
                status=status.HTTP_201_CREATED
            )
            
        except WorkflowError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def categories(self, request):
        """Get available template categories"""
        categories = WorkflowTemplate.objects.filter(
            is_active=True
        ).values_list(
            'category', flat=True
        ).distinct().order_by('category')
        
        return Response(list(categories))
