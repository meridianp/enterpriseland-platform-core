
import os
from pathlib import Path
from decouple import config, Csv
from .secrets import secrets, get_database_config, get_email_config, get_aws_config, get_celery_config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = secrets.SECRET_KEY

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,0.0.0.0,eland001.tailb381ec.ts.net', cast=lambda v: [s.strip() for s in v.split(',')])

# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',  # GeoDjango support
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',  # Token blacklisting
    'rest_framework_gis',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'storages',
    'csp',  # Content Security Policy
]

LOCAL_APPS = [
    'core',
    'accounts',
    'api_keys',
    'assessments',
    'notifications',
    'files',
    'contacts',
    'market_intelligence',
    'leads',
    'geographic_intelligence',
    'integrations',
    'deals',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Import security settings
from .security import get_secure_middleware_order, get_csp_settings, get_security_headers

MIDDLEWARE = get_secure_middleware_order()

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = 'core.wsgi.application'

# Database Configuration with Connection Pooling
DATABASES = {
    'default': get_database_config()
}

# Add read replica if configured
if config('DB_READ_HOST', default=''):
    read_config = get_database_config().copy()
    read_config.update({
        'HOST': config('DB_READ_HOST'),
        'PORT': config('DB_READ_PORT', default=5432, cast=int),
        'USER': config('DB_READ_USER', default=read_config.get('USER')),
        'PASSWORD': config('DB_READ_PASSWORD', default=read_config.get('PASSWORD')),
        'NAME': config('DB_READ_NAME', default=read_config.get('NAME')),
    })
    DATABASES['read'] = read_config

# Database Router for read/write splitting
if 'read' in DATABASES:
    DATABASE_ROUTERS = ['core.db_router.DatabaseRouter']

# Connection Pool Monitoring
DATABASE_POOL_MONITORING = {
    'ENABLED': config('DB_POOL_MONITORING', default=True, cast=bool),
    'LOG_SLOW_QUERIES': config('DB_LOG_SLOW_QUERIES', default=True, cast=bool),
    'SLOW_QUERY_THRESHOLD': config('DB_SLOW_QUERY_THRESHOLD', default=1.0, cast=float),  # seconds
    'CONNECTION_METRICS': config('DB_CONNECTION_METRICS', default=True, cast=bool),
    'POOL_SIZE_ALERTS': config('DB_POOL_SIZE_ALERTS', default=True, cast=bool),
    'MAX_POOL_USAGE': config('DB_MAX_POOL_USAGE', default=80, cast=int),  # percentage
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'api_keys.authentication.APIKeyAuthentication',  # API key authentication
        'accounts.authentication.CookieJWTAuthentication',  # Cookie-based JWT auth
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # Fallback to header-based
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'core.throttling.EnhancedUserRateThrottle',
        'core.throttling.EnhancedAnonRateThrottle',
        'core.throttling.TenantRateThrottle',
        'core.throttling.BurstRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'tenant': '10000/hour',
        'authentication': '10/hour',
        'ai_agent': '100/hour',
        'file_upload': '100/hour',
        'public_api': '100/hour',
        'burst': '10/second',
    },
}

# JWT Configuration
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(hours=8),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': secrets.JWT_SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',
    'JTI_CLAIM': 'jti',
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=30),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(hours=8),
}

# CORS Configuration
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000,http://eland001.tailb381ec.ts.net:3000,http://eland001.tailb381ec.ts.net:3001',
    cast=lambda v: [s.strip() for s in v.split(',')]
)

CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ['X-CSRFToken']

# CSRF Settings for cookie-based auth
CSRF_COOKIE_NAME = 'csrftoken'
CSRF_COOKIE_HTTPONLY = False  # Frontend needs to read this
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = not DEBUG  # True in production
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

# Session cookie settings (for CSRF)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG  # True in production

# DRF Spectacular (OpenAPI) Configuration
SPECTACULAR_SETTINGS = {
    'TITLE': 'CASA Due Diligence Platform API',
    'DESCRIPTION': '''
    Comprehensive API for CASA's Development Partner Due Diligence Platform.
    
    This API provides endpoints for:
    - Development partner assessment and management
    - PBSA scheme evaluation and monitoring
    - Gold-standard scoring frameworks
    - Risk assessment and compliance tracking
    - Performance monitoring and reporting
    - Multi-tenant access control
    
    ## Authentication
    
    The API uses JWT (JSON Web Token) authentication. Include the token in the Authorization header:
    ```
    Authorization: Bearer <your-jwt-token>
    ```
    
    ## Versioning
    
    API endpoints support semantic versioning. The current version is v1.
    
    ## Rate Limiting
    
    API requests are rate limited based on user authentication status.
    ''',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'COMPONENT_NO_READ_ONLY_REQUIRED': True,
    'ENUM_NAME_OVERRIDES': {
        'CurrencyEnum': 'assessments.enums.Currency',
        'AssessmentStatusEnum': 'assessments.enums.AssessmentStatus',
        'AssessmentDecisionEnum': 'assessments.enums.AssessmentDecision',
        'RiskLevelEnum': 'assessments.enums.RiskLevel',
        'DebtRatioCategoryEnum': 'assessments.enums.DebtRatioCategory',
        'AreaUnitEnum': 'assessments.enums.AreaUnit',
    },
    'SCHEMA_PATH_PREFIX': '/api/',
    'SCHEMA_PATH_PREFIX_TRIM': True,
    'TAGS': [
        {
            'name': 'Authentication',
            'description': 'JWT authentication endpoints'
        },
        {
            'name': 'Assessments',
            'description': 'Development partner and scheme assessments'
        },
        {
            'name': 'Partners',
            'description': 'Development partner management'
        },
        {
            'name': 'Schemes',
            'description': 'PBSA scheme management'
        },
        {
            'name': 'Risk Analysis',
            'description': 'Risk assessment and monitoring'
        },
        {
            'name': 'Performance',
            'description': 'Performance tracking and metrics'
        },
        {
            'name': 'Reports',
            'description': 'Reporting and analytics'
        },
        {
            'name': 'Files',
            'description': 'File management and uploads'
        },
        {
            'name': 'Notifications',
            'description': 'Notification system'
        },
        {
            'name': 'Market Intelligence',
            'description': 'News discovery, analysis, and target identification'
        },
        {
            'name': 'Lead Management',
            'description': 'Lead scoring, workflow automation, and conversion tracking'
        },
    ],
    'CONTACT': {
        'name': 'CASA Development Team',
        'email': 'dev@casa.com',
    },
    'LICENSE': {
        'name': 'Proprietary',
    },
    'EXTERNAL_DOCS': {
        'description': 'Full Documentation',
        'url': 'https://casa-dd-platform.com/docs/',
    },
    'SERVERS': [
        {
            'url': 'http://localhost:8000',
            'description': 'Development server'
        },
        {
            'url': 'https://api-staging.casa-dd-platform.com',
            'description': 'Staging server'
        },
        {
            'url': 'https://api.casa-dd-platform.com',
            'description': 'Production server'
        },
    ],
    'PREPROCESSING_HOOKS': [
        'assessments.openapi.preprocessing_filter_spec',
    ],
    'POSTPROCESSING_HOOKS': [
        'assessments.openapi.postprocessing_hook',
    ],
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': True,
        'tryItOutEnabled': True,
        'filter': True,
        'syntaxHighlight.theme': 'agate',
    },
    'REDOC_UI_SETTINGS': {
        'hideDownloadButton': False,
        'expandResponses': '200,201',
        'pathInMiddlePanel': True,
        'nativeScrollbars': True,
        'requiredPropsFirst': True,
    },
}


# AWS S3 Configuration
aws_config = get_aws_config()
for key, value in aws_config.items():
    globals()[key] = value

# Email Configuration
email_config = get_email_config()
for key, value in email_config.items():
    globals()[key] = value

# Celery Configuration
celery_config = get_celery_config()
for key, value in celery_config.items():
    globals()[key] = value
CELERY_TIMEZONE = TIME_ZONE

# Cache Configuration - Multi-tier caching strategy
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': secrets.REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_CLASS': 'redis.connection.BlockingConnectionPool',
            'CONNECTION_POOL_CLASS_KWARGS': {
                'max_connections': 50,
                'timeout': 20,
                'retry_on_timeout': True,
                'health_check_interval': 30,
            },
            'MAX_CONNECTIONS': 1000,
            'PICKLE_VERSION': -1,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            'IGNORE_EXCEPTIONS': True,  # Graceful degradation if Redis unavailable
        },
        'KEY_PREFIX': 'casa:default',
        'TIMEOUT': 300,  # Default timeout of 5 minutes
        'VERSION': 1,
    },
    'session': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': secrets.REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_CLASS': 'redis.connection.BlockingConnectionPool',
            'CONNECTION_POOL_CLASS_KWARGS': {
                'max_connections': 20,
                'timeout': 20,
            },
            'PICKLE_VERSION': -1,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        },
        'KEY_PREFIX': 'casa:session',
        'TIMEOUT': 3600,  # 1 hour for sessions
    },
    'api_cache': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': secrets.REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_CLASS': 'redis.connection.BlockingConnectionPool',
            'CONNECTION_POOL_CLASS_KWARGS': {
                'max_connections': 30,
                'timeout': 20,
            },
            'PICKLE_VERSION': -1,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        },
        'KEY_PREFIX': 'casa:api',
        'TIMEOUT': 600,  # 10 minutes for API responses
    },
    'model_cache': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': secrets.REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_CLASS': 'redis.connection.BlockingConnectionPool',
            'CONNECTION_POOL_CLASS_KWARGS': {
                'max_connections': 20,
                'timeout': 20,
            },
            'PICKLE_VERSION': -1,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        },
        'KEY_PREFIX': 'casa:model',
        'TIMEOUT': 1800,  # 30 minutes for model data
    },
    'template_cache': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': secrets.REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_CLASS': 'redis.connection.BlockingConnectionPool',
            'CONNECTION_POOL_CLASS_KWARGS': {
                'max_connections': 10,
                'timeout': 20,
            },
            'PICKLE_VERSION': -1,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        },
        'KEY_PREFIX': 'casa:template',
        'TIMEOUT': 3600,  # 1 hour for template fragments
    },
    'statistics': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': secrets.REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_CLASS': 'redis.connection.BlockingConnectionPool',
            'CONNECTION_POOL_CLASS_KWARGS': {
                'max_connections': 10,
                'timeout': 20,
            },
            'PICKLE_VERSION': -1,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        },
        'KEY_PREFIX': 'casa:stats',
        'TIMEOUT': 7200,  # 2 hours for statistics
    }
}

# Session Configuration - Use Redis for sessions
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'session'
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Cache warming configuration
CACHE_WARMING = {
    'ENABLED': config('CACHE_WARMING_ENABLED', default=True, cast=bool),
    'STARTUP_WARMING': config('CACHE_STARTUP_WARMING', default=False, cast=bool),
    'BACKGROUND_WARMING': config('CACHE_BACKGROUND_WARMING', default=True, cast=bool),
    'WARMING_INTERVAL': config('CACHE_WARMING_INTERVAL', default=3600, cast=int),  # 1 hour
}

# Cache monitoring configuration
CACHE_MONITORING = {
    'ENABLED': config('CACHE_MONITORING_ENABLED', default=True, cast=bool),
    'STATS_INTERVAL': config('CACHE_STATS_INTERVAL', default=300, cast=int),  # 5 minutes
    'CLEANUP_INTERVAL': config('CACHE_CLEANUP_INTERVAL', default=86400, cast=int),  # 24 hours
    'ALERT_ON_HIGH_MEMORY': config('CACHE_ALERT_HIGH_MEMORY', default=True, cast=bool),
    'MEMORY_THRESHOLD': config('CACHE_MEMORY_THRESHOLD', default=80, cast=int),  # 80%
}

# Rate Limiting Configuration
RATE_LIMITING = {
    'ENABLE_RATE_LIMITING': config('ENABLE_RATE_LIMITING', default=True, cast=bool),
    'REDIS_URL': secrets.REDIS_URL,
    
    # Token/Cost limits for AI endpoints
    'AI_TOKEN_LIMIT_PER_HOUR': config('AI_TOKEN_LIMIT_PER_HOUR', default=10000, cast=int),
    'AI_TOKEN_LIMIT_PER_DAY': config('AI_TOKEN_LIMIT_PER_DAY', default=100000, cast=int),
    
    # File upload limits
    'FILE_UPLOAD_SIZE_LIMIT_PER_HOUR': config('FILE_UPLOAD_SIZE_LIMIT_PER_HOUR', default=1024*1024*1024, cast=int),  # 1GB
    'FILE_UPLOAD_COUNT_LIMIT_PER_HOUR': config('FILE_UPLOAD_COUNT_LIMIT_PER_HOUR', default=100, cast=int),
    
    # Monitoring thresholds
    'RATE_LIMIT_WARNING_THRESHOLD': config('RATE_LIMIT_WARNING_THRESHOLD', default=80, cast=int),
    'RATE_LIMIT_CRITICAL_THRESHOLD': config('RATE_LIMIT_CRITICAL_THRESHOLD', default=95, cast=int),
}

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'assessments': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'market_intelligence': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'leads': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Create logs directory
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

# Security Settings
# Apply CSP settings
csp_settings = get_csp_settings(debug=DEBUG)
# Handle the new CSP format
if 'CONTENT_SECURITY_POLICY' in csp_settings:
    CONTENT_SECURITY_POLICY = csp_settings['CONTENT_SECURITY_POLICY']
else:
    # Fallback for old format (shouldn't happen with updated security.py)
    for key, value in csp_settings.items():
        globals()[key] = value

# Apply additional security headers
security_headers = get_security_headers(debug=DEBUG)
for key, value in security_headers.items():
    globals()[key] = value

# Import file upload security settings
from .security import SECURE_FILE_UPLOAD_SETTINGS

# Apply file upload settings
DATA_UPLOAD_MAX_MEMORY_SIZE = SECURE_FILE_UPLOAD_SETTINGS['FILE_UPLOAD_MAX_MEMORY_SIZE']
FILE_UPLOAD_MAX_MEMORY_SIZE = SECURE_FILE_UPLOAD_SETTINGS['FILE_UPLOAD_MAX_MEMORY_SIZE']
FILE_UPLOAD_PERMISSIONS = SECURE_FILE_UPLOAD_SETTINGS['FILE_UPLOAD_PERMISSIONS']
FILE_UPLOAD_DIRECTORY_PERMISSIONS = SECURE_FILE_UPLOAD_SETTINGS['FILE_UPLOAD_DIRECTORY_PERMISSIONS']

# Import provider configuration
from .integrations import PROVIDER_CONFIG

# Audit Logging Configuration
AUDIT_LOGGING_ENABLED = config('AUDIT_LOGGING_ENABLED', default=True, cast=bool)
AUDIT_ASYNC_LOGGING = config('AUDIT_ASYNC_LOGGING', default=True, cast=bool)
AUDIT_RETENTION_DAYS = config('AUDIT_RETENTION_DAYS', default=365, cast=int)
AUDIT_PATHS = config('AUDIT_PATHS', default='/api/', cast=lambda v: [s.strip() for s in v.split(',')])
AUDIT_EXCLUDE_PATHS = config('AUDIT_EXCLUDE_PATHS', 
    default='/api/health/,/api/metrics/,/static/,/media/,/admin/jsi18n/,/admin/login/', 
    cast=lambda v: [s.strip() for s in v.split(',')]
)
AUDIT_METHODS = config('AUDIT_METHODS', default='POST,PUT,PATCH,DELETE', cast=lambda v: [s.strip() for s in v.split(',')])
AUDIT_RESPONSE_TIME_THRESHOLD = config('AUDIT_RESPONSE_TIME_THRESHOLD', default=2.0, cast=float)

# Audit logging security settings
AUDIT_MASK_SENSITIVE_FIELDS = config('AUDIT_MASK_SENSITIVE_FIELDS', default=True, cast=bool)
AUDIT_LOG_SUCCESSFUL_REQUESTS = config('AUDIT_LOG_SUCCESSFUL_REQUESTS', default=True, cast=bool)
AUDIT_LOG_FAILED_REQUESTS = config('AUDIT_LOG_FAILED_REQUESTS', default=True, cast=bool)
AUDIT_LOG_AUTHENTICATION_EVENTS = config('AUDIT_LOG_AUTHENTICATION_EVENTS', default=True, cast=bool)

# API Key Configuration
API_KEY_ENABLED = config('API_KEY_ENABLED', default=True, cast=bool)
API_KEY_HEADER_NAME = config('API_KEY_HEADER_NAME', default='X-API-Key')
API_KEY_QUERY_PARAM = config('API_KEY_QUERY_PARAM', default='api_key')
API_KEY_DEFAULT_RATE_LIMIT = config('API_KEY_DEFAULT_RATE_LIMIT', default='1000/hour')
API_KEY_CACHE_TIMEOUT = config('API_KEY_CACHE_TIMEOUT', default=300, cast=int)  # 5 minutes
API_KEY_USAGE_TRACKING = config('API_KEY_USAGE_TRACKING', default=True, cast=bool)
API_KEY_AUTO_EXPIRE_DAYS = config('API_KEY_AUTO_EXPIRE_DAYS', default=365, cast=int)
API_KEY_ROTATION_WARNING_DAYS = config('API_KEY_ROTATION_WARNING_DAYS', default=30, cast=int)

# API Key Security Settings
API_KEY_REQUIRE_HTTPS = config('API_KEY_REQUIRE_HTTPS', default=not DEBUG, cast=bool)
API_KEY_ALLOW_QUERY_PARAM = config('API_KEY_ALLOW_QUERY_PARAM', default=DEBUG, cast=bool)  # Only in dev
API_KEY_LOG_USAGE = config('API_KEY_LOG_USAGE', default=True, cast=bool)

# Compression Configuration
from .compression import (
    get_compression_settings, 
    get_streaming_compression_settings, 
    get_conditional_compression_settings,
    get_compression_monitoring_settings,
    COMPRESSION_SECURITY_SETTINGS
)

# Apply compression settings
COMPRESSION_SETTINGS = get_compression_settings(debug=DEBUG, environment='development')
STREAMING_COMPRESSION_SETTINGS = get_streaming_compression_settings(debug=DEBUG, environment='development')
CONDITIONAL_COMPRESSION_SETTINGS = get_conditional_compression_settings(debug=DEBUG, environment='development')
COMPRESSION_MONITORING_SETTINGS = get_compression_monitoring_settings()

# Apply compression security settings
for key, value in COMPRESSION_SECURITY_SETTINGS.items():
    globals()[key] = value
