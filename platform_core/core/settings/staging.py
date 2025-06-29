
from .production import *

DEBUG = config('DEBUG', default=False, cast=bool)

# Staging-specific database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='rule_diligence_staging'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='postgres'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# Less strict security for staging
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Staging compression settings
from .compression import (
    get_compression_settings, 
    get_streaming_compression_settings, 
    get_conditional_compression_settings
)

# Override compression settings for staging
COMPRESSION_SETTINGS = get_compression_settings(debug=DEBUG, environment='staging')
STREAMING_COMPRESSION_SETTINGS = get_streaming_compression_settings(debug=DEBUG, environment='staging')
CONDITIONAL_COMPRESSION_SETTINGS = get_conditional_compression_settings(debug=DEBUG, environment='staging')
