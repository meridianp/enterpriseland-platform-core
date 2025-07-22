"""Analytics service for metrics, calculations, and monitoring."""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from django.db import models, transaction
from django.db.models import Avg, Sum, Count, Max, Min, StdDev, Variance, Q, F
from django.utils import timezone
from django.core.cache import cache
import statistics

from ..models import (
    Metric, MetricCalculation, Alert, AlertCondition,
    DataSource, QueryDefinition
)
from .data_service import QueryExecutor
from .notification_service import NotificationService

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for analytics operations."""
    
    def __init__(self):
        self.metric_calculator = MetricCalculator()
        self.alert_monitor = AlertMonitor()
    
    def calculate_metrics(self, metric_ids: List[str], parameters: Dict = None) -> List[Dict]:
        """Calculate multiple metrics."""
        results = []
        
        for metric_id in metric_ids:
            try:
                metric = Metric.objects.get(id=metric_id)
                result = self.metric_calculator.calculate(metric, parameters)
                results.append({
                    'metric_id': metric_id,
                    'success': True,
                    'result': result
                })
            except Exception as e:
                logger.error(f"Error calculating metric {metric_id}: {str(e)}")
                results.append({
                    'metric_id': metric_id,
                    'success': False,
                    'error': str(e)
                })
        
        return results
    
    def run_analytics_query(self, query_config: Dict) -> Dict:
        """Run an analytics query."""
        analysis_type = query_config.get('type')
        
        if analysis_type == 'time_series':
            return self._run_time_series_analysis(query_config)
        elif analysis_type == 'cohort':
            return self._run_cohort_analysis(query_config)
        elif analysis_type == 'funnel':
            return self._run_funnel_analysis(query_config)
        elif analysis_type == 'correlation':
            return self._run_correlation_analysis(query_config)
        else:
            raise ValueError(f"Unknown analysis type: {analysis_type}")
    
    def _run_time_series_analysis(self, config: Dict) -> Dict:
        """Run time series analysis."""
        # Extract configuration
        metric_id = config.get('metric_id')
        start_date = config.get('start_date')
        end_date = config.get('end_date')
        interval = config.get('interval', 'day')  # day, week, month
        
        metric = Metric.objects.get(id=metric_id)
        
        # Get historical calculations
        calculations = MetricCalculation.objects.filter(
            metric=metric,
            timestamp__range=[start_date, end_date]
        ).order_by('timestamp')
        
        # Group by interval
        grouped_data = self._group_by_interval(calculations, interval)
        
        # Calculate statistics
        values = [calc.value for calc in calculations]
        
        return {
            'metric': {
                'id': str(metric.id),
                'name': metric.display_name
            },
            'time_series': grouped_data,
            'statistics': {
                'mean': statistics.mean(values) if values else 0,
                'median': statistics.median(values) if values else 0,
                'std_dev': statistics.stdev(values) if len(values) > 1 else 0,
                'min': min(values) if values else 0,
                'max': max(values) if values else 0,
                'trend': self._calculate_trend(grouped_data)
            }
        }
    
    def _run_cohort_analysis(self, config: Dict) -> Dict:
        """Run cohort analysis."""
        # This would implement cohort analysis logic
        # For now, return a placeholder
        return {
            'type': 'cohort',
            'cohorts': [],
            'retention_matrix': []
        }
    
    def _run_funnel_analysis(self, config: Dict) -> Dict:
        """Run funnel analysis."""
        # This would implement funnel analysis logic
        # For now, return a placeholder
        return {
            'type': 'funnel',
            'steps': [],
            'conversion_rates': []
        }
    
    def _run_correlation_analysis(self, config: Dict) -> Dict:
        """Run correlation analysis between metrics."""
        metric_ids = config.get('metric_ids', [])
        start_date = config.get('start_date')
        end_date = config.get('end_date')
        
        # Get metrics
        metrics = Metric.objects.filter(id__in=metric_ids)
        
        # Get calculations for each metric
        metric_data = {}
        for metric in metrics:
            calculations = MetricCalculation.objects.filter(
                metric=metric,
                timestamp__range=[start_date, end_date]
            ).order_by('timestamp').values('timestamp', 'value')
            
            metric_data[str(metric.id)] = {
                'name': metric.display_name,
                'values': list(calculations)
            }
        
        # Calculate correlations
        correlations = self._calculate_correlations(metric_data)
        
        return {
            'type': 'correlation',
            'metrics': metric_data,
            'correlations': correlations
        }
    
    def _group_by_interval(self, calculations, interval: str) -> List[Dict]:
        """Group calculations by time interval."""
        grouped = {}
        
        for calc in calculations:
            if interval == 'day':
                key = calc.timestamp.date()
            elif interval == 'week':
                key = calc.timestamp.isocalendar()[1]  # Week number
            elif interval == 'month':
                key = calc.timestamp.strftime('%Y-%m')
            else:
                key = calc.timestamp.date()
            
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(calc.value)
        
        # Calculate aggregates for each group
        result = []
        for key, values in sorted(grouped.items()):
            result.append({
                'period': str(key),
                'value': statistics.mean(values),
                'count': len(values),
                'sum': sum(values),
                'min': min(values),
                'max': max(values)
            })
        
        return result
    
    def _calculate_trend(self, time_series: List[Dict]) -> str:
        """Calculate trend direction."""
        if len(time_series) < 2:
            return 'stable'
        
        # Simple trend calculation - compare first and last thirds
        third = len(time_series) // 3
        if third == 0:
            return 'stable'
        
        first_third_avg = statistics.mean([d['value'] for d in time_series[:third]])
        last_third_avg = statistics.mean([d['value'] for d in time_series[-third:]])
        
        change_percent = ((last_third_avg - first_third_avg) / first_third_avg) * 100
        
        if change_percent > 5:
            return 'increasing'
        elif change_percent < -5:
            return 'decreasing'
        else:
            return 'stable'
    
    def _calculate_correlations(self, metric_data: Dict) -> List[Dict]:
        """Calculate correlation coefficients between metrics."""
        correlations = []
        metric_ids = list(metric_data.keys())
        
        for i in range(len(metric_ids)):
            for j in range(i + 1, len(metric_ids)):
                metric1_id = metric_ids[i]
                metric2_id = metric_ids[j]
                
                # Align values by timestamp
                values1 = metric_data[metric1_id]['values']
                values2 = metric_data[metric2_id]['values']
                
                aligned_values = self._align_time_series(values1, values2)
                
                if len(aligned_values) > 1:
                    # Calculate Pearson correlation
                    x_values = [v[0] for v in aligned_values]
                    y_values = [v[1] for v in aligned_values]
                    
                    correlation = self._pearson_correlation(x_values, y_values)
                    
                    correlations.append({
                        'metric1': {
                            'id': metric1_id,
                            'name': metric_data[metric1_id]['name']
                        },
                        'metric2': {
                            'id': metric2_id,
                            'name': metric_data[metric2_id]['name']
                        },
                        'correlation': correlation,
                        'strength': self._correlation_strength(correlation)
                    })
        
        return correlations
    
    def _align_time_series(self, values1: List[Dict], values2: List[Dict]) -> List[Tuple]:
        """Align two time series by timestamp."""
        # Create dictionaries for fast lookup
        dict1 = {v['timestamp']: v['value'] for v in values1}
        dict2 = {v['timestamp']: v['value'] for v in values2}
        
        # Find common timestamps
        common_timestamps = set(dict1.keys()) & set(dict2.keys())
        
        # Create aligned pairs
        aligned = []
        for ts in sorted(common_timestamps):
            aligned.append((dict1[ts], dict2[ts]))
        
        return aligned
    
    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        n = len(x)
        if n == 0:
            return 0
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_x_sq = sum(xi**2 for xi in x)
        sum_y_sq = sum(yi**2 for yi in y)
        sum_xy = sum(xi*yi for xi, yi in zip(x, y))
        
        numerator = n * sum_xy - sum_x * sum_y
        denominator = ((n * sum_x_sq - sum_x**2) * (n * sum_y_sq - sum_y**2)) ** 0.5
        
        if denominator == 0:
            return 0
        
        return numerator / denominator
    
    def _correlation_strength(self, correlation: float) -> str:
        """Determine correlation strength."""
        abs_corr = abs(correlation)
        
        if abs_corr >= 0.7:
            return 'strong'
        elif abs_corr >= 0.4:
            return 'moderate'
        elif abs_corr >= 0.2:
            return 'weak'
        else:
            return 'negligible'


class MetricCalculator:
    """Service for calculating metric values."""
    
    def __init__(self):
        self.query_executor = QueryExecutor()
    
    def calculate(self, metric: Metric, parameters: Dict = None) -> Dict:
        """Calculate a metric value."""
        cache_key = f"metric_value:{metric.id}:{hash(str(parameters))}"
        cached_value = cache.get(cache_key)
        
        if cached_value:
            return cached_value
        
        try:
            if metric.type == 'simple':
                value = self._calculate_simple_metric(metric, parameters)
            elif metric.type == 'calculated':
                value = self._calculate_calculated_metric(metric, parameters)
            elif metric.type == 'composite':
                value = self._calculate_composite_metric(metric, parameters)
            elif metric.type == 'derived':
                value = self._calculate_derived_metric(metric, parameters)
            elif metric.type == 'predictive':
                value = self._calculate_predictive_metric(metric, parameters)
            else:
                raise ValueError(f"Unknown metric type: {metric.type}")
            
            # Format the value
            formatted_value = self._format_value(metric, value)
            
            # Check thresholds
            status = self._check_thresholds(metric, value)
            
            # Get previous value for trend
            previous_value = self._get_previous_value(metric)
            trend = self._calculate_trend_info(value, previous_value)
            
            # Save calculation
            self._save_calculation(metric, value, previous_value)
            
            result = {
                'value': value,
                'formatted_value': formatted_value,
                'status': status,
                'trend': trend,
                'calculated_at': timezone.now().isoformat()
            }
            
            # Cache the result
            cache.set(cache_key, result, 300)  # 5 minutes
            
            return result
            
        except Exception as e:
            logger.error(f"Error calculating metric {metric.id}: {str(e)}")
            raise
    
    def _calculate_simple_metric(self, metric: Metric, parameters: Dict = None) -> float:
        """Calculate a simple metric."""
        if not metric.data_source:
            raise ValueError("Simple metric requires a data source")
        
        # Build query based on metric configuration
        if metric.aggregation == 'count':
            query = f"SELECT COUNT({metric.column_name or '*'}) as value FROM {metric.table_name}"
        elif metric.aggregation == 'distinct':
            query = f"SELECT COUNT(DISTINCT {metric.column_name}) as value FROM {metric.table_name}"
        else:
            query = f"SELECT {metric.aggregation.upper()}({metric.column_name}) as value FROM {metric.table_name}"
        
        # Add filters
        if metric.filters:
            conditions = []
            for filter_def in metric.filters:
                field = filter_def.get('field')
                operator = filter_def.get('operator', '=')
                value = filter_def.get('value')
                
                if operator == 'eq':
                    conditions.append(f"{field} = '{value}'")
                elif operator == 'gt':
                    conditions.append(f"{field} > {value}")
                elif operator == 'lt':
                    conditions.append(f"{field} < {value}")
                # Add more operators as needed
            
            if conditions:
                query += f" WHERE {' AND '.join(conditions)}"
        
        # Execute query
        result = self.query_executor.execute(metric.data_source, query, parameters)
        
        if result['rows']:
            return float(result['rows'][0].get('value', 0))
        return 0
    
    def _calculate_calculated_metric(self, metric: Metric, parameters: Dict = None) -> float:
        """Calculate a calculated metric using a formula."""
        if not metric.formula:
            raise ValueError("Calculated metric requires a formula")
        
        # Parse formula and extract referenced metrics
        # This is a simplified implementation
        # In production, use a proper expression parser
        
        formula = metric.formula
        context = {}
        
        # Find referenced metrics (e.g., {metric_id})
        import re
        referenced_metrics = re.findall(r'\{([^}]+)\}', formula)
        
        for ref_metric_id in referenced_metrics:
            try:
                ref_metric = Metric.objects.get(id=ref_metric_id)
                ref_value = self.calculate(ref_metric, parameters)['value']
                context[ref_metric_id] = ref_value
                formula = formula.replace(f'{{{ref_metric_id}}}', str(ref_value))
            except Metric.DoesNotExist:
                logger.error(f"Referenced metric not found: {ref_metric_id}")
                context[ref_metric_id] = 0
                formula = formula.replace(f'{{{ref_metric_id}}}', '0')
        
        # Evaluate formula safely
        try:
            # Use eval with restricted namespace for safety
            allowed_names = {
                'abs': abs,
                'min': min,
                'max': max,
                'sum': sum,
                'len': len,
                'round': round,
            }
            allowed_names.update(context)
            
            value = eval(formula, {"__builtins__": {}}, allowed_names)
            return float(value)
        except Exception as e:
            logger.error(f"Error evaluating formula: {formula}, error: {str(e)}")
            raise
    
    def _calculate_composite_metric(self, metric: Metric, parameters: Dict = None) -> float:
        """Calculate a composite metric from multiple metrics."""
        # This would aggregate multiple metrics
        # Implementation depends on specific requirements
        return 0
    
    def _calculate_derived_metric(self, metric: Metric, parameters: Dict = None) -> float:
        """Calculate a derived metric."""
        # This would derive value from other data
        # Implementation depends on specific requirements
        return 0
    
    def _calculate_predictive_metric(self, metric: Metric, parameters: Dict = None) -> float:
        """Calculate a predictive metric using ML models."""
        # This would use machine learning models
        # Implementation depends on specific requirements
        return 0
    
    def _format_value(self, metric: Metric, value: float) -> str:
        """Format metric value based on format type."""
        if metric.format == 'number':
            return f"{metric.prefix}{value:,.{metric.decimals}f}{metric.suffix}"
        elif metric.format == 'currency':
            return f"{metric.prefix}${value:,.{metric.decimals}f}{metric.suffix}"
        elif metric.format == 'percentage':
            return f"{metric.prefix}{value:.{metric.decimals}f}%{metric.suffix}"
        elif metric.format == 'duration':
            # Convert to human-readable duration
            hours = int(value // 3600)
            minutes = int((value % 3600) // 60)
            seconds = int(value % 60)
            return f"{hours}h {minutes}m {seconds}s"
        elif metric.format == 'boolean':
            return "Yes" if value else "No"
        elif metric.format == 'rating':
            return "★" * int(value) + "☆" * (5 - int(value))
        else:
            return f"{metric.prefix}{value}{metric.suffix}"
    
    def _check_thresholds(self, metric: Metric, value: float) -> str:
        """Check metric value against thresholds."""
        if metric.min_threshold is not None and value < metric.min_threshold:
            return 'critical'
        elif metric.warning_threshold is not None and value < metric.warning_threshold:
            return 'warning'
        elif metric.max_threshold is not None and value > metric.max_threshold:
            return 'critical'
        elif metric.target_value is not None:
            # Check distance from target
            distance = abs(value - metric.target_value)
            tolerance = metric.target_value * 0.1  # 10% tolerance
            if distance <= tolerance:
                return 'good'
            else:
                return 'warning'
        else:
            return 'normal'
    
    def _get_previous_value(self, metric: Metric) -> Optional[float]:
        """Get previous calculated value for trend analysis."""
        previous = MetricCalculation.objects.filter(
            metric=metric
        ).order_by('-timestamp').first()
        
        return previous.value if previous else None
    
    def _calculate_trend_info(self, current_value: float, previous_value: Optional[float]) -> Dict:
        """Calculate trend information."""
        if previous_value is None:
            return {
                'direction': 'stable',
                'change_value': 0,
                'change_percentage': 0
            }
        
        change_value = current_value - previous_value
        change_percentage = (change_value / previous_value * 100) if previous_value != 0 else 0
        
        if change_percentage > 5:
            direction = 'up'
        elif change_percentage < -5:
            direction = 'down'
        else:
            direction = 'stable'
        
        return {
            'direction': direction,
            'change_value': change_value,
            'change_percentage': change_percentage
        }
    
    def _save_calculation(self, metric: Metric, value: float, previous_value: Optional[float]):
        """Save metric calculation to history."""
        change_value = 0
        change_percentage = 0
        
        if previous_value is not None:
            change_value = value - previous_value
            change_percentage = (change_value / previous_value * 100) if previous_value != 0 else 0
        
        MetricCalculation.objects.create(
            metric=metric,
            timestamp=timezone.now(),
            value=value,
            previous_value=previous_value,
            change_value=change_value,
            change_percentage=change_percentage,
            calculation_time=0.1,  # This would be actual calculation time
            period='current'
        )
    
    def get_history(self, metric: Metric, days: int = 7) -> List[Dict]:
        """Get metric calculation history."""
        start_date = timezone.now() - timedelta(days=days)
        
        calculations = MetricCalculation.objects.filter(
            metric=metric,
            timestamp__gte=start_date
        ).order_by('timestamp').values(
            'timestamp', 'value', 'change_value', 'change_percentage'
        )
        
        return [
            {
                'timestamp': calc['timestamp'].isoformat(),
                'value': calc['value'],
                'change_value': calc['change_value'],
                'change_percentage': calc['change_percentage']
            }
            for calc in calculations
        ]


class AlertMonitor:
    """Service for monitoring alerts."""
    
    def __init__(self):
        self.notification_service = NotificationService()
    
    def check_alerts(self):
        """Check all active alerts."""
        alerts = Alert.objects.filter(
            status__in=['active', 'triggered'],
            metric__isnull=False
        ).select_related('metric')
        
        for alert in alerts:
            # Check if it's time to check this alert
            if self._should_check_alert(alert):
                try:
                    self._check_alert(alert)
                except Exception as e:
                    logger.error(f"Error checking alert {alert.id}: {str(e)}")
    
    def _should_check_alert(self, alert: Alert) -> bool:
        """Determine if alert should be checked."""
        if not alert.last_checked:
            return True
        
        time_since_check = (timezone.now() - alert.last_checked).total_seconds()
        return time_since_check >= alert.check_interval
    
    def _check_alert(self, alert: Alert):
        """Check a single alert."""
        # Get latest metric value
        calculator = MetricCalculator()
        result = calculator.calculate(alert.metric)
        
        # Create a metric calculation object for checking
        calculation = MetricCalculation(
            metric=alert.metric,
            timestamp=timezone.now(),
            value=result['value'],
            change_value=result['trend']['change_value'],
            change_percentage=result['trend']['change_percentage']
        )
        
        # Check conditions
        triggered = self.check_conditions(alert, calculation)
        
        # Update alert
        alert.last_checked = timezone.now()
        
        if triggered:
            if alert.status != 'triggered':
                alert.status = 'triggered'
                alert.last_triggered = timezone.now()
                alert.trigger_count += 1
                
                # Send notifications
                self.send_alert_notifications(alert, calculation)
        else:
            if alert.status == 'triggered':
                # Check cooldown period
                if alert.last_triggered:
                    time_since_trigger = (timezone.now() - alert.last_triggered).total_seconds()
                    if time_since_trigger >= alert.cooldown_period:
                        alert.status = 'active'
        
        alert.save()
    
    def check_conditions(self, alert: Alert, calculation: MetricCalculation) -> bool:
        """Check if alert conditions are met."""
        conditions = alert.conditions.all()
        
        if not conditions:
            return False
        
        results = []
        current_operator = 'and'
        
        for condition in conditions:
            result = self._evaluate_condition(condition, calculation)
            results.append(result)
            
            # Handle logical operators
            if condition.combine_with == 'or' and result:
                return True  # Short circuit OR
            elif condition.combine_with == 'and' and not result:
                return False  # Short circuit AND
        
        # If we get here, all AND conditions passed
        return all(results)
    
    def _evaluate_condition(self, condition: AlertCondition, calculation: MetricCalculation) -> bool:
        """Evaluate a single alert condition."""
        # Get the field value
        if condition.field == 'value':
            field_value = calculation.value
        elif condition.field == 'change_value':
            field_value = calculation.change_value
        elif condition.field == 'change_percentage':
            field_value = calculation.change_percentage
        else:
            return False
        
        # Apply timeframe if needed
        if condition.timeframe != 'current':
            # This would aggregate over the timeframe
            # For now, use current value
            pass
        
        # Evaluate operator
        try:
            value = float(condition.value)
            
            if condition.operator == 'eq':
                return field_value == value
            elif condition.operator == 'ne':
                return field_value != value
            elif condition.operator == 'gt':
                return field_value > value
            elif condition.operator == 'gte':
                return field_value >= value
            elif condition.operator == 'lt':
                return field_value < value
            elif condition.operator == 'lte':
                return field_value <= value
            elif condition.operator == 'between':
                value2 = float(condition.value2)
                return value <= field_value <= value2
            elif condition.operator == 'not_between':
                value2 = float(condition.value2)
                return not (value <= field_value <= value2)
            elif condition.operator == 'trend_up':
                return calculation.change_percentage > value
            elif condition.operator == 'trend_down':
                return calculation.change_percentage < -value
            else:
                return False
                
        except (ValueError, TypeError):
            return False
    
    def send_alert_notifications(self, alert: Alert, calculation: MetricCalculation):
        """Send notifications for triggered alert."""
        context = {
            'alert_name': alert.name,
            'metric_name': alert.metric.display_name,
            'current_value': calculation.value,
            'formatted_value': alert.metric.format_value(calculation.value),
            'change_value': calculation.change_value,
            'change_percentage': calculation.change_percentage,
            'severity': alert.severity,
            'triggered_at': timezone.now().isoformat()
        }
        
        for channel in alert.notification_channels:
            try:
                if channel == 'email':
                    self._send_email_notification(alert, context)
                elif channel == 'sms':
                    self._send_sms_notification(alert, context)
                elif channel == 'webhook':
                    self._send_webhook_notification(alert, context)
                elif channel == 'in_app':
                    self._send_in_app_notification(alert, context)
                elif channel == 'slack':
                    self._send_slack_notification(alert, context)
                elif channel == 'teams':
                    self._send_teams_notification(alert, context)
            except Exception as e:
                logger.error(f"Error sending {channel} notification for alert {alert.id}: {str(e)}")
    
    def _send_email_notification(self, alert: Alert, context: Dict):
        """Send email notification."""
        subject = f"[{alert.severity.upper()}] {alert.name}"
        
        message = f"""
Alert Triggered: {alert.name}

Metric: {context['metric_name']}
Current Value: {context['formatted_value']}
Change: {context['change_value']} ({context['change_percentage']:.1f}%)

Description: {alert.description}

Triggered at: {context['triggered_at']}
        """
        
        for recipient in alert.recipients:
            if '@' in recipient:  # Email address
                self.notification_service.send_email(
                    to=recipient,
                    subject=subject,
                    body=message
                )
    
    def _send_webhook_notification(self, alert: Alert, context: Dict):
        """Send webhook notification."""
        import requests
        
        for webhook_url in alert.recipients:
            if webhook_url.startswith('http'):
                payload = {
                    'alert': {
                        'id': str(alert.id),
                        'name': alert.name,
                        'severity': alert.severity
                    },
                    'metric': {
                        'name': context['metric_name'],
                        'value': context['current_value'],
                        'formatted_value': context['formatted_value']
                    },
                    'triggered_at': context['triggered_at']
                }
                
                try:
                    response = requests.post(webhook_url, json=payload, timeout=10)
                    response.raise_for_status()
                except Exception as e:
                    logger.error(f"Webhook notification failed: {str(e)}")
    
    def _send_slack_notification(self, alert: Alert, context: Dict):
        """Send Slack notification."""
        # This would integrate with Slack API
        pass
    
    def _send_teams_notification(self, alert: Alert, context: Dict):
        """Send Microsoft Teams notification."""
        # This would integrate with Teams API
        pass
    
    def _send_sms_notification(self, alert: Alert, context: Dict):
        """Send SMS notification."""
        # This would integrate with SMS service
        pass
    
    def _send_in_app_notification(self, alert: Alert, context: Dict):
        """Send in-app notification."""
        # This would create notifications in the application
        pass


class QueryBuilder:
    """Service for building queries interactively."""
    
    def __init__(self, data_source: DataSource):
        self.data_source = data_source
    
    def build(self, query_type: str, config: Dict) -> str:
        """Build a query based on configuration."""
        if query_type == 'sql':
            return self._build_sql_query(config)
        elif query_type == 'nosql':
            return self._build_nosql_query(config)
        elif query_type == 'api':
            return self._build_api_query(config)
        else:
            raise ValueError(f"Unsupported query type: {query_type}")
    
    def _build_sql_query(self, config: Dict) -> str:
        """Build SQL query from configuration."""
        # Extract configuration
        select_fields = config.get('select', ['*'])
        from_table = config.get('from')
        joins = config.get('joins', [])
        where_conditions = config.get('where', [])
        group_by = config.get('group_by', [])
        having_conditions = config.get('having', [])
        order_by = config.get('order_by', [])
        limit = config.get('limit')
        
        # Build SELECT clause
        select_clause = f"SELECT {', '.join(select_fields)}"
        
        # Build FROM clause
        from_clause = f"FROM {from_table}"
        
        # Build JOIN clauses
        join_clauses = []
        for join in joins:
            join_type = join.get('type', 'INNER')
            join_table = join.get('table')
            join_on = join.get('on')
            join_clauses.append(f"{join_type} JOIN {join_table} ON {join_on}")
        
        # Build WHERE clause
        where_clause = ""
        if where_conditions:
            conditions = []
            for condition in where_conditions:
                field = condition.get('field')
                operator = condition.get('operator', '=')
                value = condition.get('value')
                
                if operator in ['in', 'not in']:
                    value_list = ', '.join([f"'{v}'" for v in value])
                    conditions.append(f"{field} {operator.upper()} ({value_list})")
                else:
                    conditions.append(f"{field} {operator} '{value}'")
            
            where_clause = f"WHERE {' AND '.join(conditions)}"
        
        # Build GROUP BY clause
        group_by_clause = ""
        if group_by:
            group_by_clause = f"GROUP BY {', '.join(group_by)}"
        
        # Build HAVING clause
        having_clause = ""
        if having_conditions:
            conditions = []
            for condition in having_conditions:
                aggregate = condition.get('aggregate')
                operator = condition.get('operator', '>')
                value = condition.get('value')
                conditions.append(f"{aggregate} {operator} {value}")
            
            having_clause = f"HAVING {' AND '.join(conditions)}"
        
        # Build ORDER BY clause
        order_by_clause = ""
        if order_by:
            order_parts = []
            for order in order_by:
                field = order.get('field')
                direction = order.get('direction', 'ASC')
                order_parts.append(f"{field} {direction}")
            
            order_by_clause = f"ORDER BY {', '.join(order_parts)}"
        
        # Build LIMIT clause
        limit_clause = ""
        if limit:
            limit_clause = f"LIMIT {limit}"
        
        # Combine all clauses
        query_parts = [
            select_clause,
            from_clause,
        ]
        query_parts.extend(join_clauses)
        
        if where_clause:
            query_parts.append(where_clause)
        if group_by_clause:
            query_parts.append(group_by_clause)
        if having_clause:
            query_parts.append(having_clause)
        if order_by_clause:
            query_parts.append(order_by_clause)
        if limit_clause:
            query_parts.append(limit_clause)
        
        return '\n'.join(query_parts)
    
    def _build_nosql_query(self, config: Dict) -> str:
        """Build NoSQL query from configuration."""
        # This would build MongoDB-style queries
        import json
        
        query = {
            'collection': config.get('collection'),
            'operation': config.get('operation', 'find'),
        }
        
        if query['operation'] == 'find':
            query['filter'] = config.get('filter', {})
            query['projection'] = config.get('projection')
            query['sort'] = config.get('sort')
            query['limit'] = config.get('limit')
        elif query['operation'] == 'aggregate':
            query['pipeline'] = config.get('pipeline', [])
        
        return json.dumps(query)
    
    def _build_api_query(self, config: Dict) -> str:
        """Build API query from configuration."""
        import json
        
        query = {
            'method': config.get('method', 'GET'),
            'endpoint': config.get('endpoint'),
            'params': config.get('params', {}),
            'data': config.get('data'),
        }
        
        return json.dumps(query)
    
    def validate(self, query: str) -> Dict:
        """Validate a query."""
        errors = []
        warnings = []
        
        # Basic validation
        if not query or not query.strip():
            errors.append("Query cannot be empty")
        
        # Type-specific validation
        if self.data_source.type in ['postgresql', 'mysql']:
            # SQL validation
            dangerous_keywords = ['DROP', 'DELETE', 'TRUNCATE', 'ALTER']
            query_upper = query.upper()
            
            for keyword in dangerous_keywords:
                if keyword in query_upper:
                    warnings.append(f"Query contains potentially dangerous keyword: {keyword}")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
    
    def estimate_cost(self, query: str) -> Dict:
        """Estimate query execution cost."""
        # This would analyze the query and estimate execution time/resources
        # For now, return a simple estimate
        
        return {
            'estimated_rows': 1000,
            'estimated_time': 0.5,
            'estimated_cost': 'low'
        }