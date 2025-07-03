"""
Performance Analysis Management Command

Analyze application performance and generate optimization recommendations.
"""

import json
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.apps import apps
from platform_core.performance import (
    PerformanceOptimizer,
    QueryAnalyzer,
    PerformanceMonitor
)


class Command(BaseCommand):
    help = 'Analyze application performance and generate optimization recommendations'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            type=str,
            choices=['full', 'queries', 'cache', 'health', 'optimize'],
            default='full',
            help='Type of analysis to perform'
        )
        
        parser.add_argument(
            '--model',
            type=str,
            help='Specific model to analyze (app_label.ModelName)'
        )
        
        parser.add_argument(
            '--output',
            type=str,
            help='Output file for results (JSON format)'
        )
        
        parser.add_argument(
            '--threshold',
            type=int,
            default=100,
            help='Slow query threshold in milliseconds (default: 100ms)'
        )
        
        parser.add_argument(
            '--apply-indexes',
            action='store_true',
            help='Generate SQL statements for suggested indexes'
        )
    
    def handle(self, *args, **options):
        analysis_type = options['type']
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting {analysis_type} performance analysis...')
        )
        
        try:
            if analysis_type == 'full':
                results = self.run_full_analysis(options)
            elif analysis_type == 'queries':
                results = self.analyze_queries(options)
            elif analysis_type == 'cache':
                results = self.analyze_cache(options)
            elif analysis_type == 'health':
                results = self.check_health(options)
            elif analysis_type == 'optimize':
                results = self.run_optimization(options)
            
            # Output results
            self.output_results(results, options)
            
        except Exception as e:
            raise CommandError(f'Performance analysis failed: {str(e)}')
    
    def run_full_analysis(self, options):
        """Run comprehensive performance analysis."""
        self.stdout.write('Running full performance analysis...')
        
        optimizer = PerformanceOptimizer()
        monitor = PerformanceMonitor()
        
        results = {
            'analysis_type': 'full',
            'health_check': monitor.check_health(),
            'performance_report': monitor.get_performance_report(),
            'optimization_suite': optimizer.run_optimization_suite()
        }
        
        # Analyze specific model if provided
        if options['model']:
            model = self.get_model(options['model'])
            results['model_optimization'] = optimizer.optimize_model_queries(model)
        
        return results
    
    def analyze_queries(self, options):
        """Analyze database queries."""
        self.stdout.write('Analyzing database queries...')
        
        analyzer = QueryAnalyzer()
        optimizer = PerformanceOptimizer()
        
        # Get recent queries
        recent_queries = []
        with connection.cursor() as cursor:
            # Get queries from Django's query log
            for query in connection.queries[-100:]:  # Last 100 queries
                recent_queries.append({
                    'sql': query['sql'],
                    'duration': float(query['time']) * 1000  # Convert to ms
                })
        
        # Analyze queries
        analysis = analyzer.analyze_queries(recent_queries)
        
        # Get slow queries
        slow_queries = optimizer.query_optimizer.analyze_slow_queries(
            threshold_ms=options['threshold']
        )
        
        results = {
            'analysis_type': 'queries',
            'query_analysis': analysis,
            'slow_queries': slow_queries,
            'threshold_ms': options['threshold']
        }
        
        # Generate index suggestions
        if options['apply_indexes']:
            all_suggestions = []
            for model in apps.get_models():
                suggestions = optimizer.query_optimizer.suggest_indexes(model)
                all_suggestions.extend(suggestions)
            
            results['index_suggestions'] = all_suggestions
            results['index_sql'] = self.generate_index_sql(all_suggestions)
        
        return results
    
    def analyze_cache(self, options):
        """Analyze cache performance."""
        self.stdout.write('Analyzing cache performance...')
        
        from django.core.cache import cache
        from platform_core.performance.profiling import profiler
        
        # Get cache statistics
        cache_stats = {
            'backend': cache._cache.__class__.__name__,
            'key_prefix': getattr(cache, 'key_prefix', ''),
            'timeout': cache.default_timeout
        }
        
        # Try to get Redis-specific stats if using Redis
        try:
            if hasattr(cache._cache, '_cache'):
                redis_client = cache._cache._cache.get_client()
                info = redis_client.info()
                cache_stats['redis_info'] = {
                    'used_memory': info.get('used_memory_human'),
                    'connected_clients': info.get('connected_clients'),
                    'total_commands_processed': info.get('total_commands_processed'),
                    'keyspace_hits': info.get('keyspace_hits', 0),
                    'keyspace_misses': info.get('keyspace_misses', 0),
                    'hit_rate': self.calculate_hit_rate(
                        info.get('keyspace_hits', 0),
                        info.get('keyspace_misses', 0)
                    )
                }
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'Could not get Redis stats: {e}')
            )
        
        # Get recent cache operations from profiler
        cache_operations = cache.get('performance:cache_operations', [])
        
        results = {
            'analysis_type': 'cache',
            'cache_stats': cache_stats,
            'recent_operations': cache_operations[-100:],  # Last 100 operations
            'recommendations': self.generate_cache_recommendations(cache_stats)
        }
        
        return results
    
    def check_health(self, options):
        """Check system health."""
        self.stdout.write('Checking system health...')
        
        monitor = PerformanceMonitor()
        health = monitor.check_health()
        
        # Add detailed checks
        health['detailed_checks'] = {
            'database': self.check_database_health(),
            'cache': self.check_cache_health(),
            'disk': self.check_disk_health()
        }
        
        return {
            'analysis_type': 'health',
            'health_status': health
        }
    
    def run_optimization(self, options):
        """Run performance optimization."""
        self.stdout.write('Running performance optimization...')
        
        optimizer = PerformanceOptimizer()
        
        results = {
            'analysis_type': 'optimization'
        }
        
        if options['model']:
            # Optimize specific model
            model = self.get_model(options['model'])
            results['model_optimization'] = optimizer.optimize_model_queries(model)
            
            # Warm cache for this model
            warmed_keys = optimizer.cache_warmer.warm_queryset_cache(model)
            results['cache_warming'] = {
                'model': options['model'],
                'warmed_keys': len(warmed_keys)
            }
        else:
            # Run full optimization suite
            results['optimization_suite'] = optimizer.run_optimization_suite()
        
        return results
    
    def get_model(self, model_string):
        """Get model from string like 'app_label.ModelName'."""
        try:
            app_label, model_name = model_string.split('.')
            return apps.get_model(app_label, model_name)
        except (ValueError, LookupError):
            raise CommandError(
                f'Invalid model: {model_string}. '
                'Use format: app_label.ModelName'
            )
    
    def generate_index_sql(self, suggestions):
        """Generate SQL statements for index creation."""
        sql_statements = []
        
        for suggestion in suggestions:
            sql = suggestion.get('sql', '')
            if sql:
                sql_statements.append(sql)
        
        return sql_statements
    
    def calculate_hit_rate(self, hits, misses):
        """Calculate cache hit rate."""
        total = hits + misses
        if total == 0:
            return 0
        return (hits / total) * 100
    
    def generate_cache_recommendations(self, cache_stats):
        """Generate cache optimization recommendations."""
        recommendations = []
        
        # Check hit rate
        if 'redis_info' in cache_stats:
            hit_rate = cache_stats['redis_info'].get('hit_rate', 0)
            if hit_rate < 70:
                recommendations.append(
                    f'Low cache hit rate ({hit_rate:.1f}%). '
                    'Review cache key design and TTL values.'
                )
        
        # Check timeout
        if cache_stats['timeout'] < 300:  # Less than 5 minutes
            recommendations.append(
                'Consider increasing default cache timeout for better performance.'
            )
        
        return recommendations
    
    def check_database_health(self):
        """Check database health metrics."""
        health = {'status': 'healthy', 'metrics': {}}
        
        try:
            with connection.cursor() as cursor:
                # Check connection count
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity"
                )
                connection_count = cursor.fetchone()[0]
                health['metrics']['active_connections'] = connection_count
                
                # Check for long-running queries
                cursor.execute("""
                    SELECT count(*) 
                    FROM pg_stat_activity 
                    WHERE state = 'active' 
                    AND now() - query_start > interval '1 minute'
                """)
                long_queries = cursor.fetchone()[0]
                health['metrics']['long_running_queries'] = long_queries
                
                if long_queries > 5:
                    health['status'] = 'warning'
                    health['message'] = f'{long_queries} long-running queries detected'
                
        except Exception as e:
            health['status'] = 'error'
            health['message'] = str(e)
        
        return health
    
    def check_cache_health(self):
        """Check cache health metrics."""
        health = {'status': 'healthy', 'metrics': {}}
        
        try:
            from django.core.cache import cache
            
            # Test cache connectivity
            cache.set('health_check', 'ok', 10)
            if cache.get('health_check') == 'ok':
                health['metrics']['connectivity'] = 'ok'
            else:
                health['status'] = 'error'
                health['message'] = 'Cache connectivity issue'
                
        except Exception as e:
            health['status'] = 'error'
            health['message'] = str(e)
        
        return health
    
    def check_disk_health(self):
        """Check disk space health."""
        health = {'status': 'healthy', 'metrics': {}}
        
        try:
            import psutil
            disk = psutil.disk_usage('/')
            
            health['metrics']['disk_usage_percent'] = disk.percent
            health['metrics']['free_space_gb'] = disk.free / (1024**3)
            
            if disk.percent > 90:
                health['status'] = 'critical'
                health['message'] = f'Disk usage critical: {disk.percent}%'
            elif disk.percent > 80:
                health['status'] = 'warning'
                health['message'] = f'Disk usage high: {disk.percent}%'
                
        except Exception as e:
            health['status'] = 'error'
            health['message'] = str(e)
        
        return health
    
    def output_results(self, results, options):
        """Output analysis results."""
        if options['output']:
            # Write to file
            with open(options['output'], 'w') as f:
                json.dump(results, f, indent=2, default=str)
            self.stdout.write(
                self.style.SUCCESS(f'Results written to {options["output"]}')
            )
        else:
            # Print to stdout
            self.stdout.write('\n' + '='*60)
            self.stdout.write('PERFORMANCE ANALYSIS RESULTS')
            self.stdout.write('='*60 + '\n')
            
            # Format based on analysis type
            if results['analysis_type'] == 'health':
                self.print_health_results(results['health_status'])
            elif results['analysis_type'] == 'queries':
                self.print_query_results(results)
            else:
                # Default JSON output
                self.stdout.write(json.dumps(results, indent=2, default=str))
    
    def print_health_results(self, health):
        """Print health check results in readable format."""
        status = health['status'].upper()
        
        if status == 'HEALTHY':
            self.stdout.write(self.style.SUCCESS(f'Status: {status}'))
        elif status == 'DEGRADED':
            self.stdout.write(self.style.WARNING(f'Status: {status}'))
        else:
            self.stdout.write(self.style.ERROR(f'Status: {status}'))
        
        self.stdout.write(f'\nTimestamp: {health["timestamp"]}')
        
        self.stdout.write('\nHealth Checks:')
        for check_name, check_data in health['checks'].items():
            status = check_data['status']
            value = check_data['value']
            threshold = check_data['threshold']
            
            if status == 'ok':
                style = self.style.SUCCESS
            elif status == 'warning':
                style = self.style.WARNING
            else:
                style = self.style.ERROR
            
            self.stdout.write(
                f'  {check_name}: {style(status)} '
                f'(value: {value}, threshold: {threshold})'
            )
    
    def print_query_results(self, results):
        """Print query analysis results in readable format."""
        analysis = results['query_analysis']
        
        self.stdout.write(f'\nTotal Queries: {analysis["total_queries"]}')
        self.stdout.write(f'Total Query Time: {analysis["total_time"]:.2f}ms')
        
        if analysis['slow_queries']:
            self.stdout.write(
                self.style.WARNING(
                    f'\nSlow Queries: {len(analysis["slow_queries"])}'
                )
            )
            for query in analysis['slow_queries'][:5]:  # Show top 5
                self.stdout.write(f'  - {query["sql"][:80]}...')
                self.stdout.write(f'    Duration: {query["duration"]:.2f}ms')
        
        if analysis['duplicate_queries']:
            self.stdout.write(
                self.style.WARNING(
                    f'\nDuplicate Queries Found: {len(analysis["duplicate_queries"])}'
                )
            )
        
        if analysis['n_plus_one']:
            self.stdout.write(
                self.style.ERROR('\nN+1 Query Pattern Detected!')
            )
        
        if analysis['recommendations']:
            self.stdout.write('\nRecommendations:')
            for rec in analysis['recommendations']:
                self.stdout.write(f'  - {rec}')