"""
Google Cloud Run specific settings
"""
import os
import dj_database_url
from .production import *
from .secrets import secrets

# Parse database URL from environment
DATABASE_URL = config('DATABASE_URL', default=None)
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    }
    # Ensure SSL is used for Neon
    DATABASES['default']['OPTIONS'] = {'sslmode': 'require'}

# Cloud Run specific settings
ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='*',  # Cloud Run handles host validation
    cast=lambda v: [s.strip() for s in v.split(',')]
)

# Static files - Cloud Run doesn't persist local files
# Use WhiteNoise for serving static files
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Security headers for Cloud Run
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# Logging for Cloud Run
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'cloud_run': {
            'format': '%(levelname)s %(name)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'cloud_run',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

# Cloud Run runs on port 8080 by default
PORT = int(os.environ.get('PORT', 8080))

# Production JWT settings - stronger security
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),  # Shorter for production
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': secrets.JWT_SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    
    'JTI_CLAIM': 'jti',
    
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=15),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}

# File upload settings for Cloud Run (no persistent storage)
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# CORS - Configure allowed origins from environment
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='https://casa-frontend-sdxchzqikq-uc.a.run.app,http://localhost:3000',
    cast=lambda v: [s.strip() for s in v.split(',')]
)

# Cache configuration (use Redis if available)
if config('REDIS_URL', default=None):
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': config('REDIS_URL'),
        }
    }
else:
    # Fallback to local memory cache
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

# Cloud Run compression settings - optimized for bandwidth
from .compression import (
    get_compression_settings, 
    get_streaming_compression_settings, 
    get_conditional_compression_settings
)

# Override compression settings for Cloud Run
COMPRESSION_SETTINGS = get_compression_settings(debug=False, environment='production')
STREAMING_COMPRESSION_SETTINGS = get_streaming_compression_settings(debug=False, environment='production')
CONDITIONAL_COMPRESSION_SETTINGS = get_conditional_compression_settings(debug=False, environment='production')

# Enable streaming compression for Cloud Run (large responses)
STREAMING_COMPRESSION_SETTINGS['ENABLED'] = True