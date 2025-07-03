"""
CDN Storage Backends

Django storage backends for CDN integration.
"""

import os
import json
import hashlib
from typing import Optional, Dict, Any
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
from django.conf import settings
from django.utils.encoding import filepath_to_uri
from django.utils.functional import cached_property
from storages.backends.s3boto3 import S3Boto3Storage
import logging

from .providers import get_cdn_provider
from .optimization import AssetOptimizer

logger = logging.getLogger(__name__)


class CDNStaticStorage(S3Boto3Storage):
    """
    Storage backend for static files with CDN integration.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cdn_provider = get_cdn_provider()
        self.asset_optimizer = AssetOptimizer()
        self.manifest = {}
        self.manifest_name = 'staticfiles.json'
        
        # Configure for static files
        self.location = kwargs.get('location', 'static')
        self.default_acl = kwargs.get('default_acl', 'public-read')
        self.object_parameters = kwargs.get('object_parameters', {
            'CacheControl': 'max-age=31536000'  # 1 year
        })
    
    def _save(self, name, content):
        """Save file with optimization and CDN integration."""
        # Optimize asset before saving
        if self.should_optimize(name):
            content = self.asset_optimizer.optimize(name, content)
        
        # Add content hash to filename for cache busting
        hashed_name = self.get_hashed_name(name, content)
        
        # Save to S3
        saved_name = super()._save(hashed_name, content)
        
        # Update manifest
        self.manifest[name] = {
            'path': saved_name,
            'hash': self.get_content_hash(content),
            'size': content.size,
            'modified': self.get_modified_time(saved_name)
        }
        
        # Trigger CDN preload
        if self.cdn_provider:
            cdn_url = self.cdn_provider.get_url(saved_name)
            self.cdn_provider.preload([cdn_url])
        
        return saved_name
    
    def url(self, name):
        """Return CDN URL for the file."""
        # Check manifest for hashed name
        if name in self.manifest:
            name = self.manifest[name]['path']
        
        if self.cdn_provider and self.cdn_provider.is_enabled():
            return self.cdn_provider.get_url(name)
        
        # Fallback to S3 URL
        return super().url(name)
    
    def post_process(self, paths, dry_run=False, **options):
        """Post-process static files after collectstatic."""
        if dry_run:
            return
        
        # Process all collected files
        for original_path, (storage, path) in paths.items():
            if not path:
                continue
            
            # Open and optimize file
            with storage.open(path) as original_file:
                content = original_file.read()
            
            # Create optimized version
            if self.should_optimize(path):
                optimized_content = self.asset_optimizer.optimize_content(
                    path, content
                )
                
                # Save optimized version
                optimized_file = ContentFile(optimized_content)
                saved_path = self._save(original_path, optimized_file)
                
                yield original_path, saved_path, True
            else:
                yield original_path, path, False
        
        # Save manifest
        self.save_manifest()
    
    def should_optimize(self, name):
        """Check if file should be optimized."""
        # Optimize CSS, JS, and images
        optimizable_extensions = {'.css', '.js', '.jpg', '.jpeg', '.png', '.gif', '.svg'}
        return any(name.endswith(ext) for ext in optimizable_extensions)
    
    def get_hashed_name(self, name, content):
        """Generate hashed filename for cache busting."""
        content_hash = self.get_content_hash(content)[:12]
        name_parts = name.split('.')
        
        if len(name_parts) > 1:
            # Insert hash before extension
            name_parts[-2] = f"{name_parts[-2]}.{content_hash}"
            return '.'.join(name_parts)
        else:
            # Append hash
            return f"{name}.{content_hash}"
    
    def get_content_hash(self, content):
        """Calculate content hash."""
        hasher = hashlib.md5()
        
        if hasattr(content, 'chunks'):
            for chunk in content.chunks():
                hasher.update(chunk)
        else:
            content.seek(0)
            hasher.update(content.read())
            content.seek(0)
        
        return hasher.hexdigest()
    
    def save_manifest(self):
        """Save manifest file."""
        manifest_content = json.dumps(self.manifest, indent=2)
        self._save(
            self.manifest_name,
            ContentFile(manifest_content.encode('utf-8'))
        )
    
    def load_manifest(self):
        """Load manifest file."""
        try:
            with self.open(self.manifest_name) as manifest_file:
                self.manifest = json.load(manifest_file)
        except:
            self.manifest = {}


class CDNMediaStorage(S3Boto3Storage):
    """
    Storage backend for media files with CDN integration.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cdn_provider = get_cdn_provider()
        
        # Configure for media files
        self.location = kwargs.get('location', 'media')
        self.default_acl = kwargs.get('default_acl', 'private')
        self.object_parameters = kwargs.get('object_parameters', {
            'CacheControl': 'max-age=86400'  # 24 hours
        })
        
        # Image optimization settings
        self.optimize_images = kwargs.get('optimize_images', True)
        self.image_quality = kwargs.get('image_quality', 85)
        self.max_image_size = kwargs.get('max_image_size', (2048, 2048))
    
    def _save(self, name, content):
        """Save media file with optimization."""
        # Optimize images
        if self.optimize_images and self.is_image(name):
            from .optimization import ImageOptimizer
            optimizer = ImageOptimizer()
            content = optimizer.optimize(
                content,
                quality=self.image_quality,
                max_size=self.max_image_size
            )
        
        # Save to S3
        saved_name = super()._save(name, content)
        
        # Purge CDN cache for updated files
        if self.exists(name) and self.cdn_provider:
            self.cdn_provider.purge([saved_name])
        
        return saved_name
    
    def url(self, name):
        """Return CDN URL for media file."""
        if self.cdn_provider and self.cdn_provider.is_enabled():
            # For private files, generate signed URL
            if self.default_acl == 'private':
                return self.cdn_provider.get_url(name, signed=True)
            else:
                return self.cdn_provider.get_url(name)
        
        # Fallback to S3 URL
        return super().url(name)
    
    def get_available_name(self, name, max_length=None):
        """
        Generate unique filename while preserving CDN-friendly structure.
        """
        # Split name into directory and filename
        dir_name, file_name = os.path.split(name)
        name_parts = file_name.split('.')
        
        if len(name_parts) > 1:
            base_name = '.'.join(name_parts[:-1])
            extension = name_parts[-1]
        else:
            base_name = file_name
            extension = ''
        
        # Generate unique suffix
        suffix = hashlib.md5(f"{name}{self.get_modified_time(name)}".encode()).hexdigest()[:8]
        
        # Construct new name
        if extension:
            new_name = f"{base_name}_{suffix}.{extension}"
        else:
            new_name = f"{base_name}_{suffix}"
        
        if dir_name:
            new_name = os.path.join(dir_name, new_name)
        
        # Check max length
        if max_length and len(new_name) > max_length:
            # Truncate base name to fit
            truncate_length = max_length - len(new_name) + len(base_name)
            base_name = base_name[:truncate_length]
            
            if extension:
                new_name = f"{base_name}_{suffix}.{extension}"
            else:
                new_name = f"{base_name}_{suffix}"
            
            if dir_name:
                new_name = os.path.join(dir_name, new_name)
        
        return new_name
    
    def is_image(self, name):
        """Check if file is an image."""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'}
        return any(name.lower().endswith(ext) for ext in image_extensions)


class CDNManifestStorage(CDNStaticStorage):
    """
    Static files storage with manifest for cache busting.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.manifest_version = 2
        self.hashed_files = {}
        self.keep_intermediate_files = False
    
    def post_process(self, paths, dry_run=False, **options):
        """
        Post-process files and create manifest with hashed names.
        """
        if dry_run:
            return
        
        # First pass: optimize and hash files
        hashed_files = {}
        
        for original_path, (storage, path) in paths.items():
            if not path:
                continue
            
            # Process file
            processed_path = path
            
            # Optimize if needed
            if self.should_optimize(path):
                with storage.open(path) as original_file:
                    content = ContentFile(original_file.read())
                
                optimized_content = self.asset_optimizer.optimize(path, content)
                
                # Calculate hash
                content_hash = self.get_content_hash(optimized_content)
                hashed_name = self.get_hashed_name(original_path, optimized_content)
                
                # Save optimized file with hashed name
                self._save(hashed_name, optimized_content)
                processed_path = hashed_name
                
                # Delete intermediate file if configured
                if not self.keep_intermediate_files and path != hashed_name:
                    self.delete(path)
            
            hashed_files[original_path] = processed_path
            yield original_path, processed_path, True
        
        # Second pass: update references in CSS/JS files
        for original_path, hashed_path in hashed_files.items():
            if original_path.endswith(('.css', '.js')):
                self.update_references(hashed_path, hashed_files)
        
        # Save manifest
        self.hashed_files = hashed_files
        self.save_manifest()
    
    def update_references(self, file_path, hashed_files):
        """Update references to other static files in CSS/JS."""
        # Read file content
        with self.open(file_path) as f:
            content = f.read()
        
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        # Update references
        updated = False
        
        for original, hashed in hashed_files.items():
            if original != hashed and original in content:
                content = content.replace(original, hashed)
                updated = True
        
        # Save updated content
        if updated:
            self._save(file_path, ContentFile(content.encode('utf-8')))
    
    def stored_name(self, name):
        """Get stored name from manifest."""
        return self.hashed_files.get(name, name)
    
    def save_manifest(self):
        """Save manifest with hashed files mapping."""
        manifest = {
            'version': self.manifest_version,
            'files': self.hashed_files,
            'paths': {
                name: {
                    'path': hashed,
                    'hash': self.get_file_hash(hashed),
                    'size': self.size(hashed)
                }
                for name, hashed in self.hashed_files.items()
            }
        }
        
        manifest_content = json.dumps(manifest, indent=2)
        self._save(
            'staticfiles.json',
            ContentFile(manifest_content.encode('utf-8'))
        )
    
    def get_file_hash(self, name):
        """Extract hash from hashed filename."""
        # Look for hash pattern in filename
        import re
        match = re.search(r'\.([a-f0-9]{12})\.\w+$', name)
        if match:
            return match.group(1)
        
        # Calculate hash if not in filename
        try:
            with self.open(name) as f:
                return self.get_content_hash(f)[:12]
        except:
            return ''