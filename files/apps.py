"""
Django app configuration for the files module.
"""
from django.apps import AppConfig


class FilesConfig(AppConfig):
    """Configuration for the files app."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'platform_core.files'
    verbose_name = 'Platform Files'