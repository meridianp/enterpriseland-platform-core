"""
Database router for read/write splitting in EnterpriseLand platform.

Provides intelligent routing of database queries to optimize performance
and distribute load between primary and read replica databases.
"""

import logging
import random
from typing import Optional, Any, Type
from django.conf import settings
from django.db import models
from django.apps import apps
from django.utils import timezone

logger = logging.getLogger(__name__)


class DatabaseRouter:
    """
    Database router that implements read/write splitting.
    
    Routes write operations to the primary database and read operations
    to read replicas when available. Includes intelligent fallback
    and load balancing.
    """
    
    # Models that should always use the primary database
    PRIMARY_ONLY_MODELS = {
        'auth.Session',
        'admin.LogEntry',
        'contenttypes.ContentType',
        'migrations.Migration',
    }
    
    # Apps that should always use the primary database
    PRIMARY_ONLY_APPS = {
        'sessions',
        'admin',
        'contenttypes',
        'migrations',
    }
    
    def __init__(self):
        self.read_databases = self._get_read_databases()
        self.primary_database = 'default'
        self.fallback_to_primary = getattr(settings, 'DB_FALLBACK_TO_PRIMARY', True)
        
    def _get_read_databases(self) -> list:
        """
        Get list of available read databases.
        
        Returns:
            List of read database aliases
        """
        read_dbs = []
        for alias, config in settings.DATABASES.items():
            if alias != 'default' and alias.startswith('read'):
                read_dbs.append(alias)
        return read_dbs
    
    def _get_model_key(self, model: Type[models.Model]) -> str:
        """
        Get the model key for routing decisions.
        
        Args:
            model: Django model class
            
        Returns:
            Model key in format 'app.ModelName'
        """
        return f"{model._meta.app_label}.{model.__name__}"
    
    def _should_use_primary(self, model: Type[models.Model]) -> bool:
        """
        Determine if a model should always use the primary database.
        
        Args:
            model: Django model class
            
        Returns:
            True if should use primary database
        """
        model_key = self._get_model_key(model)
        app_label = model._meta.app_label
        
        # Check model-specific rules
        if model_key in self.PRIMARY_ONLY_MODELS:
            return True
        
        # Check app-specific rules
        if app_label in self.PRIMARY_ONLY_APPS:
            return True
        
        # Check if model has specific routing hints
        if hasattr(model._meta, 'database_routing'):
            routing = model._meta.database_routing
            if routing.get('primary_only', False):
                return True
        
        return False
    
    def _select_read_database(self) -> str:
        """
        Select a read database using load balancing.
        
        Returns:
            Database alias for read operations
        """
        if not self.read_databases:
            return self.primary_database
        
        # Simple round-robin selection
        # In production, you might want more sophisticated load balancing
        return random.choice(self.read_databases)
    
    def db_for_read(self, model: Type[models.Model], **hints) -> Optional[str]:
        """
        Suggest the database to read from.
        
        Args:
            model: Django model class
            **hints: Additional routing hints
            
        Returns:
            Database alias or None
        """
        # Always use primary for certain models
        if self._should_use_primary(model):
            logger.debug(f"Routing {self._get_model_key(model)} read to primary (forced)")
            return self.primary_database
        
        # Check for explicit database hint
        if 'instance' in hints:
            instance = hints['instance']
            if hasattr(instance, '_state') and instance._state.db:
                logger.debug(f"Using instance database: {instance._state.db}")
                return instance._state.db
        
        # Check for transaction hint
        if hints.get('in_transaction', False):
            logger.debug(f"Routing {self._get_model_key(model)} read to primary (in transaction)")
            return self.primary_database
        
        # Select read database
        if self.read_databases:
            selected_db = self._select_read_database()
            logger.debug(f"Routing {self._get_model_key(model)} read to {selected_db}")
            return selected_db
        
        # Fallback to primary
        logger.debug(f"Routing {self._get_model_key(model)} read to primary (no replicas)")
        return self.primary_database
    
    def db_for_write(self, model: Type[models.Model], **hints) -> Optional[str]:
        """
        Suggest the database to write to.
        
        Args:
            model: Django model class
            **hints: Additional routing hints
            
        Returns:
            Database alias or None
        """
        # All writes go to primary
        logger.debug(f"Routing {self._get_model_key(model)} write to primary")
        return self.primary_database
    
    def allow_relation(self, obj1: models.Model, obj2: models.Model, **hints) -> Optional[bool]:
        """
        Allow relations between objects.
        
        Args:
            obj1: First model instance
            obj2: Second model instance
            **hints: Additional routing hints
            
        Returns:
            True if relation is allowed, None if no opinion
        """
        # Get database aliases for both objects
        db1 = obj1._state.db if obj1._state.db else self.primary_database
        db2 = obj2._state.db if obj2._state.db else self.primary_database
        
        # Allow relations if both objects are in the same database cluster
        # (primary or any read replica)
        database_cluster1 = 'cluster' if db1 in [self.primary_database] + self.read_databases else 'other'
        database_cluster2 = 'cluster' if db2 in [self.primary_database] + self.read_databases else 'other'
        
        if database_cluster1 == database_cluster2 == 'cluster':
            return True
        
        # Defer to Django's default behavior for other cases
        return None
    
    def allow_migrate(self, db: str, app_label: str, model_name: Optional[str] = None, **hints) -> Optional[bool]:
        """
        Determine if migrations should run on a database.
        
        Args:
            db: Database alias
            app_label: App label
            model_name: Model name (optional)
            **hints: Additional routing hints
            
        Returns:
            True if migration is allowed, False if not, None if no opinion
        """
        # Only allow migrations on the primary database
        if db == self.primary_database:
            return True
        
        # Don't migrate read replicas
        if db in self.read_databases:
            return False
        
        # No opinion on other databases
        return None


class ConnectionPoolMonitor:
    """
    Monitor database connection pool usage and performance.
    """
    
    def __init__(self):
        self.monitoring_enabled = getattr(settings, 'DATABASE_POOL_MONITORING', {}).get('ENABLED', True)
        self.slow_query_threshold = getattr(settings, 'DATABASE_POOL_MONITORING', {}).get('SLOW_QUERY_THRESHOLD', 1.0)
        self.log_slow_queries = getattr(settings, 'DATABASE_POOL_MONITORING', {}).get('LOG_SLOW_QUERIES', True)
    
    def log_connection_usage(self, db_alias: str, query_time: float, query: str) -> None:
        """
        Log connection usage statistics.
        
        Args:
            db_alias: Database alias
            query_time: Query execution time in seconds
            query: SQL query string
        """
        if not self.monitoring_enabled:
            return
        
        # Log slow queries
        if self.log_slow_queries and query_time > self.slow_query_threshold:
            logger.warning(
                f"Slow query detected on {db_alias}: {query_time:.3f}s",
                extra={
                    'database': db_alias,
                    'query_time': query_time,
                    'query': query[:200] + '...' if len(query) > 200 else query,
                    'slow_query': True
                }
            )
        
        # Log general metrics
        logger.debug(
            f"Query executed on {db_alias}: {query_time:.3f}s",
            extra={
                'database': db_alias,
                'query_time': query_time,
                'query_length': len(query)
            }
        )
    
    def check_pool_health(self, db_alias: str) -> dict:
        """
        Check the health of a database connection pool.
        
        Args:
            db_alias: Database alias
            
        Returns:
            Dictionary with pool health metrics
        """
        if not self.monitoring_enabled:
            return {}
        
        try:
            from django.db import connections
            connection = connections[db_alias]
            
            # Basic connection test
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
            
            health_status = {
                'database': db_alias,
                'status': 'healthy' if result == (1,) else 'unhealthy',
                'connection_available': True,
                'timestamp': timezone.now().isoformat()
            }
            
            # Add pool-specific metrics if available
            if hasattr(connection, 'pool'):
                pool = connection.pool
                health_status.update({
                    'pool_size': getattr(pool, 'size', None),
                    'checked_out': getattr(pool, 'checked_out', None),
                    'overflow': getattr(pool, 'overflow', None),
                })
            
            return health_status
        
        except Exception as e:
            logger.error(f"Health check failed for {db_alias}: {e}")
            return {
                'database': db_alias,
                'status': 'error',
                'error': str(e),
                'connection_available': False,
                'timestamp': timezone.now().isoformat()
            }
    
    def get_connection_stats(self) -> dict:
        """
        Get connection statistics for all databases.
        
        Returns:
            Dictionary with connection statistics
        """
        if not self.monitoring_enabled:
            return {}
        
        stats = {
            'timestamp': timezone.now().isoformat(),
            'databases': {},
            'total_connections': 0,
            'healthy_databases': 0,
            'unhealthy_databases': 0
        }
        
        for db_alias in settings.DATABASES.keys():
            db_health = self.check_pool_health(db_alias)
            stats['databases'][db_alias] = db_health
            
            if db_health.get('status') == 'healthy':
                stats['healthy_databases'] += 1
            else:
                stats['unhealthy_databases'] += 1
        
        return stats


# Global monitor instance
pool_monitor = ConnectionPoolMonitor()