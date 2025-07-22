"""API views for the reporting module."""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, Avg
from django.shortcuts import get_object_or_404

from core.permissions import GroupPermission
from ..models import (
    Report, ReportTemplate, ReportSchedule, ReportExecution, ReportExport,
    Dashboard, Widget, DashboardLayout,
    DataSource, DataSourceConnection, QueryDefinition,
    Visualization, VisualizationType, ChartConfiguration,
    Metric, MetricCalculation, Alert, AlertCondition,
    ReportShare, DashboardShare,
)
from ..services import (
    ReportService, DashboardService, DataSourceService,
    AnalyticsService, VisualizationService, ExportService,
)
from .serializers import (
    ReportSerializer, ReportDetailSerializer,
    DashboardSerializer, DashboardDetailSerializer,
    WidgetSerializer, DataSourceSerializer,
    VisualizationSerializer, MetricSerializer,
    ReportTemplateSerializer, ReportScheduleSerializer,
    ReportExecutionSerializer, ReportExportSerializer,
    AlertSerializer, QueryDefinitionSerializer,
    ReportShareSerializer, DashboardShareSerializer,
)


class ReportViewSet(viewsets.ModelViewSet):
    """ViewSet for managing reports."""
    
    queryset = Report.objects.all()
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['type', 'status', 'owner', 'is_public', 'is_favorite']
    search_fields = ['name', 'description', 'tags']
    ordering_fields = ['name', 'created_at', 'updated_at', 'version']
    ordering = ['-updated_at']
    
    def get_serializer_class(self):
        if self.action in ['retrieve', 'create', 'update', 'partial_update']:
            return ReportDetailSerializer
        return ReportSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter by access permissions
        queryset = queryset.filter(
            Q(owner=user) |
            Q(collaborators=user) |
            Q(is_public=True) |
            Q(shares__shared_with_user=user, shares__is_active=True)
        ).distinct()
        
        # Prefetch related objects
        queryset = queryset.select_related('owner', 'template').prefetch_related(
            'data_sources', 'visualizations', 'metrics', 'collaborators'
        )
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, group=self.request.user.group)
    
    @action(detail=False, methods=['post'])
    def create_from_template(self, request):
        """Create a report from a template."""
        template_id = request.data.get('template_id')
        if not template_id:
            return Response(
                {'error': 'template_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service = ReportService()
        try:
            report = service.create_from_template(
                template_id=template_id,
                data=request.data,
                user=request.user
            )
            serializer = ReportDetailSerializer(report, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """Execute a report."""
        report = self.get_object()
        parameters = request.data.get('parameters', {})
        
        service = ReportService()
        try:
            data = service.get_report_data(str(report.id), parameters)
            return Response(data)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def export(self, request, pk=None):
        """Export a report."""
        report = self.get_object()
        export_format = request.data.get('format', 'pdf')
        options = request.data.get('options', {})
        
        service = ReportService()
        exporter = service.ReportExporter()
        
        try:
            export = exporter.export(
                report_id=str(report.id),
                format=export_format,
                options=options
            )
            serializer = ReportExportSerializer(export, context={'request': request})
            return Response(serializer.data, status=status.HTTP_202_ACCEPTED)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        """Share a report."""
        report = self.get_object()
        
        # Check if user has permission to share
        if report.owner != request.user and not request.user.has_perm('reporting.can_share_report'):
            return Response(
                {'error': 'You do not have permission to share this report'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = ReportShareSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(report=report, shared_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        """Clone a report."""
        report = self.get_object()
        
        try:
            cloned_report = report.clone(user=request.user)
            serializer = ReportDetailSerializer(cloned_report, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def analytics(self, request, pk=None):
        """Get report analytics."""
        report = self.get_object()
        service = ReportService()
        
        try:
            analytics = service.get_report_analytics(str(report.id))
            return Response(analytics)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a report."""
        report = self.get_object()
        
        if not request.user.has_perm('reporting.can_publish_report'):
            return Response(
                {'error': 'You do not have permission to publish reports'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            report.publish()
            report.save()
            serializer = ReportDetailSerializer(report, context={'request': request})
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class DashboardViewSet(viewsets.ModelViewSet):
    """ViewSet for managing dashboards."""
    
    queryset = Dashboard.objects.all()
    serializer_class = DashboardSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['layout_type', 'theme', 'owner', 'is_public', 'is_default']
    search_fields = ['name', 'description', 'tags']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['name']
    
    def get_serializer_class(self):
        if self.action in ['retrieve', 'create', 'update', 'partial_update']:
            return DashboardDetailSerializer
        return DashboardSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter by access permissions
        queryset = queryset.filter(
            Q(owner=user) |
            Q(collaborators=user) |
            Q(is_public=True) |
            Q(shares__shared_with_user=user, shares__is_active=True)
        ).distinct()
        
        # Prefetch related objects
        queryset = queryset.select_related('owner').prefetch_related(
            'collaborators', 'widgets'
        )
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, group=self.request.user.group)
    
    @action(detail=True, methods=['get'])
    def widgets(self, request, pk=None):
        """Get dashboard widgets."""
        dashboard = self.get_object()
        widgets = dashboard.widgets.all().order_by('position')
        serializer = WidgetSerializer(widgets, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        """Share a dashboard."""
        dashboard = self.get_object()
        
        # Check if user has permission to share
        if dashboard.owner != request.user and not request.user.has_perm('reporting.can_share_dashboard'):
            return Response(
                {'error': 'You do not have permission to share this dashboard'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = DashboardShareSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(dashboard=dashboard, shared_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        """Clone a dashboard."""
        dashboard = self.get_object()
        
        try:
            cloned_dashboard = dashboard.clone(user=request.user)
            serializer = DashboardDetailSerializer(cloned_dashboard, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set dashboard as default."""
        dashboard = self.get_object()
        
        if not request.user.has_perm('reporting.can_set_default_dashboard'):
            return Response(
                {'error': 'You do not have permission to set default dashboards'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Remove default from other dashboards
        Dashboard.objects.filter(is_default=True).update(is_default=False)
        
        # Set this dashboard as default
        dashboard.is_default = True
        dashboard.save()
        
        serializer = DashboardDetailSerializer(dashboard, context={'request': request})
        return Response(serializer.data)


class WidgetViewSet(viewsets.ModelViewSet):
    """ViewSet for managing widgets."""
    
    queryset = Widget.objects.all()
    serializer_class = WidgetSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['dashboard', 'type', 'size']
    ordering_fields = ['position', 'name', 'created_at']
    ordering = ['position']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by dashboard access
        queryset = queryset.filter(
            Q(dashboard__owner=self.request.user) |
            Q(dashboard__collaborators=self.request.user) |
            Q(dashboard__is_public=True)
        ).distinct()
        
        # Prefetch related objects
        queryset = queryset.select_related(
            'dashboard', 'data_source', 'visualization', 'metric'
        )
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(group=self.request.user.group)
    
    @action(detail=True, methods=['post'])
    def refresh(self, request, pk=None):
        """Refresh widget data."""
        widget = self.get_object()
        service = DashboardService()
        
        try:
            data = service.get_widget_data(widget)
            return Response(data)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        """Move widget to new position."""
        widget = self.get_object()
        new_position = request.data.get('position')
        
        if new_position is None:
            return Response(
                {'error': 'position is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service = DashboardService()
        try:
            service.move_widget(widget, new_position)
            serializer = WidgetSerializer(widget, context={'request': request})
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class DataSourceViewSet(viewsets.ModelViewSet):
    """ViewSet for managing data sources."""
    
    queryset = DataSource.objects.all()
    serializer_class = DataSourceSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['type', 'status', 'owner']
    search_fields = ['name', 'description', 'tags']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['name']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter by access permissions
        if not user.has_perm('reporting.can_manage_data_sources'):
            queryset = queryset.filter(
                Q(owner=user) |
                Q(allowed_users=user) |
                Q(allowed_groups__users=user)
            ).distinct()
        
        return queryset.select_related('owner')
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, group=self.request.user.group)
    
    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """Test data source connection."""
        data_source = self.get_object()
        
        if not request.user.has_perm('reporting.can_test_data_source'):
            return Response(
                {'error': 'You do not have permission to test data sources'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        service = DataSourceService()
        result = service.test_connection(str(data_source.id))
        return Response(result)
    
    @action(detail=True, methods=['post'])
    def execute_query(self, request, pk=None):
        """Execute a query against the data source."""
        data_source = self.get_object()
        query = request.data.get('query')
        parameters = request.data.get('parameters', {})
        
        if not query:
            return Response(
                {'error': 'query is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        from ..services import QueryExecutor
        executor = QueryExecutor()
        
        try:
            result = executor.execute(data_source, query, parameters)
            return Response(result)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class VisualizationViewSet(viewsets.ModelViewSet):
    """ViewSet for managing visualizations."""
    
    queryset = Visualization.objects.all()
    serializer_class = VisualizationSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['type', 'is_template', 'is_public', 'created_by']
    search_fields = ['name', 'description', 'tags']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['name']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by access permissions
        queryset = queryset.filter(
            Q(created_by=self.request.user) |
            Q(is_public=True)
        ).distinct()
        
        # Prefetch related objects
        queryset = queryset.select_related(
            'type', 'data_source', 'query', 'created_by'
        )
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, group=self.request.user.group)
    
    @action(detail=False, methods=['get'])
    def types(self, request):
        """Get available visualization types."""
        from .serializers import VisualizationTypeSerializer
        types = VisualizationType.objects.filter(is_active=True).order_by('category', 'order')
        serializer = VisualizationTypeSerializer(types, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        """Preview visualization with sample data."""
        visualization = self.get_object()
        sample_data = request.data.get('sample_data', {})
        
        service = VisualizationService()
        try:
            preview = service.preview(visualization, sample_data)
            return Response(preview)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class MetricViewSet(viewsets.ModelViewSet):
    """ViewSet for managing metrics."""
    
    queryset = Metric.objects.all()
    serializer_class = MetricSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['type', 'category', 'is_key_metric', 'owner']
    search_fields = ['name', 'display_name', 'description', 'tags']
    ordering_fields = ['name', 'category', 'created_at']
    ordering = ['category', 'name']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by access permissions
        queryset = queryset.filter(
            Q(owner=self.request.user) |
            Q(is_public=True)
        ).distinct()
        
        # Prefetch related objects
        queryset = queryset.select_related('data_source', 'owner')
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, group=self.request.user.group)
    
    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        """Calculate metric value."""
        metric = self.get_object()
        parameters = request.data.get('parameters', {})
        
        from ..services import MetricCalculator
        calculator = MetricCalculator()
        
        try:
            result = calculator.calculate(metric, parameters)
            return Response(result)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get metric calculation history."""
        metric = self.get_object()
        
        # Get query parameters
        days = int(request.query_params.get('days', 30))
        period = request.query_params.get('period', 'day')
        
        calculations = metric.calculations.filter(
            timestamp__gte=timezone.now() - timedelta(days=days),
            period=period
        ).order_by('-timestamp')[:100]
        
        data = [
            {
                'timestamp': calc.timestamp.isoformat(),
                'value': calc.value,
                'change_value': calc.change_value,
                'change_percentage': calc.change_percentage,
            }
            for calc in calculations
        ]
        
        return Response(data)


class ReportTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for managing report templates."""
    
    queryset = ReportTemplate.objects.filter(is_active=True)
    serializer_class = ReportTemplateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'is_system']
    search_fields = ['name', 'description']
    ordering_fields = ['category', 'name']
    ordering = ['category', 'name']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Non-admin users can only see active templates
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)
        
        return queryset


class ReportScheduleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing report schedules."""
    
    queryset = ReportSchedule.objects.all()
    serializer_class = ReportScheduleSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['report', 'is_active', 'frequency', 'delivery_method']
    ordering_fields = ['name', 'next_run', 'created_at']
    ordering = ['next_run']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by report access
        queryset = queryset.filter(
            Q(report__owner=self.request.user) |
            Q(report__collaborators=self.request.user)
        ).distinct()
        
        return queryset.select_related('report')
    
    def perform_create(self, serializer):
        serializer.save(group=self.request.user.group)
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a schedule."""
        schedule = self.get_object()
        schedule.is_active = True
        schedule.save()
        
        # Calculate next run time
        from ..services import SchedulingService
        service = SchedulingService()
        service.update_next_run(schedule)
        
        serializer = ReportScheduleSerializer(schedule, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a schedule."""
        schedule = self.get_object()
        schedule.is_active = False
        schedule.save()
        
        serializer = ReportScheduleSerializer(schedule, context={'request': request})
        return Response(serializer.data)


class ReportExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing report executions."""
    
    queryset = ReportExecution.objects.all()
    serializer_class = ReportExecutionSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['report', 'status', 'schedule']
    ordering_fields = ['created_at', 'duration']
    ordering = ['-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by report access
        queryset = queryset.filter(
            Q(report__owner=self.request.user) |
            Q(report__collaborators=self.request.user) |
            Q(executed_by=self.request.user)
        ).distinct()
        
        return queryset.select_related('report', 'schedule', 'executed_by')
    
    @action(detail=True, methods=['get'])
    def result(self, request, pk=None):
        """Get execution result data."""
        execution = self.get_object()
        
        if execution.status == 'completed' and execution.result_data:
            return Response(execution.result_data)
        else:
            return Response(
                {'error': 'No result data available'},
                status=status.HTTP_404_NOT_FOUND
            )


class ReportExportViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing report exports."""
    
    queryset = ReportExport.objects.all()
    serializer_class = ReportExportSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['report', 'format', 'status']
    ordering_fields = ['created_at']
    ordering = ['-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by report access
        queryset = queryset.filter(
            Q(report__owner=self.request.user) |
            Q(report__collaborators=self.request.user) |
            Q(exported_by=self.request.user)
        ).distinct()
        
        return queryset.select_related('report', 'execution', 'exported_by')
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Get download URL for export."""
        export = self.get_object()
        
        if export.status == 'completed' and export.download_url:
            return Response({
                'download_url': export.download_url,
                'expires_at': export.expires_at.isoformat() if export.expires_at else None,
            })
        else:
            return Response(
                {'error': 'Export not ready for download'},
                status=status.HTTP_404_NOT_FOUND
            )


class AlertViewSet(viewsets.ModelViewSet):
    """ViewSet for managing alerts."""
    
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'severity', 'metric']
    search_fields = ['name', 'description', 'tags']
    ordering_fields = ['severity', 'name', 'last_triggered']
    ordering = ['severity', 'name']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by owner
        queryset = queryset.filter(owner=self.request.user)
        
        return queryset.select_related('metric', 'owner').prefetch_related('conditions')
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, group=self.request.user.group)
    
    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        """Acknowledge an alert."""
        alert = self.get_object()
        
        if alert.status == 'triggered':
            alert.status = 'acknowledged'
            alert.save()
        
        serializer = AlertSerializer(alert, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Resolve an alert."""
        alert = self.get_object()
        
        if alert.status in ['triggered', 'acknowledged']:
            alert.status = 'resolved'
            alert.save()
        
        serializer = AlertSerializer(alert, context={'request': request})
        return Response(serializer.data)


class QueryDefinitionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing query definitions."""
    
    queryset = QueryDefinition.objects.all()
    serializer_class = QueryDefinitionSerializer
    permission_classes = [IsAuthenticated, GroupPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['data_source', 'type', 'is_template', 'is_public']
    search_fields = ['name', 'description', 'tags']
    ordering_fields = ['name', 'usage_count', 'last_used']
    ordering = ['name']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by access permissions
        queryset = queryset.filter(
            Q(created_by=self.request.user) |
            Q(is_public=True)
        ).distinct()
        
        return queryset.select_related('data_source', 'created_by')
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, group=self.request.user.group)
    
    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """Execute a query definition."""
        query_def = self.get_object()
        parameters = request.data.get('parameters', {})
        
        from ..services import QueryExecutor
        executor = QueryExecutor()
        
        try:
            result = executor.execute_query_definition(str(query_def.id), parameters)
            return Response(result)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )