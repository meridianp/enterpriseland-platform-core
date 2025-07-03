"""
Django settings for platform-core.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'celery',
]

PLATFORM_APPS = [
    'platform_core.accounts',
    'platform_core.files',
    'platform_core.notifications',
    'platform_core.integrations',
    'platform_core.workflows',
    'platform_core.agents',
    'platform_core.audit',
    'platform_core.encryption',
    'platform_core.api_keys',
    'platform_core.modules',
    'platform_core.gateway',
    'platform_core.events',
    'platform_core.websocket',
    'platform_core.alerts',
    'platform_core.monitoring',
    'platform_core.performance',
    'platform_core.caching',
    'platform_core.cdn',
    'platform_core.health',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + PLATFORM_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'platform_core.core.middleware.AuditMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'platform_core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'platform_core.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'platform_core'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'password'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# Cache
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://localhost:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

# Platform-specific settings
PLATFORM_CONFIG = {
    'AUDIT_ENABLED': True,
    'ENCRYPTION_ENABLED': True,
    'API_KEY_ROTATION_ENABLED': True,
}

# Event System Configuration
EVENT_BROKER = {
    'type': os.environ.get('EVENT_BROKER_TYPE', 'redis'),  # rabbitmq, redis, kafka
    'host': os.environ.get('EVENT_BROKER_HOST', 'localhost'),
    'port': int(os.environ.get('EVENT_BROKER_PORT', '6379')),
    'username': os.environ.get('EVENT_BROKER_USERNAME', 'guest'),
    'password': os.environ.get('EVENT_BROKER_PASSWORD', 'guest'),
    'vhost': os.environ.get('EVENT_BROKER_VHOST', '/'),
    'db': int(os.environ.get('EVENT_BROKER_DB', '2')),  # For Redis
    'bootstrap_servers': os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092').split(','),  # For Kafka
    'group_id': os.environ.get('KAFKA_GROUP_ID', 'platform-core'),  # For Kafka
    'prefetch_count': int(os.environ.get('EVENT_PREFETCH_COUNT', '1')),
    'dead_letter_exchange': os.environ.get('EVENT_DLX', 'dlx'),
    'message_ttl': int(os.environ.get('EVENT_MESSAGE_TTL', '86400000')),  # 24 hours
}

# Event System Settings
EVENTS_AUTO_START = os.environ.get('EVENTS_AUTO_START', 'False').lower() == 'true'
EVENTS_REQUIRE_SCHEMA = os.environ.get('EVENTS_REQUIRE_SCHEMA', 'True').lower() == 'true'
EVENTS_BATCH_FAIL_FAST = os.environ.get('EVENTS_BATCH_FAIL_FAST', 'True').lower() == 'true'
EVENT_DEFAULT_QUEUE = os.environ.get('EVENT_DEFAULT_QUEUE', 'default-events')

# Event Routing Rules (optional)
EVENT_ROUTING_RULES = [
    {
        'event_types': ['*.error', '*.failed'],
        'match_type': 'pattern',
        'target': 'error-events',
        'priority': 100
    },
    {
        'event_types': ['user.*'],
        'match_type': 'pattern',
        'target': 'user-events',
        'priority': 50
    },
    {
        'event_types': ['order.*'],
        'match_type': 'pattern',
        'target': 'order-events',
        'priority': 50
    }
]

# Django Channels Configuration
ASGI_APPLICATION = 'platform_core.routing.application'

# Channel Layers
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [(
                os.environ.get('REDIS_HOST', 'localhost'),
                int(os.environ.get('REDIS_PORT', '6379'))
            )],
            'capacity': 100,
            'expiry': 10,
        },
    },
}

# WebSocket Configuration
WEBSOCKET_ALLOWED_ORIGINS = os.environ.get(
    'WEBSOCKET_ALLOWED_ORIGINS',
    'http://localhost:3000,http://localhost:8000'
).split(',')

WEBSOCKET_MAX_CONNECTIONS_PER_USER = int(os.environ.get('WEBSOCKET_MAX_CONNECTIONS_PER_USER', '5'))
WEBSOCKET_MAX_MESSAGE_SIZE = int(os.environ.get('WEBSOCKET_MAX_MESSAGE_SIZE', '65536'))  # 64KB

# WebSocket Rate Limiting
WEBSOCKET_RATE_LIMITS = {
    'default': {
        'messages': int(os.environ.get('WEBSOCKET_RATE_LIMIT_DEFAULT', '60')),
        'window': 60  # 1 minute
    },
    'authenticated': {
        'messages': int(os.environ.get('WEBSOCKET_RATE_LIMIT_AUTH', '120')),
        'window': 60  # 1 minute
    }
}

# Alert System Configuration
ALERT_RETENTION_DAYS = int(os.environ.get('ALERT_RETENTION_DAYS', '30'))
ALERT_SUMMARY_RECIPIENTS = os.environ.get('ALERT_SUMMARY_RECIPIENTS', '').split(',')

# Email Configuration
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'alerts@enterpriseland.com')

# Metrics Configuration
METRICS_ENABLED = os.environ.get('METRICS_ENABLED', 'True').lower() == 'true'
METRICS_REQUIRE_AUTH = os.environ.get('METRICS_REQUIRE_AUTH', 'False').lower() == 'true'

# Performance Profiling
PROFILING_ENABLED = os.environ.get('PROFILING_ENABLED', 'False').lower() == 'true'
PROFILING_SAMPLE_RATE = float(os.environ.get('PROFILING_SAMPLE_RATE', '0.1'))

# CDN Configuration
CDN_ENABLED = os.environ.get('CDN_ENABLED', 'False').lower() == 'true'
CDN_PROVIDER = os.environ.get('CDN_PROVIDER', 'cloudflare')
CDN_BASE_URL = os.environ.get('CDN_BASE_URL', '')
CDN_API_KEY = os.environ.get('CDN_API_KEY', '')
CDN_ZONE_ID = os.environ.get('CDN_ZONE_ID', '')
