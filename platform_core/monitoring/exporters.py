"""
Metrics Exporters

Export metrics to various monitoring systems.
"""

import json
import time
import requests
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod
from datetime import datetime
import logging

from .metrics import MetricsRegistry, metrics_registry

logger = logging.getLogger(__name__)


class MetricsExporter(ABC):
    """Base class for metrics exporters."""
    
    def __init__(self, registry: Optional[MetricsRegistry] = None):
        self.registry = registry or metrics_registry
        self._enabled = True
    
    @abstractmethod
    def export(self, metrics: List[Dict[str, Any]]) -> bool:
        """Export metrics to target system."""
        pass
    
    def export_all(self) -> bool:
        """Export all metrics from registry."""
        if not self._enabled:
            return False
        
        try:
            metrics = self.registry.collect()
            return self.export(metrics)
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return False
    
    def enable(self):
        """Enable exporter."""
        self._enabled = True
    
    def disable(self):
        """Disable exporter."""
        self._enabled = False


class PrometheusExporter(MetricsExporter):
    """Export metrics in Prometheus format."""
    
    def __init__(self, registry: Optional[MetricsRegistry] = None):
        super().__init__(registry)
        self._metrics_cache = []
    
    def export(self, metrics: List[Dict[str, Any]]) -> bool:
        """Export metrics in Prometheus format."""
        try:
            self._metrics_cache = metrics
            return True
        except Exception as e:
            logger.error(f"Prometheus export failed: {e}")
            return False
    
    def generate_text(self) -> str:
        """Generate Prometheus text format."""
        lines = []
        
        for metric in self._metrics_cache:
            # Add help text
            if metric.get('description'):
                lines.append(f"# HELP {metric['name']} {metric['description']}")
            
            # Add type
            metric_type = metric.get('type', 'gauge').lower()
            if metric_type == 'counter':
                prom_type = 'counter'
            elif metric_type == 'histogram':
                prom_type = 'histogram'
            elif metric_type == 'timer':
                prom_type = 'histogram'
            else:
                prom_type = 'gauge'
            
            lines.append(f"# TYPE {metric['name']} {prom_type}")
            
            # Format labels
            labels = metric.get('labels', {})
            label_str = ''
            if labels:
                label_parts = [f'{k}="{v}"' for k, v in labels.items()]
                label_str = '{' + ','.join(label_parts) + '}'
            
            # Add metric value(s)
            value = metric.get('value')
            
            if isinstance(value, dict) and metric_type in ['histogram', 'timer']:
                # Histogram/Timer metrics
                base_name = metric['name']
                
                # Bucket values
                for bucket, count in value.get('buckets', {}).items():
                    bucket_val = bucket.replace('le_', '')
                    bucket_labels = labels.copy()
                    bucket_labels['le'] = bucket_val
                    bucket_label_str = '{' + ','.join(f'{k}="{v}"' for k, v in bucket_labels.items()) + '}'
                    lines.append(f"{base_name}_bucket{bucket_label_str} {count}")
                
                # Sum and count
                lines.append(f"{base_name}_sum{label_str} {value.get('sum', 0)}")
                lines.append(f"{base_name}_count{label_str} {value.get('count', 0)}")
                
            else:
                # Simple value
                lines.append(f"{metric['name']}{label_str} {value}")
        
        return '\n'.join(lines) + '\n'


class JSONExporter(MetricsExporter):
    """Export metrics as JSON."""
    
    def __init__(self, registry: Optional[MetricsRegistry] = None, output_file: Optional[str] = None):
        super().__init__(registry)
        self.output_file = output_file
    
    def export(self, metrics: List[Dict[str, Any]]) -> bool:
        """Export metrics as JSON."""
        try:
            data = {
                'timestamp': datetime.now().isoformat(),
                'metrics': metrics
            }
            
            if self.output_file:
                with open(self.output_file, 'w') as f:
                    json.dump(data, f, indent=2)
            else:
                # Log to stdout
                print(json.dumps(data, indent=2))
            
            return True
        except Exception as e:
            logger.error(f"JSON export failed: {e}")
            return False


class CloudWatchExporter(MetricsExporter):
    """Export metrics to AWS CloudWatch."""
    
    def __init__(
        self,
        registry: Optional[MetricsRegistry] = None,
        namespace: str = 'EnterpriseLand',
        region: str = 'us-east-1'
    ):
        super().__init__(registry)
        self.namespace = namespace
        self.region = region
        self._client = None
    
    def _get_client(self):
        """Get CloudWatch client."""
        if not self._client:
            try:
                import boto3
                self._client = boto3.client('cloudwatch', region_name=self.region)
            except ImportError:
                logger.error("boto3 not installed")
        return self._client
    
    def export(self, metrics: List[Dict[str, Any]]) -> bool:
        """Export metrics to CloudWatch."""
        client = self._get_client()
        if not client:
            return False
        
        try:
            # Convert metrics to CloudWatch format
            metric_data = []
            
            for metric in metrics:
                # Skip complex metrics
                value = metric.get('value')
                if isinstance(value, dict):
                    continue
                
                # Build metric data
                data_point = {
                    'MetricName': metric['name'],
                    'Value': float(value),
                    'Timestamp': datetime.now(),
                    'Unit': 'None'
                }
                
                # Add dimensions from labels
                if metric.get('labels'):
                    data_point['Dimensions'] = [
                        {'Name': k, 'Value': str(v)}
                        for k, v in metric['labels'].items()
                    ]
                
                metric_data.append(data_point)
            
            # Send in batches of 20 (CloudWatch limit)
            for i in range(0, len(metric_data), 20):
                batch = metric_data[i:i+20]
                client.put_metric_data(
                    Namespace=self.namespace,
                    MetricData=batch
                )
            
            return True
            
        except Exception as e:
            logger.error(f"CloudWatch export failed: {e}")
            return False


class DatadogExporter(MetricsExporter):
    """Export metrics to Datadog."""
    
    def __init__(
        self,
        registry: Optional[MetricsRegistry] = None,
        api_key: Optional[str] = None,
        app_key: Optional[str] = None,
        host: str = 'https://api.datadoghq.com'
    ):
        super().__init__(registry)
        self.api_key = api_key
        self.app_key = app_key
        self.host = host
    
    def export(self, metrics: List[Dict[str, Any]]) -> bool:
        """Export metrics to Datadog."""
        if not self.api_key:
            logger.error("Datadog API key not configured")
            return False
        
        try:
            # Convert metrics to Datadog format
            series = []
            current_time = int(time.time())
            
            for metric in metrics:
                value = metric.get('value')
                
                # Handle different value types
                points = []
                if isinstance(value, dict):
                    # For histograms, send percentiles
                    for k, v in value.get('percentiles', {}).items():
                        series.append({
                            'metric': f"{metric['name']}.{k}",
                            'points': [[current_time, v]],
                            'type': 'gauge',
                            'tags': self._format_tags(metric.get('labels', {}))
                        })
                else:
                    points = [[current_time, float(value)]]
                
                if points:
                    # Determine metric type
                    metric_type = 'gauge'
                    if metric.get('type') == 'Counter':
                        metric_type = 'count'
                    
                    series.append({
                        'metric': metric['name'],
                        'points': points,
                        'type': metric_type,
                        'tags': self._format_tags(metric.get('labels', {}))
                    })
            
            # Send to Datadog
            response = requests.post(
                f"{self.host}/api/v1/series",
                headers={
                    'Content-Type': 'application/json',
                    'DD-API-KEY': self.api_key
                },
                json={'series': series}
            )
            
            return response.status_code == 202
            
        except Exception as e:
            logger.error(f"Datadog export failed: {e}")
            return False
    
    def _format_tags(self, labels: Dict[str, str]) -> List[str]:
        """Format labels as Datadog tags."""
        return [f"{k}:{v}" for k, v in labels.items()]


class PushGatewayExporter(MetricsExporter):
    """Export metrics to Prometheus Push Gateway."""
    
    def __init__(
        self,
        registry: Optional[MetricsRegistry] = None,
        gateway_url: str = 'http://localhost:9091',
        job_name: str = 'enterpriseland'
    ):
        super().__init__(registry)
        self.gateway_url = gateway_url
        self.job_name = job_name
        self.prometheus_exporter = PrometheusExporter(registry)
    
    def export(self, metrics: List[Dict[str, Any]]) -> bool:
        """Push metrics to Prometheus Push Gateway."""
        try:
            # Generate Prometheus format
            self.prometheus_exporter.export(metrics)
            text_data = self.prometheus_exporter.generate_text()
            
            # Push to gateway
            response = requests.put(
                f"{self.gateway_url}/metrics/job/{self.job_name}",
                data=text_data,
                headers={'Content-Type': 'text/plain'}
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Push Gateway export failed: {e}")
            return False