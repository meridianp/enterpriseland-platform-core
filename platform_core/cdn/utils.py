"""
CDN Utilities

Utility functions for CDN operations.
"""

import os
import hashlib
import mimetypes
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse
from django.conf import settings
from django.core.cache import cache
from django.utils.module_loading import import_string
import logging

logger = logging.getLogger(__name__)


def get_cdn_provider():
    """Get configured CDN provider instance."""
    provider_config = getattr(settings, 'CDN_PROVIDER_CONFIG', None)
    
    if not provider_config:
        return None
    
    try:
        provider_class = import_string(provider_config['class'])
        return provider_class(provider_config)
    except Exception as e:
        logger.error(f"Failed to initialize CDN provider: {e}")
        return None


def should_use_cdn(path: str) -> bool:
    """Check if CDN should be used for given path."""
    # Check if CDN is enabled
    if not getattr(settings, 'CDN_ENABLED', False):
        return False
    
    # Check file extension
    allowed_extensions = getattr(settings, 'CDN_ALLOWED_EXTENSIONS', [
        '.css', '.js', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
        '.woff', '.woff2', '.ttf', '.eot', '.ico', '.pdf'
    ])
    
    if not any(path.lower().endswith(ext) for ext in allowed_extensions):
        return False
    
    # Check path exclusions
    excluded_patterns = getattr(settings, 'CDN_EXCLUDE_PATTERNS', [])
    for pattern in excluded_patterns:
        if pattern in path:
            return False
    
    return True


def get_asset_version(path: str) -> Optional[str]:
    """Get version/hash for asset for cache busting."""
    # Check if versioning is enabled
    if not getattr(settings, 'CDN_VERSIONING_ENABLED', True):
        return None
    
    # Try to get from manifest
    manifest = _load_manifest()
    if manifest and path in manifest:
        return manifest[path].get('hash', '')[:8]
    
    # Try to get from file modification time
    try:
        file_path = os.path.join(settings.STATIC_ROOT, path)
        if os.path.exists(file_path):
            mtime = os.path.getmtime(file_path)
            return str(int(mtime))
    except:
        pass
    
    # Generate from path
    return hashlib.md5(path.encode()).hexdigest()[:8]


def calculate_cache_key(prefix: str, *args) -> str:
    """Calculate cache key for CDN operations."""
    parts = [prefix]
    
    for arg in args:
        if isinstance(arg, (list, dict)):
            parts.append(hashlib.md5(str(arg).encode()).hexdigest())
        else:
            parts.append(str(arg))
    
    return ':'.join(parts)


def generate_cdn_url(path: str, **kwargs) -> str:
    """Generate CDN URL for given path."""
    from .manager import cdn_manager
    
    return cdn_manager.get_url(path, **kwargs)


def get_cdn_url(path: str, **kwargs) -> str:
    """Alias for generate_cdn_url."""
    return generate_cdn_url(path, **kwargs)


def purge_cdn_cache(paths: List[str]) -> bool:
    """Purge CDN cache for given paths."""
    from .manager import cdn_manager
    
    return cdn_manager.purge(paths)


def preload_assets(urls: List[str]) -> bool:
    """Preload assets into CDN cache."""
    from .manager import cdn_manager
    
    return cdn_manager.preload(urls)


def get_content_type(path: str) -> str:
    """Get content type for file path."""
    content_type, _ = mimetypes.guess_type(path)
    return content_type or 'application/octet-stream'


def is_cacheable(path: str, response_headers: Optional[Dict] = None) -> bool:
    """Check if resource is cacheable."""
    # Check file type
    content_type = get_content_type(path)
    
    non_cacheable_types = getattr(settings, 'CDN_NON_CACHEABLE_TYPES', [
        'text/html',
        'application/json',
        'application/xml'
    ])
    
    if content_type in non_cacheable_types:
        return False
    
    # Check response headers
    if response_headers:
        # Check cache-control
        cache_control = response_headers.get('Cache-Control', '')
        if 'no-cache' in cache_control or 'no-store' in cache_control:
            return False
        
        # Check pragma
        if response_headers.get('Pragma') == 'no-cache':
            return False
    
    return True


def get_cache_headers(path: str, content_type: Optional[str] = None) -> Dict[str, str]:
    """Get appropriate cache headers for path."""
    if not content_type:
        content_type = get_content_type(path)
    
    headers = {}
    
    # Get cache age based on content type
    cache_ages = getattr(settings, 'CDN_CACHE_AGES', {
        'text/css': 31536000,  # 1 year
        'application/javascript': 31536000,  # 1 year
        'image/': 2592000,  # 30 days
        'font/': 31536000,  # 1 year
        'application/pdf': 86400,  # 1 day
    })
    
    max_age = 3600  # Default 1 hour
    
    for type_prefix, age in cache_ages.items():
        if content_type.startswith(type_prefix):
            max_age = age
            break
    
    # Set cache control
    headers['Cache-Control'] = f'public, max-age={max_age}'
    
    # Add immutable for versioned assets
    if get_asset_version(path):
        headers['Cache-Control'] += ', immutable'
    
    # Add vary header
    headers['Vary'] = 'Accept-Encoding'
    
    return headers


def normalize_path(path: str) -> str:
    """Normalize path for CDN operations."""
    # Remove leading slash
    if path.startswith('/'):
        path = path[1:]
    
    # Remove query string
    if '?' in path:
        path = path.split('?')[0]
    
    # Remove fragment
    if '#' in path:
        path = path.split('#')[0]
    
    return path


def get_cdn_domain(url: str) -> Optional[str]:
    """Extract CDN domain from URL."""
    parsed = urlparse(url)
    
    if parsed.netloc:
        cdn_domains = getattr(settings, 'CDN_DOMAINS', [])
        
        if parsed.netloc in cdn_domains:
            return parsed.netloc
    
    return None


def is_cdn_url(url: str) -> bool:
    """Check if URL is from CDN."""
    return get_cdn_domain(url) is not None


def rewrite_url_to_cdn(url: str) -> str:
    """Rewrite URL to use CDN."""
    # Check if already CDN URL
    if is_cdn_url(url):
        return url
    
    # Parse URL
    parsed = urlparse(url)
    
    # Check if it's a local static/media URL
    static_url = getattr(settings, 'STATIC_URL', '/static/')
    media_url = getattr(settings, 'MEDIA_URL', '/media/')
    
    if parsed.path.startswith(static_url) or parsed.path.startswith(media_url):
        # Get path relative to static/media
        if parsed.path.startswith(static_url):
            path = parsed.path[len(static_url):]
        else:
            path = parsed.path[len(media_url):]
        
        # Generate CDN URL
        return generate_cdn_url(path)
    
    return url


def batch_rewrite_urls(content: str, base_url: Optional[str] = None) -> str:
    """Rewrite all URLs in content to use CDN."""
    import re
    
    # Pattern to match URLs
    url_pattern = re.compile(
        r'(src|href)=["\']([^"\']+)["\']',
        re.IGNORECASE
    )
    
    def replace_url(match):
        attr = match.group(1)
        url = match.group(2)
        
        # Make absolute if relative
        if base_url and not url.startswith(('http://', 'https://', '//')):
            url = urljoin(base_url, url)
        
        # Rewrite to CDN
        cdn_url = rewrite_url_to_cdn(url)
        
        return f'{attr}="{cdn_url}"'
    
    return url_pattern.sub(replace_url, content)


def _load_manifest() -> Optional[Dict]:
    """Load asset manifest."""
    manifest_key = 'cdn_asset_manifest'
    manifest = cache.get(manifest_key)
    
    if manifest:
        return manifest
    
    # Try to load from file
    manifest_path = os.path.join(settings.STATIC_ROOT, 'staticfiles.json')
    
    if os.path.exists(manifest_path):
        try:
            import json
            with open(manifest_path, 'r') as f:
                data = json.load(f)
                
            manifest = data.get('paths', data.get('files', {}))
            cache.set(manifest_key, manifest, 3600)  # Cache for 1 hour
            
            return manifest
        except:
            pass
    
    return None


def get_optimal_image_format(user_agent: str, original_format: str) -> str:
    """Determine optimal image format based on browser support."""
    # Check WebP support
    webp_browsers = ['Chrome/', 'Edge/', 'Firefox/', 'Opera/']
    
    if any(browser in user_agent for browser in webp_browsers):
        if original_format in ['jpg', 'jpeg', 'png']:
            return 'webp'
    
    # Check AVIF support (newer browsers)
    avif_browsers = ['Chrome/9', 'Chrome/10', 'Firefox/9', 'Firefox/10']
    
    if any(browser in user_agent for browser in avif_browsers):
        if original_format in ['jpg', 'jpeg', 'png']:
            return 'avif'
    
    return original_format


def estimate_bandwidth_savings(original_size: int, optimized_size: int) -> Dict[str, Any]:
    """Calculate bandwidth savings from optimization."""
    if original_size == 0:
        return {
            'savings_bytes': 0,
            'savings_percent': 0,
            'monthly_savings_gb': 0
        }
    
    savings_bytes = original_size - optimized_size
    savings_percent = (savings_bytes / original_size) * 100
    
    # Estimate monthly savings (assuming 1000 requests/day)
    requests_per_month = 30000
    monthly_savings_bytes = savings_bytes * requests_per_month
    monthly_savings_gb = monthly_savings_bytes / (1024 ** 3)
    
    return {
        'savings_bytes': savings_bytes,
        'savings_percent': round(savings_percent, 2),
        'monthly_savings_gb': round(monthly_savings_gb, 2)
    }