from .base import *

DEBUG = True

# Use SQLite for simple local development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Use local file storage in development
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# CORS settings for development
CORS_ALLOW_ALL_ORIGINS = True

# Simplified for local dev - disable some features that require external services
CELERY_TASK_ALWAYS_EAGER = True  # Run Celery tasks synchronously
CELERY_TASK_EAGER_PROPAGATES = True

# Development logging
LOGGING['handlers']['console']['level'] = 'DEBUG'
LOGGING['loggers']['assessments']['level'] = 'DEBUG'

# Allow all hosts in development
ALLOWED_HOSTS = ['*']

# Disable HTTPS requirements
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False