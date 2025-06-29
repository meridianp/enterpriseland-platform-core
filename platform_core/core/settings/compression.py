"""
Compression settings for Django application.

This module defines compression configurations for different environments
and content types, with security considerations.
"""
from decouple import config


def get_compression_settings(debug=False, environment='development'):
    """
    Get compression settings based on environment.
    
    Args:
        debug: Whether in debug mode
        environment: Environment name (development, staging, production)
        
    Returns:
        dict: Compression settings
    """
    
    # Base compression settings
    base_settings = {
        'ENABLED': config('COMPRESSION_ENABLED', default=True, cast=bool),
        'MIN_SIZE': config('COMPRESSION_MIN_SIZE', default=200, cast=int),  # Don't compress < 200 bytes
        'MAX_SIZE': config('COMPRESSION_MAX_SIZE', default=10 * 1024 * 1024, cast=int),  # 10MB limit
        'COMPRESSION_LEVEL': config('COMPRESSION_LEVEL', default=6, cast=int),  # 1-9 for gzip
        'BROTLI_ENABLED': config('COMPRESSION_BROTLI_ENABLED', default=True, cast=bool),
        
        # Content types that should be compressed
        'COMPRESSIBLE_TYPES': [
            # Text formats
            'text/html',
            'text/css',
            'text/javascript',
            'text/plain',
            'text/xml',
            'text/csv',
            
            # Application formats
            'application/json',
            'application/javascript',
            'application/xml',
            'application/xhtml+xml',
            'application/rss+xml',
            'application/atom+xml',
            'application/ld+json',
            
            # API responses
            'application/vnd.api+json',  # JSON API
            'application/hal+json',     # HAL JSON
            
            # Images (vector only)
            'image/svg+xml',
        ],
        
        # Paths to exclude from compression (security-sensitive)
        'EXCLUDE_PATHS': [
            # Authentication endpoints
            r'^/api/auth/login/$',
            r'^/api/auth/register/$',
            r'^/api/auth/password/',
            r'^/api/auth/token/',
            
            # User-sensitive endpoints
            r'^/api/users/.*/password/',
            r'^/api/users/.*/profile/',
            
            # Admin endpoints
            r'^/admin/login/',
            r'^/admin/password_change/',
            
            # File upload endpoints (already handling compression)
            r'^/api/files/upload/',
            r'^/api/files/.*/download/',
            
            # Health checks and monitoring (no need to compress)
            r'^/api/health/',
            r'^/api/metrics/',
            
            # API documentation (often cached separately)
            r'^/api/docs/',
            r'^/api/schema/',
        ],
        
        # HTTP methods to compress
        'COMPRESSIBLE_METHODS': ['GET', 'POST', 'PUT', 'PATCH'],
        
        # Response headers that indicate pre-compressed content
        'SKIP_HEADERS': {
            'Content-Encoding': ['gzip', 'br', 'compress', 'deflate'],
            'Cache-Control': ['no-store'],  # Don't compress no-store responses
        },
    }
    
    # Environment-specific overrides
    if environment == 'development' or debug:
        # Development: Lower compression for faster response times
        base_settings.update({
            'COMPRESSION_LEVEL': 3,  # Faster compression
            'MIN_SIZE': 500,  # Compress fewer small responses
            'BROTLI_ENABLED': False,  # Disable brotli in development for simplicity
        })
    
    elif environment == 'production':
        # Production: Optimize for bandwidth
        base_settings.update({
            'COMPRESSION_LEVEL': 6,  # Balanced compression
            'MIN_SIZE': 150,  # Compress more content
            'BROTLI_ENABLED': True,  # Enable brotli for better compression
        })
    
    elif environment == 'staging':
        # Staging: Similar to production but with some debug features
        base_settings.update({
            'COMPRESSION_LEVEL': 5,
            'MIN_SIZE': 200,
            'BROTLI_ENABLED': True,
        })
    
    return base_settings


def get_streaming_compression_settings(debug=False, environment='development'):
    """
    Get streaming compression settings for large responses.
    
    Args:
        debug: Whether in debug mode
        environment: Environment name
        
    Returns:
        dict: Streaming compression settings
    """
    
    base_settings = {
        'ENABLED': config('STREAMING_COMPRESSION_ENABLED', default=False, cast=bool),
        'CHUNK_SIZE': config('STREAMING_COMPRESSION_CHUNK_SIZE', default=8192, cast=int),
        'BUFFER_SIZE': config('STREAMING_COMPRESSION_BUFFER_SIZE', default=64 * 1024, cast=int),
        
        # Minimum response size to enable streaming compression
        'MIN_RESPONSE_SIZE': config('STREAMING_COMPRESSION_MIN_SIZE', default=1024 * 1024, cast=int),  # 1MB
        
        # Content types suitable for streaming compression
        'STREAMING_TYPES': [
            'application/json',  # Large JSON responses
            'text/csv',          # CSV exports
            'application/xml',   # XML data
            'text/plain',        # Large text files
        ],
    }
    
    # Enable streaming compression in production for large responses
    if environment == 'production':
        base_settings['ENABLED'] = True
    
    return base_settings


def get_conditional_compression_settings(debug=False, environment='development'):
    """
    Get conditional compression settings for intelligent compression decisions.
    
    Args:
        debug: Whether in debug mode
        environment: Environment name
        
    Returns:
        dict: Conditional compression settings
    """
    
    base_settings = {
        'ENABLED': config('CONDITIONAL_COMPRESSION_ENABLED', default=True, cast=bool),
        
        # System load thresholds
        'CPU_THRESHOLD': config('COMPRESSION_CPU_THRESHOLD', default=80, cast=int),
        'MEMORY_THRESHOLD': config('COMPRESSION_MEMORY_THRESHOLD', default=85, cast=int),
        
        # Client-specific compression settings
        'QUALITY_SETTINGS': {
            'mobile': {
                'level': 4,      # Faster compression for mobile devices
                'enabled': True,
                'min_size': 300,  # Smaller threshold for mobile
            },
            'desktop': {
                'level': 6,      # Standard compression for desktop
                'enabled': True,
                'min_size': 200,
            },
            'bot': {
                'level': 9,      # Maximum compression for bots (they don't care about speed)
                'enabled': config('COMPRESSION_ENABLE_FOR_BOTS', default=False, cast=bool),
                'min_size': 100,
            },
            'api': {
                'level': 7,      # High compression for API clients
                'enabled': True,
                'min_size': 150,
            },
        },
        
        # User-Agent patterns for client detection
        'CLIENT_PATTERNS': {
            'mobile': [
                'mobile', 'android', 'iphone', 'ipad', 'ipod',
                'blackberry', 'windows phone', 'palm', 'symbian'
            ],
            'bot': [
                'bot', 'crawler', 'spider', 'scraper', 'checker',
                'googlebot', 'bingbot', 'facebookexternalhit'
            ],
            'api': [
                'curl', 'wget', 'httpie', 'postman', 'insomnia',
                'python-requests', 'go-http-client', 'java/',
                'okhttp', 'axios'
            ],
        },
    }
    
    # Disable conditional compression in development for simplicity
    if debug or environment == 'development':
        base_settings['ENABLED'] = False
    
    return base_settings


# Security settings for compression
COMPRESSION_SECURITY_SETTINGS = {
    # Content that should never be compressed (security reasons)
    'NEVER_COMPRESS_PATHS': [
        r'^/api/auth/.*',           # Authentication endpoints
        r'^/api/users/.*/secrets/', # User secrets
        r'^/api/keys/.*',          # API keys
        r'^/api/tokens/.*',        # Access tokens
        r'^/api/certificates/.*',   # Certificates
    ],
    
    # Headers that indicate sensitive content
    'SENSITIVE_HEADERS': {
        'Authorization': True,      # Skip responses with auth data
        'Set-Cookie': True,        # Skip responses setting cookies
        'X-CSRFToken': True,       # Skip CSRF token responses
    },
    
    # Content types that might contain sensitive data
    'SENSITIVE_CONTENT_TYPES': [
        'application/x-www-form-urlencoded',  # Form data
        'multipart/form-data',               # File uploads
    ],
    
    # Compression timing attack prevention
    'TIMING_ATTACK_PREVENTION': {
        'ENABLED': config('COMPRESSION_TIMING_ATTACK_PREVENTION', default=True, cast=bool),
        'RANDOM_DELAY_MS': config('COMPRESSION_RANDOM_DELAY_MS', default=5, cast=int),
        'PADDING_ENABLED': config('COMPRESSION_PADDING_ENABLED', default=True, cast=bool),
    },
}


def get_compression_monitoring_settings():
    """
    Get compression monitoring and metrics settings.
    
    Returns:
        dict: Monitoring settings
    """
    
    return {
        'ENABLED': config('COMPRESSION_MONITORING_ENABLED', default=True, cast=bool),
        
        # Metrics to track
        'TRACK_METRICS': {
            'compression_ratio': True,      # Original size / compressed size
            'compression_time': True,       # Time taken to compress
            'bytes_saved': True,           # Bytes saved by compression
            'hit_rate': True,              # % of responses compressed
            'error_rate': True,            # % of compression failures
        },
        
        # Alert thresholds
        'ALERT_THRESHOLDS': {
            'low_compression_ratio': 1.2,  # Alert if compression ratio < 1.2
            'high_compression_time': 100,  # Alert if compression takes > 100ms
            'high_error_rate': 5,          # Alert if error rate > 5%
        },
        
        # Log compression events
        'LOG_COMPRESSION_EVENTS': config('LOG_COMPRESSION_EVENTS', default=False, cast=bool),
        'LOG_COMPRESSION_STATS': config('LOG_COMPRESSION_STATS', default=True, cast=bool),
    }