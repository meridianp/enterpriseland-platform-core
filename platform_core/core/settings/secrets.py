"""
Centralized secret management for the CASA platform.
All secrets should be loaded through this module to ensure proper validation and security.
"""

import os
import sys
import warnings
from typing import Optional, Dict, Any, List
from pathlib import Path

from decouple import config, Csv, UndefinedValueError


class SecretValidationError(Exception):
    """Raised when a required secret is missing or invalid."""
    pass


class Secrets:
    """Centralized secret management with validation."""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self._cache: Dict[str, Any] = {}
        self.environment = config('ENVIRONMENT', default='development')
        self.is_production = self.environment == 'production'
        self.is_testing = 'test' in sys.argv or 'pytest' in sys.modules
    
    def _get_secret(self, key: str, default: Any = None, cast: Any = None, 
                    required_in_production: bool = True) -> Any:
        """Get a secret with caching and validation."""
        if key in self._cache:
            return self._cache[key]
        
        try:
            if cast is not None:
                value = config(key, default=default, cast=cast)
            else:
                value = config(key, default=default)
            
            # Validate required secrets in production
            if self.is_production and required_in_production and value == default:
                self.errors.append(f"{key} is required in production but not set")
                
            self._cache[key] = value
            return value
            
        except UndefinedValueError:
            if self.is_production and required_in_production:
                self.errors.append(f"{key} is required but not defined")
            return default
    
    # ===========================
    # DJANGO CORE SECRETS
    # ===========================
    
    @property
    def SECRET_KEY(self) -> str:
        """Django secret key."""
        default = 'django-insecure-change-me-in-production' if not self.is_production else None
        key = self._get_secret('SECRET_KEY', default=default)
        
        if key and 'insecure' in key and self.is_production:
            self.errors.append("SECRET_KEY contains 'insecure' in production")
        
        if key and len(key) < 50:
            self.warnings.append("SECRET_KEY should be at least 50 characters long")
            
        return key
    
    @property
    def JWT_SECRET_KEY(self) -> str:
        """JWT signing key - should be different from Django SECRET_KEY."""
        default = None if self.is_production else self.SECRET_KEY
        key = self._get_secret('JWT_SECRET_KEY', default=default)
        
        if key == self.SECRET_KEY:
            self.warnings.append("JWT_SECRET_KEY should be different from SECRET_KEY")
            
        return key
    
    # ===========================
    # DATABASE SECRETS
    # ===========================
    
    @property
    def DATABASE_URL(self) -> Optional[str]:
        """Full database URL if provided."""
        return self._get_secret('DATABASE_URL', required_in_production=False)
    
    @property
    def DB_PASSWORD(self) -> str:
        """Database password."""
        default = 'postgres' if not self.is_production else None
        password = self._get_secret('DB_PASSWORD', default=default)
        
        if password and len(password) < 8 and self.is_production:
            self.warnings.append("DB_PASSWORD should be at least 8 characters long")
            
        return password
    
    @property
    def DB_USER(self) -> str:
        """Database user."""
        return self._get_secret('DB_USER', default='postgres', required_in_production=False)
    
    @property
    def DB_NAME(self) -> str:
        """Database name."""
        return self._get_secret('DB_NAME', default='rule_diligence', required_in_production=False)
    
    @property
    def DB_HOST(self) -> str:
        """Database host."""
        return self._get_secret('DB_HOST', default='localhost', required_in_production=False)
    
    @property
    def DB_PORT(self) -> str:
        """Database port."""
        return self._get_secret('DB_PORT', default='5432', required_in_production=False)
    
    # ===========================
    # AWS SECRETS
    # ===========================
    
    @property
    def AWS_ACCESS_KEY_ID(self) -> str:
        """AWS Access Key ID."""
        key = self._get_secret('AWS_ACCESS_KEY_ID', default='', required_in_production=False)
        
        if key and not key.startswith('AKIA') and len(key) == 20:
            self.warnings.append("AWS_ACCESS_KEY_ID doesn't appear to be valid")
            
        return key
    
    @property
    def AWS_SECRET_ACCESS_KEY(self) -> str:
        """AWS Secret Access Key."""
        return self._get_secret('AWS_SECRET_ACCESS_KEY', default='', required_in_production=False)
    
    @property
    def AWS_STORAGE_BUCKET_NAME(self) -> str:
        """S3 bucket name for file storage."""
        return self._get_secret('AWS_STORAGE_BUCKET_NAME', default='', required_in_production=False)
    
    # ===========================
    # EMAIL SECRETS
    # ===========================
    
    @property
    def EMAIL_HOST_USER(self) -> str:
        """Email host user."""
        return self._get_secret('EMAIL_HOST_USER', default='', required_in_production=False)
    
    @property
    def EMAIL_HOST_PASSWORD(self) -> str:
        """Email host password."""
        return self._get_secret('EMAIL_HOST_PASSWORD', default='', required_in_production=False)
    
    # ===========================
    # REDIS SECRETS
    # ===========================
    
    @property
    def REDIS_URL(self) -> str:
        """Redis connection URL."""
        default = 'redis://localhost:6379/0' if not self.is_production else None
        return self._get_secret('REDIS_URL', default=default)
    
    @property
    def REDIS_PASSWORD(self) -> Optional[str]:
        """Redis password if required."""
        return self._get_secret('REDIS_PASSWORD', default=None, required_in_production=False)
    
    # ===========================
    # EXTERNAL SERVICE SECRETS
    # ===========================
    
    @property
    def SENTRY_DSN(self) -> str:
        """Sentry DSN for error tracking."""
        return self._get_secret('SENTRY_DSN', default='', required_in_production=False)
    
    @property
    def GCP_SERVICE_ACCOUNT_KEY(self) -> str:
        """Google Cloud service account key JSON."""
        return self._get_secret('GCP_SERVICE_ACCOUNT_KEY', default='', required_in_production=False)
    
    # ===========================
    # VALIDATION METHODS
    # ===========================
    
    def validate(self, raise_on_error: bool = True) -> bool:
        """Validate all secrets and return True if valid."""
        # Force evaluation of all secrets
        secrets_to_check = [
            'SECRET_KEY', 'JWT_SECRET_KEY', 'DB_PASSWORD',
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
            'EMAIL_HOST_PASSWORD', 'REDIS_URL'
        ]
        
        for secret in secrets_to_check:
            getattr(self, secret, None)
        
        if self.errors and raise_on_error:
            error_msg = "Secret validation failed:\n" + "\n".join(f"  - {e}" for e in self.errors)
            raise SecretValidationError(error_msg)
        
        if self.warnings:
            warning_msg = "Secret validation warnings:\n" + "\n".join(f"  - {w}" for w in self.warnings)
            warnings.warn(warning_msg, UserWarning)
        
        return len(self.errors) == 0
    
    def get_validation_report(self) -> Dict[str, List[str]]:
        """Get a detailed validation report."""
        self.validate(raise_on_error=False)
        return {
            'errors': self.errors,
            'warnings': self.warnings,
            'environment': self.environment,
            'is_production': self.is_production,
        }
    
    def check_rotation_needed(self) -> List[str]:
        """Check which secrets might need rotation."""
        rotation_needed = []
        
        # Check if using default or insecure values
        if 'insecure' in self.SECRET_KEY.lower():
            rotation_needed.append("SECRET_KEY contains 'insecure'")
        
        if self.JWT_SECRET_KEY == self.SECRET_KEY:
            rotation_needed.append("JWT_SECRET_KEY is same as SECRET_KEY")
        
        if self.DB_PASSWORD and self.DB_PASSWORD in ['postgres', 'password', '123456']:
            rotation_needed.append("DB_PASSWORD appears to be a default value")
        
        return rotation_needed


# Create a singleton instance
secrets = Secrets()


# ===========================
# SECRET ROTATION HELPERS
# ===========================

def generate_secret_key() -> str:
    """Generate a new Django secret key."""
    from django.core.management.utils import get_random_secret_key
    return get_random_secret_key()


def generate_jwt_key(length: int = 64) -> str:
    """Generate a new JWT secret key."""
    import secrets
    return secrets.token_urlsafe(length)


def rotate_secret(secret_name: str, new_value: str, update_env_file: bool = False) -> None:
    """Rotate a secret value with optional .env file update."""
    if update_env_file:
        env_path = Path(__file__).parent.parent.parent / '.env'
        if env_path.exists():
            # Read current .env file
            with open(env_path, 'r') as f:
                lines = f.readlines()
            
            # Update the secret
            updated = False
            for i, line in enumerate(lines):
                if line.startswith(f"{secret_name}="):
                    lines[i] = f"{secret_name}={new_value}\n"
                    updated = True
                    break
            
            # If not found, append it
            if not updated:
                lines.append(f"\n{secret_name}={new_value}\n")
            
            # Write back
            with open(env_path, 'w') as f:
                f.writelines(lines)
    
    # Update the cached value
    secrets._cache[secret_name] = new_value


# ===========================
# DJANGO SETTINGS INTEGRATION
# ===========================

def get_database_config() -> Dict[str, Any]:
    """Get database configuration with advanced connection pooling."""
    if secrets.DATABASE_URL:
        import dj_database_url
        config_dict = dj_database_url.parse(secrets.DATABASE_URL)
        
        # Enhance parsed config with connection pooling
        config_dict.update(_get_connection_pool_options())
        return config_dict
    
    base_config = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': secrets.DB_NAME,
        'USER': secrets.DB_USER,
        'PASSWORD': secrets.DB_PASSWORD,
        'HOST': secrets.DB_HOST,
        'PORT': secrets.DB_PORT,
    }
    
    # Add connection pooling options
    base_config.update(_get_connection_pool_options())
    return base_config


def _get_connection_pool_options() -> Dict[str, Any]:
    """Get advanced connection pooling options."""
    return {
        # Connection Persistence
        'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=600, cast=int),  # 10 minutes
        'CONN_HEALTH_CHECKS': config('DB_CONN_HEALTH_CHECKS', default=True, cast=bool),
        
        # PostgreSQL-specific connection pooling options
        'OPTIONS': {
            # SSL Configuration
            'sslmode': config('DB_SSL_MODE', default='prefer'),
            'sslcert': config('DB_SSL_CERT', default=''),
            'sslkey': config('DB_SSL_KEY', default=''),
            'sslrootcert': config('DB_SSL_ROOT_CERT', default=''),
            
            # Connection Pool Configuration
            'MAX_CONNS': config('DB_MAX_CONNECTIONS', default=20, cast=int),
            'MIN_CONNS': config('DB_MIN_CONNECTIONS', default=5, cast=int),
            
            # Connection Timeouts
            'connect_timeout': config('DB_CONNECT_TIMEOUT', default=10, cast=int),
            'application_name': config('DB_APPLICATION_NAME', default='EnterpriseLand'),
            
            # Performance Tuning
            'work_mem': config('DB_WORK_MEM', default='4MB'),
            'shared_preload_libraries': config('DB_SHARED_PRELOAD_LIBS', default=''),
            'effective_cache_size': config('DB_EFFECTIVE_CACHE_SIZE', default='1GB'),
            
            # Connection Pool Settings for PgBouncer compatibility
            'server_reset_query': 'DISCARD ALL',
            'server_check_query': 'SELECT 1',
            
            # Prepared Statement Settings
            'DISABLE_SERVER_SIDE_CURSORS': config('DB_DISABLE_SERVER_CURSORS', default=False, cast=bool),
            'ATOMIC_REQUESTS': config('DB_ATOMIC_REQUESTS', default=True, cast=bool),
            
            # Query Optimization
            'CONN_HEALTH_CHECKS': config('DB_HEALTH_CHECKS', default=True, cast=bool),
            'autocommit': True,
            
            # Monitoring and Logging
            'log_statement': config('DB_LOG_STATEMENT', default='none'),  # none, ddl, mod, all
            'log_min_duration_statement': config('DB_LOG_MIN_DURATION', default=-1, cast=int),
        },
        
        # Test Database Configuration
        'TEST': {
            'NAME': config('DB_TEST_NAME', default=f'test_{secrets.DB_NAME}'),
            'CREATE_DB': config('DB_TEST_CREATE', default=True, cast=bool),
            'CHARSET': 'UTF8',
            'MIGRATE': config('DB_TEST_MIGRATE', default=True, cast=bool),
        }
    }


def get_email_config() -> Dict[str, Any]:
    """Get email configuration from secrets."""
    return {
        'EMAIL_BACKEND': config('EMAIL_BACKEND', 
                               default='django.core.mail.backends.console.EmailBackend'),
        'EMAIL_HOST': config('EMAIL_HOST', default='smtp.gmail.com'),
        'EMAIL_PORT': config('EMAIL_PORT', default=587, cast=int),
        'EMAIL_USE_TLS': config('EMAIL_USE_TLS', default=True, cast=bool),
        'EMAIL_USE_SSL': config('EMAIL_USE_SSL', default=False, cast=bool),
        'EMAIL_HOST_USER': secrets.EMAIL_HOST_USER,
        'EMAIL_HOST_PASSWORD': secrets.EMAIL_HOST_PASSWORD,
        'EMAIL_TIMEOUT': config('EMAIL_TIMEOUT', default=30, cast=int),
        'DEFAULT_FROM_EMAIL': config('DEFAULT_FROM_EMAIL', default='noreply@casaplatform.com'),
        'SERVER_EMAIL': config('SERVER_EMAIL', default='server@casaplatform.com'),
    }


def get_aws_config() -> Dict[str, Any]:
    """Get AWS configuration from secrets."""
    return {
        'AWS_ACCESS_KEY_ID': secrets.AWS_ACCESS_KEY_ID,
        'AWS_SECRET_ACCESS_KEY': secrets.AWS_SECRET_ACCESS_KEY,
        'AWS_STORAGE_BUCKET_NAME': secrets.AWS_STORAGE_BUCKET_NAME,
        'AWS_S3_REGION_NAME': config('AWS_S3_REGION_NAME', default='us-east-1'),
        'AWS_S3_CUSTOM_DOMAIN': config('AWS_S3_CUSTOM_DOMAIN', default=''),
        'AWS_DEFAULT_ACL': config('AWS_DEFAULT_ACL', default='private'),
        'AWS_S3_OBJECT_PARAMETERS': {
            'CacheControl': 'max-age=86400',
        },
        'AWS_S3_FILE_OVERWRITE': config('AWS_S3_FILE_OVERWRITE', default=False, cast=bool),
        'AWS_S3_ENCRYPTION': config('AWS_S3_ENCRYPTION', default='AES256'),
        'AWS_S3_SIGNATURE_VERSION': config('AWS_S3_SIGNATURE_VERSION', default='s3v4'),
    }


def get_celery_config() -> Dict[str, Any]:
    """Get Celery configuration from secrets."""
    broker_url = config('CELERY_BROKER_URL', default=secrets.REDIS_URL)
    result_backend = config('CELERY_RESULT_BACKEND', default=secrets.REDIS_URL)
    
    return {
        'CELERY_BROKER_URL': broker_url,
        'CELERY_RESULT_BACKEND': result_backend,
        'CELERY_ACCEPT_CONTENT': ['json'],
        'CELERY_TASK_SERIALIZER': 'json',
        'CELERY_RESULT_SERIALIZER': 'json',
        'CELERY_WORKER_CONCURRENCY': config('CELERY_WORKER_CONCURRENCY', default=4, cast=int),
        'CELERY_TASK_TIME_LIMIT': config('CELERY_TASK_TIME_LIMIT', default=300, cast=int),
        'CELERY_TASK_SOFT_TIME_LIMIT': config('CELERY_TASK_SOFT_TIME_LIMIT', default=240, cast=int),
    }