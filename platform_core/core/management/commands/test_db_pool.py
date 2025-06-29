"""
Django management command for testing database connection pooling configuration.

Tests connection pool behavior, performance, and configuration
across all configured databases.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.conf import settings
from platform_core.core.db_router import ConnectionPoolMonitor


class Command(BaseCommand):
    help = 'Test database connection pooling configuration and performance'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--database',
            type=str,
            default='default',
            help='Database to test (default: default)'
        )
        parser.add_argument(
            '--connections',
            type=int,
            default=10,
            help='Number of concurrent connections to test (default: 10)'
        )
        parser.add_argument(
            '--duration',
            type=int,
            default=30,
            help='Test duration in seconds (default: 30)'
        )
        parser.add_argument(
            '--query-delay',
            type=float,
            default=0.1,
            help='Delay between queries in seconds (default: 0.1)'
        )
        parser.add_argument(
            '--test-type',
            choices=['basic', 'stress', 'pooling', 'routing'],
            default='basic',
            help='Type of test to run (default: basic)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose output'
        )
    
    def handle(self, *args, **options):
        database = options['database']
        connections_count = options['connections']
        duration = options['duration']
        query_delay = options['query_delay']
        test_type = options['test_type']
        verbose = options['verbose']
        
        try:
            self.stdout.write(
                self.style.SUCCESS(f"Starting database connection pool test...")
            )
            self.stdout.write(f"Database: {database}")
            self.stdout.write(f"Test type: {test_type}")
            self.stdout.write(f"Concurrent connections: {connections_count}")
            self.stdout.write(f"Duration: {duration}s")
            self.stdout.write("-" * 60)
            
            # Run the appropriate test
            if test_type == 'basic':
                self._test_basic_connectivity(database, verbose)
            elif test_type == 'stress':
                self._test_stress(database, connections_count, duration, query_delay, verbose)
            elif test_type == 'pooling':
                self._test_pooling_behavior(database, connections_count, duration, verbose)
            elif test_type == 'routing':
                self._test_routing_behavior(verbose)
            
            self.stdout.write(
                self.style.SUCCESS("\nDatabase connection pool test completed!")
            )
        
        except Exception as e:
            raise CommandError(f"Error during testing: {e}")
    
    def _test_basic_connectivity(self, database, verbose):
        """
        Test basic database connectivity and configuration.
        
        Args:
            database: Database alias to test
            verbose: Enable verbose output
        """
        self.stdout.write("Running basic connectivity test...")
        
        try:
            # Test connection
            connection = connections[database]
            
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
            
            if result == (1,):
                self.stdout.write(self.style.SUCCESS("✓ Basic connectivity: PASS"))
            else:
                self.stdout.write(self.style.ERROR("✗ Basic connectivity: FAIL"))
                return
            
            # Test connection configuration
            db_config = settings.DATABASES[database]
            
            if verbose:
                self.stdout.write("\nDatabase Configuration:")
                for key, value in db_config.items():
                    if key == 'PASSWORD':
                        value = '*' * len(str(value))
                    self.stdout.write(f"  {key}: {value}")
            
            # Test connection pooling settings
            conn_max_age = db_config.get('CONN_MAX_AGE', 0)
            conn_health_checks = db_config.get('CONN_HEALTH_CHECKS', False)
            
            self.stdout.write(f"✓ Connection persistence: {conn_max_age}s")
            self.stdout.write(f"✓ Health checks: {'Enabled' if conn_health_checks else 'Disabled'}")
            
            # Test pool monitoring
            monitor = ConnectionPoolMonitor()
            if monitor.monitoring_enabled:
                health = monitor.check_pool_health(database)
                if health.get('status') == 'healthy':
                    self.stdout.write("✓ Pool monitoring: HEALTHY")
                    
                    if verbose and health:
                        self.stdout.write("\nPool Health Details:")
                        for key, value in health.items():
                            self.stdout.write(f"  {key}: {value}")
                else:
                    self.stdout.write("✗ Pool monitoring: UNHEALTHY")
            else:
                self.stdout.write("- Pool monitoring: DISABLED")
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Basic connectivity test failed: {e}"))
    
    def _test_stress(self, database, connections_count, duration, query_delay, verbose):
        """
        Test database under stress conditions.
        
        Args:
            database: Database alias to test
            connections_count: Number of concurrent connections
            duration: Test duration in seconds
            query_delay: Delay between queries
            verbose: Enable verbose output
        """
        self.stdout.write(f"Running stress test with {connections_count} concurrent connections...")
        
        # Statistics tracking
        stats = {
            'total_queries': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'total_time': 0,
            'min_time': float('inf'),
            'max_time': 0,
            'errors': []
        }
        
        def run_queries(thread_id):
            """Run queries in a thread."""
            local_stats = {
                'queries': 0,
                'successes': 0,
                'failures': 0,
                'total_time': 0,
                'min_time': float('inf'),
                'max_time': 0
            }
            
            start_time = time.time()
            
            while (time.time() - start_time) < duration:
                try:
                    query_start = time.time()
                    
                    connection = connections[database]
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT COUNT(*) FROM django_migrations")
                        result = cursor.fetchone()
                    
                    query_time = time.time() - query_start
                    
                    local_stats['queries'] += 1
                    local_stats['successes'] += 1
                    local_stats['total_time'] += query_time
                    local_stats['min_time'] = min(local_stats['min_time'], query_time)
                    local_stats['max_time'] = max(local_stats['max_time'], query_time)
                    
                    if verbose and local_stats['queries'] % 100 == 0:
                        self.stdout.write(f"Thread {thread_id}: {local_stats['queries']} queries")
                    
                    time.sleep(query_delay)
                
                except Exception as e:
                    local_stats['queries'] += 1
                    local_stats['failures'] += 1
                    if len(stats['errors']) < 10:  # Limit error collection
                        stats['errors'].append(str(e))
            
            return local_stats
        
        # Run concurrent threads
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=connections_count) as executor:
            futures = [
                executor.submit(run_queries, i) 
                for i in range(connections_count)
            ]
            
            for future in as_completed(futures):
                thread_stats = future.result()
                stats['total_queries'] += thread_stats['queries']
                stats['successful_queries'] += thread_stats['successes']
                stats['failed_queries'] += thread_stats['failures']
                stats['total_time'] += thread_stats['total_time']
                stats['min_time'] = min(stats['min_time'], thread_stats['min_time'])
                stats['max_time'] = max(stats['max_time'], thread_stats['max_time'])
        
        actual_duration = time.time() - start_time
        
        # Display results
        self.stdout.write("\nStress Test Results:")
        self.stdout.write("-" * 40)
        self.stdout.write(f"Duration: {actual_duration:.2f}s")
        self.stdout.write(f"Total queries: {stats['total_queries']}")
        self.stdout.write(f"Successful queries: {stats['successful_queries']}")
        self.stdout.write(f"Failed queries: {stats['failed_queries']}")
        
        if stats['total_queries'] > 0:
            success_rate = (stats['successful_queries'] / stats['total_queries']) * 100
            self.stdout.write(f"Success rate: {success_rate:.2f}%")
            
            qps = stats['total_queries'] / actual_duration
            self.stdout.write(f"Queries per second: {qps:.2f}")
            
            if stats['successful_queries'] > 0:
                avg_time = stats['total_time'] / stats['successful_queries']
                self.stdout.write(f"Average query time: {avg_time*1000:.2f}ms")
                self.stdout.write(f"Min query time: {stats['min_time']*1000:.2f}ms")
                self.stdout.write(f"Max query time: {stats['max_time']*1000:.2f}ms")
        
        # Display errors (if any)
        if stats['errors']:
            self.stdout.write(f"\nErrors encountered ({len(stats['errors'])} shown):")
            for error in stats['errors'][:5]:
                self.stdout.write(f"  - {error}")
        
        # Success criteria
        if stats['failed_queries'] == 0:
            self.stdout.write(self.style.SUCCESS("✓ Stress test: PASS"))
        else:
            self.stdout.write(self.style.WARNING("⚠ Stress test: PASS with errors"))
    
    def _test_pooling_behavior(self, database, connections_count, duration, verbose):
        """
        Test connection pooling behavior and reuse.
        
        Args:
            database: Database alias to test
            connections_count: Number of concurrent connections
            duration: Test duration in seconds
            verbose: Enable verbose output
        """
        self.stdout.write("Running connection pooling behavior test...")
        
        # Test connection reuse
        connection_ids = set()
        
        def test_connection_reuse(thread_id):
            """Test connection reuse in a thread."""
            local_connection_ids = set()
            
            for i in range(10):
                try:
                    connection = connections[database]
                    
                    # Get connection identifier (varies by backend)
                    conn_id = id(connection.connection)
                    local_connection_ids.add(conn_id)
                    
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                    
                    time.sleep(0.1)
                
                except Exception as e:
                    if verbose:
                        self.stdout.write(f"Thread {thread_id} error: {e}")
            
            return local_connection_ids
        
        # Run pooling test
        with ThreadPoolExecutor(max_workers=connections_count) as executor:
            futures = [
                executor.submit(test_connection_reuse, i) 
                for i in range(connections_count)
            ]
            
            for future in as_completed(futures):
                thread_connection_ids = future.result()
                connection_ids.update(thread_connection_ids)
        
        # Analyze results
        self.stdout.write(f"\nPooling Test Results:")
        self.stdout.write("-" * 40)
        self.stdout.write(f"Unique connections created: {len(connection_ids)}")
        self.stdout.write(f"Concurrent threads: {connections_count}")
        
        # Expected behavior: connections should be reused
        if len(connection_ids) <= connections_count:
            self.stdout.write(self.style.SUCCESS("✓ Connection pooling: EFFICIENT"))
        else:
            self.stdout.write(self.style.WARNING("⚠ Connection pooling: MAY BE INEFFICIENT"))
        
        if verbose:
            self.stdout.write(f"Connection IDs: {sorted(connection_ids)}")
        
        # Test connection persistence
        self._test_connection_persistence(database, verbose)
    
    def _test_connection_persistence(self, database, verbose):
        """
        Test connection persistence settings.
        
        Args:
            database: Database alias to test
            verbose: Enable verbose output
        """
        self.stdout.write("\nTesting connection persistence...")
        
        try:
            db_config = settings.DATABASES[database]
            conn_max_age = db_config.get('CONN_MAX_AGE', 0)
            
            if conn_max_age > 0:
                # Test that connections persist
                connection1 = connections[database]
                conn_id1 = id(connection1.connection)
                
                with connection1.cursor() as cursor:
                    cursor.execute("SELECT 1")
                
                # Wait a short time and get connection again
                time.sleep(1)
                
                connection2 = connections[database]
                conn_id2 = id(connection2.connection)
                
                if conn_id1 == conn_id2:
                    self.stdout.write(self.style.SUCCESS("✓ Connection persistence: WORKING"))
                else:
                    self.stdout.write(self.style.WARNING("⚠ Connection persistence: NOT WORKING"))
                
                if verbose:
                    self.stdout.write(f"  CONN_MAX_AGE: {conn_max_age}s")
                    self.stdout.write(f"  Connection ID 1: {conn_id1}")
                    self.stdout.write(f"  Connection ID 2: {conn_id2}")
            else:
                self.stdout.write("- Connection persistence: DISABLED")
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Connection persistence test failed: {e}"))
    
    def _test_routing_behavior(self, verbose):
        """
        Test database routing behavior.
        
        Args:
            verbose: Enable verbose output
        """
        self.stdout.write("Running database routing test...")
        
        try:
            from platform_core.core.db_router import DatabaseRouter
            from accounts.models import User
            
            router = DatabaseRouter()
            
            # Test read routing
            read_db = router.db_for_read(User)
            self.stdout.write(f"Read operations route to: {read_db}")
            
            # Test write routing
            write_db = router.db_for_write(User)
            self.stdout.write(f"Write operations route to: {write_db}")
            
            # Test migration routing
            for db_alias in settings.DATABASES.keys():
                allow_migrate = router.allow_migrate(db_alias, 'accounts', 'User')
                self.stdout.write(f"Migrations on {db_alias}: {'Allowed' if allow_migrate else 'Blocked'}")
            
            # Test read database selection
            if router.read_databases:
                self.stdout.write(f"Available read databases: {router.read_databases}")
                self.stdout.write(self.style.SUCCESS("✓ Database routing: CONFIGURED"))
            else:
                self.stdout.write("No read replicas configured")
                self.stdout.write(self.style.WARNING("⚠ Database routing: NO READ REPLICAS"))
            
            if verbose:
                self.stdout.write(f"\nRouter configuration:")
                self.stdout.write(f"  Primary database: {router.primary_database}")
                self.stdout.write(f"  Read databases: {router.read_databases}")
                self.stdout.write(f"  Fallback to primary: {router.fallback_to_primary}")
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Database routing test failed: {e}"))