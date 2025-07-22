"""URL configuration for the reporting module."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .api.views import (
    ReportViewSet,
    DashboardViewSet,
    WidgetViewSet,
    DataSourceViewSet,
    VisualizationViewSet,
    MetricViewSet,
    ReportTemplateViewSet,
    ReportScheduleViewSet,
    ReportExecutionViewSet,
    ReportExportViewSet,
    AlertViewSet,
    QueryDefinitionViewSet,
)
from .api.analytics_views import (
    AnalyticsOverviewView,
    UsageAnalyticsView,
    PerformanceAnalyticsView,
    QueryBuilderView,
    PublicReportView,
    PublicDashboardView,
    EmbedDashboardView,
    EmbedWidgetView,
)

app_name = 'reporting'

# Create router
router = DefaultRouter()

# Register viewsets
router.register(r'reports', ReportViewSet, basename='report')
router.register(r'dashboards', DashboardViewSet, basename='dashboard')
router.register(r'widgets', WidgetViewSet, basename='widget')
router.register(r'data-sources', DataSourceViewSet, basename='datasource')
router.register(r'visualizations', VisualizationViewSet, basename='visualization')
router.register(r'metrics', MetricViewSet, basename='metric')
router.register(r'templates', ReportTemplateViewSet, basename='template')
router.register(r'schedules', ReportScheduleViewSet, basename='schedule')
router.register(r'executions', ReportExecutionViewSet, basename='execution')
router.register(r'exports', ReportExportViewSet, basename='export')
router.register(r'alerts', AlertViewSet, basename='alert')
router.register(r'queries', QueryDefinitionViewSet, basename='query')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
    
    # Analytics endpoints
    path('analytics/', include([
        path('overview/', AnalyticsOverviewView.as_view(), name='analytics-overview'),
        path('usage/', UsageAnalyticsView.as_view(), name='analytics-usage'),
        path('performance/', PerformanceAnalyticsView.as_view(), name='analytics-performance'),
    ])),
    
    # Query builder endpoint
    path('query-builder/', QueryBuilderView.as_view(), name='query-builder'),
    
    # Share endpoints
    path('share/', include([
        path('report/<uuid:token>/', PublicReportView.as_view(), name='share-report'),
        path('dashboard/<uuid:token>/', PublicDashboardView.as_view(), name='share-dashboard'),
    ])),
    
    # Embed endpoints
    path('embed/', include([
        path('dashboard/<uuid:token>/', EmbedDashboardView.as_view(), name='embed-dashboard'),
        path('widget/<uuid:widget_id>/', EmbedWidgetView.as_view(), name='embed-widget'),
    ])),
]