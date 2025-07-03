"""
Cache Management Command

Manage cache warming, invalidation, and monitoring.
"""

import json
from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from platform_core.caching import cache_manager


class Command(BaseCommand):
    help = 'Manage cache operations: warm, invalidate, monitor, and optimize'
    
    def add_arguments(self, parser):
        # Operation type
        parser.add_argument(
            'operation',
            type=str,
            choices=['warm', 'invalidate', 'status', 'optimize', 'clear', 'monitor'],
            help='Cache operation to perform'
        )
        
        # Warming options
        parser.add_argument(
            '--model',
            type=str,
            help='Model to warm cache for (app_label.ModelName)'
        )
        
        parser.add_argument(
            '--view',
            type=str,
            help='View name to warm cache for'
        )
        
        parser.add_argument(
            '--api',
            type=str,
            help='API endpoint to warm cache for'
        )
        
        # Invalidation options
        parser.add_argument(
            '--tags',
            type=str,
            nargs='+',
            help='Tags to invalidate'
        )
        
        parser.add_argument(
            '--pattern',
            type=str,
            help='Key pattern to invalidate (regex)'
        )
        
        parser.add_argument(
            '--cascade',
            action='store_true',
            help='Cascade invalidation to related keys'
        )
        
        # Monitoring options
        parser.add_argument(
            '--export',
            type=str,
            choices=['json', 'prometheus'],
            help='Export format for metrics'
        )
        
        parser.add_argument(
            '--output',
            type=str,
            help='Output file for results'
        )
        
        # Common options
        parser.add_argument(
            '--schedule',
            type=int,
            help='Schedule operation after N seconds'
        )
    
    def handle(self, *args, **options):
        operation = options['operation']
        
        try:
            if operation == 'warm':
                self.handle_warm(options)
            elif operation == 'invalidate':
                self.handle_invalidate(options)
            elif operation == 'status':
                self.handle_status(options)
            elif operation == 'optimize':
                self.handle_optimize(options)
            elif operation == 'clear':
                self.handle_clear(options)
            elif operation == 'monitor':
                self.handle_monitor(options)
        except Exception as e:
            raise CommandError(f"Cache operation failed: {str(e)}")
    
    def handle_warm(self, options):
        """Handle cache warming."""
        self.stdout.write(self.style.SUCCESS('Starting cache warming...'))
        
        if options['model']:
            # Warm model cache
            app_label, model_name = options['model'].split('.')
            model = apps.get_model(app_label, model_name)
            
            results = cache_manager.warm_cache(
                'query',
                model=model,
                filters={}  # Could be extended to accept filters
            )
            
            self.stdout.write(
                f"Warmed {results['warmed_count']} entries for {model._meta.label} "
                f"in {results['duration']:.2f}s"
            )
            
        elif options['view']:
            # Warm view cache
            view_config = [{
                'view_name': options['view'],
                'method': 'GET',
                'kwargs': {}
            }]
            
            results = cache_manager.warm_cache('view', view_configs=view_config)
            
            self.stdout.write(
                f"Warmed {results['success_count']} view(s) "
                f"in {results['duration']:.2f}s"
            )
            
        elif options['api']:
            # Warm API endpoint cache
            endpoint_config = [{
                'endpoint': options['api'],
                'data_func': lambda: {},  # Would need actual implementation
                'params': {}
            }]
            
            results = cache_manager.warm_cache('api', endpoint_configs=endpoint_config)
            
            self.stdout.write(
                f"Warmed {results['success_count']} endpoint(s) "
                f"in {results['duration']:.2f}s"
            )
            
        else:
            # Warm all configured caches
            results = cache_manager.warm_cache('smart')
            
            self.stdout.write(
                f"Warmed {results['total_warmed']} total entries "
                f"in {results['total_duration']:.2f}s"
            )
            
            # Show strategy results
            for strategy_name, strategy_result in results['strategies'].items():
                self.stdout.write(f"  {strategy_name}: {strategy_result}")
        
        # Handle scheduling
        if options['schedule']:
            job_id = cache_manager.schedule_invalidation(
                options['schedule'],
                'smart',
                context={'operation': 'warm'}
            )
            self.stdout.write(f"Scheduled warming job: {job_id}")
    
    def handle_invalidate(self, options):
        """Handle cache invalidation."""
        self.stdout.write(self.style.WARNING('Starting cache invalidation...'))
        
        context = {}
        
        if options['tags']:
            context['tags'] = options['tags']
            
        if options['pattern']:
            context['pattern'] = options['pattern']
            
        if options['model']:
            app_label, model_name = options['model'].split('.')
            context['model'] = f"{app_label}.{model_name}"
        
        # Perform invalidation
        if options['schedule']:
            # Schedule for later
            job_id = cache_manager.schedule_invalidation(
                options['schedule'],
                'smart',
                context=context
            )
            self.stdout.write(f"Scheduled invalidation job: {job_id}")
        else:
            # Invalidate now
            results = cache_manager.invalidate('smart', context=context)
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"Invalidated {results['total']} cache entries"
                )
            )
            
            # Show breakdown
            for strategy, count in results['by_strategy'].items():
                self.stdout.write(f"  {strategy}: {count} entries")
    
    def handle_status(self, options):
        """Handle cache status display."""
        self.stdout.write('Gathering cache status...')
        
        status = cache_manager.get_cache_status()
        
        # Format output
        if options['output']:
            with open(options['output'], 'w') as f:
                json.dump(status, f, indent=2, default=str)
            self.stdout.write(
                self.style.SUCCESS(f"Status written to {options['output']}")
            )
        else:
            # Display to console
            self.stdout.write('\n' + '='*60)
            self.stdout.write('CACHE STATUS')
            self.stdout.write('='*60 + '\n')
            
            # Health status
            self.stdout.write('Cache Health:')
            for alias, health in status['health'].items():
                if health.get('healthy', False):
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ {alias}: Healthy")
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  ✗ {alias}: {health.get('error', 'Unhealthy')}"
                        )
                    )
            
            # Performance metrics
            perf = status['performance']
            self.stdout.write(f"\nPerformance Metrics:")
            self.stdout.write(f"  Hit Rate: {perf['hit_rate']:.1%}")
            self.stdout.write(f"  Avg Response Time: {perf['avg_response_time_ms']:.2f}ms")
            
            # Warming schedule
            if status['warming_schedule']:
                self.stdout.write(f"\nWarming Schedule:")
                for schedule in status['warming_schedule'][:5]:
                    self.stdout.write(
                        f"  {schedule['name']}: "
                        f"Next run at {schedule['next_run']}"
                    )
    
    def handle_optimize(self, options):
        """Handle cache optimization analysis."""
        self.stdout.write('Analyzing cache configuration...')
        
        analysis = cache_manager.optimize_cache_configuration()
        
        if options['output']:
            with open(options['output'], 'w') as f:
                json.dump(analysis, f, indent=2, default=str)
            self.stdout.write(
                self.style.SUCCESS(f"Analysis written to {options['output']}")
            )
        else:
            # Display recommendations
            self.stdout.write('\n' + '='*60)
            self.stdout.write('CACHE OPTIMIZATION ANALYSIS')
            self.stdout.write('='*60 + '\n')
            
            # Current performance
            current = analysis['current_performance']
            self.stdout.write('Current Performance:')
            self.stdout.write(f"  Hit Rate: {current['hit_rate']:.1%}")
            self.stdout.write(f"  Response Time: {current['avg_response_time']:.2f}ms")
            
            # Recommendations
            if analysis['recommendations']:
                self.stdout.write('\nRecommendations:')
                
                for i, rec in enumerate(analysis['recommendations'], 1):
                    priority = rec.get('priority', 'medium')
                    
                    if priority == 'critical':
                        style = self.style.ERROR
                    elif priority == 'high':
                        style = self.style.WARNING
                    else:
                        style = self.style.NOTICE
                    
                    self.stdout.write(
                        style(f"\n{i}. [{priority.upper()}] {rec['issue']}")
                    )
                    
                    if 'current' in rec:
                        self.stdout.write(f"   Current: {rec['current']}")
                    
                    self.stdout.write(f"   Recommendation: {rec['recommendation']}")
            else:
                self.stdout.write(
                    self.style.SUCCESS('\nNo optimization recommendations. Cache is well-configured!')
                )
    
    def handle_clear(self, options):
        """Handle cache clearing."""
        self.stdout.write(self.style.WARNING('Clearing all caches...'))
        
        # Confirm action
        if input('Are you sure? This will clear ALL cache data. (yes/no): ').lower() != 'yes':
            self.stdout.write('Operation cancelled.')
            return
        
        results = cache_manager.clear_all_caches()
        
        for alias, success in results.items():
            if success:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Cleared {alias}"))
            else:
                self.stdout.write(self.style.ERROR(f"  ✗ Failed to clear {alias}"))
    
    def handle_monitor(self, options):
        """Handle cache monitoring."""
        if options['export']:
            # Export metrics
            metrics = cache_manager.export_metrics(format=options['export'])
            
            if options['output']:
                with open(options['output'], 'w') as f:
                    f.write(metrics)
                self.stdout.write(
                    self.style.SUCCESS(f"Metrics exported to {options['output']}")
                )
            else:
                self.stdout.write(metrics)
        else:
            # Display monitoring dashboard
            self.stdout.write('\n' + '='*60)
            self.stdout.write('CACHE MONITORING DASHBOARD')
            self.stdout.write('='*60 + '\n')
            
            # Get current metrics
            from platform_core.caching.monitoring import cache_monitor
            report = cache_monitor.get_performance_report()
            
            # Hit rate gauge
            hit_rate = report['hit_rate']
            gauge_width = 30
            filled = int(hit_rate * gauge_width)
            gauge = '█' * filled + '░' * (gauge_width - filled)
            
            self.stdout.write(f"Hit Rate: [{gauge}] {hit_rate:.1%}")
            
            # Response time
            self.stdout.write(
                f"Avg Response Time: {report['avg_response_time_ms']:.2f}ms"
            )
            
            # Key statistics
            self.stdout.write('\nTop Key Patterns:')
            key_stats = sorted(
                report['key_statistics'].items(),
                key=lambda x: x[1]['hits'] + x[1]['misses'],
                reverse=True
            )[:5]
            
            for pattern, stats in key_stats:
                total = stats['hits'] + stats['misses']
                if total > 0:
                    self.stdout.write(
                        f"  {pattern}: "
                        f"{stats['hit_rate']:.1%} hit rate, "
                        f"{total} requests"
                    )