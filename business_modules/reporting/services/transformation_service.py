"""Data transformation service for the reporting module."""

import logging
from typing import Dict, List, Any, Optional, Union
import json
import re
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from celery import shared_task

from ..models import DataPipeline, DataTransformation, TransformationStep
from .data_service import QueryExecutor

logger = logging.getLogger(__name__)


class TransformationService:
    """Service for data transformations."""
    
    def __init__(self):
        self.query_executor = QueryExecutor()
        self.pipeline_executor = DataPipelineExecutor()
    
    def transform_data(self, data: Dict, transformations: List[Dict]) -> Dict:
        """Apply a series of transformations to data."""
        result = data.copy()
        
        for transformation in transformations:
            transform_type = transformation.get('type')
            
            if transform_type == 'filter':
                result = self._apply_filter(result, transformation)
            elif transform_type == 'aggregate':
                result = self._apply_aggregation(result, transformation)
            elif transform_type == 'join':
                result = self._apply_join(result, transformation)
            elif transform_type == 'pivot':
                result = self._apply_pivot(result, transformation)
            elif transform_type == 'unpivot':
                result = self._apply_unpivot(result, transformation)
            elif transform_type == 'calculate':
                result = self._apply_calculation(result, transformation)
            elif transform_type == 'rename':
                result = self._apply_rename(result, transformation)
            elif transform_type == 'cast':
                result = self._apply_type_cast(result, transformation)
            elif transform_type == 'clean':
                result = self._apply_cleaning(result, transformation)
            elif transform_type == 'enrich':
                result = self._apply_enrichment(result, transformation)
            elif transform_type == 'custom':
                result = self._apply_custom_transformation(result, transformation)
            else:
                logger.warning(f"Unknown transformation type: {transform_type}")
        
        return result
    
    def _apply_filter(self, data: Dict, config: Dict) -> Dict:
        """Apply filter transformation."""
        rows = data.get('rows', [])
        conditions = config.get('conditions', [])
        
        filtered_rows = []
        for row in rows:
            if self._evaluate_conditions(row, conditions, config.get('operator', 'and')):
                filtered_rows.append(row)
        
        return {
            **data,
            'rows': filtered_rows,
            'row_count': len(filtered_rows)
        }
    
    def _apply_aggregation(self, data: Dict, config: Dict) -> Dict:
        """Apply aggregation transformation."""
        rows = data.get('rows', [])
        group_by = config.get('group_by', [])
        aggregations = config.get('aggregations', [])
        
        if not rows:
            return data
        
        # Group data
        groups = {}
        for row in rows:
            # Create group key
            key_parts = []
            for field in group_by:
                key_parts.append(str(row.get(field, '')))
            key = tuple(key_parts) if key_parts else ('all',)
            
            if key not in groups:
                groups[key] = []
            groups[key].append(row)
        
        # Apply aggregations
        result_rows = []
        for key, group_rows in groups.items():
            result_row = {}
            
            # Add group by fields
            if group_by:
                for i, field in enumerate(group_by):
                    result_row[field] = group_rows[0].get(field)
            
            # Apply aggregations
            for agg in aggregations:
                field = agg.get('field')
                func = agg.get('function')
                alias = agg.get('alias', f"{func}_{field}")
                
                values = [row.get(field) for row in group_rows if field in row]
                
                if func == 'count':
                    result_row[alias] = len(values)
                elif func == 'sum':
                    result_row[alias] = sum(float(v) for v in values if v is not None)
                elif func == 'avg':
                    numeric_values = [float(v) for v in values if v is not None]
                    result_row[alias] = sum(numeric_values) / len(numeric_values) if numeric_values else 0
                elif func == 'min':
                    result_row[alias] = min(values) if values else None
                elif func == 'max':
                    result_row[alias] = max(values) if values else None
                elif func == 'count_distinct':
                    result_row[alias] = len(set(values))
                elif func == 'first':
                    result_row[alias] = values[0] if values else None
                elif func == 'last':
                    result_row[alias] = values[-1] if values else None
            
            result_rows.append(result_row)
        
        # Update columns
        new_columns = group_by + [agg.get('alias', f"{agg['function']}_{agg['field']}") 
                                 for agg in aggregations]
        
        return {
            'columns': new_columns,
            'rows': result_rows,
            'row_count': len(result_rows)
        }
    
    def _apply_join(self, data: Dict, config: Dict) -> Dict:
        """Apply join transformation."""
        # This would join with another dataset
        # For now, return as is
        return data
    
    def _apply_pivot(self, data: Dict, config: Dict) -> Dict:
        """Apply pivot transformation."""
        rows = data.get('rows', [])
        index = config.get('index')  # Row identifier
        columns_field = config.get('columns')  # Field to pivot to columns
        values_field = config.get('values')  # Field containing values
        agg_func = config.get('agg_func', 'first')  # Aggregation function
        
        if not all([index, columns_field, values_field]):
            return data
        
        # Create pivot structure
        pivot_data = {}
        column_values = set()
        
        for row in rows:
            row_key = row.get(index)
            col_value = row.get(columns_field)
            value = row.get(values_field)
            
            if row_key and col_value:
                if row_key not in pivot_data:
                    pivot_data[row_key] = {index: row_key}
                
                column_values.add(col_value)
                
                # Handle aggregation if multiple values
                col_key = str(col_value)
                if col_key in pivot_data[row_key]:
                    # Aggregate values
                    existing = pivot_data[row_key][col_key]
                    if agg_func == 'sum':
                        pivot_data[row_key][col_key] = float(existing) + float(value)
                    elif agg_func == 'count':
                        pivot_data[row_key][col_key] = existing + 1
                    # Add more aggregation functions as needed
                else:
                    pivot_data[row_key][col_key] = value
        
        # Convert to rows
        result_rows = list(pivot_data.values())
        
        # Update columns
        new_columns = [index] + sorted(list(column_values))
        
        return {
            'columns': new_columns,
            'rows': result_rows,
            'row_count': len(result_rows)
        }
    
    def _apply_unpivot(self, data: Dict, config: Dict) -> Dict:
        """Apply unpivot transformation."""
        rows = data.get('rows', [])
        id_vars = config.get('id_vars', [])  # Columns to keep
        value_vars = config.get('value_vars', [])  # Columns to unpivot
        var_name = config.get('var_name', 'variable')
        value_name = config.get('value_name', 'value')
        
        if not value_vars:
            # If no value_vars specified, use all columns except id_vars
            if rows:
                all_cols = list(rows[0].keys())
                value_vars = [col for col in all_cols if col not in id_vars]
        
        result_rows = []
        
        for row in rows:
            # Create a row for each value variable
            for var in value_vars:
                if var in row:
                    new_row = {}
                    
                    # Copy id variables
                    for id_var in id_vars:
                        if id_var in row:
                            new_row[id_var] = row[id_var]
                    
                    # Add variable name and value
                    new_row[var_name] = var
                    new_row[value_name] = row[var]
                    
                    result_rows.append(new_row)
        
        # Update columns
        new_columns = id_vars + [var_name, value_name]
        
        return {
            'columns': new_columns,
            'rows': result_rows,
            'row_count': len(result_rows)
        }
    
    def _apply_calculation(self, data: Dict, config: Dict) -> Dict:
        """Apply calculation transformation."""
        rows = data.get('rows', [])
        calculations = config.get('calculations', [])
        
        for row in rows:
            for calc in calculations:
                field_name = calc.get('name')
                expression = calc.get('expression')
                
                if field_name and expression:
                    try:
                        # Evaluate expression with row context
                        # This is a simplified version - use a proper expression evaluator
                        result = self._evaluate_expression(expression, row)
                        row[field_name] = result
                    except Exception as e:
                        logger.error(f"Calculation error: {str(e)}")
                        row[field_name] = None
        
        # Update columns if new fields were added
        if rows and calculations:
            current_columns = list(data.get('columns', []))
            for calc in calculations:
                if calc['name'] not in current_columns:
                    current_columns.append(calc['name'])
            data['columns'] = current_columns
        
        return data
    
    def _apply_rename(self, data: Dict, config: Dict) -> Dict:
        """Apply rename transformation."""
        rows = data.get('rows', [])
        mapping = config.get('mapping', {})
        
        # Rename in rows
        for row in rows:
            for old_name, new_name in mapping.items():
                if old_name in row and old_name != new_name:
                    row[new_name] = row.pop(old_name)
        
        # Rename in columns
        columns = data.get('columns', [])
        new_columns = []
        for col in columns:
            new_columns.append(mapping.get(col, col))
        
        return {
            **data,
            'columns': new_columns,
            'rows': rows
        }
    
    def _apply_type_cast(self, data: Dict, config: Dict) -> Dict:
        """Apply type casting transformation."""
        rows = data.get('rows', [])
        casts = config.get('casts', {})
        
        for row in rows:
            for field, target_type in casts.items():
                if field in row:
                    try:
                        value = row[field]
                        
                        if target_type == 'int':
                            row[field] = int(value) if value is not None else None
                        elif target_type == 'float':
                            row[field] = float(value) if value is not None else None
                        elif target_type == 'str':
                            row[field] = str(value) if value is not None else ''
                        elif target_type == 'bool':
                            row[field] = bool(value) if value is not None else False
                        elif target_type == 'date':
                            if isinstance(value, str):
                                row[field] = datetime.strptime(value, '%Y-%m-%d').date()
                            elif isinstance(value, datetime):
                                row[field] = value.date()
                        elif target_type == 'datetime':
                            if isinstance(value, str):
                                row[field] = datetime.fromisoformat(value)
                        elif target_type == 'json':
                            if isinstance(value, str):
                                row[field] = json.loads(value)
                            else:
                                row[field] = value
                        
                    except Exception as e:
                        logger.warning(f"Type cast error for {field}: {str(e)}")
                        row[field] = None
        
        return data
    
    def _apply_cleaning(self, data: Dict, config: Dict) -> Dict:
        """Apply data cleaning transformation."""
        rows = data.get('rows', [])
        rules = config.get('rules', [])
        
        cleaned_rows = []
        for row in rows:
            cleaned_row = row.copy()
            skip_row = False
            
            for rule in rules:
                rule_type = rule.get('type')
                
                if rule_type == 'remove_nulls':
                    fields = rule.get('fields', [])
                    for field in fields:
                        if field in cleaned_row and cleaned_row[field] is None:
                            skip_row = True
                            break
                
                elif rule_type == 'trim':
                    fields = rule.get('fields', [])
                    for field in fields:
                        if field in cleaned_row and isinstance(cleaned_row[field], str):
                            cleaned_row[field] = cleaned_row[field].strip()
                
                elif rule_type == 'lowercase':
                    fields = rule.get('fields', [])
                    for field in fields:
                        if field in cleaned_row and isinstance(cleaned_row[field], str):
                            cleaned_row[field] = cleaned_row[field].lower()
                
                elif rule_type == 'uppercase':
                    fields = rule.get('fields', [])
                    for field in fields:
                        if field in cleaned_row and isinstance(cleaned_row[field], str):
                            cleaned_row[field] = cleaned_row[field].upper()
                
                elif rule_type == 'replace':
                    field = rule.get('field')
                    pattern = rule.get('pattern')
                    replacement = rule.get('replacement', '')
                    
                    if field in cleaned_row and isinstance(cleaned_row[field], str):
                        if rule.get('regex', False):
                            cleaned_row[field] = re.sub(pattern, replacement, cleaned_row[field])
                        else:
                            cleaned_row[field] = cleaned_row[field].replace(pattern, replacement)
                
                elif rule_type == 'remove_duplicates':
                    # This would need to track seen values across rows
                    pass
            
            if not skip_row:
                cleaned_rows.append(cleaned_row)
        
        return {
            **data,
            'rows': cleaned_rows,
            'row_count': len(cleaned_rows)
        }
    
    def _apply_enrichment(self, data: Dict, config: Dict) -> Dict:
        """Apply data enrichment transformation."""
        # This would add data from external sources
        # For now, return as is
        return data
    
    def _apply_custom_transformation(self, data: Dict, config: Dict) -> Dict:
        """Apply custom transformation."""
        # This would execute custom transformation logic
        # Could integrate with user-defined functions or scripts
        return data
    
    def _evaluate_conditions(self, row: Dict, conditions: List[Dict], operator: str = 'and') -> bool:
        """Evaluate filter conditions."""
        if not conditions:
            return True
        
        results = []
        for condition in conditions:
            field = condition.get('field')
            op = condition.get('operator', 'eq')
            value = condition.get('value')
            
            if field not in row:
                results.append(False)
                continue
            
            field_value = row[field]
            
            try:
                if op == 'eq':
                    results.append(field_value == value)
                elif op == 'ne':
                    results.append(field_value != value)
                elif op == 'gt':
                    results.append(float(field_value) > float(value))
                elif op == 'gte':
                    results.append(float(field_value) >= float(value))
                elif op == 'lt':
                    results.append(float(field_value) < float(value))
                elif op == 'lte':
                    results.append(float(field_value) <= float(value))
                elif op == 'contains':
                    results.append(str(value) in str(field_value))
                elif op == 'not_contains':
                    results.append(str(value) not in str(field_value))
                elif op == 'starts_with':
                    results.append(str(field_value).startswith(str(value)))
                elif op == 'ends_with':
                    results.append(str(field_value).endswith(str(value)))
                elif op == 'in':
                    results.append(field_value in value)
                elif op == 'not_in':
                    results.append(field_value not in value)
                elif op == 'is_null':
                    results.append(field_value is None)
                elif op == 'is_not_null':
                    results.append(field_value is not None)
                else:
                    results.append(True)
            except Exception:
                results.append(False)
        
        if operator == 'and':
            return all(results)
        elif operator == 'or':
            return any(results)
        else:
            return all(results)
    
    def _evaluate_expression(self, expression: str, context: Dict) -> Any:
        """Evaluate a calculation expression."""
        # This is a simplified expression evaluator
        # In production, use a proper expression parser/evaluator
        
        # Replace field references with values
        for field, value in context.items():
            # Handle different reference styles
            expression = expression.replace(f'{{{field}}}', str(value))
            expression = expression.replace(f'${field}', str(value))
            expression = expression.replace(f'[{field}]', str(value))
        
        # Define safe functions
        safe_functions = {
            'abs': abs,
            'round': round,
            'min': min,
            'max': max,
            'sum': sum,
            'len': len,
            'str': str,
            'int': int,
            'float': float,
            'upper': lambda x: str(x).upper(),
            'lower': lambda x: str(x).lower(),
            'strip': lambda x: str(x).strip(),
        }
        
        try:
            # Evaluate expression with restricted namespace
            result = eval(expression, {"__builtins__": {}}, safe_functions)
            return result
        except Exception as e:
            logger.error(f"Expression evaluation error: {str(e)}")
            raise


class DataPipelineExecutor:
    """Execute data transformation pipelines."""
    
    def __init__(self):
        self.transformation_service = TransformationService()
        self.query_executor = QueryExecutor()
    
    def execute_pipeline(self, pipeline_id: str, parameters: Dict = None) -> Dict:
        """Execute a data pipeline."""
        pipeline = DataPipeline.objects.get(id=pipeline_id)
        
        if pipeline.status not in ['active', 'draft']:
            raise ValueError(f"Pipeline {pipeline.name} is not active")
        
        start_time = datetime.now()
        
        try:
            # Get source data
            source_data = self._get_source_data(pipeline, parameters)
            
            # Apply transformations
            result_data = self._apply_pipeline_transformations(pipeline, source_data)
            
            # Save to target if configured
            if pipeline.target_data_source:
                self._save_to_target(pipeline, result_data)
            
            # Update pipeline stats
            pipeline.last_run = datetime.now()
            pipeline.last_success = datetime.now()
            pipeline.run_count += 1
            pipeline.save()
            
            return {
                'success': True,
                'pipeline': {
                    'id': str(pipeline.id),
                    'name': pipeline.name
                },
                'execution_time': (datetime.now() - start_time).total_seconds(),
                'row_count': result_data.get('row_count', 0),
                'data': result_data
            }
            
        except Exception as e:
            logger.error(f"Pipeline execution failed: {str(e)}")
            
            # Update error stats
            pipeline.last_run = datetime.now()
            pipeline.error_count += 1
            pipeline.save()
            
            raise
    
    def _get_source_data(self, pipeline: DataPipeline, parameters: Dict = None) -> Dict:
        """Get data from source data sources."""
        combined_data = {
            'columns': [],
            'rows': [],
            'row_count': 0
        }
        
        for source in pipeline.source_data_sources.all():
            # Execute default query for the source
            # In a real implementation, this would be configured
            query = "SELECT * FROM data LIMIT 1000"  # Example query
            
            try:
                result = self.query_executor.execute(source, query, parameters)
                
                # Combine results (simple concatenation for now)
                if not combined_data['columns']:
                    combined_data['columns'] = result.get('columns', [])
                
                combined_data['rows'].extend(result.get('rows', []))
                combined_data['row_count'] += result.get('row_count', 0)
                
            except Exception as e:
                logger.error(f"Failed to get data from source {source.name}: {str(e)}")
                if not pipeline.parallel_execution:
                    raise
        
        return combined_data
    
    def _apply_pipeline_transformations(self, pipeline: DataPipeline, data: Dict) -> Dict:
        """Apply all pipeline transformations."""
        transformations = pipeline.transformations.filter(
            is_active=True
        ).order_by('order')
        
        result = data
        
        for transformation in transformations:
            try:
                # Convert transformation model to config dict
                config = transformation.configuration
                config['type'] = transformation.type
                
                # Apply transformation
                result = self.transformation_service.transform_data(
                    result,
                    [config]
                )
                
            except Exception as e:
                logger.error(f"Transformation {transformation.name} failed: {str(e)}")
                if not transformation.skip_on_error:
                    raise
        
        return result
    
    def _save_to_target(self, pipeline: DataPipeline, data: Dict):
        """Save transformed data to target data source."""
        # This would implement saving logic based on target type
        # For now, just log
        logger.info(f"Would save {data['row_count']} rows to {pipeline.target_data_source.name}")


@shared_task
def execute_pipeline_task(pipeline_id: str, parameters: Dict = None):
    """Celery task to execute a pipeline."""
    executor = DataPipelineExecutor()
    return executor.execute_pipeline(pipeline_id, parameters)