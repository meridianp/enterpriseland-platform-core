"""
Performance Monitoring Management Command

Monitor system performance and export metrics.
"""

import json
import time
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from platform_core.monitoring import (
    metrics_registry,
    PerformanceMonitor,
    HealthMonitor,
    PrometheusExporter,
    JSONExporter,
    SystemMetricsCollector,
    DatabaseMetricsCollector,
    CacheMetricsCollector,
    BusinessMetricsCollector
)


class Command(BaseCommand):
    help = 'Monitor system performance and export metrics'

    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            choices=['status', 'collect', 'export', 'monitor', 'health'],
            help='Action to perform'
        )
        
        parser.add_argument(
            '--format',
            choices=['json', 'prometheus', 'console'],
            default='console',
            help='Output format for metrics'
        )
        
        parser.add_argument(
            '--output',
            type=str,
            help='Output file (for json/prometheus formats)'
        )
        
        parser.add_argument(
            '--duration',
            type=int,
            default=60,
            help='Monitoring duration in seconds (for monitor action)'
        )
        
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Collection interval in seconds (for monitor action)'
        )

    def handle(self, *args, **options):
        """Handle monitoring command."""
        action = options['action']
        
        try:
            if action == 'status':
                self._show_status()
            elif action == 'collect':
                self._collect_metrics(options)
            elif action == 'export':
                self._export_metrics(options)
            elif action == 'monitor':
                self._monitor_performance(options)
            elif action == 'health':
                self._check_health()
                
        except Exception as e:
            raise CommandError(f'Monitoring failed: {e}')
    
    def _show_status(self):
        """Show current monitoring status."""
        self.stdout.write(self.style.SUCCESS('=== Monitoring Status ==='))
        
        # Check if monitoring is enabled
        enabled = getattr(settings, 'METRICS_ENABLED', True)
        if enabled:
            self.stdout.write(self.style.SUCCESS('✓ Monitoring enabled'))
        else:
            self.stdout.write(self.style.ERROR('✗ Monitoring disabled'))
        
        # Show registered metrics
        metrics = metrics_registry.get_all_metrics()
        self.stdout.write(f"\nRegistered metrics: {len(metrics)}")
        
        # Show metric types
        metric_types = {}
        for metric in metrics.values():
            metric_type = type(metric).__name__
            metric_types[metric_type] = metric_types.get(metric_type, 0) + 1
        
        self.stdout.write("\nMetric types:")
        for metric_type, count in metric_types.items():
            self.stdout.write(f"  {metric_type}: {count}")
        
        # Show collectors
        self.stdout.write("\nCollectors:")
        collectors = [
            ('System', SystemMetricsCollector),
            ('Database', DatabaseMetricsCollector),
            ('Cache', CacheMetricsCollector),
            ('Business', BusinessMetricsCollector)
        ]
        
        for name, collector_class in collectors:
            try:
                collector = collector_class()
                status = "✓ Available" if collector.is_enabled() else "✗ Disabled"
                self.stdout.write(f"  {name}: {status}")
            except:
                self.stdout.write(f"  {name}: ✗ Not configured")
    
    def _collect_metrics(self, options):
        """Collect current metrics."""
        self.stdout.write(self.style.SUCCESS('=== Collecting Metrics ==='))
        
        # Initialize collectors
        collectors = {
            'system': SystemMetricsCollector(),
            'database': DatabaseMetricsCollector(),
            'cache': CacheMetricsCollector(),
            'business': BusinessMetricsCollector()
        }
        
        # Collect from each
        for name, collector in collectors.items():
            try:
                self.stdout.write(f"\nCollecting {name} metrics...")
                collector.collect()
                self.stdout.write(self.style.SUCCESS(f"  ✓ {name} metrics collected"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ {name} collection failed: {e}"))
        
        # Get all metrics
        all_metrics = metrics_registry.collect()
        
        # Format output
        format_type = options['format']
        if format_type == 'console':
            self._print_metrics_console(all_metrics)
        elif format_type == 'json':
            self._export_json(all_metrics, options['output'])
        elif format_type == 'prometheus':
            self._export_prometheus(all_metrics, options['output'])
    
    def _print_metrics_console(self, metrics):
        """Print metrics to console."""
        self.stdout.write(f"\nCollected {len(metrics)} metrics:")
        
        for metric in metrics:
            name = metric.get('name', 'unknown')
            value = metric.get('value')
            metric_type = metric.get('type', 'unknown')
            
            # Format value based on type
            if isinstance(value, dict):
                if 'count' in value and 'sum' in value:
                    # Histogram/Timer
                    value_str = f"count={value['count']}, mean={value.get('mean', 0):.3f}"
                else:
                    value_str = json.dumps(value, indent=2)
            else:
                value_str = str(value)
            
            self.stdout.write(f"\n{name} ({metric_type}):")
            self.stdout.write(f"  Value: {value_str}")
            
            if metric.get('labels'):
                self.stdout.write(f"  Labels: {metric['labels']}")
    
    def _export_json(self, metrics, output_file):
        """Export metrics as JSON."""
        exporter = JSONExporter(output_file=output_file)
        
        if exporter.export(metrics):
            if output_file:
                self.stdout.write(self.style.SUCCESS(f"Metrics exported to {output_file}"))
            else:
                self.stdout.write(self.style.SUCCESS("Metrics exported to stdout"))
        else:
            self.stdout.write(self.style.ERROR("Export failed"))
    
    def _export_prometheus(self, metrics, output_file):
        """Export metrics in Prometheus format."""
        exporter = PrometheusExporter()
        exporter.export(metrics)
        
        prometheus_text = exporter.generate_text()
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(prometheus_text)
            self.stdout.write(self.style.SUCCESS(f"Metrics exported to {output_file}"))
        else:
            self.stdout.write(prometheus_text)
    
    def _monitor_performance(self, options):
        """Monitor performance for specified duration."""
        duration = options['duration']
        interval = options['interval']
        
        self.stdout.write(self.style.SUCCESS(
            f'=== Monitoring Performance for {duration}s (interval: {interval}s) ==='
        ))
        
        # Start performance monitor
        monitor = PerformanceMonitor()
        monitor.start()
        
        # Initialize collectors
        collectors = {
            'system': SystemMetricsCollector(),
            'database': DatabaseMetricsCollector(),
            'cache': CacheMetricsCollector()
        }
        
        start_time = time.time()
        
        try:
            while time.time() - start_time < duration:
                # Collect metrics
                for collector in collectors.values():
                    collector.collect()
                
                # Get current status
                status = monitor.get_status()
                
                # Display key metrics
                self.stdout.write(f"\n[{time.strftime('%H:%M:%S')}] Metrics:")
                
                if status.get('metrics'):
                    for key, value in status['metrics'].items():
                        self.stdout.write(f"  {key}: {value:.2f}")
                
                # Show alerts
                if status.get('alerts'):
                    self.stdout.write(self.style.WARNING("\nAlerts:"))
                    for alert in status['alerts']:
                        self.stdout.write(self.style.WARNING(
                            f"  - {alert['message']} (severity: {alert['severity']})"
                        ))
                
                # Wait for next interval
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.stdout.write("\nMonitoring stopped by user")
        
        finally:
            monitor.stop()
    
    def _check_health(self):
        """Check system health."""
        self.stdout.write(self.style.SUCCESS('=== Health Check ==='))
        
        monitor = HealthMonitor()
        health_status = monitor.run_health_checks()
        
        # Overall status
        overall = health_status['overall_status'].value
        style = self.style.SUCCESS if overall == 'healthy' else self.style.ERROR
        self.stdout.write(style(f"\nOverall Status: {overall.upper()}"))
        
        # Individual checks
        self.stdout.write("\nHealth Checks:")
        
        for name, check in health_status['checks'].items():
            status = check.status.value
            
            # Choose style based on status
            if status == 'healthy':
                style = self.style.SUCCESS
                symbol = '✓'
            elif status == 'degraded':
                style = self.style.WARNING
                symbol = '⚠'
            else:
                style = self.style.ERROR
                symbol = '✗'
            
            self.stdout.write(style(f"  {symbol} {name}: {status}"))
            self.stdout.write(f"     {check.message}")
            
            if check.details:
                for key, value in check.details.items():
                    self.stdout.write(f"     - {key}: {value}")
    
    def _export_metrics(self, options):
        """Export all metrics."""
        format_type = options['format']
        output_file = options['output']
        
        # Collect all metrics first
        self._collect_metrics({'format': 'console'})
        
        # Then export in requested format
        all_metrics = metrics_registry.collect()
        
        if format_type == 'json':
            self._export_json(all_metrics, output_file)
        elif format_type == 'prometheus':
            self._export_prometheus(all_metrics, output_file)
        else:
            self._print_metrics_console(all_metrics)