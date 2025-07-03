"""
Cache Warming

Proactive cache population to improve performance.
"""

import logging
import time
from typing import Dict, List, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.test import Client
from celery import shared_task

from .cache import cache_manager

logger = logging.getLogger(__name__)


class CacheWarmer:
    """
    Cache warming manager.
    """
    
    def __init__(self):
        """Initialize cache warmer."""
        self.warming_config = getattr(settings, 'CACHE_WARMING_CONFIG', {})
        self.max_workers = self.warming_config.get('max_workers', 4)
        self.timeout = self.warming_config.get('timeout', 30)
        self.client = Client()
        self.warmers = {}
        
    def register_warmer(
        self,
        name: str,
        warmer_func: Callable[[], List[Dict[str, Any]]]
    ):
        """
        Register a cache warmer function.
        
        Args:
            name: Warmer name
            warmer_func: Function that returns list of URLs to warm
        """
        self.warmers[name] = warmer_func
        logger.info(f"Registered cache warmer: {name}")
        
    def warm_url(self, url: str, method: str = 'GET', **kwargs) -> bool:
        """
        Warm a single URL.
        
        Args:
            url: URL to warm
            method: HTTP method
            **kwargs: Additional request parameters
            
        Returns:
            True if successful
        """
        try:
            start_time = time.time()
            
            # Add warming header
            headers = kwargs.get('headers', {})
            headers['X-Cache-Warm'] = 'true'
            kwargs['headers'] = headers
            
            # Make request
            response = getattr(self.client, method.lower())(
                url,
                **kwargs
            )
            
            duration = time.time() - start_time
            
            if response.status_code == 200:
                logger.info(
                    f"Warmed {url} in {duration:.2f}s"
                )
                return True
            else:
                logger.warning(
                    f"Failed to warm {url}: {response.status_code}"
                )
                return False
                
        except Exception as e:
            logger.error(f"Error warming {url}: {e}")
            return False
            
    def warm_urls(self, urls: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Warm multiple URLs concurrently.
        
        Args:
            urls: List of URL configurations
            
        Returns:
            Statistics dict
        """
        stats = {
            'total': len(urls),
            'success': 0,
            'failed': 0,
            'duration': 0
        }
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_url = {
                executor.submit(
                    self.warm_url,
                    url_config.get('url'),
                    url_config.get('method', 'GET'),
                    **url_config.get('kwargs', {})
                ): url_config
                for url_config in urls
            }
            
            # Process completed tasks
            for future in as_completed(future_to_url):
                url_config = future_to_url[future]
                try:
                    if future.result():
                        stats['success'] += 1
                    else:
                        stats['failed'] += 1
                except Exception as e:
                    logger.error(
                        f"Error processing {url_config.get('url')}: {e}"
                    )
                    stats['failed'] += 1
                    
        stats['duration'] = time.time() - start_time
        
        logger.info(
            f"Cache warming completed: {stats['success']}/{stats['total']} "
            f"successful in {stats['duration']:.2f}s"
        )
        
        return stats
        
    def run_warmer(self, warmer_name: str) -> Dict[str, int]:
        """
        Run a specific warmer.
        
        Args:
            warmer_name: Name of registered warmer
            
        Returns:
            Statistics dict
        """
        if warmer_name not in self.warmers:
            raise ValueError(f"Unknown warmer: {warmer_name}")
            
        # Get URLs from warmer
        urls = self.warmers[warmer_name]()
        
        # Warm URLs
        return self.warm_urls(urls)
        
    def run_all_warmers(self) -> Dict[str, Dict[str, int]]:
        """
        Run all registered warmers.
        
        Returns:
            Dict of statistics per warmer
        """
        results = {}
        
        for warmer_name in self.warmers:
            try:
                results[warmer_name] = self.run_warmer(warmer_name)
            except Exception as e:
                logger.error(f"Error running warmer {warmer_name}: {e}")
                results[warmer_name] = {
                    'total': 0,
                    'success': 0,
                    'failed': 0,
                    'error': str(e)
                }
                
        return results


# Global warmer instance
cache_warmer = CacheWarmer()


# Built-in warmers

def popular_pages_warmer() -> List[Dict[str, Any]]:
    """
    Warm popular/frequently accessed pages.
    """
    urls = []
    
    # Add homepage
    urls.append({'url': '/'})
    
    # Add configured popular pages
    popular_pages = getattr(settings, 'CACHE_WARMING_POPULAR_PAGES', [])
    for page in popular_pages:
        if isinstance(page, str):
            urls.append({'url': page})
        else:
            urls.append(page)
            
    return urls


def model_list_warmer() -> List[Dict[str, Any]]:
    """
    Warm model list views.
    """
    urls = []
    
    # Get models to warm from config
    models_config = getattr(settings, 'CACHE_WARMING_MODELS', {})
    
    for app_model, config in models_config.items():
        try:
            app_label, model_name = app_model.split('.')
            
            # Try to reverse URL for model list
            list_url_name = config.get(
                'list_url_name',
                f'{app_label}:{model_name}_list'
            )
            
            try:
                url = reverse(list_url_name)
                urls.append({
                    'url': url,
                    'kwargs': config.get('kwargs', {})
                })
            except Exception:
                logger.warning(f"Could not reverse {list_url_name}")
                
        except Exception as e:
            logger.error(f"Error processing model {app_model}: {e}")
            
    return urls


def model_detail_warmer() -> List[Dict[str, Any]]:
    """
    Warm model detail views for recent/popular objects.
    """
    urls = []
    
    # Get models to warm from config
    models_config = getattr(settings, 'CACHE_WARMING_MODELS', {})
    
    for app_model, config in models_config.items():
        try:
            # Get model class
            app_label, model_name = app_model.split('.')
            model_class = models.get_model(app_label, model_name)
            
            # Get objects to warm
            queryset = model_class.objects.all()
            
            # Apply filters
            if 'filter' in config:
                queryset = queryset.filter(**config['filter'])
                
            # Apply ordering
            if 'order_by' in config:
                queryset = queryset.order_by(config['order_by'])
                
            # Limit results
            limit = config.get('limit', 10)
            queryset = queryset[:limit]
            
            # Generate URLs
            detail_url_name = config.get(
                'detail_url_name',
                f'{app_label}:{model_name}_detail'
            )
            
            for obj in queryset:
                try:
                    url = reverse(detail_url_name, args=[obj.pk])
                    urls.append({
                        'url': url,
                        'kwargs': config.get('kwargs', {})
                    })
                except Exception:
                    logger.warning(
                        f"Could not reverse {detail_url_name} for {obj.pk}"
                    )
                    
        except Exception as e:
            logger.error(f"Error processing model {app_model}: {e}")
            
    return urls


def api_endpoint_warmer() -> List[Dict[str, Any]]:
    """
    Warm API endpoints.
    """
    urls = []
    
    # Get API endpoints from config
    api_endpoints = getattr(settings, 'CACHE_WARMING_API_ENDPOINTS', [])
    
    for endpoint in api_endpoints:
        if isinstance(endpoint, str):
            urls.append({
                'url': endpoint,
                'headers': {'Accept': 'application/json'}
            })
        else:
            # Endpoint with custom config
            url_config = endpoint.copy()
            headers = url_config.get('headers', {})
            headers.setdefault('Accept', 'application/json')
            url_config['headers'] = headers
            urls.append(url_config)
            
    return urls


# Register built-in warmers
cache_warmer.register_warmer('popular_pages', popular_pages_warmer)
cache_warmer.register_warmer('model_list', model_list_warmer)
cache_warmer.register_warmer('model_detail', model_detail_warmer)
cache_warmer.register_warmer('api_endpoints', api_endpoint_warmer)


# Celery tasks

@shared_task
def warm_cache(warmer_name: Optional[str] = None):
    """
    Celery task to warm cache.
    
    Args:
        warmer_name: Specific warmer to run, or None for all
    """
    if warmer_name:
        return cache_warmer.run_warmer(warmer_name)
    else:
        return cache_warmer.run_all_warmers()


@shared_task
def scheduled_cache_warming():
    """
    Scheduled cache warming task.
    """
    # Run all warmers
    results = cache_warmer.run_all_warmers()
    
    # Log results
    total_success = sum(r.get('success', 0) for r in results.values())
    total_failed = sum(r.get('failed', 0) for r in results.values())
    
    logger.info(
        f"Scheduled cache warming completed: "
        f"{total_success} successful, {total_failed} failed"
    )
    
    return results


# Helper functions

def warm_url_pattern(pattern: str, **kwargs):
    """
    Warm all URLs matching a pattern.
    
    Args:
        pattern: URL pattern with placeholders
        **kwargs: Values for placeholders
    """
    # This would require URL pattern matching logic
    # For now, it's a placeholder for future implementation
    pass


def warm_queryset(
    queryset,
    url_name: str,
    url_args: Optional[List[str]] = None,
    url_kwargs: Optional[Dict[str, str]] = None
):
    """
    Warm URLs for a queryset.
    
    Args:
        queryset: Django queryset
        url_name: URL name to reverse
        url_args: List of attribute names for URL args
        url_kwargs: Dict of attribute names for URL kwargs
    """
    urls = []
    
    for obj in queryset:
        try:
            # Build args
            args = []
            if url_args:
                for arg_name in url_args:
                    args.append(getattr(obj, arg_name))
                    
            # Build kwargs
            kwargs = {}
            if url_kwargs:
                for kwarg_name, attr_name in url_kwargs.items():
                    kwargs[kwarg_name] = getattr(obj, attr_name)
                    
            # Reverse URL
            url = reverse(url_name, args=args, kwargs=kwargs)
            urls.append({'url': url})
            
        except Exception as e:
            logger.error(f"Error building URL for {obj}: {e}")
            
    # Warm URLs
    return cache_warmer.warm_urls(urls)


def start_cache_warming():
    """
    Start cache warming based on configuration.
    """
    warming_config = getattr(settings, 'CACHE_WARMING_CONFIG', {})
    
    if warming_config.get('startup_warming', False):
        # Run warmers on startup
        logger.info("Running startup cache warming...")
        
        # Use thread to avoid blocking startup
        from threading import Thread
        thread = Thread(target=cache_warmer.run_all_warmers)
        thread.daemon = True
        thread.start()
        
    if warming_config.get('scheduled_warming', False):
        # Schedule periodic warming
        from celery.schedules import crontab
        from celery import current_app
        
        schedule = warming_config.get('schedule', {'hour': 3, 'minute': 0})
        
        current_app.conf.beat_schedule['cache_warming'] = {
            'task': 'platform_core.cache.warming.scheduled_cache_warming',
            'schedule': crontab(**schedule),
        }
        
        logger.info(f"Scheduled cache warming with: {schedule}")