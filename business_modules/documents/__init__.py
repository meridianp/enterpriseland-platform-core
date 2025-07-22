"""
Document Management Module for EnterpriseLand Platform.

This module provides comprehensive document management capabilities including:
- Hierarchical folder structures
- Document versioning with diff tracking
- Full-text search with Elasticsearch
- Granular access control
- Document sharing with expiring links
- Audit trail for all operations
- Document preview and OCR
- Template management
"""

default_app_config = 'business_modules.documents.apps.DocumentsConfig'

__version__ = '1.0.0'