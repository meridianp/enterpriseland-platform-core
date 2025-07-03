"""
CDN Manager

Central management for CDN operations.
"""

import time
import logging
from typing import Dict, List, Any, Optional, Union
from django.conf import settings
from django.core.cache import cache
from django.utils.module_loading import import_string
from datetime import datetime, timedelta

from .providers import CDNProvider, MultiCDN, get_cdn_provider
from .optimization import AssetOptimizer
from .utils import (
    calculate_cache_key,
    should_use_cdn,
    get_asset_version,
    get_cdn_url
)

logger = logging.getLogger(__name__)


class CDNManager:
    """Central CDN management system."""
    
    def __init__(self):
        self.provider = None
        self.optimizer = None
        self.stats = {}
        self.initialized = False
        self._init_lock = False
        
    def initialize(self):
        """Initialize CDN manager."""
        if self.initialized or self._init_lock:
            return
        
        self._init_lock = True
        
        try:
            # Initialize provider
            self.provider = get_cdn_provider()
            
            # Initialize optimizer
            optimizer_config = getattr(settings, 'CDN_OPTIMIZER_CONFIG', {})
            self.optimizer = AssetOptimizer(optimizer_config)
            
            # Load stats from cache
            self.stats = cache.get('cdn_manager_stats', {})
            
            self.initialized = True
            logger.info("CDN Manager initialized successfully")
            
        except Exception as e:
            logger.error(f"CDN Manager initialization failed: {e}")
            
        finally:
            self._init_lock = False
    
    def get_url(self, path: str, **kwargs) -> str:
        """Get CDN URL for a path."""
        self.initialize()
        
        if not self.provider or not self.provider.is_enabled():
            return path
        
        # Check if CDN should be used for this path
        if not should_use_cdn(path):
            return path
        
        # Track usage
        self._track_usage('url_generation', path)
        
        return self.provider.get_url(path, **kwargs)
    
    def purge(self, paths: Union[str, List[str]], **kwargs) -> bool:
        """Purge paths from CDN cache."""
        self.initialize()
        
        if not self.provider:
            return False
        
        if isinstance(paths, str):
            paths = [paths]
        
        # Track purge
        self._track_usage('purge', {'paths': paths, 'count': len(paths)})
        
        success = self.provider.purge(paths)
        
        # Update stats
        if success:
            self.stats['last_purge'] = datetime.now().isoformat()
            self.stats['purge_count'] = self.stats.get('purge_count', 0) + len(paths)
        
        self._save_stats()
        
        return success
    
    def purge_pattern(self, pattern: str) -> bool:
        """Purge paths matching pattern."""
        self.initialize()
        
        if not self.provider:
            return False
        
        # Get all cached keys matching pattern
        # This would require integration with cache backend
        paths = self._get_paths_by_pattern(pattern)
        
        if paths:
            return self.purge(paths)
        
        return True
    
    def purge_tag(self, tag: str) -> bool:
        """Purge paths by tag."""
        self.initialize()
        
        if not self.provider:
            return False
        
        # Get paths associated with tag
        tag_key = f"cdn_tag:{tag}"
        paths = cache.get(tag_key, [])
        
        if paths:
            success = self.purge(paths)
            
            # Clear tag
            if success:
                cache.delete(tag_key)
            
            return success
        
        return True
    
    def purge_all(self) -> bool:
        """Purge all CDN content."""
        self.initialize()
        
        if not self.provider:
            return False
        
        # Track purge
        self._track_usage('purge_all', {})
        
        success = self.provider.purge_all()
        
        # Update stats
        if success:
            self.stats['last_full_purge'] = datetime.now().isoformat()
            self.stats['full_purge_count'] = self.stats.get('full_purge_count', 0) + 1
        
        self._save_stats()
        
        return success
    
    def preload(self, urls: List[str]) -> bool:
        """Preload URLs into CDN cache."""
        self.initialize()
        
        if not self.provider:
            return False
        
        # Track preload
        self._track_usage('preload', {'urls': urls, 'count': len(urls)})
        
        return self.provider.preload(urls)
    
    def optimize_asset(self, filename: str, content: bytes) -> bytes:
        """Optimize asset content."""
        self.initialize()
        
        if not self.optimizer:
            return content
        
        return self.optimizer.optimize_content(filename, content)
    
    def tag_path(self, path: str, tags: List[str]):
        """Associate tags with a path for invalidation."""
        for tag in tags:
            tag_key = f"cdn_tag:{tag}"
            paths = cache.get(tag_key, [])
            
            if path not in paths:
                paths.append(path)
                cache.set(tag_key, paths, 86400)  # 24 hours
    
    def get_stats(self) -> Dict[str, Any]:
        """Get CDN statistics."""
        self.initialize()
        
        stats = {
            'manager': self.stats.copy(),
            'provider': None,
            'usage': self._get_usage_stats()
        }
        
        if self.provider:
            try:
                stats['provider'] = self.provider.get_stats()
            except Exception as e:
                logger.error(f"Failed to get provider stats: {e}")
                stats['provider'] = {'error': str(e)}
        
        return stats
    
    def health_check(self) -> Dict[str, Any]:
        """Check CDN health status."""
        self.initialize()
        
        health = {
            'status': 'healthy',
            'initialized': self.initialized,
            'provider_enabled': False,
            'checks': {}
        }
        
        if self.provider:
            health['provider_enabled'] = self.provider.is_enabled()
            
            # Test URL generation
            try:
                test_url = self.provider.get_url('/test.jpg')
                health['checks']['url_generation'] = 'passed'
            except:
                health['checks']['url_generation'] = 'failed'
                health['status'] = 'unhealthy'
            
            # Test stats retrieval
            try:
                stats = self.provider.get_stats()
                health['checks']['stats'] = 'passed' if stats else 'warning'
            except:
                health['checks']['stats'] = 'failed'
                health['status'] = 'degraded' if health['status'] == 'healthy' else health['status']
        else:
            health['status'] = 'unhealthy'
            health['checks']['provider'] = 'not_initialized'
        
        return health
    
    def configure(self, config: Dict[str, Any]):
        """Update CDN configuration."""
        # Update settings
        for key, value in config.items():
            setattr(settings, f'CDN_{key.upper()}', value)
        
        # Reinitialize
        self.initialized = False
        self.initialize()
    
    def _track_usage(self, operation: str, data: Any):
        """Track CDN usage."""
        # Update operation counter
        counter_key = f"cdn_usage:{operation}:{datetime.now().strftime('%Y%m%d')}"
        
        try:
            current = cache.get(counter_key, 0)
            cache.set(counter_key, current + 1, 86400 * 7)  # Keep for 7 days
        except:
            pass
        
        # Log operation
        logger.debug(f"CDN operation: {operation} - {data}")
    
    def _get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        stats = {}
        
        # Get today's stats
        today = datetime.now().strftime('%Y%m%d')
        
        operations = ['url_generation', 'purge', 'purge_all', 'preload']
        
        for op in operations:
            key = f"cdn_usage:{op}:{today}"
            stats[f"{op}_today"] = cache.get(key, 0)
        
        return stats
    
    def _get_paths_by_pattern(self, pattern: str) -> List[str]:
        """Get paths matching pattern from cache tracking."""
        # This would require integration with cache backend
        # For now, return empty list
        return []
    
    def _save_stats(self):
        """Save stats to cache."""
        cache.set('cdn_manager_stats', self.stats, 86400)  # 24 hours


class CDNContextManager:
    """Context manager for CDN operations."""
    
    def __init__(self, manager: CDNManager):
        self.manager = manager
        self.original_enabled = None
        
    def __enter__(self):
        """Enter context."""
        if self.manager.provider:
            self.original_enabled = self.manager.provider.enabled
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context."""
        if self.manager.provider and self.original_enabled is not None:
            self.manager.provider.enabled = self.original_enabled
    
    def disable(self):
        """Temporarily disable CDN."""
        if self.manager.provider:
            self.manager.provider.enabled = False
    
    def enable(self):
        """Temporarily enable CDN."""
        if self.manager.provider:
            self.manager.provider.enabled = True


# Global CDN manager instance
cdn_manager = CDNManager()


def with_cdn(func):
    """Decorator to ensure CDN is initialized."""
    def wrapper(*args, **kwargs):
        cdn_manager.initialize()
        return func(*args, **kwargs)
    return wrapper


def without_cdn(func):
    """Decorator to disable CDN for function."""
    def wrapper(*args, **kwargs):
        with CDNContextManager(cdn_manager) as ctx:
            ctx.disable()
            return func(*args, **kwargs)
    return wrapper