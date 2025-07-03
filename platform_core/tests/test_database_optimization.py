"""
Database Optimization Tests

Tests for database query optimization, monitoring, and migration tools.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from django.test import TestCase, TransactionTestCase
from django.db import connection, models
from django.contrib.auth import get_user_model
from django.core.management import call_command
from io import StringIO

from platform_core.database import (
    DatabaseOptimizer,
    QueryPlanAnalyzer,
    IndexAnalyzer,
    ConnectionPoolManager,
    SlowQueryLogger,
    ConnectionMonitor,
    DatabaseMonitor,
    database_monitor
)
from platform_core.database.migrations import (
    OptimizedMigrationExecutor,
    IndexMigrationGenerator,
    MigrationOptimizationAdvisor
)

User = get_user_model()


class TestModel(models.Model):
    """Test model for optimization tests."""
    name = models.CharField(max_length=100, db_index=True)
    status = models.CharField(max_length=20, default='active')
    created_date = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    category = models.CharField(max_length=50, null=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        app_label = 'test'
        indexes = [
            models.Index(fields=['status', 'created_date']),
        ]


class TestQueryPlanAnalyzer(TestCase):
    """Test query execution plan analysis."""
    
    def setUp(self):
        self.analyzer = QueryPlanAnalyzer()
    
    def test_analyze_simple_query(self):
        """Test analyzing a simple query."""
        query = "SELECT * FROM auth_user WHERE id = 1"
        
        with patch.object(self.analyzer.connection, 'cursor') as mock_cursor:
            # Mock EXPLAIN output
            mock_cursor.return_value.__enter__.return_value.fetchone.return_value = [{
                "Plan": {
                    "Node Type": "Index Scan",
                    "Relation Name": "auth_user",
                    "Total Cost": 8.29,
                    "Actual Rows": 1
                },
                "Planning Time": 0.1,
                "Execution Time": 0.05
            }]
            
            analysis = self.analyzer.analyze_query(query)
            
            self.assertEqual(analysis['query'], query)
            self.assertEqual(analysis['execution_time'], 0.05)
            self.assertEqual(analysis['planning_time'], 0.1)
            self.assertEqual(len(analysis['issues']), 0)  # No issues for index scan
    
    def test_detect_sequential_scan(self):
        """Test detection of sequential scans."""
        plan = {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "large_table",
                "Actual Rows": 50000,
                "Total Cost": 1000
            }
        }
        
        analysis = self.analyzer._analyze_plan(plan)
        
        self.assertIn("Sequential scan on large table", analysis['issues'][0])
        self.assertIn("Consider adding index", analysis['suggestions'][0])
    
    def test_detect_nested_loops(self):
        """Test detection of expensive nested loops."""
        plan = {
            "Plan": {
                "Node Type": "Nested Loop",
                "Total Cost": 5000,
                "Actual Rows": 10000,
                "Plans": []
            }
        }
        
        analysis = self.analyzer._analyze_plan(plan)
        
        self.assertIn("High-cost nested loop", analysis['issues'][0])
        self.assertIn("hash join or merge join", analysis['suggestions'][0])


class TestIndexAnalyzer(TestCase):
    """Test index analysis functionality."""
    
    def setUp(self):
        self.analyzer = IndexAnalyzer()
        # Create test data
        User.objects.create_user('test1', 'test1@example.com')
        User.objects.create_user('test2', 'test2@example.com')
    
    @patch('platform_core.database.optimization.connections')
    def test_analyze_missing_indexes(self, mock_connections):
        """Test detection of missing indexes."""
        # Mock database statistics
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ('public', 'test_table', 1000, 50000, 0, 0, 100),  # High seq scans
        ]
        
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
        
        suggestions = self.analyzer.analyze_missing_indexes()
        
        self.assertGreater(len(suggestions), 0)
        self.assertIn('High sequential scan activity', suggestions[0]['issue'])
    
    def test_suggest_composite_indexes(self):
        """Test composite index suggestions."""
        # Use the User model for testing
        suggestions = self.analyzer.suggest_composite_indexes(User)
        
        # Should suggest some composite indexes based on common patterns
        self.assertIsInstance(suggestions, list)
        
        # Verify suggestion structure
        for suggestion in suggestions:
            self.assertIn('table', suggestion)
            self.assertIn('columns', suggestion)
            self.assertIn('type', suggestion)
            self.assertIn('sql', suggestion)
    
    @patch('platform_core.database.optimization.connections')
    def test_analyze_index_usage(self, mock_connections):
        """Test index usage analysis."""
        # Mock index statistics
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ('public', 'users', 'idx_unused', 0, 0, 0, '1 MB'),  # Unused index
            ('public', 'users', 'idx_used', 1000, 5000, 4500, '2 MB'),  # Used index
        ]
        
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
        
        usage = self.analyzer.analyze_index_usage()
        
        self.assertEqual(usage['total_indexes'], 2)
        self.assertEqual(len(usage['unused_indexes']), 1)
        self.assertEqual(usage['unused_indexes'][0]['index'], 'public.idx_unused')


class TestDatabaseOptimizer(TestCase):
    """Test database optimization coordinator."""
    
    def setUp(self):
        self.optimizer = DatabaseOptimizer()
    
    @patch('platform_core.database.optimization.IndexAnalyzer.analyze_missing_indexes')
    @patch('platform_core.database.optimization.IndexAnalyzer.analyze_index_usage')
    def test_run_optimization_analysis(self, mock_usage, mock_missing):
        """Test comprehensive optimization analysis."""
        # Mock results
        mock_missing.return_value = []
        mock_usage.return_value = {
            'total_indexes': 10,
            'unused_indexes': [],
            'inefficient_indexes': []
        }
        
        results = self.optimizer.run_optimization_analysis()
        
        self.assertIn('timestamp', results)
        self.assertIn('optimizations', results)
        self.assertIn('recommendations', results)
        
        # Should include various optimization categories
        opts = results['optimizations']
        self.assertIn('missing_indexes', opts)
        self.assertIn('index_usage', opts)
        self.assertIn('table_stats', opts)
    
    def test_optimize_model_queries(self):
        """Test model-specific query optimization."""
        # Create some test data
        for i in range(5):
            User.objects.create_user(f'user{i}', f'user{i}@example.com')
        
        results = self.optimizer.optimize_model_queries(User)
        
        self.assertEqual(results['model'], 'auth.User')
        self.assertIn('optimizations', results)
        
        # Should analyze common query patterns
        self.assertIsInstance(results['optimizations'], list)


class TestConnectionPoolManager(TestCase):
    """Test connection pool management."""
    
    def setUp(self):
        self.manager = ConnectionPoolManager()
    
    def test_pool_configuration(self):
        """Test getting pool configuration."""
        config = self.manager._get_pool_config()
        
        self.assertIn('max_connections', config)
        self.assertIn('min_connections', config)
        self.assertIn('pool_timeout', config)
    
    @patch('platform_core.database.optimization.connection.cursor')
    def test_optimize_pool_settings(self, mock_cursor):
        """Test pool optimization recommendations."""
        # Mock connection statistics
        mock_cursor.return_value.__enter__.return_value.fetchall.return_value = [
            ('active', 80),  # High active connections
            ('idle', 10),
            ('idle in transaction', 8),  # Connection leaks
        ]
        
        recommendations = self.manager.optimize_pool_settings()
        
        self.assertIn('recommendations', recommendations)
        self.assertGreater(len(recommendations['recommendations']), 0)
        
        # Should detect high usage and connection leaks
        rec_types = [r.get('setting') or r.get('issue') for r in recommendations['recommendations']]
        self.assertIn('max_connections', rec_types)
        self.assertIn('Connection leak detected', rec_types)


class TestSlowQueryLogger(TestCase):
    """Test slow query logging."""
    
    def setUp(self):
        self.logger = SlowQueryLogger(threshold_ms=50)
    
    def test_log_slow_query(self):
        """Test logging of slow queries."""
        sql = "SELECT * FROM large_table WHERE complex_condition = true"
        duration = 150.0  # 150ms - slow
        
        self.logger.log_query(sql, duration)
        
        slow_queries = self.logger.get_slow_queries()
        self.assertEqual(len(slow_queries), 1)
        self.assertEqual(slow_queries[0]['sql'], sql)
        self.assertEqual(slow_queries[0]['duration_ms'], duration)
        self.assertTrue(slow_queries[0]['is_slow'])
    
    def test_query_pattern_extraction(self):
        """Test query pattern extraction."""
        queries = [
            "SELECT * FROM users WHERE id = 1",
            "SELECT * FROM users WHERE id = 2",
            "SELECT * FROM users WHERE id = 3",
        ]
        
        for i, query in enumerate(queries):
            self.logger.log_query(query, 100.0)
        
        patterns = self.logger.get_query_patterns()
        
        # Should group similar queries
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]['count'], 3)
        self.assertEqual(patterns[0]['pattern'], 'SELECT FROM USERS')
    
    def test_trend_analysis(self):
        """Test slow query trend analysis."""
        # Add queries over time
        base_time = datetime.now()
        
        # Simulate increasing slow queries
        for i in range(10):
            with patch('platform_core.database.monitoring.datetime') as mock_dt:
                mock_dt.now.return_value = base_time + timedelta(minutes=i*5)
                self.logger.log_query(f"SLOW QUERY {i}", 100 + i*10)
        
        trends = self.logger.analyze_trends(window_minutes=60)
        
        self.assertEqual(trends['total_slow_queries'], 10)
        self.assertIn('trend', trends)
        # Trend should be increasing due to increasing durations


class TestConnectionMonitor(TestCase):
    """Test connection monitoring."""
    
    def setUp(self):
        self.monitor = ConnectionMonitor()
        # Stop the monitoring thread for testing
        self.monitor._monitoring = False
    
    def tearDown(self):
        self.monitor.stop()
    
    @patch('platform_core.database.monitoring.connections')
    def test_get_connection_stats(self, mock_connections):
        """Test getting connection statistics."""
        # Mock pg_stat_activity query
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ('active', 5),
            ('idle', 10),
            ('idle in transaction', 2),
        ]
        
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
        
        stats = self.monitor._get_connection_stats('default')
        
        self.assertEqual(stats['active'], 5)
        self.assertEqual(stats['idle'], 10)
        self.assertEqual(stats['idle_in_transaction'], 2)
        self.assertEqual(stats['total'], 17)
    
    def test_connection_health_check(self):
        """Test connection health checking."""
        # Set up problematic stats
        self.monitor.connection_stats['default'] = {
            'idle_in_transaction': 10,  # High - indicates leak
            'total': 95,  # Near max (assuming 100)
            'active': 50,
            'idle': 35
        }
        
        with patch.object(self.monitor, '_trigger_connection_alert') as mock_alert:
            self.monitor._check_connection_health()
            
            # Should trigger alerts for both issues
            self.assertEqual(mock_alert.call_count, 2)
            alert_types = [call[0][1] for call in mock_alert.call_args_list]
            self.assertIn('leak', alert_types)
            self.assertIn('exhaustion', alert_types)


class TestDatabaseMonitor(TestCase):
    """Test database monitoring coordinator."""
    
    def setUp(self):
        # Use the global instance but reset it
        self.monitor = database_monitor
    
    def test_dashboard_data_structure(self):
        """Test dashboard data generation."""
        data = self.monitor.get_dashboard_data()
        
        # Verify structure
        self.assertIn('timestamp', data)
        self.assertIn('slow_queries', data)
        self.assertIn('connections', data)
        self.assertIn('alerts', data)
        self.assertIn('health_score', data)
        
        # Verify sub-structures
        self.assertIn('recent', data['slow_queries'])
        self.assertIn('patterns', data['slow_queries'])
        self.assertIn('trends', data['slow_queries'])
    
    def test_health_score_calculation(self):
        """Test health score calculation."""
        # Mock various issues
        with patch.object(self.monitor.slow_query_logger, 'analyze_trends') as mock_trends:
            mock_trends.return_value = {'trend': 'increasing'}
            
            with patch.object(self.monitor.connection_monitor, 'get_current_stats') as mock_stats:
                mock_stats.return_value = {
                    'default': {
                        'idle_in_transaction': 10,  # High
                        'max_seen': 90  # Very high
                    }
                }
                
                health = self.monitor._calculate_health_score()
                
                # Score should be reduced due to issues
                self.assertLess(health['score'], 100)
                self.assertGreater(len(health['issues']), 0)
                self.assertIn('status', health)
    
    def test_export_prometheus_metrics(self):
        """Test Prometheus metrics export."""
        metrics = self.monitor.export_metrics(format='prometheus')
        
        # Should contain Prometheus format metrics
        self.assertIn('# HELP', metrics)
        self.assertIn('# TYPE', metrics)
        self.assertIn('db_slow_queries_total', metrics)
        self.assertIn('db_connections_active', metrics)
        self.assertIn('db_health_score', metrics)


class TestOptimizedMigrations(TestCase):
    """Test optimized migration tools."""
    
    def setUp(self):
        self.executor = OptimizedMigrationExecutor()
        self.generator = IndexMigrationGenerator()
    
    def test_optimize_operations(self):
        """Test migration operation optimization."""
        from django.db import migrations
        
        # Create test operations
        operations = [
            migrations.CreateModel(
                name='ModelA',
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('name', models.CharField(max_length=100)),
                ]
            ),
            migrations.CreateModel(
                name='ModelB',
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('model_a', models.ForeignKey('ModelA', on_delete=models.CASCADE)),
                ]
            ),
            migrations.AddField(
                model_name='ModelA',
                name='field1',
                field=models.CharField(max_length=50)
            ),
            migrations.AddField(
                model_name='ModelA',
                name='field2',
                field=models.CharField(max_length=50)
            ),
        ]
        
        optimized = self.executor._optimize_operations(operations)
        
        # Should maintain dependency order
        self.assertEqual(len(optimized), len(operations))
        
        # ModelA should come before ModelB due to FK dependency
        model_names = [op.name for op in optimized if hasattr(op, 'name')]
        self.assertEqual(model_names.index('ModelA'), 0)
        self.assertEqual(model_names.index('ModelB'), 1)
    
    def test_index_migration_generation(self):
        """Test index migration generation."""
        suggestions = [
            {
                'type': 'single',
                'field': 'status',
                'table': 'test_model'
            },
            {
                'type': 'composite',
                'fields': ['status', 'created_date'],
                'table': 'test_model'
            }
        ]
        
        # Mock model
        mock_model = Mock()
        mock_model._meta.db_table = 'test_model'
        mock_model._meta.model_name = 'TestModel'
        mock_model._meta.app_label = 'test'
        
        migration = self.generator.generate_index_migration(mock_model, suggestions)
        
        # Should have operations for each suggestion
        self.assertEqual(len(migration.operations), 2)
    
    def test_migration_advisor(self):
        """Test migration optimization advisor."""
        from django.db import migrations
        
        # Create problematic migration
        migration = migrations.Migration(
            'test',
            operations=[
                migrations.AddField(
                    model_name='TestModel',
                    name='new_field',
                    field=models.CharField(max_length=100, null=False)  # Non-nullable
                ),
                migrations.RunSQL(
                    "CREATE INDEX idx_test ON test_model (status);"  # No CONCURRENTLY
                )
            ]
        )
        
        advice = MigrationOptimizationAdvisor.analyze_migration(migration)
        
        # Should warn about issues
        self.assertGreater(len(advice['warnings']), 0)
        self.assertTrue(
            any('non-nullable' in w for w in advice['warnings'])
        )
        self.assertTrue(
            any('CONCURRENTLY' in w for w in advice['warnings'])
        )


class TestManagementCommands(TestCase):
    """Test management commands."""
    
    def test_optimize_database_command(self):
        """Test optimize_database command."""
        out = StringIO()
        
        # Test analysis mode
        call_command('optimize_database', '--analyze', stdout=out)
        output = out.getvalue()
        
        self.assertIn('Starting database analysis', output)
        self.assertIn('DATABASE OPTIMIZATION ANALYSIS', output)
    
    def test_optimize_database_monitor(self):
        """Test database monitoring command."""
        out = StringIO()
        
        # Test monitoring mode
        call_command('optimize_database', '--monitor', stdout=out)
        output = out.getvalue()
        
        self.assertIn('DATABASE MONITORING DASHBOARD', output)
        self.assertIn('Health Score:', output)
    
    def test_optimize_database_export(self):
        """Test metrics export."""
        out = StringIO()
        
        # Test Prometheus export
        call_command('optimize_database', '--monitor', '--export=prometheus', stdout=out)
        output = out.getvalue()
        
        self.assertIn('# HELP', output)
        self.assertIn('db_slow_queries_total', output)