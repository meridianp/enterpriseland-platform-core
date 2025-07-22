"""Analytics and special views for the reporting module."""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.db.models import Count, Avg, Sum, Q
from django.utils import timezone
from datetime import timedelta

from ..models import Report, Dashboard, ReportExecution, Widget, Metric, DataSource
from ..services import AnalyticsService, QueryBuilder


class AnalyticsOverviewView(APIView):
    """Overview analytics for the reporting module."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get overview analytics."""
        user = request.user
        
        # Get counts
        report_count = Report.objects.filter(
            Q(owner=user) | Q(collaborators=user)
        ).distinct().count()
        
        dashboard_count = Dashboard.objects.filter(
            Q(owner=user) | Q(collaborators=user)
        ).distinct().count()
        
        metric_count = Metric.objects.filter(
            Q(owner=user) | Q(is_public=True)
        ).distinct().count()
        
        data_source_count = DataSource.objects.filter(
            Q(owner=user) | Q(allowed_users=user)
        ).distinct().count()
        
        # Get recent activity
        recent_executions = ReportExecution.objects.filter(
            Q(report__owner=user) | Q(executed_by=user)
        ).order_by('-created_at')[:10]
        
        # Get popular reports
        popular_reports = Report.objects.filter(
            Q(owner=user) | Q(collaborators=user)
        ).annotate(
            execution_count=Count('executions')
        ).order_by('-execution_count')[:5]
        
        # Get key metrics
        key_metrics = Metric.objects.filter(
            is_key_metric=True
        ).filter(
            Q(owner=user) | Q(is_public=True)
        )[:10]
        
        data = {
            'counts': {
                'reports': report_count,
                'dashboards': dashboard_count,
                'metrics': metric_count,
                'data_sources': data_source_count,
            },
            'recent_activity': [
                {
                    'id': str(exec.id),
                    'report_name': exec.report.name,
                    'status': exec.status,
                    'created_at': exec.created_at.isoformat(),
                    'duration': exec.duration,
                }
                for exec in recent_executions
            ],
            'popular_reports': [
                {
                    'id': str(report.id),
                    'name': report.name,
                    'execution_count': report.execution_count,
                }
                for report in popular_reports
            ],
            'key_metrics': [
                {
                    'id': str(metric.id),
                    'name': metric.display_name,
                    'value': self._get_latest_metric_value(metric),
                }
                for metric in key_metrics
            ],
        }
        
        return Response(data)
    
    def _get_latest_metric_value(self, metric):
        """Get latest value for a metric."""
        latest = metric.calculations.order_by('-timestamp').first()
        if latest:
            return {
                'value': latest.value,
                'formatted': self._format_metric_value(metric, latest.value),
                'timestamp': latest.timestamp.isoformat(),
                'trend': {
                    'value': latest.change_value,
                    'percentage': latest.change_percentage,
                }
            }
        return None
    
    def _format_metric_value(self, metric, value):
        """Format metric value based on format type."""
        if metric.format == 'currency':
            return f"{metric.prefix}${value:,.{metric.decimals}f}{metric.suffix}"
        elif metric.format == 'percentage':
            return f"{metric.prefix}{value:.{metric.decimals}f}%{metric.suffix}"
        else:
            return f"{metric.prefix}{value:,.{metric.decimals}f}{metric.suffix}"


class UsageAnalyticsView(APIView):
    """Usage analytics for the reporting module."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get usage analytics."""
        # Get time range from query params
        days = int(request.query_params.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Report executions over time
        executions_by_day = self._get_executions_by_day(start_date, end_date)
        
        # Most active users
        active_users = ReportExecution.objects.filter(
            created_at__gte=start_date,
            executed_by__isnull=False
        ).values('executed_by__username').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        # Export statistics
        export_stats = self._get_export_statistics(start_date, end_date)
        
        # Data source usage
        data_source_usage = self._get_data_source_usage(start_date, end_date)
        
        data = {
            'time_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': days,
            },
            'executions_by_day': executions_by_day,
            'active_users': active_users,
            'export_statistics': export_stats,
            'data_source_usage': data_source_usage,
        }
        
        return Response(data)
    
    def _get_executions_by_day(self, start_date, end_date):
        """Get report executions grouped by day."""
        executions = ReportExecution.objects.filter(
            created_at__range=[start_date, end_date]
        ).extra(
            select={'day': 'date(created_at)'}
        ).values('day').annotate(
            count=Count('id'),
            avg_duration=Avg('duration')
        ).order_by('day')
        
        # Fill in missing days
        result = []
        current_date = start_date.date()
        execution_dict = {e['day']: e for e in executions}
        
        while current_date <= end_date.date():
            if current_date in execution_dict:
                result.append({
                    'date': current_date.isoformat(),
                    'count': execution_dict[current_date]['count'],
                    'avg_duration': execution_dict[current_date]['avg_duration'],
                })
            else:
                result.append({
                    'date': current_date.isoformat(),
                    'count': 0,
                    'avg_duration': 0,
                })
            current_date += timedelta(days=1)
        
        return result
    
    def _get_export_statistics(self, start_date, end_date):
        """Get export statistics."""
        from ..models import ReportExport
        
        exports = ReportExport.objects.filter(
            created_at__range=[start_date, end_date]
        )
        
        by_format = exports.values('format').annotate(
            count=Count('id')
        ).order_by('-count')
        
        by_status = exports.values('status').annotate(
            count=Count('id')
        )
        
        return {
            'total': exports.count(),
            'by_format': list(by_format),
            'by_status': list(by_status),
        }
    
    def _get_data_source_usage(self, start_date, end_date):
        """Get data source usage statistics."""
        from ..models import DataSourceConnection
        
        connections = DataSourceConnection.objects.filter(
            last_used__range=[start_date, end_date]
        ).values(
            'data_source__name',
            'data_source__type'
        ).annotate(
            connection_count=Count('id'),
            query_count=Sum('query_count'),
            total_rows=Sum('total_rows_fetched')
        ).order_by('-query_count')[:10]
        
        return list(connections)


class PerformanceAnalyticsView(APIView):
    """Performance analytics for the reporting module."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get performance analytics."""
        # Get time range
        days = int(request.query_params.get('days', 7))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Query performance
        query_performance = self._get_query_performance(start_date, end_date)
        
        # Report performance
        report_performance = self._get_report_performance(start_date, end_date)
        
        # Cache effectiveness
        cache_stats = self._get_cache_statistics()
        
        # Error rates
        error_rates = self._get_error_rates(start_date, end_date)
        
        data = {
            'time_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': days,
            },
            'query_performance': query_performance,
            'report_performance': report_performance,
            'cache_statistics': cache_stats,
            'error_rates': error_rates,
        }
        
        return Response(data)
    
    def _get_query_performance(self, start_date, end_date):
        """Get query performance metrics."""
        from ..models import DataSourceConnection
        
        connections = DataSourceConnection.objects.filter(
            last_used__range=[start_date, end_date]
        ).aggregate(
            total_queries=Sum('query_count'),
            total_duration=Sum('total_duration'),
            avg_duration=Avg('total_duration')
        )
        
        # Get slowest queries
        slowest_queries = DataSourceConnection.objects.filter(
            last_used__range=[start_date, end_date],
            total_duration__gt=0
        ).order_by('-total_duration')[:10].values(
            'data_source__name',
            'user__username',
            'query_count',
            'total_duration'
        )
        
        return {
            'summary': connections,
            'slowest_queries': list(slowest_queries),
        }
    
    def _get_report_performance(self, start_date, end_date):
        """Get report performance metrics."""
        executions = ReportExecution.objects.filter(
            created_at__range=[start_date, end_date],
            status='completed'
        )
        
        performance = executions.aggregate(
            total_executions=Count('id'),
            avg_duration=Avg('duration'),
            max_duration=Max('duration'),
            total_rows=Sum('row_count')
        )
        
        # Get slowest reports
        slowest_reports = executions.filter(
            duration__isnull=False
        ).order_by('-duration')[:10].values(
            'report__name',
            'duration',
            'row_count',
            'created_at'
        )
        
        return {
            'summary': performance,
            'slowest_reports': list(slowest_reports),
        }
    
    def _get_cache_statistics(self):
        """Get cache effectiveness statistics."""
        # This would integrate with your cache backend
        # For now, return mock data
        return {
            'hit_rate': 0.85,
            'miss_rate': 0.15,
            'total_hits': 12450,
            'total_misses': 2190,
            'cache_size': '245 MB',
        }
    
    def _get_error_rates(self, start_date, end_date):
        """Get error rates for various operations."""
        total_executions = ReportExecution.objects.filter(
            created_at__range=[start_date, end_date]
        ).count()
        
        failed_executions = ReportExecution.objects.filter(
            created_at__range=[start_date, end_date],
            status='failed'
        ).count()
        
        from ..models import ReportExport
        total_exports = ReportExport.objects.filter(
            created_at__range=[start_date, end_date]
        ).count()
        
        failed_exports = ReportExport.objects.filter(
            created_at__range=[start_date, end_date],
            status='failed'
        ).count()
        
        return {
            'execution_error_rate': (failed_executions / total_executions * 100) if total_executions > 0 else 0,
            'export_error_rate': (failed_exports / total_exports * 100) if total_exports > 0 else 0,
            'failed_executions': failed_executions,
            'failed_exports': failed_exports,
        }


class QueryBuilderView(APIView):
    """Interactive query builder endpoint."""
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Build and validate a query."""
        data_source_id = request.data.get('data_source_id')
        query_type = request.data.get('query_type', 'sql')
        query_config = request.data.get('query_config', {})
        
        if not data_source_id:
            return Response(
                {'error': 'data_source_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Get data source
            data_source = DataSource.objects.get(id=data_source_id)
            
            # Check permissions
            if not self._can_access_data_source(request.user, data_source):
                return Response(
                    {'error': 'You do not have access to this data source'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Build query
            builder = QueryBuilder(data_source)
            query = builder.build(query_type, query_config)
            
            # Validate query
            validation = builder.validate(query)
            
            return Response({
                'query': query,
                'validation': validation,
                'estimated_cost': builder.estimate_cost(query),
            })
            
        except DataSource.DoesNotExist:
            return Response(
                {'error': 'Data source not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def _can_access_data_source(self, user, data_source):
        """Check if user can access data source."""
        return (
            data_source.owner == user or
            user in data_source.allowed_users.all() or
            user.groups.filter(id__in=data_source.allowed_groups.all()).exists() or
            user.has_perm('reporting.can_manage_data_sources')
        )


class PublicReportView(APIView):
    """View for publicly shared reports."""
    
    permission_classes = []  # No authentication required
    
    def get(self, request, token):
        """Get shared report."""
        from ..models import ReportShare
        
        try:
            share = ReportShare.objects.get(
                share_token=token,
                is_active=True
            )
            
            # Check if expired
            if share.is_expired():
                return Response(
                    {'error': 'This share link has expired'},
                    status=status.HTTP_410_GONE
                )
            
            # Check authentication requirement
            if share.require_authentication and not request.user.is_authenticated:
                return Response(
                    {'error': 'Authentication required'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Record access
            share.record_access()
            
            # Get report data
            from ..services import ReportService
            service = ReportService()
            
            # Apply any filters from the share
            parameters = request.query_params.dict()
            
            data = service.get_report_data(
                str(share.report.id),
                parameters
            )
            
            # Add share metadata
            data['share'] = {
                'permission': share.permission,
                'allow_export': share.allow_export,
                'allow_drill_down': share.allow_drill_down,
                'message': share.message,
            }
            
            return Response(data)
            
        except ReportShare.DoesNotExist:
            return Response(
                {'error': 'Invalid share link'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PublicDashboardView(APIView):
    """View for publicly shared dashboards."""
    
    permission_classes = []  # No authentication required
    
    def get(self, request, token):
        """Get shared dashboard."""
        from ..models import DashboardShare
        
        try:
            share = DashboardShare.objects.get(
                share_token=token,
                is_active=True
            )
            
            # Check if expired
            if share.is_expired():
                return Response(
                    {'error': 'This share link has expired'},
                    status=status.HTTP_410_GONE
                )
            
            # Check authentication requirement
            if share.require_authentication and not request.user.is_authenticated:
                return Response(
                    {'error': 'Authentication required'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Record access
            share.record_access()
            
            # Get dashboard data
            from ..services import DashboardService
            from .serializers import DashboardDetailSerializer, WidgetSerializer
            
            service = DashboardService()
            dashboard = share.dashboard
            
            # Serialize dashboard
            dashboard_data = DashboardDetailSerializer(
                dashboard,
                context={'request': request}
            ).data
            
            # Get widgets
            widgets = dashboard.widgets.all().order_by('position')
            widgets_data = WidgetSerializer(
                widgets,
                many=True,
                context={'request': request}
            ).data
            
            # Add share metadata
            data = {
                'dashboard': dashboard_data,
                'widgets': widgets_data,
                'share': {
                    'permission': share.permission,
                    'allow_export': share.allow_export,
                    'allow_full_screen': share.allow_full_screen,
                    'show_title': share.show_title,
                    'message': share.message,
                }
            }
            
            return Response(data)
            
        except DashboardShare.DoesNotExist:
            return Response(
                {'error': 'Invalid share link'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class EmbedDashboardView(PublicDashboardView):
    """View for embedded dashboards."""
    
    def get(self, request, token):
        """Get embedded dashboard with special formatting."""
        response = super().get(request, token)
        
        if response.status_code == 200:
            # Add embed-specific headers
            response['X-Frame-Options'] = 'ALLOWALL'
            response['Content-Security-Policy'] = "frame-ancestors *"
        
        return response


class EmbedWidgetView(APIView):
    """View for embedding individual widgets."""
    
    permission_classes = []
    
    def get(self, request, widget_id):
        """Get widget for embedding."""
        try:
            widget = Widget.objects.get(id=widget_id)
            
            # Check if dashboard allows embedding
            if not widget.dashboard.is_public:
                return Response(
                    {'error': 'Widget not available for embedding'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            from ..services import DashboardService
            from .serializers import WidgetSerializer
            
            service = DashboardService()
            
            # Get widget data
            widget_data = WidgetSerializer(
                widget,
                context={'request': request}
            ).data
            
            # Get widget content
            content = service.get_widget_data(widget)
            
            data = {
                'widget': widget_data,
                'content': content,
            }
            
            response = Response(data)
            response['X-Frame-Options'] = 'ALLOWALL'
            response['Content-Security-Policy'] = "frame-ancestors *"
            
            return response
            
        except Widget.DoesNotExist:
            return Response(
                {'error': 'Widget not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )