"""
Django management command for monitoring database connection pool health.

Provides real-time monitoring of database connection pools,
performance metrics, and health status across all configured databases.
"""

import json
import time
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from platform_core.core.db_router import ConnectionPoolMonitor


class Command(BaseCommand):
    help = 'Monitor database connection pool health and performance'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--database',
            type=str,
            help='Specific database to monitor (default: all)'
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help='Monitoring interval in seconds (default: 30)'
        )
        parser.add_argument(
            '--duration',
            type=int,
            default=0,
            help='Total monitoring duration in seconds (default: continuous)'
        )
        parser.add_argument(
            '--format',
            choices=['table', 'json'],
            default='table',
            help='Output format (default: table)'
        )
        parser.add_argument(
            '--alert-threshold',
            type=int,
            default=80,
            help='Pool usage percentage to trigger alerts (default: 80)'
        )
        parser.add_argument(
            '--output-file',
            type=str,
            help='Output file to save monitoring data'
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run once and exit (ignore interval and duration)'
        )
    
    def handle(self, *args, **options):
        database = options.get('database')
        interval = options['interval']
        duration = options['duration']
        output_format = options['format']
        alert_threshold = options['alert_threshold']
        output_file = options.get('output_file')
        run_once = options['once']
        
        try:
            monitor = ConnectionPoolMonitor()
            
            if not monitor.monitoring_enabled:
                self.stdout.write(
                    self.style.WARNING("Database pool monitoring is disabled in settings")
                )
                return
            
            self.stdout.write(
                self.style.SUCCESS("Starting database connection pool monitoring...")
            )
            self.stdout.write(f"Interval: {interval}s")
            
            if duration > 0:
                self.stdout.write(f"Duration: {duration}s")
            else:
                self.stdout.write("Duration: Continuous (Ctrl+C to stop)")
            
            self.stdout.write(f"Alert threshold: {alert_threshold}%")
            self.stdout.write("-" * 60)
            
            start_time = time.time()
            monitoring_data = []
            
            try:
                while True:
                    if database:
                        # Monitor specific database
                        health_data = monitor.check_pool_health(database)
                        stats = {
                            'timestamp': time.time(),
                            'databases': {database: health_data},
                            'healthy_databases': 1 if health_data.get('status') == 'healthy' else 0,
                            'unhealthy_databases': 1 if health_data.get('status') != 'healthy' else 0,
                        }
                    else:
                        # Monitor all databases
                        stats = monitor.get_connection_stats()
                    
                    # Add to monitoring data
                    monitoring_data.append(stats)
                    
                    # Display current status
                    self._display_stats(stats, output_format, alert_threshold)
                    
                    # Check for alerts
                    self._check_alerts(stats, alert_threshold)
                    
                    # Save to file if specified
                    if output_file:
                        self._save_to_file(monitoring_data, output_file, output_format)
                    
                    # Exit if running once
                    if run_once:
                        break
                    
                    # Check duration
                    if duration > 0 and (time.time() - start_time) >= duration:
                        break
                    
                    # Wait for next interval
                    time.sleep(interval)
            
            except KeyboardInterrupt:
                self.stdout.write("\nMonitoring stopped by user")
            
            # Final summary
            if monitoring_data:
                self._display_summary(monitoring_data)
        
        except Exception as e:
            raise CommandError(f"Error during monitoring: {e}")
    
    def _display_stats(self, stats, output_format, alert_threshold):
        """
        Display current statistics.
        
        Args:
            stats: Statistics dictionary
            output_format: Output format ('table' or 'json')
            alert_threshold: Alert threshold percentage
        """
        if output_format == 'json':
            self.stdout.write(json.dumps(stats, indent=2, default=str))
            return
        
        # Table format
        timestamp = stats.get('timestamp', 'Unknown')
        if isinstance(timestamp, (int, float)):
            from datetime import datetime
            timestamp = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        self.stdout.write(f"\nTimestamp: {timestamp}")
        self.stdout.write(f"Healthy DBs: {stats.get('healthy_databases', 0)}")
        self.stdout.write(f"Unhealthy DBs: {stats.get('unhealthy_databases', 0)}")
        
        # Database details
        databases = stats.get('databases', {})
        if databases:
            self.stdout.write("\nDatabase Status:")
            self.stdout.write("-" * 80)
            self.stdout.write(f"{'Database':<15} {'Status':<10} {'Pool Size':<10} {'Checked Out':<12} {'Usage %':<10}")
            self.stdout.write("-" * 80)
            
            for db_name, db_stats in databases.items():
                status = db_stats.get('status', 'unknown')
                pool_size = db_stats.get('pool_size', 'N/A')
                checked_out = db_stats.get('checked_out', 'N/A')
                
                # Calculate usage percentage
                usage_pct = 'N/A'
                if pool_size != 'N/A' and checked_out != 'N/A' and pool_size > 0:
                    usage_pct = f"{(checked_out / pool_size) * 100:.1f}"
                
                # Color coding for status
                if status == 'healthy':
                    status_colored = self.style.SUCCESS(status)
                elif status == 'error':
                    status_colored = self.style.ERROR(status)
                else:
                    status_colored = self.style.WARNING(status)
                
                # Color coding for usage
                if usage_pct != 'N/A' and float(usage_pct) >= alert_threshold:
                    usage_colored = self.style.WARNING(f"{usage_pct}%")
                else:
                    usage_colored = f"{usage_pct}%" if usage_pct != 'N/A' else usage_pct
                
                self.stdout.write(
                    f"{db_name:<15} {status_colored:<10} {pool_size:<10} "
                    f"{checked_out:<12} {usage_colored:<10}"
                )
    
    def _check_alerts(self, stats, alert_threshold):
        """
        Check for alert conditions and display warnings.
        
        Args:
            stats: Statistics dictionary
            alert_threshold: Alert threshold percentage
        """
        databases = stats.get('databases', {})
        
        for db_name, db_stats in databases.items():
            # Check health status
            if db_stats.get('status') != 'healthy':
                error = db_stats.get('error', 'Unknown error')
                self.stdout.write(
                    self.style.ERROR(f"ALERT: Database {db_name} is unhealthy: {error}")
                )
            
            # Check pool usage
            pool_size = db_stats.get('pool_size')
            checked_out = db_stats.get('checked_out')
            
            if pool_size and checked_out and pool_size > 0:
                usage_pct = (checked_out / pool_size) * 100
                if usage_pct >= alert_threshold:
                    self.stdout.write(
                        self.style.WARNING(
                            f"ALERT: Database {db_name} pool usage is high: "
                            f"{usage_pct:.1f}% (threshold: {alert_threshold}%)"
                        )
                    )
    
    def _save_to_file(self, monitoring_data, output_file, output_format):
        """
        Save monitoring data to file.
        
        Args:
            monitoring_data: List of monitoring data points
            output_file: Output file path
            output_format: Output format
        """
        try:
            with open(output_file, 'w') as f:
                if output_format == 'json':
                    json.dump(monitoring_data, f, indent=2, default=str)
                else:
                    # CSV format for table data
                    import csv
                    if monitoring_data:
                        # Write header
                        writer = csv.writer(f)
                        writer.writerow([
                            'timestamp', 'database', 'status', 'pool_size', 
                            'checked_out', 'usage_percent'
                        ])
                        
                        # Write data
                        for data_point in monitoring_data:
                            timestamp = data_point.get('timestamp', '')
                            databases = data_point.get('databases', {})
                            
                            for db_name, db_stats in databases.items():
                                pool_size = db_stats.get('pool_size', '')
                                checked_out = db_stats.get('checked_out', '')
                                usage_pct = ''
                                
                                if pool_size and checked_out and pool_size > 0:
                                    usage_pct = f"{(checked_out / pool_size) * 100:.1f}"
                                
                                writer.writerow([
                                    timestamp, db_name, db_stats.get('status', ''),
                                    pool_size, checked_out, usage_pct
                                ])
        
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Failed to save to file {output_file}: {e}")
            )
    
    def _display_summary(self, monitoring_data):
        """
        Display monitoring summary.
        
        Args:
            monitoring_data: List of monitoring data points
        """
        if not monitoring_data:
            return
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("MONITORING SUMMARY")
        self.stdout.write("=" * 60)
        
        total_checks = len(monitoring_data)
        self.stdout.write(f"Total checks performed: {total_checks}")
        
        # Calculate uptime statistics
        database_stats = {}
        
        for data_point in monitoring_data:
            databases = data_point.get('databases', {})
            
            for db_name, db_stats in databases.items():
                if db_name not in database_stats:
                    database_stats[db_name] = {
                        'total_checks': 0,
                        'healthy_checks': 0,
                        'max_usage': 0,
                        'avg_usage': 0,
                        'usage_samples': []
                    }
                
                database_stats[db_name]['total_checks'] += 1
                
                if db_stats.get('status') == 'healthy':
                    database_stats[db_name]['healthy_checks'] += 1
                
                # Track usage
                pool_size = db_stats.get('pool_size')
                checked_out = db_stats.get('checked_out')
                
                if pool_size and checked_out and pool_size > 0:
                    usage_pct = (checked_out / pool_size) * 100
                    database_stats[db_name]['usage_samples'].append(usage_pct)
                    database_stats[db_name]['max_usage'] = max(
                        database_stats[db_name]['max_usage'], usage_pct
                    )
        
        # Display database statistics
        self.stdout.write(f"\n{'Database':<15} {'Uptime %':<10} {'Max Usage %':<12} {'Avg Usage %':<12}")
        self.stdout.write("-" * 60)
        
        for db_name, stats in database_stats.items():
            uptime_pct = (stats['healthy_checks'] / stats['total_checks']) * 100
            max_usage = stats['max_usage']
            
            avg_usage = 0
            if stats['usage_samples']:
                avg_usage = sum(stats['usage_samples']) / len(stats['usage_samples'])
            
            # Color coding
            if uptime_pct >= 99:
                uptime_colored = self.style.SUCCESS(f"{uptime_pct:.1f}")
            elif uptime_pct >= 95:
                uptime_colored = self.style.WARNING(f"{uptime_pct:.1f}")
            else:
                uptime_colored = self.style.ERROR(f"{uptime_pct:.1f}")
            
            self.stdout.write(
                f"{db_name:<15} {uptime_colored:<10} {max_usage:<12.1f} {avg_usage:<12.1f}"
            )
        
        self.stdout.write("=" * 60)