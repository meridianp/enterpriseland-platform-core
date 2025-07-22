"""Visualization service for rendering charts and visualizations."""

import logging
from typing import Dict, List, Optional, Any
import json
from django.core.cache import cache

from ..models import Visualization, VisualizationType, ChartConfiguration

logger = logging.getLogger(__name__)


class VisualizationService:
    """Service for managing and rendering visualizations."""
    
    def render(self, visualization: Visualization, data: Dict) -> Dict:
        """Render a visualization with data."""
        renderer = self._get_renderer(visualization.type)
        
        # Apply dimension and measure mappings
        mapped_data = self._map_data(visualization, data)
        
        # Apply filters
        filtered_data = self._apply_filters(visualization, mapped_data)
        
        # Render the visualization
        rendered = renderer.render(
            data=filtered_data,
            config=visualization.configuration,
            dimensions=visualization.dimensions,
            measures=visualization.measures
        )
        
        # Apply color configuration
        if visualization.colors:
            rendered['colors'] = visualization.colors
        
        return rendered
    
    def preview(self, visualization: Visualization, sample_data: Dict = None) -> Dict:
        """Preview a visualization with sample data."""
        if not sample_data:
            sample_data = self._generate_sample_data(visualization.type)
        
        return self.render(visualization, sample_data)
    
    def validate_configuration(self, viz_type: VisualizationType, config: Dict) -> Dict:
        """Validate visualization configuration."""
        errors = []
        warnings = []
        
        # Check dimension requirements
        dimensions = config.get('dimensions', [])
        if len(dimensions) < viz_type.min_dimensions:
            errors.append(f"At least {viz_type.min_dimensions} dimension(s) required")
        if len(dimensions) > viz_type.max_dimensions:
            errors.append(f"Maximum {viz_type.max_dimensions} dimension(s) allowed")
        
        # Check measure requirements
        measures = config.get('measures', [])
        if len(measures) < viz_type.min_measures:
            errors.append(f"At least {viz_type.min_measures} measure(s) required")
        if len(measures) > viz_type.max_measures:
            errors.append(f"Maximum {viz_type.max_measures} measure(s) allowed")
        
        # Type-specific validation
        renderer = self._get_renderer(viz_type)
        type_validation = renderer.validate_config(config)
        errors.extend(type_validation.get('errors', []))
        warnings.extend(type_validation.get('warnings', []))
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
    
    def _get_renderer(self, viz_type: VisualizationType):
        """Get renderer for visualization type."""
        # This would return the appropriate renderer based on type
        # For now, return a generic renderer
        return ChartRenderer(viz_type)
    
    def _map_data(self, visualization: Visualization, data: Dict) -> Dict:
        """Map data fields to dimensions and measures."""
        rows = data.get('rows', [])
        mapped_rows = []
        
        for row in rows:
            mapped_row = {}
            
            # Map dimensions
            for i, dim in enumerate(visualization.dimensions):
                field = dim.get('field')
                alias = dim.get('alias', f'dimension_{i}')
                if field and field in row:
                    mapped_row[alias] = row[field]
            
            # Map measures
            for i, measure in enumerate(visualization.measures):
                field = measure.get('field')
                alias = measure.get('alias', f'measure_{i}')
                if field and field in row:
                    mapped_row[alias] = row[field]
            
            mapped_rows.append(mapped_row)
        
        return {
            'rows': mapped_rows,
            'columns': list(set(mapped_rows[0].keys())) if mapped_rows else []
        }
    
    def _apply_filters(self, visualization: Visualization, data: Dict) -> Dict:
        """Apply filters to the data."""
        if not visualization.filters:
            return data
        
        rows = data.get('rows', [])
        filtered_rows = []
        
        for row in rows:
            include = True
            
            for filter_def in visualization.filters:
                field = filter_def.get('field')
                operator = filter_def.get('operator')
                value = filter_def.get('value')
                
                if field in row:
                    if not self._evaluate_filter(row[field], operator, value):
                        include = False
                        break
            
            if include:
                filtered_rows.append(row)
        
        return {
            'rows': filtered_rows,
            'columns': data.get('columns', [])
        }
    
    def _evaluate_filter(self, field_value, operator: str, filter_value) -> bool:
        """Evaluate a single filter condition."""
        try:
            if operator == 'eq':
                return field_value == filter_value
            elif operator == 'ne':
                return field_value != filter_value
            elif operator == 'gt':
                return float(field_value) > float(filter_value)
            elif operator == 'gte':
                return float(field_value) >= float(filter_value)
            elif operator == 'lt':
                return float(field_value) < float(filter_value)
            elif operator == 'lte':
                return float(field_value) <= float(filter_value)
            elif operator == 'contains':
                return str(filter_value).lower() in str(field_value).lower()
            elif operator == 'not_contains':
                return str(filter_value).lower() not in str(field_value).lower()
            elif operator == 'in':
                return field_value in filter_value
            elif operator == 'not_in':
                return field_value not in filter_value
            else:
                return True
        except (ValueError, TypeError):
            return False
    
    def _generate_sample_data(self, viz_type: VisualizationType) -> Dict:
        """Generate sample data for a visualization type."""
        # Generate appropriate sample data based on visualization type
        if viz_type.name == 'line_chart':
            return {
                'columns': ['date', 'value'],
                'rows': [
                    {'date': '2024-01-01', 'value': 100},
                    {'date': '2024-01-02', 'value': 120},
                    {'date': '2024-01-03', 'value': 115},
                    {'date': '2024-01-04', 'value': 130},
                    {'date': '2024-01-05', 'value': 145},
                ]
            }
        elif viz_type.name == 'bar_chart':
            return {
                'columns': ['category', 'value'],
                'rows': [
                    {'category': 'A', 'value': 25},
                    {'category': 'B', 'value': 40},
                    {'category': 'C', 'value': 35},
                    {'category': 'D', 'value': 50},
                ]
            }
        elif viz_type.name == 'pie_chart':
            return {
                'columns': ['segment', 'value'],
                'rows': [
                    {'segment': 'Segment 1', 'value': 30},
                    {'segment': 'Segment 2', 'value': 25},
                    {'segment': 'Segment 3', 'value': 20},
                    {'segment': 'Segment 4', 'value': 25},
                ]
            }
        else:
            # Generic sample data
            return {
                'columns': ['dimension', 'measure'],
                'rows': [
                    {'dimension': 'Item 1', 'measure': 10},
                    {'dimension': 'Item 2', 'measure': 20},
                    {'dimension': 'Item 3', 'measure': 15},
                ]
            }


class ChartRenderer:
    """Base chart renderer."""
    
    def __init__(self, viz_type: VisualizationType):
        self.viz_type = viz_type
    
    def render(self, data: Dict, config: Dict, dimensions: List, measures: List) -> Dict:
        """Render the chart."""
        # Get the appropriate rendering method
        render_method = getattr(self, f'_render_{self.viz_type.name}', self._render_generic)
        
        return render_method(data, config, dimensions, measures)
    
    def validate_config(self, config: Dict) -> Dict:
        """Validate chart configuration."""
        # Get the appropriate validation method
        validate_method = getattr(self, f'_validate_{self.viz_type.name}', self._validate_generic)
        
        return validate_method(config)
    
    def _render_line_chart(self, data: Dict, config: Dict, dimensions: List, measures: List) -> Dict:
        """Render line chart."""
        rows = data.get('rows', [])
        
        # Extract series data
        series_data = {}
        x_field = dimensions[0].get('alias', 'dimension_0') if dimensions else None
        
        for measure in measures:
            y_field = measure.get('alias', 'measure_0')
            series_name = measure.get('name', y_field)
            series_data[series_name] = []
            
            for row in rows:
                if x_field and x_field in row and y_field in row:
                    series_data[series_name].append({
                        'x': row[x_field],
                        'y': row[y_field]
                    })
        
        return {
            'type': 'line',
            'data': {
                'series': [
                    {
                        'name': name,
                        'data': points
                    }
                    for name, points in series_data.items()
                ]
            },
            'config': {
                'xAxis': {
                    'type': config.get('xAxisType', 'category'),
                    'label': dimensions[0].get('name') if dimensions else ''
                },
                'yAxis': {
                    'type': 'value',
                    'label': config.get('yAxisLabel', '')
                },
                'legend': {
                    'show': config.get('showLegend', True)
                },
                'tooltip': {
                    'show': config.get('showTooltip', True)
                }
            }
        }
    
    def _render_bar_chart(self, data: Dict, config: Dict, dimensions: List, measures: List) -> Dict:
        """Render bar chart."""
        rows = data.get('rows', [])
        
        # Extract categories and values
        categories = []
        series_data = {}
        
        x_field = dimensions[0].get('alias', 'dimension_0') if dimensions else None
        
        for row in rows:
            if x_field and x_field in row:
                category = row[x_field]
                if category not in categories:
                    categories.append(category)
                
                for measure in measures:
                    y_field = measure.get('alias', 'measure_0')
                    series_name = measure.get('name', y_field)
                    
                    if series_name not in series_data:
                        series_data[series_name] = []
                    
                    if y_field in row:
                        series_data[series_name].append(row[y_field])
        
        return {
            'type': 'bar',
            'data': {
                'categories': categories,
                'series': [
                    {
                        'name': name,
                        'data': values
                    }
                    for name, values in series_data.items()
                ]
            },
            'config': {
                'orientation': config.get('orientation', 'vertical'),
                'stacked': config.get('stacked', False),
                'showValues': config.get('showValues', False),
                'legend': {
                    'show': config.get('showLegend', True)
                }
            }
        }
    
    def _render_pie_chart(self, data: Dict, config: Dict, dimensions: List, measures: List) -> Dict:
        """Render pie chart."""
        rows = data.get('rows', [])
        
        # Extract slices
        slices = []
        
        label_field = dimensions[0].get('alias', 'dimension_0') if dimensions else None
        value_field = measures[0].get('alias', 'measure_0') if measures else None
        
        for row in rows:
            if label_field and value_field and label_field in row and value_field in row:
                slices.append({
                    'name': row[label_field],
                    'value': row[value_field]
                })
        
        return {
            'type': 'pie',
            'data': {
                'slices': slices
            },
            'config': {
                'donut': config.get('donut', False),
                'donutWidth': config.get('donutWidth', 60),
                'showLabels': config.get('showLabels', True),
                'showPercentages': config.get('showPercentages', True),
                'legend': {
                    'show': config.get('showLegend', True),
                    'position': config.get('legendPosition', 'right')
                }
            }
        }
    
    def _render_heatmap(self, data: Dict, config: Dict, dimensions: List, measures: List) -> Dict:
        """Render heatmap."""
        rows = data.get('rows', [])
        
        # Extract matrix data
        x_field = dimensions[0].get('alias') if len(dimensions) > 0 else None
        y_field = dimensions[1].get('alias') if len(dimensions) > 1 else None
        value_field = measures[0].get('alias') if measures else None
        
        # Build matrix
        x_values = []
        y_values = []
        matrix_data = {}
        
        for row in rows:
            if x_field and y_field and value_field:
                x = row.get(x_field)
                y = row.get(y_field)
                value = row.get(value_field, 0)
                
                if x not in x_values:
                    x_values.append(x)
                if y not in y_values:
                    y_values.append(y)
                
                matrix_data[(x, y)] = value
        
        # Convert to array format
        matrix = []
        for y in y_values:
            row_data = []
            for x in x_values:
                row_data.append(matrix_data.get((x, y), 0))
            matrix.append(row_data)
        
        return {
            'type': 'heatmap',
            'data': {
                'xLabels': x_values,
                'yLabels': y_values,
                'matrix': matrix
            },
            'config': {
                'colorScheme': config.get('colorScheme', 'sequential'),
                'showValues': config.get('showValues', True),
                'minColor': config.get('minColor', '#f0f0f0'),
                'maxColor': config.get('maxColor', '#000080')
            }
        }
    
    def _render_scatter_plot(self, data: Dict, config: Dict, dimensions: List, measures: List) -> Dict:
        """Render scatter plot."""
        rows = data.get('rows', [])
        
        # Extract points
        points = []
        
        x_field = measures[0].get('alias') if len(measures) > 0 else None
        y_field = measures[1].get('alias') if len(measures) > 1 else None
        size_field = measures[2].get('alias') if len(measures) > 2 else None
        color_field = dimensions[0].get('alias') if dimensions else None
        
        for row in rows:
            if x_field and y_field and x_field in row and y_field in row:
                point = {
                    'x': row[x_field],
                    'y': row[y_field]
                }
                
                if size_field and size_field in row:
                    point['size'] = row[size_field]
                
                if color_field and color_field in row:
                    point['category'] = row[color_field]
                
                points.append(point)
        
        return {
            'type': 'scatter',
            'data': {
                'points': points
            },
            'config': {
                'xAxis': {
                    'label': measures[0].get('name') if len(measures) > 0 else ''
                },
                'yAxis': {
                    'label': measures[1].get('name') if len(measures) > 1 else ''
                },
                'showTrendLine': config.get('showTrendLine', False),
                'bubbleChart': bool(size_field)
            }
        }
    
    def _render_generic(self, data: Dict, config: Dict, dimensions: List, measures: List) -> Dict:
        """Generic render method."""
        return {
            'type': self.viz_type.name,
            'data': data,
            'config': config,
            'dimensions': dimensions,
            'measures': measures
        }
    
    def _validate_line_chart(self, config: Dict) -> Dict:
        """Validate line chart configuration."""
        errors = []
        warnings = []
        
        if config.get('xAxisType') not in ['category', 'time', 'value', None]:
            errors.append("Invalid xAxisType")
        
        if config.get('interpolation') and config['interpolation'] not in ['linear', 'smooth', 'step']:
            warnings.append("Invalid interpolation type, using linear")
        
        return {'errors': errors, 'warnings': warnings}
    
    def _validate_bar_chart(self, config: Dict) -> Dict:
        """Validate bar chart configuration."""
        errors = []
        warnings = []
        
        if config.get('orientation') not in ['vertical', 'horizontal', None]:
            errors.append("Invalid orientation")
        
        if config.get('stacked') and config.get('grouped'):
            errors.append("Cannot have both stacked and grouped enabled")
        
        return {'errors': errors, 'warnings': warnings}
    
    def _validate_pie_chart(self, config: Dict) -> Dict:
        """Validate pie chart configuration."""
        errors = []
        warnings = []
        
        if config.get('donut') and config.get('donutWidth'):
            width = config['donutWidth']
            if not isinstance(width, (int, float)) or width < 0 or width > 100:
                errors.append("donutWidth must be between 0 and 100")
        
        return {'errors': errors, 'warnings': warnings}
    
    def _validate_generic(self, config: Dict) -> Dict:
        """Generic validation method."""
        return {'errors': [], 'warnings': []}