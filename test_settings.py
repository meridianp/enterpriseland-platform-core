"""
Test settings for platform-core
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = 'test-secret-key-for-platform-core-tests'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'platform_core.modules',
    'platform_core.security',
    'platform_core.gateway',
    'platform_core.events',
    'platform_core.websocket',
    'platform_core.cache',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'platform_core.urls'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'test_db.sqlite3'),
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Cache configuration
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

CACHE_DEFAULT_TIMEOUT = 300
CACHE_KEY_PREFIX = 'test'

# Redis configuration for tests
REDIS_CACHE_CONFIG = {
    'host': 'localhost',
    'port': 6379,
    'db': 15,  # Test database
    'password': None,
}

# Tiered cache config
TIERED_CACHE_CONFIG = {
    'l1_size': 100,
}

# Cache warming config
CACHE_WARMING_CONFIG = {
    'enabled': False,  # Disabled for tests
    'max_workers': 2,
}

# WebSocket configuration
ASGI_APPLICATION = 'platform_core.websocket.routing.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

# Event system configuration
EVENT_BROKER = 'memory'  # Use in-memory broker for tests

# Security settings
JWT_SECRET_KEY = 'test-jwt-secret'
ENCRYPTION_KEY = b'test-encryption-key-32-bytes-long!!!'

# Module system settings
MODULE_STORAGE_PATH = os.path.join(BASE_DIR, 'test_modules')
MODULE_SANDBOX_ENABLED = False  # Disable sandboxing for tests

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'platform_core': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}