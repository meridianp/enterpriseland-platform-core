"""
Security-specific settings for the CASA platform.
"""
from decouple import config


def get_csp_settings(debug=False):
    """
    Get Content Security Policy settings based on environment.
    
    Args:
        debug: Whether in debug mode
        
    Returns:
        dict: CSP settings for django-csp
    """
    if debug:
        # Development CSP - more permissive
        return {
            'CONTENT_SECURITY_POLICY': {
                'DIRECTIVES': {
                    'default-src': ["'self'"],
                    'script-src': [
                        "'self'",
                        "'unsafe-inline'",  # For development tools
                        "'unsafe-eval'",    # For React DevTools
                        "http://localhost:*",
                        "http://127.0.0.1:*",
                        "https://cdn.jsdelivr.net",  # For any CDN scripts
                    ],
                    'style-src': [
                        "'self'",
                        "'unsafe-inline'",  # For styled-components, emotion, etc.
                        "https://fonts.googleapis.com",
                        "https://cdn.jsdelivr.net",
                    ],
                    'font-src': [
                        "'self'",
                        "https://fonts.gstatic.com",
                        "data:",  # For inline fonts
                    ],
                    'img-src': [
                        "'self'",
                        "data:",
                        "blob:",
                        "https:",  # Allow all HTTPS images in dev
                        "http://localhost:*",
                        "http://127.0.0.1:*",
                    ],
                    'connect-src': [
                        "'self'",
                        "http://localhost:*",
                        "http://127.0.0.1:*",
                        "ws://localhost:*",  # For hot reload
                        "wss://localhost:*",
                        "https://api.github.com",  # If using GitHub API
                    ],
                    'media-src': ["'self'", "blob:", "data:"],
                    'object-src': ["'none'"],
                    'frame-src': ["'self'"],
                    'worker-src': ["'self'", "blob:"],
                    'frame-ancestors': ["'self'"],
                    'form-action': ["'self'"],
                    'base-uri': ["'self'"],
                    'manifest-src': ["'self'"],
                }
            }
        }
    else:
        # Production CSP - strict
        aws_domain = config('AWS_S3_CUSTOM_DOMAIN', default='')
        directives = {
            'default-src': ["'self'"],
            'script-src': [
                "'self'",
                "'strict-dynamic'",  # For dynamically loaded scripts
                "'nonce-{nonce}'",   # Nonce-based CSP
                "https://cdn.jsdelivr.net",
                "https://www.google-analytics.com",  # If using GA
                "https://www.googletagmanager.com",  # If using GTM
            ],
            'style-src': [
                "'self'",
                "'nonce-{nonce}'",  # For inline styles with nonce
                "https://fonts.googleapis.com",
                "https://cdn.jsdelivr.net",
            ],
            'font-src': [
                "'self'",
                "https://fonts.gstatic.com",
            ],
            'img-src': [
                "'self'",
                "data:",
                "https:",  # All HTTPS images
            ],
            'connect-src': [
                "'self'",
                "https://api.casa-dd-platform.com",
                "https://api-staging.casa-dd-platform.com",
                "https://www.google-analytics.com",  # If using GA
            ],
            'media-src': ["'self'"],
            'object-src': ["'none'"],
            'frame-src': ["'none'"],
            'worker-src': ["'self'"],
            'frame-ancestors': ["'none'"],
            'form-action': ["'self'"],
            'base-uri': ["'self'"],
            'manifest-src': ["'self'"],
            'upgrade-insecure-requests': [],
            'block-all-mixed-content': [],
        }
        
        # Add AWS domain if configured
        if aws_domain:
            directives['img-src'].append(aws_domain)
            directives['connect-src'].append(aws_domain)
            directives['media-src'].append(aws_domain)
        
        return {
            'CONTENT_SECURITY_POLICY': {
                'DIRECTIVES': directives
            }
        }


def get_security_headers(debug=False):
    """
    Get additional security headers based on environment.
    
    Args:
        debug: Whether in debug mode
        
    Returns:
        dict: Security headers configuration
    """
    headers = {
        # X-Frame-Options - Prevent clickjacking
        'X_FRAME_OPTIONS': 'DENY',
        
        # X-Content-Type-Options - Prevent MIME sniffing
        'SECURE_CONTENT_TYPE_NOSNIFF': True,
        
        # X-XSS-Protection - Legacy XSS protection
        'SECURE_BROWSER_XSS_FILTER': True,
        
        # Referrer-Policy
        'SECURE_REFERRER_POLICY': 'strict-origin-when-cross-origin',
    }
    
    if not debug:
        # Production-only headers
        headers.update({
            # HSTS - Enforce HTTPS
            'SECURE_HSTS_SECONDS': 31536000,  # 1 year
            'SECURE_HSTS_INCLUDE_SUBDOMAINS': True,
            'SECURE_HSTS_PRELOAD': True,
            
            # Force HTTPS
            'SECURE_SSL_REDIRECT': True,
            'SECURE_PROXY_SSL_HEADER': ('HTTP_X_FORWARDED_PROTO', 'https'),
            
            # Secure cookies
            'SESSION_COOKIE_SECURE': True,
            'SESSION_COOKIE_HTTPONLY': True,
            'SESSION_COOKIE_SAMESITE': 'Strict',
            'CSRF_COOKIE_SECURE': True,
            'CSRF_COOKIE_HTTPONLY': False,  # Frontend needs to read this
            'CSRF_COOKIE_SAMESITE': 'Strict',
        })
    
    return headers


def get_secure_middleware_order():
    """
    Get the correct middleware order for security.
    
    Returns:
        list: Ordered middleware classes
    """
    return [
        # Django's security middleware should be first
        'django.middleware.security.SecurityMiddleware',
        
        # Whitenoise for static files (if used)
        'whitenoise.middleware.WhiteNoiseMiddleware',
        
        # Custom security headers
        'core.middleware.security.SecurityHeadersMiddleware',
        
        # CORS headers
        'corsheaders.middleware.CorsMiddleware',
        
        # Django session
        'django.contrib.sessions.middleware.SessionMiddleware',
        
        # CSP headers
        'csp.middleware.CSPMiddleware',
        
        # Request validation
        'core.middleware.security.RequestValidationMiddleware',
        
        # Common middleware
        'django.middleware.common.CommonMiddleware',
        
        # CSRF protection
        'django.middleware.csrf.CsrfViewMiddleware',
        
        # Content type validation (before auth to prevent attacks)
        'core.middleware.security.ContentTypeValidationMiddleware',
        
        # Authentication
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        
        # Token blacklist middleware (after auth)
        'accounts.middleware.TokenBlacklistMiddleware',
        
        # Audit logging (after auth to track user actions)
        'core.middleware.audit.AuditLoggingMiddleware',
        
        # API key usage tracking (after auth to know API key)
        'api_keys.middleware.APIKeyUsageMiddleware',
        
        # Rate limiting headers (after auth to know user)
        'core.middleware.rate_limiting.RateLimitHeadersMiddleware',
        'core.middleware.rate_limiting.RateLimitMonitoringMiddleware',
        
        # Messages
        'django.contrib.messages.middleware.MessageMiddleware',
        
        # Clickjacking protection
        'django.middleware.clickjacking.XFrameOptionsMiddleware',
        
        # Compression middleware (should be last to compress final response)
        'core.middleware.compression.ConditionalCompressionMiddleware',
        'core.middleware.compression.CompressionMiddleware',
    ]


# Security-related settings for file uploads
SECURE_FILE_UPLOAD_SETTINGS = {
    # Maximum upload size (10MB)
    'FILE_UPLOAD_MAX_MEMORY_SIZE': 10 * 1024 * 1024,
    
    # Allowed file extensions
    'ALLOWED_FILE_EXTENSIONS': [
        '.pdf', '.doc', '.docx', '.xls', '.xlsx',
        '.png', '.jpg', '.jpeg', '.gif',
        '.txt', '.csv', '.zip',
    ],
    
    # Allowed MIME types
    'ALLOWED_MIME_TYPES': [
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'image/png',
        'image/jpeg',
        'image/gif',
        'text/plain',
        'text/csv',
        'application/zip',
    ],
    
    # File upload permissions
    'FILE_UPLOAD_PERMISSIONS': 0o644,
    'FILE_UPLOAD_DIRECTORY_PERMISSIONS': 0o755,
}


# Rate limiting settings (for future implementation)
RATE_LIMIT_SETTINGS = {
    'DEFAULT_RATE': '100/hour',
    'AUTH_RATE': '20/hour',
    'API_RATE': '1000/hour',
    'UPLOAD_RATE': '50/day',
}