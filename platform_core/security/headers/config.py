"""
Security Headers Configuration

Provides default configurations and helpers for security headers.
"""

from typing import Dict, List, Optional


class SecurityHeadersConfig:
    """
    Configuration builder for security headers.
    
    Provides sensible defaults and easy customization.
    """
    
    @staticmethod
    def development() -> Dict:
        """Development configuration - more permissive"""
        return {
            'ENABLED': True,
            'REPORT_ONLY': True,  # Don't block in development
            'CSP': {
                'ENABLED': True,
                'REPORT_ONLY': True,
                'USE_NONCE': True,
                'DIRECTIVES': {
                    'default-src': ["'self'"],
                    'script-src': ["'self'", "'unsafe-inline'", "'unsafe-eval'", 'http://localhost:*'],
                    'style-src': ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com'],
                    'img-src': ["'self'", 'data:', 'https:', 'http://localhost:*'],
                    'font-src': ["'self'", 'https://fonts.gstatic.com'],
                    'connect-src': ["'self'", 'http://localhost:*', 'ws://localhost:*'],
                    'frame-src': ["'self'"],
                    'object-src': ["'none'"],
                    'base-uri': ["'self'"],
                    'form-action': ["'self'"],
                },
                'REPORT_URI': '/api/security/reports/csp/',
            },
            'HSTS': {
                'ENABLED': False,  # Don't use HSTS in development
            },
            'X_FRAME_OPTIONS': 'SAMEORIGIN',  # Allow same-origin framing
            'X_CONTENT_TYPE_OPTIONS': True,
            'X_XSS_PROTECTION': '1; mode=block',
            'REFERRER_POLICY': 'strict-origin-when-cross-origin',
            'PERMISSIONS_POLICY': {
                'camera': 'self',
                'microphone': 'self',
                'geolocation': 'self',
                'payment': 'none',
            },
        }
    
    @staticmethod
    def production() -> Dict:
        """Production configuration - strict security"""
        return {
            'ENABLED': True,
            'REPORT_ONLY': False,
            'CSP': {
                'ENABLED': True,
                'REPORT_ONLY': False,
                'USE_NONCE': True,
                'DIRECTIVES': {
                    'default-src': ["'none'"],
                    'script-src': ["'self'"],
                    'style-src': ["'self'"],
                    'img-src': ["'self'", 'data:', 'https:'],
                    'font-src': ["'self'"],
                    'connect-src': ["'self'"],
                    'media-src': ["'self'"],
                    'object-src': ["'none'"],
                    'frame-ancestors': ["'none'"],
                    'base-uri': ["'self'"],
                    'form-action': ["'self'"],
                    'upgrade-insecure-requests': [],
                },
                'REPORT_URI': '/api/security/reports/csp/',
                'REPORT_TO': 'csp-endpoint',
            },
            'HSTS': {
                'ENABLED': True,
                'MAX_AGE': 63072000,  # 2 years
                'INCLUDE_SUBDOMAINS': True,
                'PRELOAD': True,
            },
            'X_FRAME_OPTIONS': 'DENY',
            'X_CONTENT_TYPE_OPTIONS': True,
            'X_XSS_PROTECTION': '1; mode=block',
            'REFERRER_POLICY': 'strict-origin-when-cross-origin',
            'PERMISSIONS_POLICY': {
                'camera': 'none',
                'microphone': 'none',
                'geolocation': 'none',
                'payment': 'none',
                'usb': 'none',
                'magnetometer': 'none',
                'accelerometer': 'none',
                'gyroscope': 'none',
                'fullscreen': 'self',
            },
            'CUSTOM_HEADERS': {
                'X-Permitted-Cross-Domain-Policies': 'none',
                'Expect-CT': 'max-age=86400, enforce, report-uri="/api/security/reports/expect-ct/"',
            },
        }
    
    @staticmethod
    def api_only() -> Dict:
        """Configuration for API-only services"""
        return {
            'ENABLED': True,
            'CSP': {
                'ENABLED': False,  # CSP not needed for APIs
            },
            'HSTS': {
                'ENABLED': True,
                'MAX_AGE': 31536000,
                'INCLUDE_SUBDOMAINS': True,
            },
            'X_FRAME_OPTIONS': 'DENY',
            'X_CONTENT_TYPE_OPTIONS': True,
            'X_XSS_PROTECTION': '0',  # Disable for APIs
            'REFERRER_POLICY': 'no-referrer',
            'CORS': {
                'ENABLED': True,
                'ALLOWED_ORIGINS': [],  # Configure based on clients
                'ALLOW_CREDENTIALS': True,
                'ALLOWED_METHODS': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
                'ALLOWED_HEADERS': ['Content-Type', 'Authorization', 'X-Requested-With'],
                'EXPOSED_HEADERS': ['X-Total-Count', 'Link'],
                'MAX_AGE': 86400,
            },
        }
    
    @staticmethod
    def with_cdn(base_config: Dict, cdn_domains: List[str]) -> Dict:
        """Add CDN domains to existing configuration"""
        config = base_config.copy()
        
        # Add CDN domains to relevant CSP directives
        if 'CSP' in config and 'DIRECTIVES' in config['CSP']:
            directives = config['CSP']['DIRECTIVES']
            
            for cdn in cdn_domains:
                # Add to script-src
                if 'script-src' in directives:
                    directives['script-src'].append(cdn)
                
                # Add to style-src
                if 'style-src' in directives:
                    directives['style-src'].append(cdn)
                
                # Add to img-src
                if 'img-src' in directives:
                    directives['img-src'].append(cdn)
                
                # Add to font-src
                if 'font-src' in directives:
                    directives['font-src'].append(cdn)
        
        return config
    
    @staticmethod
    def with_analytics(base_config: Dict, analytics_domains: List[str]) -> Dict:
        """Add analytics domains to configuration"""
        config = base_config.copy()
        
        if 'CSP' in config and 'DIRECTIVES' in config['CSP']:
            directives = config['CSP']['DIRECTIVES']
            
            # Common analytics domains
            default_analytics = [
                'https://www.google-analytics.com',
                'https://www.googletagmanager.com',
                'https://stats.g.doubleclick.net',
            ]
            
            all_analytics = list(set(default_analytics + analytics_domains))
            
            # Add to script-src
            if 'script-src' not in directives:
                directives['script-src'] = ["'self'"]
            directives['script-src'].extend(all_analytics)
            
            # Add to img-src
            if 'img-src' not in directives:
                directives['img-src'] = ["'self'"]
            directives['img-src'].extend(all_analytics)
            
            # Add to connect-src
            if 'connect-src' not in directives:
                directives['connect-src'] = ["'self'"]
            directives['connect-src'].extend(all_analytics)
        
        return config


def get_security_headers_config(environment: str = 'production', **kwargs) -> Dict:
    """
    Get security headers configuration for environment.
    
    Args:
        environment: 'development', 'production', or 'api'
        **kwargs: Additional configuration options
        
    Returns:
        Security headers configuration dict
    """
    if environment == 'development':
        config = SecurityHeadersConfig.development()
    elif environment == 'production':
        config = SecurityHeadersConfig.production()
    elif environment == 'api':
        config = SecurityHeadersConfig.api_only()
    else:
        raise ValueError(f"Unknown environment: {environment}")
    
    # Apply additional configurations
    if 'cdn_domains' in kwargs:
        config = SecurityHeadersConfig.with_cdn(config, kwargs['cdn_domains'])
    
    if 'analytics_domains' in kwargs:
        config = SecurityHeadersConfig.with_analytics(config, kwargs['analytics_domains'])
    
    if 'cors_origins' in kwargs and 'CORS' in config:
        config['CORS']['ALLOWED_ORIGINS'] = kwargs['cors_origins']
    
    return config