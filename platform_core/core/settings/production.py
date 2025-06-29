
from .base import *
from .security import get_csp_settings, get_security_headers

DEBUG = False

# Override with production security settings
# CSP settings for production
csp_settings = get_csp_settings(debug=False)
# Handle the new CSP format
if 'CONTENT_SECURITY_POLICY' in csp_settings:
    CONTENT_SECURITY_POLICY = csp_settings['CONTENT_SECURITY_POLICY']
else:
    # Fallback for old format (shouldn't happen with updated security.py)
    for key, value in csp_settings.items():
        globals()[key] = value

# Security headers for production
security_headers = get_security_headers(debug=False)
for key, value in security_headers.items():
    globals()[key] = value

# Additional production security settings
SECURE_REDIRECT_EXEMPT = []

# Add secure proxy settings for Cloud Run
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# Stricter session settings for production
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

# CSRF settings for production
CSRF_FAILURE_VIEW = 'core.views.csrf_failure'
CSRF_USE_SESSIONS = False  # Use cookies for CSRF tokens

# Additional security headers via secure package
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Use S3 for file storage in production
if AWS_STORAGE_BUCKET_NAME:
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    STATICFILES_STORAGE = 'storages.backends.s3boto3.StaticS3Boto3Storage'

# Production email backend
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# Production logging
LOGGING['handlers']['file']['level'] = 'WARNING'
LOGGING['handlers']['console']['level'] = 'ERROR'

# Production compression settings
from .compression import (
    get_compression_settings, 
    get_streaming_compression_settings, 
    get_conditional_compression_settings
)

# Override compression settings for production
COMPRESSION_SETTINGS = get_compression_settings(debug=False, environment='production')
STREAMING_COMPRESSION_SETTINGS = get_streaming_compression_settings(debug=False, environment='production')
CONDITIONAL_COMPRESSION_SETTINGS = get_conditional_compression_settings(debug=False, environment='production')
