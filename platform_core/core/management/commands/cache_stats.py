"""
Django management command for cache statistics and monitoring.

Provides detailed cache performance metrics, health checks,
and maintenance operations.
"""

import json
from django.core.management.base import BaseCommand, CommandError
from django.core.cache import caches
from django.conf import settings
from platform_core.core.cache_strategies import CacheMonitor


class Command(BaseCommand):
    help = 'Display cache statistics and performance metrics'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--cache',
            default='default',
            help='Cache alias to check (default: default)'
        )
        parser.add_argument(
            '--format',
            choices=['table', 'json'],
            default='table',
            help='Output format (default: table)'
        )
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Perform cache cleanup after showing stats'
        )
        parser.add_argument(
            '--keys-pattern',
            default='*',
            help='Pattern to match keys for counting (default: *)'
        )
    
    def handle(self, *args, **options):
        cache_alias = options['cache']
        output_format = options['format']
        cleanup = options['cleanup']
        keys_pattern = options['keys_pattern']
        
        try:
            # Validate cache alias
            if cache_alias not in settings.CACHES:
                raise CommandError(f"Cache alias '{cache_alias}' not found in settings")
            
            monitor = CacheMonitor(cache_alias)
            
            # Get cache statistics
            stats = monitor.get_cache_stats()
            
            # Add key count
            key_count = monitor.get_key_count_by_pattern(keys_pattern)
            stats['key_count'] = key_count
            
            # Display statistics
            if output_format == 'json':
                self.stdout.write(json.dumps(stats, indent=2))
            else:
                self._display_table(stats, cache_alias)
            
            # Perform cleanup if requested
            if cleanup:
                self.stdout.write("\nPerforming cache cleanup...")
                freed_bytes = monitor.cleanup_expired_keys()
                self.stdout.write(
                    self.style.SUCCESS(f"Cache cleanup completed. Freed {freed_bytes} bytes.")
                )
        
        except Exception as e:
            raise CommandError(f"Error getting cache stats: {e}")
    
    def _display_table(self, stats: dict, cache_alias: str):
        """
        Display statistics in table format.
        
        Args:
            stats: Statistics dictionary
            cache_alias: Cache alias name
        """
        self.stdout.write(f"\n{self.style.HTTP_INFO('Cache Statistics')}: {cache_alias}")
        self.stdout.write("=" * 50)
        
        # Basic info
        self.stdout.write(f"Backend: {stats.get('backend', 'Unknown')}")
        self.stdout.write(f"Timestamp: {stats.get('timestamp', 'Unknown')}")
        self.stdout.write(f"Key Count: {stats.get('key_count', 'Unknown')}")
        
        # Redis-specific stats
        if 'redis_version' in stats:
            self.stdout.write("\nRedis Information:")
            self.stdout.write("-" * 20)
            self.stdout.write(f"Version: {stats.get('redis_version', 'Unknown')}")
            self.stdout.write(f"Memory Used: {stats.get('used_memory', 'Unknown')}")
            self.stdout.write(f"Connected Clients: {stats.get('connected_clients', 'Unknown')}")
            self.stdout.write(f"Commands Processed: {stats.get('total_commands_processed', 'Unknown')}")
            
            # Cache performance
            hit_rate = stats.get('cache_hit_rate', 0)
            hits = stats.get('keyspace_hits', 0)
            misses = stats.get('keyspace_misses', 0)
            
            self.stdout.write("\nPerformance Metrics:")
            self.stdout.write("-" * 20)
            self.stdout.write(f"Hit Rate: {hit_rate}%")
            self.stdout.write(f"Hits: {hits:,}")
            self.stdout.write(f"Misses: {misses:,}")
            
            # Performance assessment
            if hit_rate >= 80:
                performance = self.style.SUCCESS("Excellent")
            elif hit_rate >= 60:
                performance = self.style.WARNING("Good")
            else:
                performance = self.style.ERROR("Poor - Consider cache optimization")
            
            self.stdout.write(f"Performance: {performance}")
        
        # Error information
        if 'redis_error' in stats:
            self.stdout.write("\n" + self.style.ERROR(f"Redis Error: {stats['redis_error']}"))
        
        self.stdout.write("\n")


def warm_cache_command():
    """
    Warm the cache with frequently accessed data.
    """
    from platform_core.core.cache_strategies import CacheWarmer
    from contacts.models import Contact
    from assessments.models import DevelopmentPartnerAssessment
    
    warmer = CacheWarmer()
    
    # Warm model caches
    contact_count = warmer.warm_model_cache(Contact)
    assessment_count = warmer.warm_model_cache(DevelopmentPartnerAssessment)
    
    return contact_count + assessment_count