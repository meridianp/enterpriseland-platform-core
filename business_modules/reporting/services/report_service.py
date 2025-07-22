"""Report service for managing reports and executions."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json

from django.db import transaction
from django.db.models import Q, Count, Avg, Sum
from django.core.cache import cache
from django.utils import timezone
from celery import shared_task

from ..models import (
    Report, ReportTemplate, ReportSchedule, ReportExecution, ReportExport,
    DataSource, Visualization, Metric
)
from .data_service import QueryExecutor
from .visualization_service import VisualizationService
from .analytics_service import MetricCalculator

logger = logging.getLogger(__name__)


class ReportService:
    """Service for managing reports."""
    
    def __init__(self):
        self.query_executor = QueryExecutor()
        self.visualization_service = VisualizationService()
        self.metric_calculator = MetricCalculator()
    
    def create_report(self, data: Dict, user) -> Report:
        """Create a new report."""
        with transaction.atomic():
            # Extract relationships
            data_source_ids = data.pop('data_source_ids', [])
            visualization_ids = data.pop('visualization_ids', [])
            metric_ids = data.pop('metric_ids', [])
            collaborator_ids = data.pop('collaborator_ids', [])
            
            # Create report
            report = Report.objects.create(
                owner=user,
                group=user.group,
                **data
            )
            
            # Set relationships
            if data_source_ids:
                report.data_sources.set(DataSource.objects.filter(id__in=data_source_ids))
            
            if visualization_ids:
                report.visualizations.set(Visualization.objects.filter(id__in=visualization_ids))
            
            if metric_ids:
                report.metrics.set(Metric.objects.filter(id__in=metric_ids))
            
            if collaborator_ids:
                report.collaborators.set(collaborator_ids)
            
            return report
    
    def create_from_template(self, template_id: str, data: Dict, user) -> Report:
        """Create a report from a template."""
        template = ReportTemplate.objects.get(id=template_id)
        
        # Merge template config with user data
        config = template.template_config.copy()
        config.update(data.get('configuration', {}))
        
        report_data = {
            'name': data.get('name', f"Report from {template.name}"),
            'description': data.get('description', template.description),
            'type': data.get('type', 'standard'),
            'template': template,
            'configuration': config,
            'tags': data.get('tags', []),
        }
        
        return self.create_report(report_data, user)
    
    def update_report(self, report_id: str, data: Dict, user) -> Report:
        """Update an existing report."""
        report = Report.objects.get(id=report_id)
        
        # Check permissions
        if report.owner != user and user not in report.collaborators.all():
            raise PermissionError("You don't have permission to update this report")
        
        with transaction.atomic():
            # Update relationships if provided
            if 'data_source_ids' in data:
                report.data_sources.set(data.pop('data_source_ids'))
            
            if 'visualization_ids' in data:
                report.visualizations.set(data.pop('visualization_ids'))
            
            if 'metric_ids' in data:
                report.metrics.set(data.pop('metric_ids'))
            
            if 'collaborator_ids' in data:
                report.collaborators.set(data.pop('collaborator_ids'))
            
            # Update fields
            for key, value in data.items():
                setattr(report, key, value)
            
            report.save()
            
            # Clear cache
            self._clear_report_cache(report_id)
            
            return report
    
    def get_report_data(self, report_id: str, parameters: Dict = None) -> Dict:
        """Get report data with caching."""
        cache_key = f"report_data:{report_id}:{json.dumps(parameters or {}, sort_keys=True)}"
        cached_data = cache.get(cache_key)
        
        if cached_data:
            return cached_data
        
        report = Report.objects.get(id=report_id)
        executor = ReportExecutor()
        data = executor.execute_report(report, parameters)
        
        # Cache the data
        cache.set(cache_key, data, report.cache_duration)
        
        return data
    
    def search_reports(self, query: str, filters: Dict = None) -> List[Report]:
        """Search reports with filters."""
        qs = Report.objects.all()
        
        if query:
            qs = qs.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(tags__contains=[query])
            )
        
        if filters:
            if filters.get('type'):
                qs = qs.filter(type=filters['type'])
            
            if filters.get('status'):
                qs = qs.filter(status=filters['status'])
            
            if filters.get('owner_id'):
                qs = qs.filter(owner_id=filters['owner_id'])
            
            if filters.get('tags'):
                for tag in filters['tags']:
                    qs = qs.filter(tags__contains=[tag])
        
        return qs.select_related('owner', 'template').prefetch_related(
            'data_sources', 'visualizations', 'metrics'
        )
    
    def get_report_analytics(self, report_id: str) -> Dict:
        """Get analytics for a report."""
        report = Report.objects.get(id=report_id)
        
        executions = ReportExecution.objects.filter(report=report)
        exports = ReportExport.objects.filter(report=report)
        
        analytics = {
            'execution_count': executions.count(),
            'export_count': exports.count(),
            'avg_execution_time': executions.filter(
                duration__isnull=False
            ).aggregate(Avg('duration'))['duration__avg'],
            'success_rate': self._calculate_success_rate(executions),
            'popular_export_formats': self._get_popular_export_formats(exports),
            'recent_executions': self._get_recent_executions(executions),
            'usage_trend': self._get_usage_trend(executions),
        }
        
        return analytics
    
    def _clear_report_cache(self, report_id: str):
        """Clear all cache entries for a report."""
        # This is a simplified version - in production you'd want a more sophisticated cache invalidation
        cache_pattern = f"report_data:{report_id}:*"
        # Note: This requires a cache backend that supports pattern deletion
        cache.delete_pattern(cache_pattern)
    
    def _calculate_success_rate(self, executions):
        """Calculate execution success rate."""
        total = executions.count()
        if total == 0:
            return 0
        
        successful = executions.filter(status='completed').count()
        return (successful / total) * 100
    
    def _get_popular_export_formats(self, exports):
        """Get popular export formats."""
        return exports.values('format').annotate(
            count=Count('id')
        ).order_by('-count')[:5]
    
    def _get_recent_executions(self, executions):
        """Get recent execution summary."""
        return executions.order_by('-created_at')[:10].values(
            'id', 'status', 'created_at', 'duration', 'row_count'
        )
    
    def _get_usage_trend(self, executions):
        """Get usage trend over last 30 days."""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=30)
        
        trend_data = []
        current_date = start_date
        
        while current_date <= end_date:
            count = executions.filter(
                created_at__date=current_date.date()
            ).count()
            
            trend_data.append({
                'date': current_date.date().isoformat(),
                'count': count
            })
            
            current_date += timedelta(days=1)
        
        return trend_data


class ReportExecutor:
    """Execute reports and generate data."""
    
    def __init__(self):
        self.query_executor = QueryExecutor()
        self.visualization_service = VisualizationService()
        self.metric_calculator = MetricCalculator()
    
    def execute_report(self, report: Report, parameters: Dict = None) -> Dict:
        """Execute a report and return the data."""
        execution = ReportExecution.objects.create(
            report=report,
            status='running',
            started_at=timezone.now(),
            parameters=parameters or {}
        )
        
        try:
            # Execute queries
            query_results = self._execute_queries(report, parameters)
            
            # Calculate metrics
            metric_results = self._calculate_metrics(report, query_results)
            
            # Generate visualizations
            visualization_results = self._generate_visualizations(report, query_results)
            
            # Combine results
            result_data = {
                'report': {
                    'id': str(report.id),
                    'name': report.name,
                    'type': report.type,
                    'generated_at': timezone.now().isoformat(),
                },
                'data': query_results,
                'metrics': metric_results,
                'visualizations': visualization_results,
                'parameters': parameters or {},
            }
            
            # Update execution
            execution.status = 'completed'
            execution.completed_at = timezone.now()
            execution.duration = (execution.completed_at - execution.started_at).total_seconds()
            execution.row_count = sum(len(data.get('rows', [])) for data in query_results.values())
            execution.result_data = result_data
            execution.save()
            
            return result_data
            
        except Exception as e:
            logger.error(f"Report execution failed: {str(e)}")
            execution.status = 'failed'
            execution.completed_at = timezone.now()
            execution.duration = (execution.completed_at - execution.started_at).total_seconds()
            execution.error_message = str(e)
            execution.save()
            raise
    
    def _execute_queries(self, report: Report, parameters: Dict = None) -> Dict:
        """Execute report queries."""
        results = {}
        
        for query_def in report.queries:
            query_id = query_def.get('id', 'default')
            
            # Apply parameters to query
            query = self._apply_parameters(query_def['query'], parameters)
            
            # Execute query
            data_source = DataSource.objects.get(id=query_def['data_source_id'])
            result = self.query_executor.execute(data_source, query)
            
            results[query_id] = result
        
        return results
    
    def _calculate_metrics(self, report: Report, query_results: Dict) -> List[Dict]:
        """Calculate report metrics."""
        metric_results = []
        
        for metric in report.metrics.all():
            result = self.metric_calculator.calculate(metric, query_results)
            metric_results.append({
                'id': str(metric.id),
                'name': metric.display_name,
                'value': result['value'],
                'formatted_value': result['formatted_value'],
                'trend': result.get('trend'),
                'status': result.get('status'),
            })
        
        return metric_results
    
    def _generate_visualizations(self, report: Report, query_results: Dict) -> List[Dict]:
        """Generate report visualizations."""
        visualization_results = []
        
        for viz in report.visualizations.all():
            # Get data for visualization
            data_key = viz.configuration.get('data_key', 'default')
            data = query_results.get(data_key, {})
            
            # Generate visualization
            result = self.visualization_service.render(viz, data)
            visualization_results.append({
                'id': str(viz.id),
                'name': viz.name,
                'type': viz.type.name,
                'data': result['data'],
                'config': result['config'],
            })
        
        return visualization_results
    
    def _apply_parameters(self, query: str, parameters: Dict = None) -> str:
        """Apply parameters to query template."""
        if not parameters:
            return query
        
        # Simple parameter replacement - in production, use proper SQL parameterization
        for key, value in parameters.items():
            placeholder = f"{{{key}}}"
            if placeholder in query:
                # Escape value to prevent SQL injection
                if isinstance(value, str):
                    value = value.replace("'", "''")
                    query = query.replace(placeholder, f"'{value}'")
                else:
                    query = query.replace(placeholder, str(value))
        
        return query


class ReportExporter:
    """Export reports to various formats."""
    
    def export(self, report_id: str, format: str, options: Dict = None) -> ReportExport:
        """Export a report to the specified format."""
        report = Report.objects.get(id=report_id)
        
        # Create export record
        export = ReportExport.objects.create(
            report=report,
            format=format,
            status='processing',
            include_visualizations=options.get('include_visualizations', True),
            include_raw_data=options.get('include_raw_data', False),
            filters=options.get('filters', {}),
        )
        
        # Delegate to async task
        export_report_task.delay(export.id)
        
        return export


@shared_task
def export_report_task(export_id: str):
    """Async task to export a report."""
    from .export_service import ExportService
    
    export = ReportExport.objects.get(id=export_id)
    export_service = ExportService()
    
    try:
        # Get report data
        report_service = ReportService()
        report_data = report_service.get_report_data(
            str(export.report.id),
            export.filters
        )
        
        # Export to format
        result = export_service.export(
            data=report_data,
            format=export.format,
            options={
                'include_visualizations': export.include_visualizations,
                'include_raw_data': export.include_raw_data,
            }
        )
        
        # Update export record
        export.status = 'completed'
        export.file_path = result['file_path']
        export.file_size = result['file_size']
        export.download_url = result['download_url']
        export.expires_at = timezone.now() + timedelta(days=7)
        export.save()
        
    except Exception as e:
        logger.error(f"Export failed: {str(e)}")
        export.status = 'failed'
        export.error_message = str(e)
        export.save()