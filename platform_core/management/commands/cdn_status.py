"""
CDN Status Management Command

Check CDN status and configuration.
"""

import json
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from platform_core.cdn import cdn_manager


class Command(BaseCommand):
    help = 'Check CDN status and configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output in JSON format',
        )
        parser.add_argument(
            '--check',
            choices=['health', 'stats', 'config'],
            help='Specific check to perform',
        )

    def handle(self, *args, **options):
        """Handle CDN status command."""
        try:
            # Initialize CDN manager
            cdn_manager.initialize()
            
            output_json = options.get('json')
            check = options.get('check')
            
            if check == 'health':
                self._check_health(output_json)
            elif check == 'stats':
                self._check_stats(output_json)
            elif check == 'config':
                self._check_config(output_json)
            else:
                self._full_status(output_json)
                
        except Exception as e:
            raise CommandError(f'CDN status check failed: {e}')
    
    def _check_health(self, output_json):
        """Check CDN health."""
        health = cdn_manager.health_check()
        
        if output_json:
            self.stdout.write(json.dumps(health, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS('=== CDN Health Check ==='))
            self.stdout.write(f"Status: {self._format_status(health['status'])}")
            self.stdout.write(f"Initialized: {health['initialized']}")
            self.stdout.write(f"Provider Enabled: {health['provider_enabled']}")
            
            if health.get('checks'):
                self.stdout.write("\nChecks:")
                for check, result in health['checks'].items():
                    status = self._format_check_result(result)
                    self.stdout.write(f"  {check}: {status}")
    
    def _check_stats(self, output_json):
        """Check CDN statistics."""
        stats = cdn_manager.get_stats()
        
        if output_json:
            self.stdout.write(json.dumps(stats, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS('=== CDN Statistics ==='))
            
            # Provider stats
            if stats.get('provider'):
                self.stdout.write("\nProvider Stats:")
                for key, value in stats['provider'].items():
                    if key == 'bandwidth':
                        value = self._format_bytes(value)
                    elif key == 'cache_hit_rate':
                        value = f"{value}%"
                    self.stdout.write(f"  {key}: {value}")
            
            # Usage stats
            if stats.get('usage'):
                self.stdout.write("\nUsage Today:")
                for key, value in stats['usage'].items():
                    self.stdout.write(f"  {key}: {value}")
            
            # Manager stats
            if stats.get('manager'):
                self.stdout.write("\nManager Info:")
                for key, value in stats['manager'].items():
                    self.stdout.write(f"  {key}: {value}")
    
    def _check_config(self, output_json):
        """Check CDN configuration."""
        config = {
            'enabled': getattr(settings, 'CDN_ENABLED', False),
            'provider': getattr(settings, 'CDN_PROVIDER_CONFIG', {}).get('class', 'None'),
            'base_url': getattr(settings, 'CDN_PROVIDER_CONFIG', {}).get('base_url', ''),
            'cache_ages': getattr(settings, 'CDN_CACHE_AGES', {}),
            'exclude_patterns': getattr(settings, 'CDN_EXCLUDE_PATTERNS', []),
            'optimizer_enabled': getattr(settings, 'CDN_OPTIMIZER_CONFIG', {}).get('enabled', False),
        }
        
        if output_json:
            self.stdout.write(json.dumps(config, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS('=== CDN Configuration ==='))
            self.stdout.write(f"Enabled: {config['enabled']}")
            self.stdout.write(f"Provider: {config['provider'].split('.')[-1]}")
            self.stdout.write(f"Base URL: {config['base_url']}")
            self.stdout.write(f"Optimizer: {config['optimizer_enabled']}")
            
            if config['cache_ages']:
                self.stdout.write("\nCache Ages:")
                for content_type, age in config['cache_ages'].items():
                    self.stdout.write(f"  {content_type}: {self._format_seconds(age)}")
            
            if config['exclude_patterns']:
                self.stdout.write("\nExclude Patterns:")
                for pattern in config['exclude_patterns']:
                    self.stdout.write(f"  - {pattern}")
    
    def _full_status(self, output_json):
        """Show full CDN status."""
        status = {
            'health': cdn_manager.health_check(),
            'stats': cdn_manager.get_stats(),
            'config': {
                'enabled': getattr(settings, 'CDN_ENABLED', False),
                'provider': getattr(settings, 'CDN_PROVIDER_CONFIG', {}).get('class', 'None'),
            }
        }
        
        if output_json:
            self.stdout.write(json.dumps(status, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS('=== CDN Status Report ===\n'))
            
            # Quick summary
            health_status = status['health']['status']
            provider_enabled = status['health']['provider_enabled']
            cdn_enabled = status['config']['enabled']
            
            if not cdn_enabled:
                self.stdout.write(self.style.WARNING('CDN is DISABLED in settings'))
            elif not provider_enabled:
                self.stdout.write(self.style.WARNING('CDN provider is not initialized'))
            elif health_status == 'healthy':
                self.stdout.write(self.style.SUCCESS('CDN is operational'))
            else:
                self.stdout.write(self.style.ERROR(f'CDN status: {health_status}'))
            
            # Show details
            self.stdout.write("")
            self._check_health(False)
            self.stdout.write("")
            self._check_stats(False)
            self.stdout.write("")
            self._check_config(False)
    
    def _format_status(self, status):
        """Format health status with color."""
        if status == 'healthy':
            return self.style.SUCCESS(status)
        elif status == 'degraded':
            return self.style.WARNING(status)
        else:
            return self.style.ERROR(status)
    
    def _format_check_result(self, result):
        """Format check result with color."""
        if result == 'passed':
            return self.style.SUCCESS('✓ passed')
        elif result == 'warning':
            return self.style.WARNING('⚠ warning')
        else:
            return self.style.ERROR('✗ failed')
    
    def _format_bytes(self, bytes_value):
        """Format bytes to human readable."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} PB"
    
    def _format_seconds(self, seconds):
        """Format seconds to human readable."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        elif seconds < 86400:
            return f"{seconds // 3600}h"
        else:
            return f"{seconds // 86400}d"