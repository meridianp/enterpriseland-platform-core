"""
Platform Core Files App

Provides generic file storage and management capabilities for the platform.

Features:
- Secure file upload/download with access control
- S3 and local storage support
- File metadata and categorization
- Automatic virus scanning (when configured)
- File versioning support
- Temporary URL generation for secure downloads
"""

default_app_config = 'platform_core.files.apps.FilesConfig'