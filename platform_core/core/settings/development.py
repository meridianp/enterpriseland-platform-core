
from .base import *

DEBUG = True

# Allowed hosts for development
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'backend', '*.localhost', 'testserver']

# Database for development - check if PostGIS is available
import os
USE_POSTGIS = config('USE_POSTGIS', default='true', cast=bool)

if USE_POSTGIS:
    # Try to use PostGIS for geographic features
    try:
        from django.contrib.gis.gdal import gdal_version
        DATABASE_ENGINE = 'django.contrib.gis.db.backends.postgis'
        print(f"Using PostGIS backend with GDAL version: {gdal_version()}")
    except Exception as e:
        # Fall back to regular PostgreSQL if PostGIS/GDAL not available
        print(f"GDAL not available ({e}), falling back to regular PostgreSQL")
        DATABASE_ENGINE = 'django.db.backends.postgresql'
        USE_POSTGIS = False
else:
    DATABASE_ENGINE = 'django.db.backends.postgresql'

DATABASES = {
    'default': {
        'ENGINE': DATABASE_ENGINE,
        'NAME': config('DB_NAME', default='rule_diligence_dev'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='postgres'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# Store whether PostGIS is available for use in models
POSTGIS_AVAILABLE = USE_POSTGIS

# Use local file storage in development
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# CORS settings for development
CORS_ALLOW_ALL_ORIGINS = True

# Additional development apps
INSTALLED_APPS += [
    'django_extensions',
]

# Development logging
LOGGING['handlers']['console']['level'] = 'DEBUG'
LOGGING['loggers']['assessments']['level'] = 'DEBUG'

# Security overrides for development
# CSP settings are now handled by get_csp_settings() in security.py
# which provides comprehensive development-friendly CSP directives

# Disable HTTPS redirect in development
SECURE_SSL_REDIRECT = False

# Keep cookies accessible in development
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Add whitenoise for static files in development
if 'whitenoise.middleware.WhiteNoiseMiddleware' not in MIDDLEWARE:
    # Insert after SecurityMiddleware
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
