"""
CDN Integration

Content Delivery Network integration for static assets and dynamic content.
"""

from .providers import (
    CDNProvider,
    CloudflareCDN,
    CloudFrontCDN,
    FastlyCDN,
    MultiCDN
)
from .storage import (
    CDNStaticStorage,
    CDNMediaStorage,
    CDNManifestStorage
)
from .middleware import (
    CDNMiddleware,
    CDNHeadersMiddleware,
    CDNPurgeMiddleware
)
from .optimization import (
    AssetOptimizer,
    ImageOptimizer,
    CSSOptimizer,
    JSOptimizer
)
from .manager import CDNManager, cdn_manager
from .utils import (
    generate_cdn_url,
    get_cdn_provider,
    purge_cdn_cache,
    preload_assets
)

__all__ = [
    # Providers
    'CDNProvider',
    'CloudflareCDN',
    'CloudFrontCDN',
    'FastlyCDN',
    'MultiCDN',
    
    # Storage
    'CDNStaticStorage',
    'CDNMediaStorage',
    'CDNManifestStorage',
    
    # Middleware
    'CDNMiddleware',
    'CDNHeadersMiddleware',
    'CDNPurgeMiddleware',
    
    # Optimization
    'AssetOptimizer',
    'ImageOptimizer',
    'CSSOptimizer',
    'JSOptimizer',
    
    # Manager
    'CDNManager',
    'cdn_manager',
    
    # Utils
    'generate_cdn_url',
    'get_cdn_provider',
    'purge_cdn_cache',
    'preload_assets'
]