"""Serializers for the reporting module."""

from rest_framework import serializers
from django.contrib.auth import get_user_model

from ..models import (
    Report, ReportTemplate, ReportSchedule, ReportExecution, ReportExport,
    Dashboard, Widget, DashboardLayout,
    DataSource, DataSourceConnection, QueryDefinition,
    Visualization, VisualizationType, ChartConfiguration,
    Metric, MetricCalculation, Alert, AlertCondition,
    ReportShare, DashboardShare,
    DataTransformation, TransformationStep, DataPipeline,
)

User = get_user_model()


class ReportTemplateSerializer(serializers.ModelSerializer):
    """Serializer for report templates."""
    
    class Meta:
        model = ReportTemplate
        fields = [
            'id', 'name', 'description', 'category', 'template_config',
            'is_active', 'is_system', 'preview_image', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'is_system', 'created_at', 'updated_at']


class ReportSerializer(serializers.ModelSerializer):
    """Basic report serializer."""
    
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True)
    data_source_count = serializers.IntegerField(source='data_sources.count', read_only=True)
    visualization_count = serializers.IntegerField(source='visualizations.count', read_only=True)
    metric_count = serializers.IntegerField(source='metrics.count', read_only=True)
    
    class Meta:
        model = Report
        fields = [
            'id', 'name', 'description', 'type', 'status', 'template', 'template_name',
            'owner', 'owner_name', 'tags', 'version', 'is_favorite', 'is_public',
            'data_source_count', 'visualization_count', 'metric_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'version', 'created_at', 'updated_at']


class ReportDetailSerializer(ReportSerializer):
    """Detailed report serializer with relationships."""
    
    data_sources = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=DataSource.objects.all(),
        required=False
    )
    visualizations = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Visualization.objects.all(),
        required=False
    )
    metrics = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Metric.objects.all(),
        required=False
    )
    collaborators = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=User.objects.all(),
        required=False
    )
    
    class Meta(ReportSerializer.Meta):
        fields = ReportSerializer.Meta.fields + [
            'configuration', 'queries', 'data_sources', 'visualizations',
            'metrics', 'collaborators', 'cache_duration', 'enable_real_time'
        ]


class DashboardSerializer(serializers.ModelSerializer):
    """Basic dashboard serializer."""
    
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    widget_count = serializers.IntegerField(source='widgets.count', read_only=True)
    
    class Meta:
        model = Dashboard
        fields = [
            'id', 'name', 'description', 'slug', 'layout_type', 'theme',
            'is_public', 'is_default', 'auto_refresh', 'refresh_interval',
            'tags', 'icon', 'owner', 'owner_name', 'widget_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at']


class DashboardDetailSerializer(DashboardSerializer):
    """Detailed dashboard serializer with configuration."""
    
    collaborators = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=User.objects.all(),
        required=False
    )
    
    class Meta(DashboardSerializer.Meta):
        fields = DashboardSerializer.Meta.fields + [
            'configuration', 'collaborators', 'cache_widgets', 'lazy_load'
        ]


class WidgetSerializer(serializers.ModelSerializer):
    """Widget serializer."""
    
    data_source_name = serializers.CharField(source='data_source.name', read_only=True)
    visualization_name = serializers.CharField(source='visualization.name', read_only=True)
    metric_name = serializers.CharField(source='metric.display_name', read_only=True)
    
    class Meta:
        model = Widget
        fields = [
            'id', 'dashboard', 'name', 'type', 'size', 'position',
            'row', 'column', 'width', 'height', 'data_source', 'data_source_name',
            'query', 'visualization', 'visualization_name', 'metric', 'metric_name',
            'configuration', 'style', 'is_interactive', 'drill_down_enabled',
            'export_enabled', 'cache_duration', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class DataSourceSerializer(serializers.ModelSerializer):
    """Data source serializer."""
    
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    connection_string = serializers.SerializerMethodField()
    
    class Meta:
        model = DataSource
        fields = [
            'id', 'name', 'description', 'type', 'status', 'host', 'port',
            'database', 'schema', 'username', 'connection_options', 'ssl_enabled',
            'timeout', 'max_rows', 'tags', 'test_query', 'owner', 'owner_name',
            'enable_caching', 'cache_duration', 'last_tested', 'is_healthy',
            'connection_string', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'last_tested', 'is_healthy', 'created_at', 'updated_at']
        extra_kwargs = {
            'password': {'write_only': True},
            'api_key': {'write_only': True},
        }
    
    def get_connection_string(self, obj):
        """Get masked connection string."""
        return obj.get_connection_string()


class QueryDefinitionSerializer(serializers.ModelSerializer):
    """Query definition serializer."""
    
    data_source_name = serializers.CharField(source='data_source.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        model = QueryDefinition
        fields = [
            'id', 'data_source', 'data_source_name', 'name', 'description',
            'type', 'query', 'parameters', 'transformations', 'tags',
            'is_template', 'estimated_duration', 'estimated_rows',
            'usage_count', 'last_used', 'created_by', 'created_by_name',
            'is_public', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'usage_count', 'last_used', 'created_at', 'updated_at']


class VisualizationTypeSerializer(serializers.ModelSerializer):
    """Visualization type serializer."""
    
    class Meta:
        model = VisualizationType
        fields = [
            'id', 'name', 'display_name', 'category', 'description',
            'icon', 'component_name', 'default_config', 'min_dimensions',
            'max_dimensions', 'min_measures', 'max_measures', 'supports_3d',
            'supports_animation', 'supports_interaction', 'supports_export',
            'is_active', 'order'
        ]
        read_only_fields = ['id']


class VisualizationSerializer(serializers.ModelSerializer):
    """Visualization serializer."""
    
    type_display = serializers.CharField(source='type.display_name', read_only=True)
    data_source_name = serializers.CharField(source='data_source.name', read_only=True)
    query_name = serializers.CharField(source='query.name', read_only=True)
    
    class Meta:
        model = Visualization
        fields = [
            'id', 'name', 'description', 'type', 'type_display',
            'data_source', 'data_source_name', 'query', 'query_name',
            'dimensions', 'measures', 'filters', 'configuration', 'colors',
            'width', 'height', 'responsive', 'interactive', 'drill_down_config',
            'tooltip_config', 'tags', 'is_template', 'created_by', 'is_public',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class MetricSerializer(serializers.ModelSerializer):
    """Metric serializer."""
    
    data_source_name = serializers.CharField(source='data_source.name', read_only=True)
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    current_value = serializers.SerializerMethodField()
    
    class Meta:
        model = Metric
        fields = [
            'id', 'name', 'display_name', 'description', 'type',
            'data_source', 'data_source_name', 'table_name', 'column_name',
            'aggregation', 'formula', 'filters', 'format', 'decimals',
            'prefix', 'suffix', 'target_value', 'min_threshold', 'max_threshold',
            'warning_threshold', 'icon', 'color', 'show_trend', 'show_sparkline',
            'category', 'tags', 'is_key_metric', 'owner', 'owner_name',
            'is_public', 'current_value', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_current_value(self, obj):
        """Get the most recent calculated value."""
        latest = obj.calculations.order_by('-timestamp').first()
        if latest:
            return {
                'value': latest.value,
                'timestamp': latest.timestamp.isoformat(),
                'change_value': latest.change_value,
                'change_percentage': latest.change_percentage,
            }
        return None


class AlertSerializer(serializers.ModelSerializer):
    """Alert serializer."""
    
    metric_name = serializers.CharField(source='metric.display_name', read_only=True)
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    
    class Meta:
        model = Alert
        fields = [
            'id', 'name', 'description', 'status', 'severity', 'metric',
            'metric_name', 'notification_channels', 'recipients',
            'check_interval', 'cooldown_period', 'last_checked', 'last_triggered',
            'trigger_count', 'tags', 'owner', 'owner_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'last_checked', 'last_triggered', 'trigger_count', 'created_at', 'updated_at']


class ReportScheduleSerializer(serializers.ModelSerializer):
    """Report schedule serializer."""
    
    report_name = serializers.CharField(source='report.name', read_only=True)
    
    class Meta:
        model = ReportSchedule
        fields = [
            'id', 'report', 'report_name', 'name', 'is_active', 'frequency',
            'cron_expression', 'start_date', 'end_date', 'timezone',
            'delivery_method', 'delivery_config', 'export_format',
            'last_run', 'next_run', 'run_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'last_run', 'next_run', 'run_count', 'created_at', 'updated_at']


class ReportExecutionSerializer(serializers.ModelSerializer):
    """Report execution serializer."""
    
    report_name = serializers.CharField(source='report.name', read_only=True)
    executed_by_name = serializers.CharField(source='executed_by.get_full_name', read_only=True)
    
    class Meta:
        model = ReportExecution
        fields = [
            'id', 'report', 'report_name', 'schedule', 'status',
            'started_at', 'completed_at', 'duration', 'executed_by',
            'executed_by_name', 'parameters', 'row_count', 'error_message',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ReportExportSerializer(serializers.ModelSerializer):
    """Report export serializer."""
    
    report_name = serializers.CharField(source='report.name', read_only=True)
    exported_by_name = serializers.CharField(source='exported_by.get_full_name', read_only=True)
    
    class Meta:
        model = ReportExport
        fields = [
            'id', 'report', 'report_name', 'execution', 'format', 'status',
            'include_visualizations', 'include_raw_data', 'filters',
            'file_path', 'file_size', 'download_url', 'expires_at',
            'exported_by', 'exported_by_name', 'error_message',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'file_path', 'file_size', 'download_url', 'expires_at',
            'created_at', 'updated_at'
        ]


class ReportShareSerializer(serializers.ModelSerializer):
    """Report share serializer."""
    
    report_name = serializers.CharField(source='report.name', read_only=True)
    shared_by_name = serializers.CharField(source='shared_by.get_full_name', read_only=True)
    share_url = serializers.SerializerMethodField()
    
    class Meta:
        model = ReportShare
        fields = [
            'id', 'report', 'report_name', 'share_type', 'shared_with_user',
            'shared_with_group', 'shared_with_email', 'permission', 'message',
            'allow_export', 'allow_drill_down', 'require_authentication',
            'share_token', 'is_active', 'expires_at', 'access_count',
            'last_accessed', 'shared_by', 'shared_by_name', 'share_url',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'share_token', 'access_count', 'last_accessed',
            'created_at', 'updated_at'
        ]
    
    def get_share_url(self, obj):
        """Generate share URL."""
        if obj.share_type == 'link':
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(f'/share/report/{obj.share_token}/')
        return None


class DashboardShareSerializer(serializers.ModelSerializer):
    """Dashboard share serializer."""
    
    dashboard_name = serializers.CharField(source='dashboard.name', read_only=True)
    shared_by_name = serializers.CharField(source='shared_by.get_full_name', read_only=True)
    share_url = serializers.SerializerMethodField()
    embed_code = serializers.SerializerMethodField()
    
    class Meta:
        model = DashboardShare
        fields = [
            'id', 'dashboard', 'dashboard_name', 'share_type', 'shared_with_user',
            'shared_with_group', 'shared_with_email', 'permission', 'message',
            'allow_export', 'allow_full_screen', 'show_title',
            'require_authentication', 'share_token', 'is_active', 'expires_at',
            'embed_width', 'embed_height', 'embed_theme', 'access_count',
            'last_accessed', 'shared_by', 'shared_by_name', 'share_url',
            'embed_code', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'share_token', 'access_count', 'last_accessed',
            'created_at', 'updated_at'
        ]
    
    def get_share_url(self, obj):
        """Generate share URL."""
        if obj.share_type in ['link', 'embed']:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(f'/share/dashboard/{obj.share_token}/')
        return None
    
    def get_embed_code(self, obj):
        """Get embed code if applicable."""
        if obj.share_type == 'embed':
            return obj.get_embed_code()
        return None