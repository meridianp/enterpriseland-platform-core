"""Dashboard service for managing dashboards and widgets."""

import logging
from typing import Dict, List, Optional, Any
from django.db import transaction
from django.core.cache import cache

from ..models import Dashboard, Widget, DashboardLayout
from .data_service import QueryExecutor
from .visualization_service import VisualizationService
from .analytics_service import MetricCalculator

logger = logging.getLogger(__name__)


class DashboardService:
    """Service for managing dashboards."""
    
    def __init__(self):
        self.widget_service = WidgetService()
    
    def create_dashboard(self, data: Dict, user) -> Dashboard:
        """Create a new dashboard."""
        with transaction.atomic():
            # Extract relationships
            collaborator_ids = data.pop('collaborator_ids', [])
            
            # Create dashboard
            dashboard = Dashboard.objects.create(
                owner=user,
                group=user.group,
                **data
            )
            
            # Set collaborators
            if collaborator_ids:
                dashboard.collaborators.set(collaborator_ids)
            
            # Create default layout
            self._create_default_layout(dashboard)
            
            return dashboard
    
    def update_dashboard(self, dashboard_id: str, data: Dict, user) -> Dashboard:
        """Update an existing dashboard."""
        dashboard = Dashboard.objects.get(id=dashboard_id)
        
        # Check permissions
        if dashboard.owner != user and user not in dashboard.collaborators.all():
            raise PermissionError("You don't have permission to update this dashboard")
        
        with transaction.atomic():
            # Update relationships if provided
            if 'collaborator_ids' in data:
                dashboard.collaborators.set(data.pop('collaborator_ids'))
            
            # Update fields
            for key, value in data.items():
                setattr(dashboard, key, value)
            
            dashboard.save()
            
            # Clear cache
            self._clear_dashboard_cache(dashboard_id)
            
            return dashboard
    
    def get_dashboard_data(self, dashboard_id: str, refresh: bool = False) -> Dict:
        """Get complete dashboard data with all widgets."""
        if not refresh:
            cache_key = f"dashboard_data:{dashboard_id}"
            cached_data = cache.get(cache_key)
            if cached_data:
                return cached_data
        
        dashboard = Dashboard.objects.get(id=dashboard_id)
        widgets = dashboard.widgets.all().order_by('position')
        
        # Get data for each widget
        widget_data = []
        for widget in widgets:
            try:
                data = self.widget_service.get_widget_data(widget)
                widget_data.append({
                    'id': str(widget.id),
                    'data': data,
                    'config': widget.configuration,
                    'position': widget.position,
                })
            except Exception as e:
                logger.error(f"Error loading widget {widget.id}: {str(e)}")
                widget_data.append({
                    'id': str(widget.id),
                    'error': str(e),
                    'position': widget.position,
                })
        
        dashboard_data = {
            'dashboard': {
                'id': str(dashboard.id),
                'name': dashboard.name,
                'theme': dashboard.theme,
                'layout_type': dashboard.layout_type,
                'configuration': dashboard.configuration,
            },
            'widgets': widget_data,
            'last_updated': dashboard.updated_at.isoformat(),
        }
        
        # Cache the data
        if dashboard.cache_widgets:
            cache_key = f"dashboard_data:{dashboard_id}"
            cache.set(cache_key, dashboard_data, 300)  # 5 minutes
        
        return dashboard_data
    
    def add_widget(self, dashboard_id: str, widget_data: Dict, user) -> Widget:
        """Add a widget to a dashboard."""
        dashboard = Dashboard.objects.get(id=dashboard_id)
        
        # Check permissions
        if dashboard.owner != user and user not in dashboard.collaborators.all():
            raise PermissionError("You don't have permission to add widgets to this dashboard")
        
        # Get next position
        max_position = dashboard.widgets.aggregate(
            max_pos=models.Max('position')
        )['max_pos'] or -1
        
        widget_data['dashboard'] = dashboard
        widget_data['position'] = max_position + 1
        widget_data['group'] = dashboard.group
        
        widget = self.widget_service.create_widget(widget_data)
        
        # Clear dashboard cache
        self._clear_dashboard_cache(dashboard_id)
        
        return widget
    
    def reorder_widgets(self, dashboard_id: str, widget_order: List[str], user):
        """Reorder widgets in a dashboard."""
        dashboard = Dashboard.objects.get(id=dashboard_id)
        
        # Check permissions
        if dashboard.owner != user and user not in dashboard.collaborators.all():
            raise PermissionError("You don't have permission to reorder widgets")
        
        with transaction.atomic():
            for position, widget_id in enumerate(widget_order):
                Widget.objects.filter(
                    id=widget_id,
                    dashboard=dashboard
                ).update(position=position)
        
        # Clear dashboard cache
        self._clear_dashboard_cache(dashboard_id)
    
    def save_layout(self, dashboard_id: str, layout_name: str, layout_data: Dict, user) -> DashboardLayout:
        """Save a dashboard layout."""
        dashboard = Dashboard.objects.get(id=dashboard_id)
        
        layout = DashboardLayout.objects.create(
            dashboard=dashboard,
            name=layout_name,
            layout_data=layout_data,
            created_by=user,
            group=dashboard.group
        )
        
        return layout
    
    def apply_layout(self, dashboard_id: str, layout_id: str, user):
        """Apply a saved layout to a dashboard."""
        dashboard = Dashboard.objects.get(id=dashboard_id)
        layout = DashboardLayout.objects.get(id=layout_id, dashboard=dashboard)
        
        # Apply layout data to widgets
        with transaction.atomic():
            for widget_layout in layout.layout_data.get('widgets', []):
                widget_id = widget_layout.get('id')
                if widget_id:
                    Widget.objects.filter(
                        id=widget_id,
                        dashboard=dashboard
                    ).update(
                        position=widget_layout.get('position', 0),
                        row=widget_layout.get('row', 0),
                        column=widget_layout.get('column', 0),
                        width=widget_layout.get('width', 1),
                        height=widget_layout.get('height', 1),
                    )
        
        # Clear dashboard cache
        self._clear_dashboard_cache(dashboard_id)
    
    def _create_default_layout(self, dashboard: Dashboard):
        """Create default layout for a new dashboard."""
        if dashboard.layout_type == 'grid':
            dashboard.configuration['grid'] = {
                'columns': 12,
                'row_height': 100,
                'margin': [10, 10],
                'container_padding': [10, 10],
            }
        elif dashboard.layout_type == 'flex':
            dashboard.configuration['flex'] = {
                'direction': 'row',
                'wrap': True,
                'gap': 10,
            }
        
        dashboard.save()
    
    def _clear_dashboard_cache(self, dashboard_id: str):
        """Clear cache for a dashboard."""
        cache_key = f"dashboard_data:{dashboard_id}"
        cache.delete(cache_key)
        
        # Also clear widget caches
        dashboard = Dashboard.objects.get(id=dashboard_id)
        for widget in dashboard.widgets.all():
            widget_cache_key = f"widget_data:{widget.id}"
            cache.delete(widget_cache_key)


class WidgetService:
    """Service for managing widgets."""
    
    def __init__(self):
        self.query_executor = QueryExecutor()
        self.visualization_service = VisualizationService()
        self.metric_calculator = MetricCalculator()
    
    def create_widget(self, data: Dict) -> Widget:
        """Create a new widget."""
        return Widget.objects.create(**data)
    
    def update_widget(self, widget_id: str, data: Dict) -> Widget:
        """Update a widget."""
        widget = Widget.objects.get(id=widget_id)
        
        for key, value in data.items():
            setattr(widget, key, value)
        
        widget.save()
        
        # Clear widget cache
        cache_key = f"widget_data:{widget_id}"
        cache.delete(cache_key)
        
        return widget
    
    def get_widget_data(self, widget: Widget) -> Dict:
        """Get data for a widget."""
        cache_key = f"widget_data:{widget.id}"
        cached_data = cache.get(cache_key)
        
        if cached_data and widget.cache_duration > 0:
            return cached_data
        
        try:
            if widget.type == 'metric':
                data = self._get_metric_data(widget)
            elif widget.type == 'chart':
                data = self._get_chart_data(widget)
            elif widget.type == 'table':
                data = self._get_table_data(widget)
            elif widget.type == 'text':
                data = self._get_text_data(widget)
            elif widget.type == 'map':
                data = self._get_map_data(widget)
            else:
                data = self._get_custom_data(widget)
            
            # Add widget metadata
            data['widget'] = {
                'id': str(widget.id),
                'name': widget.name,
                'type': widget.type,
                'size': widget.size,
            }
            
            # Cache the data
            if widget.cache_duration > 0:
                cache.set(cache_key, data, widget.cache_duration)
            
            return data
            
        except Exception as e:
            logger.error(f"Error getting widget data: {str(e)}")
            raise
    
    def _get_metric_data(self, widget: Widget) -> Dict:
        """Get data for metric widget."""
        if not widget.metric:
            raise ValueError("Metric widget requires a metric")
        
        # Calculate metric value
        result = self.metric_calculator.calculate(widget.metric)
        
        # Get historical data if configured
        history = None
        if widget.configuration.get('show_history', False):
            days = widget.configuration.get('history_days', 7)
            history = self.metric_calculator.get_history(widget.metric, days)
        
        return {
            'value': result['value'],
            'formatted_value': result['formatted_value'],
            'trend': result.get('trend'),
            'status': result.get('status'),
            'history': history,
        }
    
    def _get_chart_data(self, widget: Widget) -> Dict:
        """Get data for chart widget."""
        if widget.visualization:
            # Use predefined visualization
            if widget.query:
                # Execute custom query
                data = self.query_executor.execute_query_definition(
                    str(widget.query.id),
                    widget.configuration.get('parameters', {})
                )
            elif widget.data_source:
                # Execute inline query
                query = widget.configuration.get('query')
                if not query:
                    raise ValueError("Chart widget requires a query")
                
                data = self.query_executor.execute(
                    widget.data_source,
                    query,
                    widget.configuration.get('parameters', {})
                )
            else:
                raise ValueError("Chart widget requires a data source")
            
            # Render visualization
            return self.visualization_service.render(widget.visualization, data)
        
        else:
            # Inline chart configuration
            if widget.data_source and widget.query:
                # Execute query
                data = self.query_executor.execute_query_definition(
                    str(widget.query.id),
                    widget.configuration.get('parameters', {})
                )
                
                # Apply chart configuration
                return {
                    'data': data['rows'],
                    'config': widget.configuration.get('chart_config', {}),
                }
            else:
                raise ValueError("Chart widget requires data source and query")
    
    def _get_table_data(self, widget: Widget) -> Dict:
        """Get data for table widget."""
        if widget.data_source and widget.query:
            # Execute query
            data = self.query_executor.execute_query_definition(
                str(widget.query.id),
                widget.configuration.get('parameters', {})
            )
            
            # Apply table configuration
            return {
                'columns': data['columns'],
                'rows': data['rows'],
                'total_rows': data.get('row_count', len(data['rows'])),
                'config': widget.configuration.get('table_config', {}),
            }
        else:
            raise ValueError("Table widget requires data source and query")
    
    def _get_text_data(self, widget: Widget) -> Dict:
        """Get data for text widget."""
        return {
            'content': widget.configuration.get('content', ''),
            'format': widget.configuration.get('format', 'markdown'),
        }
    
    def _get_map_data(self, widget: Widget) -> Dict:
        """Get data for map widget."""
        if widget.data_source and widget.query:
            # Execute query for map data
            data = self.query_executor.execute_query_definition(
                str(widget.query.id),
                widget.configuration.get('parameters', {})
            )
            
            # Format for map visualization
            return {
                'features': self._format_map_features(data['rows']),
                'config': widget.configuration.get('map_config', {}),
            }
        else:
            # Static map configuration
            return {
                'features': widget.configuration.get('features', []),
                'config': widget.configuration.get('map_config', {}),
            }
    
    def _get_custom_data(self, widget: Widget) -> Dict:
        """Get data for custom widget."""
        # Execute custom data retrieval logic
        if widget.configuration.get('data_handler'):
            # This would call a registered custom handler
            handler_name = widget.configuration['data_handler']
            # Implementation would look up and execute the handler
            pass
        
        return widget.configuration.get('static_data', {})
    
    def _format_map_features(self, rows: List[Dict]) -> List[Dict]:
        """Format data rows as GeoJSON features."""
        features = []
        
        for row in rows:
            if 'latitude' in row and 'longitude' in row:
                feature = {
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [row['longitude'], row['latitude']]
                    },
                    'properties': {k: v for k, v in row.items() 
                                 if k not in ['latitude', 'longitude']}
                }
                features.append(feature)
        
        return features
    
    def move_widget(self, widget: Widget, new_position: int):
        """Move widget to a new position."""
        dashboard = widget.dashboard
        old_position = widget.position
        
        with transaction.atomic():
            if new_position > old_position:
                # Moving down
                Widget.objects.filter(
                    dashboard=dashboard,
                    position__gt=old_position,
                    position__lte=new_position
                ).update(position=models.F('position') - 1)
            else:
                # Moving up
                Widget.objects.filter(
                    dashboard=dashboard,
                    position__gte=new_position,
                    position__lt=old_position
                ).update(position=models.F('position') + 1)
            
            # Update widget position
            widget.position = new_position
            widget.save()
        
        # Clear caches
        self._clear_widget_cache(widget)
        self._clear_dashboard_cache(str(dashboard.id))
    
    def _clear_widget_cache(self, widget: Widget):
        """Clear cache for a widget."""
        cache_key = f"widget_data:{widget.id}"
        cache.delete(cache_key)
    
    def _clear_dashboard_cache(self, dashboard_id: str):
        """Clear cache for a dashboard."""
        cache_key = f"dashboard_data:{dashboard_id}"
        cache.delete(cache_key)