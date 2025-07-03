# CDN Integration

## Overview

The EnterpriseLand platform includes comprehensive CDN (Content Delivery Network) integration to improve performance, reduce server load, and provide global content delivery. The CDN system supports multiple providers, intelligent asset optimization, and advanced caching strategies.

## Features

### Multi-Provider Support
- **Cloudflare** - Global CDN with image optimization
- **AWS CloudFront** - Amazon's CDN with S3 integration
- **Fastly** - Real-time CDN with instant purging
- **Multi-CDN** - Failover and load balancing across providers

### Asset Optimization
- **CSS Minification** - Removes whitespace and comments
- **JavaScript Minification** - Reduces file size while preserving functionality
- **Image Optimization** - Automatic compression and format conversion
- **Responsive Images** - Multiple sizes for different devices
- **SVG Optimization** - Cleans and compresses vector graphics

### Intelligent Caching
- **Automatic Cache Headers** - Content-type based cache control
- **Version-Based Cache Busting** - Ensures updates are delivered
- **Tag-Based Invalidation** - Purge related content together
- **Pattern-Based Purging** - Wildcard cache clearing

### Django Integration
- **Storage Backends** - Drop-in replacements for static/media storage
- **Middleware** - Automatic URL rewriting and header management
- **Template Tags** - Easy CDN URL generation in templates
- **Management Commands** - CLI tools for CDN operations

## Configuration

### Basic Setup

```python
# settings.py

# Enable CDN
CDN_ENABLED = True

# Configure provider
CDN_PROVIDER_CONFIG = {
    'class': 'platform_core.cdn.providers.CloudflareCDN',
    'base_url': 'https://cdn.example.com/',
    'api_key': os.environ.get('CLOUDFLARE_API_KEY'),
    'zone_id': os.environ.get('CLOUDFLARE_ZONE_ID'),
    'account_id': os.environ.get('CLOUDFLARE_ACCOUNT_ID'),
    'enabled': True
}

# Use CDN storage backends
STATICFILES_STORAGE = 'platform_core.cdn.storage.CDNStaticStorage'
DEFAULT_FILE_STORAGE = 'platform_core.cdn.storage.CDNMediaStorage'

# Add CDN middleware
MIDDLEWARE = [
    # ... other middleware ...
    'platform_core.cdn.middleware.CDNMiddleware',
    'platform_core.cdn.middleware.CDNHeadersMiddleware',
    'platform_core.cdn.middleware.CDNPurgeMiddleware',
]

# Configure cache ages by content type
CDN_CACHE_AGES = {
    'text/css': 31536000,           # 1 year
    'application/javascript': 31536000,  # 1 year
    'image/': 2592000,              # 30 days
    'font/': 31536000,              # 1 year
    'application/pdf': 86400,        # 1 day
}

# Asset optimization
CDN_OPTIMIZER_CONFIG = {
    'enabled': True,
    'inline_small_images': True,
    'max_inline_size': 4096,  # 4KB
}

# Exclude patterns from CDN
CDN_EXCLUDE_PATTERNS = [
    '/admin/',
    '/api/',
    '/__debug__/'
]
```

### Multi-CDN Configuration

```python
# Use multiple CDN providers for redundancy
CDN_PROVIDER_CONFIG = {
    'class': 'platform_core.cdn.providers.MultiCDN',
    'strategy': 'failover',  # Options: failover, round-robin, geographic
    'providers': [
        {
            'type': 'cloudflare',
            'weight': 1,
            'base_url': 'https://cdn1.example.com/',
            'api_key': os.environ.get('CLOUDFLARE_API_KEY'),
            'zone_id': os.environ.get('CLOUDFLARE_ZONE_ID'),
            'enabled': True
        },
        {
            'type': 'cloudfront',
            'weight': 1,
            'base_url': 'https://d1234567890.cloudfront.net/',
            'distribution_id': os.environ.get('CLOUDFRONT_DISTRIBUTION_ID'),
            'aws_access_key': os.environ.get('AWS_ACCESS_KEY_ID'),
            'aws_secret_key': os.environ.get('AWS_SECRET_ACCESS_KEY'),
            'enabled': True
        }
    ]
}
```

## Usage

### In Templates

```django
{% load cdn_tags %}

<!-- Basic CDN URL -->
<img src="{% cdn_url 'images/logo.png' %}" alt="Logo">

<!-- With image optimization -->
<img src="{% cdn_url 'images/hero.jpg' width=800 quality=85 %}" alt="Hero">

<!-- Responsive images -->
<picture>
  <source srcset="{% cdn_url 'images/hero.jpg' format='webp' %}" type="image/webp">
  <source srcset="{% cdn_url 'images/hero.jpg' format='avif' %}" type="image/avif">
  <img src="{% cdn_url 'images/hero.jpg' %}" alt="Hero">
</picture>
```

### In Python Code

```python
from platform_core.cdn import cdn_manager, get_cdn_url

# Get CDN URL
cdn_url = get_cdn_url('static/css/style.css')

# With versioning
cdn_url = cdn_manager.get_url('static/js/app.js', versioned=True)

# Purge cache
cdn_manager.purge(['static/css/style.css', 'static/js/app.js'])

# Purge by pattern
cdn_manager.purge_pattern('^static/css/.*')

# Purge by tag
cdn_manager.tag_path('static/css/style.css', ['css', 'styles'])
cdn_manager.purge_tag('css')

# Preload assets
cdn_manager.preload([
    'static/css/critical.css',
    'static/js/app.js',
    'static/fonts/main.woff2'
])

# Check CDN health
health = cdn_manager.health_check()
```

### Storage Backend Usage

```python
from platform_core.cdn.storage import CDNStaticStorage

# Use CDN storage directly
storage = CDNStaticStorage()

# Save file with optimization
from django.core.files.base import ContentFile
content = ContentFile(b'body { color: red; }')
path = storage.save('css/custom.css', content)

# Get CDN URL
url = storage.url('css/custom.css')
```

### Management Commands

```bash
# Check CDN status
python manage.py cdn_status

# Purge CDN cache
python manage.py cdn_purge --all
python manage.py cdn_purge --paths static/css/style.css static/js/app.js
python manage.py cdn_purge --pattern "^static/css/.*"
python manage.py cdn_purge --tag css

# Preload assets
python manage.py cdn_preload --manifest staticfiles.json
python manage.py cdn_preload --paths static/css/critical.css

# Optimize assets
python manage.py cdn_optimize --directory static/
python manage.py cdn_optimize --file static/images/hero.jpg

# CDN analytics
python manage.py cdn_stats
python manage.py cdn_stats --export stats.json
```

## Asset Optimization

### Image Optimization

The CDN system automatically optimizes images:

```python
# Configure image optimization
CDN_IMAGE_CONFIG = {
    'formats': ['webp', 'original'],  # Generate WebP versions
    'sizes': [
        (320, 'small'),
        (768, 'medium'),
        (1200, 'large'),
        (2400, 'xlarge')
    ],
    'quality': 85,
    'progressive': True
}
```

### CSS Optimization

CSS files are automatically:
- Minified (whitespace removed)
- Comments stripped
- Colors optimized (#ffffff → #fff)
- Units optimized (0px → 0)
- Small images inlined as data URIs

### JavaScript Optimization

JavaScript files are:
- Minified with rjsmin
- Comments removed (except licenses)
- Whitespace optimized
- Dead code eliminated

## Advanced Features

### Conditional CDN Usage

```python
from platform_core.cdn import without_cdn, with_cdn

@without_cdn
def serve_dynamic_content(request):
    """This view's assets won't use CDN."""
    return render(request, 'dynamic.html')

@with_cdn
def serve_static_content(request):
    """Ensures CDN is used for this view."""
    return render(request, 'static.html')
```

### Custom Asset Processing

```python
from platform_core.cdn.optimization import AssetOptimizer

class CustomOptimizer(AssetOptimizer):
    def _optimize_css(self, content):
        # Custom CSS optimization
        optimized = super()._optimize_css(content)
        # Add custom processing
        return self._add_prefixes(optimized)
```

### CDN Warming

```python
# Warm cache after deployment
from platform_core.cdn import cdn_manager

# Warm critical assets
critical_assets = [
    'static/css/critical.css',
    'static/js/app.js',
    'static/fonts/main.woff2'
]

cdn_manager.preload(critical_assets)

# Warm based on usage patterns
popular_assets = get_popular_assets()  # Your logic
cdn_manager.preload(popular_assets)
```

### Performance Monitoring

```python
# Get CDN performance metrics
stats = cdn_manager.get_stats()

# Example output:
{
    'provider': {
        'requests': 1000000,
        'bandwidth': 1234567890,  # bytes
        'cache_hit_rate': 92.5,   # percentage
        'errors': 42
    },
    'usage': {
        'url_generation_today': 5000,
        'purge_today': 10,
        'preload_today': 50
    }
}
```

## Best Practices

### 1. Cache Control
- Use long cache times for versioned assets (CSS, JS)
- Shorter cache times for frequently updated content
- Always version static assets for cache busting

### 2. Image Optimization
- Serve WebP format when supported
- Provide multiple sizes for responsive design
- Use lazy loading with CDN URLs

### 3. Purging Strategy
- Use tag-based purging for related content
- Schedule purges during low-traffic periods
- Monitor purge frequency to avoid abuse

### 4. Security
- Use signed URLs for private content
- Implement rate limiting on purge operations
- Monitor for unusual CDN usage patterns

### 5. Performance
- Preload critical assets during deployment
- Use CDN health checks before major operations
- Monitor cache hit rates (target >90%)

## Troubleshooting

### CDN URLs Not Generated

1. Check `CDN_ENABLED = True` in settings
2. Verify provider configuration
3. Check middleware is installed
4. Review logs for initialization errors

### Low Cache Hit Rate

1. Review cache headers configuration
2. Check for unnecessary cache purging
3. Verify asset versioning is working
4. Consider longer cache times

### Optimization Not Working

1. Ensure optimization libraries are installed:
   ```bash
   pip install csscompressor rjsmin Pillow
   ```
2. Check `CDN_OPTIMIZER_CONFIG['enabled'] = True`
3. Review optimization logs for errors

### Provider Connection Issues

1. Verify API credentials
2. Check network connectivity
3. Test provider API directly
4. Review rate limits

## Performance Benchmarks

Expected improvements with CDN integration:

| Metric | Without CDN | With CDN | Improvement |
|--------|-------------|----------|-------------|
| Static Asset Load Time | 200-500ms | 20-50ms | 90% |
| Page Load Time | 2-3s | 0.8-1.2s | 60% |
| Server Bandwidth | 100GB/day | 10GB/day | 90% |
| Cache Hit Rate | N/A | 85-95% | - |

## Security Considerations

### API Key Management
- Store CDN API keys in environment variables
- Rotate keys regularly
- Use separate keys for staging/production

### Content Security
- Implement CORS headers appropriately
- Use signed URLs for sensitive content
- Monitor for hotlinking abuse

### Cache Poisoning Prevention
- Validate cache keys
- Implement proper URL normalization
- Monitor for suspicious purge patterns

---

*The CDN integration provides enterprise-grade content delivery with multiple provider support, intelligent optimization, and comprehensive management tools, ensuring fast and reliable asset delivery for the EnterpriseLand platform.*