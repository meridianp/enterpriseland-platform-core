"""
Tests for database router and connection pooling functionality.

Tests read/write splitting, connection pool monitoring,
and database routing decisions.
"""

import time
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.db import connections
from accounts.models import Group
from platform_core.core.db_router import DatabaseRouter, ConnectionPoolMonitor

User = get_user_model()


@override_settings(
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'test_db',
            'USER': 'test',
            'PASSWORD': 'test',
            'HOST': 'localhost',
            'PORT': '5432',
        },
        'read': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'test_db_read',
            'USER': 'test',
            'PASSWORD': 'test',
            'HOST': 'localhost',
            'PORT': '5432',
        },
        'read2': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'test_db_read2',
            'USER': 'test',
            'PASSWORD': 'test',
            'HOST': 'localhost',
            'PORT': '5432',
        }
    },
    DATABASE_ROUTERS=['core.db_router.DatabaseRouter']
)
class DatabaseRouterTest(TestCase):
    """
    Test cases for DatabaseRouter functionality.
    """
    
    def setUp(self):
        self.router = DatabaseRouter()
        self.group = Group.objects.create(name='Test Group')
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_init_detects_read_databases(self):
        """
        Test router initialization detects read databases.
        """
        # Should detect 'read' and 'read2' databases
        self.assertIn('read', self.router.read_databases)
        self.assertIn('read2', self.router.read_databases)
        self.assertEqual(len(self.router.read_databases), 2)
        self.assertEqual(self.router.primary_database, 'default')
    
    def test_get_model_key(self):
        """
        Test model key generation.
        """
        key = self.router._get_model_key(User)
        self.assertEqual(key, 'accounts.User')
        
        key = self.router._get_model_key(Group)
        self.assertEqual(key, 'accounts.Group')
    
    def test_should_use_primary_for_admin_models(self):
        """
        Test that admin and system models use primary database.
        """
        from django.contrib.admin.models import LogEntry
        from django.contrib.sessions.models import Session
        
        # Test by model key (if we can't import models)
        router = DatabaseRouter()
        router.PRIMARY_ONLY_MODELS.add('admin.LogEntry')
        router.PRIMARY_ONLY_MODELS.add('sessions.Session')
        
        # Mock models for testing
        mock_admin_model = MagicMock()
        mock_admin_model._meta.app_label = 'admin'
        mock_admin_model.__name__ = 'LogEntry'
        
        mock_session_model = MagicMock()
        mock_session_model._meta.app_label = 'sessions'
        mock_session_model.__name__ = 'Session'
        
        self.assertTrue(router._should_use_primary(mock_admin_model))
        self.assertTrue(router._should_use_primary(mock_session_model))
    
    def test_should_use_primary_for_apps(self):
        """
        Test that certain apps always use primary database.
        """
        mock_model = MagicMock()
        mock_model._meta.app_label = 'admin'
        mock_model.__name__ = 'TestModel'
        
        self.assertTrue(self.router._should_use_primary(mock_model))
        
        # Test normal app model
        self.assertFalse(self.router._should_use_primary(User))
    
    def test_db_for_read_uses_read_database(self):
        """
        Test that read operations use read databases.
        """
        db = self.router.db_for_read(User)
        
        # Should return one of the read databases
        self.assertIn(db, ['read', 'read2'])
    
    def test_db_for_read_primary_only_models(self):
        """
        Test that primary-only models read from primary.
        """
        mock_model = MagicMock()
        mock_model._meta.app_label = 'admin'
        mock_model.__name__ = 'LogEntry'
        
        db = self.router.db_for_read(mock_model)
        self.assertEqual(db, 'default')
    
    def test_db_for_read_with_instance_hint(self):
        """
        Test reading uses instance's database when hinted.
        """
        # Mock instance with specific database
        mock_instance = MagicMock()
        mock_instance._state.db = 'specific_db'
        
        db = self.router.db_for_read(User, instance=mock_instance)
        self.assertEqual(db, 'specific_db')
    
    def test_db_for_read_in_transaction(self):
        """
        Test that reads in transaction use primary database.
        """
        db = self.router.db_for_read(User, in_transaction=True)
        self.assertEqual(db, 'default')
    
    def test_db_for_write_always_primary(self):
        """
        Test that all writes go to primary database.
        """
        db = self.router.db_for_write(User)
        self.assertEqual(db, 'default')
        
        db = self.router.db_for_write(Group)
        self.assertEqual(db, 'default')
        
        # Even for admin models
        mock_model = MagicMock()
        mock_model._meta.app_label = 'admin'
        mock_model.__name__ = 'LogEntry'
        
        db = self.router.db_for_write(mock_model)
        self.assertEqual(db, 'default')
    
    def test_allow_relation_same_cluster(self):
        """
        Test that relations are allowed within the same database cluster.
        """
        # Create objects with database states
        obj1 = MagicMock()
        obj1._state.db = 'default'
        
        obj2 = MagicMock()
        obj2._state.db = 'read'
        
        # Should allow relation between primary and read replica
        result = self.router.allow_relation(obj1, obj2)
        self.assertTrue(result)
        
        # Both in primary
        obj2._state.db = 'default'
        result = self.router.allow_relation(obj1, obj2)
        self.assertTrue(result)
        
        # Both in read replica
        obj1._state.db = 'read'
        result = self.router.allow_relation(obj1, obj2)
        self.assertTrue(result)
    
    def test_allow_relation_different_clusters(self):
        """
        Test relation handling for different database clusters.
        """
        obj1 = MagicMock()
        obj1._state.db = 'default'
        
        obj2 = MagicMock()
        obj2._state.db = 'other_cluster'
        
        # Should defer to Django for different clusters
        result = self.router.allow_relation(obj1, obj2)
        self.assertIsNone(result)
    
    def test_allow_migrate_primary_only(self):
        """
        Test that migrations only run on primary database.
        """
        # Primary database should allow migrations
        result = self.router.allow_migrate('default', 'accounts', 'User')
        self.assertTrue(result)
        
        # Read replicas should not allow migrations
        result = self.router.allow_migrate('read', 'accounts', 'User')
        self.assertFalse(result)
        
        result = self.router.allow_migrate('read2', 'accounts', 'User')
        self.assertFalse(result)
        
        # Other databases should get no opinion
        result = self.router.allow_migrate('other_db', 'accounts', 'User')
        self.assertIsNone(result)
    
    @patch('random.choice')
    def test_select_read_database_load_balancing(self, mock_choice):
        """
        Test load balancing between read databases.
        """
        mock_choice.return_value = 'read2'
        
        db = self.router._select_read_database()
        self.assertEqual(db, 'read2')
        
        # Verify random.choice was called with read databases
        mock_choice.assert_called_once_with(['read', 'read2'])
    
    def test_select_read_database_no_replicas(self):
        """
        Test fallback when no read databases available.
        """
        router = DatabaseRouter()
        router.read_databases = []
        
        db = router._select_read_database()
        self.assertEqual(db, 'default')


@override_settings(
    DATABASE_POOL_MONITORING={
        'ENABLED': True,
        'SLOW_QUERY_THRESHOLD': 0.5,
        'LOG_SLOW_QUERIES': True,
    }
)
class ConnectionPoolMonitorTest(TestCase):
    """
    Test cases for ConnectionPoolMonitor.
    """
    
    def setUp(self):
        self.monitor = ConnectionPoolMonitor()
    
    def test_init_with_settings(self):
        """
        Test monitor initialization with settings.
        """
        self.assertTrue(self.monitor.monitoring_enabled)
        self.assertEqual(self.monitor.slow_query_threshold, 0.5)
        self.assertTrue(self.monitor.log_slow_queries)
    
    @patch('core.db_router.logger')
    def test_log_connection_usage_normal_query(self, mock_logger):
        """
        Test logging normal query usage.
        """
        self.monitor.log_connection_usage('default', 0.1, 'SELECT * FROM users')
        
        # Should log debug message for normal query
        mock_logger.debug.assert_called_once()
        self.assertIn('Query executed on default', mock_logger.debug.call_args[0][0])
    
    @patch('core.db_router.logger')
    def test_log_connection_usage_slow_query(self, mock_logger):
        """
        Test logging slow query usage.
        """
        slow_query = 'SELECT * FROM large_table WHERE complex_condition'
        self.monitor.log_connection_usage('default', 1.0, slow_query)
        
        # Should log warning for slow query
        mock_logger.warning.assert_called_once()
        self.assertIn('Slow query detected', mock_logger.warning.call_args[0][0])
        
        # Should also log debug message
        mock_logger.debug.assert_called_once()
    
    @patch('core.db_router.logger')
    def test_log_connection_usage_disabled(self, mock_logger):
        """
        Test that logging respects enabled flag.
        """
        self.monitor.monitoring_enabled = False
        self.monitor.log_connection_usage('default', 1.0, 'SELECT 1')
        
        # Should not log anything when disabled
        mock_logger.debug.assert_not_called()
        mock_logger.warning.assert_not_called()
    
    @patch('django.utils.timezone.now')
    @patch('django.db.connections')
    def test_check_pool_health_success(self, mock_connections, mock_now):
        """
        Test successful pool health check.
        """
        mock_now.return_value.isoformat.return_value = '2023-01-01T12:00:00Z'
        
        # Mock database connection and cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        
        mock_connections.__getitem__.return_value = mock_connection
        
        health = self.monitor.check_pool_health('default')
        
        self.assertEqual(health['database'], 'default')
        self.assertEqual(health['status'], 'healthy')
        self.assertTrue(health['connection_available'])
        self.assertEqual(health['timestamp'], '2023-01-01T12:00:00Z')
    
    @patch('django.utils.timezone.now')
    @patch('django.db.connections')
    @patch('core.db_router.logger')
    def test_check_pool_health_failure(self, mock_logger, mock_connections, mock_now):
        """
        Test pool health check failure.
        """
        mock_now.return_value.isoformat.return_value = '2023-01-01T12:00:00Z'
        mock_connections.__getitem__.side_effect = Exception('Connection failed')
        
        health = self.monitor.check_pool_health('default')
        
        self.assertEqual(health['database'], 'default')
        self.assertEqual(health['status'], 'error')
        self.assertFalse(health['connection_available'])
        self.assertEqual(health['error'], 'Connection failed')
        
        # Should log error
        mock_logger.error.assert_called_once()
    
    @patch('django.utils.timezone.now')
    @patch('django.db.connections')
    def test_check_pool_health_with_pool_metrics(self, mock_connections, mock_now):
        """
        Test health check includes pool metrics when available.
        """
        mock_now.return_value.isoformat.return_value = '2023-01-01T12:00:00Z'
        
        # Mock cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        
        # Mock connection with pool
        mock_pool = MagicMock()
        mock_pool.size = 20
        mock_pool.checked_out = 5
        mock_pool.overflow = 0
        
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connection.pool = mock_pool
        
        mock_connections.__getitem__.return_value = mock_connection
        
        health = self.monitor.check_pool_health('default')
        
        self.assertEqual(health['pool_size'], 20)
        self.assertEqual(health['checked_out'], 5)
        self.assertEqual(health['overflow'], 0)
    
    def test_check_pool_health_disabled(self):
        """
        Test that health check respects enabled flag.
        """
        self.monitor.monitoring_enabled = False
        health = self.monitor.check_pool_health('default')
        
        self.assertEqual(health, {})
    
    @patch('django.utils.timezone.now')
    @patch('core.db_router.ConnectionPoolMonitor.check_pool_health')
    @override_settings(DATABASES={
        'default': {'ENGINE': 'django.db.backends.postgresql'},
        'read': {'ENGINE': 'django.db.backends.postgresql'},
    })
    def test_get_connection_stats(self, mock_check_health, mock_now):
        """
        Test getting connection statistics for all databases.
        """
        mock_now.return_value.isoformat.return_value = '2023-01-01T12:00:00Z'
        
        # Mock health check results
        mock_check_health.side_effect = [
            {'status': 'healthy', 'database': 'default'},
            {'status': 'error', 'database': 'read'},
        ]
        
        stats = self.monitor.get_connection_stats()
        
        self.assertEqual(stats['timestamp'], '2023-01-01T12:00:00Z')
        self.assertEqual(stats['healthy_databases'], 1)
        self.assertEqual(stats['unhealthy_databases'], 1)
        self.assertIn('default', stats['databases'])
        self.assertIn('read', stats['databases'])
    
    def test_get_connection_stats_disabled(self):
        """
        Test that connection stats respects enabled flag.
        """
        self.monitor.monitoring_enabled = False
        stats = self.monitor.get_connection_stats()
        
        self.assertEqual(stats, {})


class DatabaseRouterIntegrationTest(TestCase):
    """
    Integration tests for database router with real models.
    """
    
    @override_settings(
        DATABASE_ROUTERS=['core.db_router.DatabaseRouter'],
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        }
    )
    def test_router_with_real_models(self):
        """
        Test router behavior with real model operations.
        """
        router = DatabaseRouter()
        
        # Test read operations
        read_db = router.db_for_read(User)
        self.assertEqual(read_db, 'default')  # No read replicas configured
        
        # Test write operations
        write_db = router.db_for_write(User)
        self.assertEqual(write_db, 'default')
        
        # Test migration decisions
        allow_migrate = router.allow_migrate('default', 'accounts', 'User')
        self.assertTrue(allow_migrate)
    
    def test_model_operations_with_router(self):
        """
        Test that model operations work correctly with router.
        """
        # Create objects (should work normally)
        group = Group.objects.create(name='Test Group')
        user = User.objects.create_user(
            username='routeruser',
            email='router@example.com',
            password='testpass123'
        )
        
        # Read operations (should work normally)
        retrieved_user = User.objects.get(id=user.id)
        self.assertEqual(retrieved_user.email, 'router@example.com')
        
        # Update operations (should work normally)
        user.email = 'updated@example.com'
        user.save()
        
        retrieved_user.refresh_from_db()
        self.assertEqual(retrieved_user.email, 'updated@example.com')