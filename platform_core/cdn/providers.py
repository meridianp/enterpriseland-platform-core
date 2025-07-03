"""
CDN Providers

Integration with various CDN providers.
"""

import logging
import hashlib
import requests
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta
from django.conf import settings
import time

logger = logging.getLogger(__name__)


class CDNProvider(ABC):
    """Base CDN provider interface."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_url = config.get('base_url', '')
        self.api_key = config.get('api_key', '')
        self.zone_id = config.get('zone_id', '')
        self.enabled = config.get('enabled', True)
    
    @abstractmethod
    def get_url(self, path: str, **kwargs) -> str:
        """Get CDN URL for a given path."""
        pass
    
    @abstractmethod
    def purge(self, paths: List[str]) -> bool:
        """Purge cached content."""
        pass
    
    @abstractmethod
    def purge_all(self) -> bool:
        """Purge all cached content."""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get CDN statistics."""
        pass
    
    @abstractmethod
    def preload(self, urls: List[str]) -> bool:
        """Preload content into CDN cache."""
        pass
    
    def is_enabled(self) -> bool:
        """Check if CDN is enabled."""
        return self.enabled and bool(self.base_url)
    
    def _build_cdn_url(self, path: str, query_params: Optional[Dict] = None) -> str:
        """Build full CDN URL."""
        # Remove leading slash for urljoin
        if path.startswith('/'):
            path = path[1:]
        
        url = urljoin(self.base_url, path)
        
        # Add query parameters
        if query_params:
            params = '&'.join(f"{k}={v}" for k, v in query_params.items())
            url = f"{url}?{params}"
        
        return url


class CloudflareCDN(CDNProvider):
    """Cloudflare CDN provider."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_base = 'https://api.cloudflare.com/client/v4'
        self.account_id = config.get('account_id', '')
    
    def get_url(self, path: str, **kwargs) -> str:
        """Get Cloudflare CDN URL."""
        if not self.is_enabled():
            return path
        
        # Add image optimization parameters
        if kwargs.get('optimize_images') and self._is_image(path):
            query_params = self._get_image_params(kwargs)
            return self._build_cdn_url(path, query_params)
        
        return self._build_cdn_url(path)
    
    def purge(self, paths: List[str]) -> bool:
        """Purge specific paths from Cloudflare cache."""
        if not self.zone_id or not self.api_key:
            logger.warning("Cloudflare credentials not configured")
            return False
        
        # Build full URLs
        urls = [self._build_cdn_url(path) for path in paths]
        
        # Cloudflare API limits to 30 URLs per request
        for i in range(0, len(urls), 30):
            batch = urls[i:i+30]
            
            response = requests.post(
                f"{self.api_base}/zones/{self.zone_id}/purge_cache",
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                },
                json={'files': batch}
            )
            
            if response.status_code != 200:
                logger.error(f"Cloudflare purge failed: {response.text}")
                return False
        
        return True
    
    def purge_all(self) -> bool:
        """Purge all content from Cloudflare cache."""
        if not self.zone_id or not self.api_key:
            return False
        
        response = requests.post(
            f"{self.api_base}/zones/{self.zone_id}/purge_cache",
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            },
            json={'purge_everything': True}
        )
        
        return response.status_code == 200
    
    def get_stats(self) -> Dict[str, Any]:
        """Get Cloudflare analytics."""
        if not self.zone_id or not self.api_key:
            return {'error': 'Credentials not configured'}
        
        # Get last 24 hours of data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)
        
        response = requests.get(
            f"{self.api_base}/zones/{self.zone_id}/analytics/dashboard",
            headers={'Authorization': f'Bearer {self.api_key}'},
            params={
                'since': start_date.isoformat(),
                'until': end_date.isoformat()
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                analytics = data.get('result', {}).get('totals', {})
                return {
                    'requests': analytics.get('requests', {}).get('all', 0),
                    'bandwidth': analytics.get('bandwidth', {}).get('all', 0),
                    'cached_requests': analytics.get('requests', {}).get('cached', 0),
                    'cache_hit_rate': self._calculate_hit_rate(analytics),
                    'threats': analytics.get('threats', {}).get('all', 0)
                }
        
        return {'error': 'Failed to fetch analytics'}
    
    def preload(self, urls: List[str]) -> bool:
        """Preload content using Cloudflare's prefetch."""
        # Cloudflare doesn't have a direct preload API
        # We can warm the cache by making requests
        success_count = 0
        
        for url in urls:
            try:
                response = requests.head(url, timeout=5)
                if response.status_code == 200:
                    success_count += 1
            except:
                pass
        
        return success_count == len(urls)
    
    def _is_image(self, path: str) -> bool:
        """Check if path is an image."""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}
        return any(path.lower().endswith(ext) for ext in image_extensions)
    
    def _get_image_params(self, kwargs: Dict) -> Dict[str, str]:
        """Get Cloudflare image optimization parameters."""
        params = {}
        
        if 'width' in kwargs:
            params['width'] = str(kwargs['width'])
        if 'height' in kwargs:
            params['height'] = str(kwargs['height'])
        if 'quality' in kwargs:
            params['quality'] = str(kwargs['quality'])
        if 'format' in kwargs:
            params['format'] = kwargs['format']
        
        return params
    
    def _calculate_hit_rate(self, analytics: Dict) -> float:
        """Calculate cache hit rate."""
        requests = analytics.get('requests', {})
        total = requests.get('all', 0)
        cached = requests.get('cached', 0)
        
        if total > 0:
            return (cached / total) * 100
        return 0.0


class CloudFrontCDN(CDNProvider):
    """AWS CloudFront CDN provider."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.distribution_id = config.get('distribution_id', '')
        self.aws_access_key = config.get('aws_access_key', '')
        self.aws_secret_key = config.get('aws_secret_key', '')
        self.region = config.get('region', 'us-east-1')
    
    def get_url(self, path: str, **kwargs) -> str:
        """Get CloudFront CDN URL."""
        if not self.is_enabled():
            return path
        
        # Add signed URL support for private content
        if kwargs.get('signed'):
            return self._create_signed_url(path, kwargs.get('expires_in', 3600))
        
        return self._build_cdn_url(path)
    
    def purge(self, paths: List[str]) -> bool:
        """Create CloudFront invalidation."""
        if not self.distribution_id:
            return False
        
        try:
            import boto3
            
            client = boto3.client(
                'cloudfront',
                aws_access_key_id=self.aws_access_key,
                aws_secret_access_key=self.aws_secret_key,
                region_name=self.region
            )
            
            # Create invalidation
            response = client.create_invalidation(
                DistributionId=self.distribution_id,
                InvalidationBatch={
                    'Paths': {
                        'Quantity': len(paths),
                        'Items': paths
                    },
                    'CallerReference': str(int(time.time()))
                }
            )
            
            return response['ResponseMetadata']['HTTPStatusCode'] == 201
            
        except Exception as e:
            logger.error(f"CloudFront invalidation failed: {e}")
            return False
    
    def purge_all(self) -> bool:
        """Purge all CloudFront content."""
        return self.purge(['/*'])
    
    def get_stats(self) -> Dict[str, Any]:
        """Get CloudFront distribution metrics."""
        try:
            import boto3
            
            cloudwatch = boto3.client(
                'cloudwatch',
                aws_access_key_id=self.aws_access_key,
                aws_secret_access_key=self.aws_secret_key,
                region_name=self.region
            )
            
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=24)
            
            # Get various metrics
            metrics = {}
            metric_names = ['Requests', 'BytesDownloaded', 'CacheHitRate', '4xxErrorRate', '5xxErrorRate']
            
            for metric_name in metric_names:
                response = cloudwatch.get_metric_statistics(
                    Namespace='AWS/CloudFront',
                    MetricName=metric_name,
                    Dimensions=[
                        {'Name': 'DistributionId', 'Value': self.distribution_id}
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,  # 24 hours
                    Statistics=['Sum', 'Average']
                )
                
                if response['Datapoints']:
                    point = response['Datapoints'][0]
                    if metric_name.endswith('Rate'):
                        metrics[metric_name.lower()] = point.get('Average', 0)
                    else:
                        metrics[metric_name.lower()] = point.get('Sum', 0)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get CloudFront stats: {e}")
            return {'error': str(e)}
    
    def preload(self, urls: List[str]) -> bool:
        """Preload content by making requests."""
        # CloudFront doesn't have a preload API
        # Warm cache by making requests
        success_count = 0
        
        for url in urls:
            try:
                response = requests.head(url, timeout=5)
                if response.status_code == 200:
                    success_count += 1
            except:
                pass
        
        return success_count == len(urls)
    
    def _create_signed_url(self, path: str, expires_in: int) -> str:
        """Create CloudFront signed URL."""
        # This would require CloudFront signing implementation
        # For now, return regular URL
        return self._build_cdn_url(path)


class FastlyCDN(CDNProvider):
    """Fastly CDN provider."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.service_id = config.get('service_id', '')
        self.api_key = config.get('api_key', '')
    
    def get_url(self, path: str, **kwargs) -> str:
        """Get Fastly CDN URL."""
        if not self.is_enabled():
            return path
        
        # Add Fastly image optimization
        if kwargs.get('optimize_images') and self._is_image(path):
            return self._build_image_url(path, kwargs)
        
        return self._build_cdn_url(path)
    
    def purge(self, paths: List[str]) -> bool:
        """Purge content from Fastly cache."""
        if not self.service_id or not self.api_key:
            return False
        
        success = True
        
        for path in paths:
            url = self._build_cdn_url(path)
            response = requests.post(
                f"https://api.fastly.com/purge/{url}",
                headers={'Fastly-Key': self.api_key}
            )
            
            if response.status_code != 200:
                logger.error(f"Fastly purge failed for {url}")
                success = False
        
        return success
    
    def purge_all(self) -> bool:
        """Purge all Fastly content."""
        if not self.service_id or not self.api_key:
            return False
        
        response = requests.post(
            f"https://api.fastly.com/service/{self.service_id}/purge_all",
            headers={'Fastly-Key': self.api_key}
        )
        
        return response.status_code == 200
    
    def get_stats(self) -> Dict[str, Any]:
        """Get Fastly real-time analytics."""
        if not self.service_id or not self.api_key:
            return {'error': 'Credentials not configured'}
        
        response = requests.get(
            f"https://api.fastly.com/stats/service/{self.service_id}",
            headers={'Fastly-Key': self.api_key},
            params={'from': '1 day ago', 'to': 'now', 'by': 'day'}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('data'):
                stats = data['data'][0]
                return {
                    'requests': stats.get('requests', 0),
                    'hits': stats.get('hits', 0),
                    'misses': stats.get('miss', 0),
                    'bandwidth': stats.get('bandwidth', 0),
                    'cache_hit_rate': self._calculate_hit_rate(stats),
                    'errors': stats.get('errors', 0)
                }
        
        return {'error': 'Failed to fetch stats'}
    
    def preload(self, urls: List[str]) -> bool:
        """Preload content into Fastly cache."""
        # Use Fastly's edge dictionaries or custom VCL
        # For now, warm cache by making requests
        success_count = 0
        
        for url in urls:
            try:
                response = requests.head(url, timeout=5)
                if response.status_code == 200:
                    success_count += 1
            except:
                pass
        
        return success_count == len(urls)
    
    def _is_image(self, path: str) -> bool:
        """Check if path is an image."""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        return any(path.lower().endswith(ext) for ext in image_extensions)
    
    def _build_image_url(self, path: str, kwargs: Dict) -> str:
        """Build Fastly image optimization URL."""
        base_url = self._build_cdn_url(path)
        
        # Fastly Image Optimizer parameters
        params = []
        
        if 'width' in kwargs:
            params.append(f"width={kwargs['width']}")
        if 'height' in kwargs:
            params.append(f"height={kwargs['height']}")
        if 'quality' in kwargs:
            params.append(f"quality={kwargs['quality']}")
        if 'format' in kwargs:
            params.append(f"format={kwargs['format']}")
        
        if params:
            return f"{base_url}?{{'&'.join(params)}}"
        
        return base_url
    
    def _calculate_hit_rate(self, stats: Dict) -> float:
        """Calculate cache hit rate."""
        hits = stats.get('hits', 0)
        misses = stats.get('miss', 0)
        total = hits + misses
        
        if total > 0:
            return (hits / total) * 100
        return 0.0


class MultiCDN(CDNProvider):
    """Multi-CDN provider for redundancy and performance."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.providers = []
        self.strategy = config.get('strategy', 'failover')  # failover, round-robin, geographic
        self.current_index = 0
        
        # Initialize configured providers
        for provider_config in config.get('providers', []):
            provider = self._create_provider(provider_config)
            if provider:
                self.providers.append(provider)
    
    def _create_provider(self, config: Dict[str, Any]) -> Optional[CDNProvider]:
        """Create CDN provider instance."""
        provider_type = config.get('type')
        
        if provider_type == 'cloudflare':
            return CloudflareCDN(config)
        elif provider_type == 'cloudfront':
            return CloudFrontCDN(config)
        elif provider_type == 'fastly':
            return FastlyCDN(config)
        
        return None
    
    def get_url(self, path: str, **kwargs) -> str:
        """Get CDN URL using configured strategy."""
        if not self.providers:
            return path
        
        if self.strategy == 'round-robin':
            provider = self._get_round_robin_provider()
        elif self.strategy == 'geographic':
            provider = self._get_geographic_provider(kwargs.get('region'))
        else:  # failover
            provider = self._get_active_provider()
        
        if provider:
            return provider.get_url(path, **kwargs)
        
        return path
    
    def purge(self, paths: List[str]) -> bool:
        """Purge from all CDN providers."""
        success = True
        
        for provider in self.providers:
            if provider.is_enabled():
                if not provider.purge(paths):
                    success = False
        
        return success
    
    def purge_all(self) -> bool:
        """Purge all content from all providers."""
        success = True
        
        for provider in self.providers:
            if provider.is_enabled():
                if not provider.purge_all():
                    success = False
        
        return success
    
    def get_stats(self) -> Dict[str, Any]:
        """Get aggregated stats from all providers."""
        stats = {
            'providers': {},
            'total_requests': 0,
            'total_bandwidth': 0,
            'average_hit_rate': 0
        }
        
        hit_rates = []
        
        for provider in self.providers:
            if provider.is_enabled():
                provider_stats = provider.get_stats()
                provider_name = provider.__class__.__name__
                stats['providers'][provider_name] = provider_stats
                
                if 'requests' in provider_stats:
                    stats['total_requests'] += provider_stats['requests']
                if 'bandwidth' in provider_stats:
                    stats['total_bandwidth'] += provider_stats['bandwidth']
                if 'cache_hit_rate' in provider_stats:
                    hit_rates.append(provider_stats['cache_hit_rate'])
        
        if hit_rates:
            stats['average_hit_rate'] = sum(hit_rates) / len(hit_rates)
        
        return stats
    
    def preload(self, urls: List[str]) -> bool:
        """Preload content to all providers."""
        success = True
        
        for provider in self.providers:
            if provider.is_enabled():
                if not provider.preload(urls):
                    success = False
        
        return success
    
    def _get_round_robin_provider(self) -> Optional[CDNProvider]:
        """Get next provider in round-robin."""
        if not self.providers:
            return None
        
        provider = self.providers[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.providers)
        
        return provider if provider.is_enabled() else self._get_active_provider()
    
    def _get_geographic_provider(self, region: Optional[str]) -> Optional[CDNProvider]:
        """Get provider based on geographic region."""
        # This would use geo-routing logic
        # For now, fallback to active provider
        return self._get_active_provider()
    
    def _get_active_provider(self) -> Optional[CDNProvider]:
        """Get first active provider (failover)."""
        for provider in self.providers:
            if provider.is_enabled():
                return provider
        
        return None