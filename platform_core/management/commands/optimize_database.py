"""
Database Optimization Management Command

Analyze and optimize database performance.
"""

import json
from typing import Optional
from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from platform_core.database import (
    DatabaseOptimizer,
    IndexAnalyzer,
    database_monitor
)
from platform_core.database.migrations import IndexMigrationGenerator


class Command(BaseCommand):
    help = 'Analyze and optimize database performance'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--analyze',
            action='store_true',
            help='Run database analysis only'
        )
        
        parser.add_argument(
            '--optimize',
            action='store_true',
            help='Apply optimization suggestions'
        )
        
        parser.add_argument(
            '--model',
            type=str,
            help='Specific model to optimize (app_label.ModelName)'
        )
        
        parser.add_argument(
            '--create-indexes',
            action='store_true',
            help='Create suggested indexes'
        )
        
        parser.add_argument(
            '--monitor',
            action='store_true',
            help='Show current monitoring data'
        )
        
        parser.add_argument(
            '--export',
            type=str,
            choices=['json', 'prometheus'],
            help='Export monitoring metrics'
        )
        
        parser.add_argument(
            '--output',
            type=str,
            help='Output file for results'
        )
    
    def handle(self, *args, **options):
        if options['monitor']:
            self.show_monitoring_data(options)
        elif options['analyze'] or not any([options['optimize'], options['create_indexes']]):
            self.run_analysis(options)
        elif options['optimize']:
            self.run_optimization(options)
        elif options['create_indexes']:
            self.create_indexes(options)
    
    def run_analysis(self, options):
        """Run database analysis."""
        self.stdout.write(self.style.SUCCESS('Starting database analysis...'))
        
        optimizer = DatabaseOptimizer()
        
        if options['model']:
            # Analyze specific model
            model = self.get_model(options['model'])
            results = optimizer.optimize_model_queries(model)
            
            # Add index analysis
            index_analyzer = IndexAnalyzer()
            results['index_analysis'] = index_analyzer.analyze_missing_indexes()
            results['index_suggestions'] = index_analyzer.suggest_composite_indexes(model)
            
        else:
            # Run comprehensive analysis
            results = optimizer.run_optimization_analysis()
        
        # Output results
        self.output_results(results, options)
    
    def run_optimization(self, options):
        """Apply optimization suggestions."""
        self.stdout.write(self.style.SUCCESS('Running database optimization...'))
        
        optimizer = DatabaseOptimizer()
        
        # Run analysis first
        analysis = optimizer.run_optimization_analysis()
        
        # Apply optimizations
        applied = []
        
        # 1. Vacuum tables that need it
        table_stats = analysis['optimizations']['table_stats']
        for table_info in table_stats.get('tables_need_vacuum', []):
            table = table_info['table']
            self.stdout.write(f"Vacuuming {table}...")
            
            try:
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(f"VACUUM ANALYZE {table}")
                applied.append(f"Vacuumed {table}")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Failed to vacuum {table}: {e}")
                )
        
        # 2. Analyze tables
        for table_info in table_stats.get('tables_need_analyze', []):
            table = table_info['table']
            self.stdout.write(f"Analyzing {table}...")
            
            try:
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(f"ANALYZE {table}")
                applied.append(f"Analyzed {table}")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Failed to analyze {table}: {e}")
                )
        
        # 3. Display other recommendations
        self.stdout.write('\nOptimization Summary:')
        for action in applied:
            self.stdout.write(self.style.SUCCESS(f"✓ {action}"))
        
        # Show remaining recommendations
        if analysis['recommendations']:
            self.stdout.write('\nAdditional Recommendations:')
            for rec in analysis['recommendations']:
                self.stdout.write(f"• {rec}")
    
    def create_indexes(self, options):
        """Create suggested indexes."""
        self.stdout.write(self.style.SUCCESS('Creating suggested indexes...'))
        
        index_analyzer = IndexAnalyzer()
        index_generator = IndexMigrationGenerator()
        
        created_indexes = []
        
        if options['model']:
            # Create indexes for specific model
            model = self.get_model(options['model'])
            suggestions = index_analyzer.suggest_composite_indexes(model)
            
            if suggestions:
                self.stdout.write(f"\nCreating {len(suggestions)} indexes for {model._meta.label}...")
                
                for suggestion in suggestions:
                    try:
                        sql = suggestion.get('sql', '')
                        if sql:
                            from django.db import connection
                            with connection.cursor() as cursor:
                                cursor.execute(sql)
                            created_indexes.append(suggestion)
                            self.stdout.write(
                                self.style.SUCCESS(f"✓ Created index on {suggestion['columns']}")
                            )
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"✗ Failed to create index: {e}")
                        )
        else:
            # Create indexes for all models with missing indexes
            missing_indexes = index_analyzer.analyze_missing_indexes()
            
            for index_info in missing_indexes[:10]:  # Limit to 10 for safety
                if 'sql' in index_info:
                    try:
                        from django.db import connection
                        with connection.cursor() as cursor:
                            cursor.execute(index_info['sql'])
                        created_indexes.append(index_info)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"✓ Created index on {index_info['table']}.{index_info.get('column', 'unknown')}"
                            )
                        )
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"✗ Failed to create index: {e}")
                        )
        
        self.stdout.write(f"\nCreated {len(created_indexes)} indexes.")
    
    def show_monitoring_data(self, options):
        """Show current monitoring data."""
        if options['export']:
            # Export metrics
            metrics = database_monitor.export_metrics(format=options['export'])
            
            if options['output']:
                with open(options['output'], 'w') as f:
                    f.write(metrics)
                self.stdout.write(
                    self.style.SUCCESS(f"Metrics exported to {options['output']}")
                )
            else:
                self.stdout.write(metrics)
        else:
            # Show dashboard data
            data = database_monitor.get_dashboard_data()
            
            self.stdout.write('\n' + '='*60)
            self.stdout.write('DATABASE MONITORING DASHBOARD')
            self.stdout.write('='*60 + '\n')
            
            # Health Score
            health = data['health_score']
            status_style = (
                self.style.SUCCESS if health['status'] == 'healthy'
                else self.style.WARNING if health['status'] == 'degraded'
                else self.style.ERROR
            )
            
            self.stdout.write(f"Health Score: {status_style(f\"{health['score']}/100 ({health['status']})\")})")
            
            if health['issues']:
                self.stdout.write("\nIssues:")
                for issue in health['issues']:
                    self.stdout.write(f"  • {issue}")
            
            # Slow Queries
            self.stdout.write(f"\nSlow Query Trends: {data['slow_queries']['trends']['trend']}")
            self.stdout.write(f"Recent slow queries: {len(data['slow_queries']['recent'])}")
            
            # Top slow query patterns
            patterns = data['slow_queries']['patterns'][:5]
            if patterns:
                self.stdout.write("\nTop Slow Query Patterns:")
                for pattern in patterns:
                    self.stdout.write(
                        f"  • {pattern['pattern']}: "
                        f"{pattern['count']} queries, "
                        f"avg {pattern['avg_time']:.2f}ms"
                    )
            
            # Connections
            self.stdout.write("\nConnection Status:")
            for alias, stats in data['connections']['current'].items():
                self.stdout.write(
                    f"  • {alias}: {stats['active']} active, "
                    f"{stats['idle']} idle, {stats['total']} total"
                )
            
            # Recent Alerts
            if data['alerts']['slow_queries'] or data['alerts']['connections']:
                self.stdout.write("\nRecent Alerts:")
                
                for alert in data['alerts']['slow_queries'][-3:]:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  • Slow query ({alert['duration_ms']:.0f}ms): "
                            f"{alert['sql'][:50]}..."
                        )
                    )
                
                for alert in data['alerts']['connections'][-3:]:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  • Connection {alert['type']} on {alert['alias']}"
                        )
                    )
    
    def get_model(self, model_string: str):
        """Get model from string."""
        try:
            app_label, model_name = model_string.split('.')
            return apps.get_model(app_label, model_name)
        except (ValueError, LookupError):
            raise CommandError(
                f'Invalid model: {model_string}. Use format: app_label.ModelName'
            )
    
    def output_results(self, results: dict, options: dict):
        """Output analysis results."""
        if options['output']:
            with open(options['output'], 'w') as f:
                json.dump(results, f, indent=2, default=str)
            self.stdout.write(
                self.style.SUCCESS(f"Results written to {options['output']}")
            )
        else:
            # Pretty print to console
            self.stdout.write('\n' + '='*60)
            self.stdout.write('DATABASE OPTIMIZATION ANALYSIS')
            self.stdout.write('='*60 + '\n')
            
            # Print key findings
            if 'optimizations' in results:
                opts = results['optimizations']
                
                # Slow queries
                if 'slow_queries' in opts and opts['slow_queries']:
                    self.stdout.write(
                        self.style.WARNING(
                            f"\nFound {len(opts['slow_queries'])} slow queries"
                        )
                    )
                
                # Missing indexes
                if 'missing_indexes' in opts and opts['missing_indexes']:
                    self.stdout.write(
                        self.style.WARNING(
                            f"\nFound {len(opts['missing_indexes'])} missing indexes"
                        )
                    )
                
                # Index usage
                if 'index_usage' in opts:
                    usage = opts['index_usage']
                    if usage.get('unused_indexes'):
                        self.stdout.write(
                            self.style.WARNING(
                                f"\nFound {len(usage['unused_indexes'])} unused indexes"
                            )
                        )
            
            # Print recommendations
            if 'recommendations' in results and results['recommendations']:
                self.stdout.write('\nRecommendations:')
                for i, rec in enumerate(results['recommendations'], 1):
                    self.stdout.write(f"{i}. {rec}")
            
            # Model-specific results
            if 'model' in results:
                self.stdout.write(f"\nModel: {results['model']}")
                if 'index_suggestions' in results:
                    self.stdout.write(f"Index suggestions: {len(results['index_suggestions'])}")
                    for suggestion in results['index_suggestions'][:5]:
                        self.stdout.write(
                            f"  • Create index on {suggestion['columns']} "
                            f"(benefit score: {suggestion['benefit_score']:.2f})"
                        )