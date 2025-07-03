"""
CDN Asset Optimization

Optimizes static assets for CDN delivery.
"""

import io
import re
import gzip
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from django.core.files.base import ContentFile
from django.conf import settings
import logging

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import csscompressor
except ImportError:
    csscompressor = None

try:
    import rjsmin
except ImportError:
    rjsmin = None

logger = logging.getLogger(__name__)


class AssetOptimizer:
    """Base asset optimizer."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = self.config.get('enabled', True)
        
    def optimize(self, filename: str, content: ContentFile) -> ContentFile:
        """Optimize asset based on type."""
        if not self.enabled:
            return content
        
        # Determine optimization based on file extension
        if self._is_css(filename):
            return self._optimize_css(content)
        elif self._is_js(filename):
            return self._optimize_js(content)
        elif self._is_image(filename):
            return self._optimize_image(filename, content)
        elif self._is_svg(filename):
            return self._optimize_svg(content)
        
        return content
    
    def optimize_content(self, filename: str, content: bytes) -> bytes:
        """Optimize raw content."""
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        file_obj = ContentFile(content)
        optimized = self.optimize(filename, file_obj)
        
        optimized.seek(0)
        return optimized.read()
    
    def _is_css(self, filename: str) -> bool:
        """Check if file is CSS."""
        return filename.lower().endswith('.css')
    
    def _is_js(self, filename: str) -> bool:
        """Check if file is JavaScript."""
        return filename.lower().endswith(('.js', '.mjs'))
    
    def _is_image(self, filename: str) -> bool:
        """Check if file is an image."""
        return any(filename.lower().endswith(ext) for ext in 
                  ['.jpg', '.jpeg', '.png', '.gif', '.webp'])
    
    def _is_svg(self, filename: str) -> bool:
        """Check if file is SVG."""
        return filename.lower().endswith('.svg')
    
    def _optimize_css(self, content: ContentFile) -> ContentFile:
        """Optimize CSS content."""
        if not csscompressor:
            return content
        
        try:
            content.seek(0)
            css_content = content.read()
            
            if isinstance(css_content, bytes):
                css_content = css_content.decode('utf-8')
            
            # Compress CSS
            compressed = csscompressor.compress(css_content)
            
            return ContentFile(compressed.encode('utf-8'))
            
        except Exception as e:
            logger.error(f"CSS optimization failed: {e}")
            return content
    
    def _optimize_js(self, content: ContentFile) -> ContentFile:
        """Optimize JavaScript content."""
        if not rjsmin:
            return content
        
        try:
            content.seek(0)
            js_content = content.read()
            
            if isinstance(js_content, bytes):
                js_content = js_content.decode('utf-8')
            
            # Minify JavaScript
            minified = rjsmin.jsmin(js_content)
            
            return ContentFile(minified.encode('utf-8'))
            
        except Exception as e:
            logger.error(f"JS optimization failed: {e}")
            return content
    
    def _optimize_image(self, filename: str, content: ContentFile) -> ContentFile:
        """Optimize image content."""
        if not Image:
            return content
        
        try:
            content.seek(0)
            img = Image.open(content)
            
            # Convert RGBA to RGB for JPEG
            if filename.lower().endswith(('.jpg', '.jpeg')) and img.mode == 'RGBA':
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[3])
                img = rgb_img
            
            # Optimize
            output = io.BytesIO()
            
            # Determine format and quality
            if filename.lower().endswith(('.jpg', '.jpeg')):
                img.save(output, format='JPEG', optimize=True, quality=85)
            elif filename.lower().endswith('.png'):
                img.save(output, format='PNG', optimize=True)
            elif filename.lower().endswith('.webp'):
                img.save(output, format='WebP', quality=85)
            else:
                img.save(output, format=img.format, optimize=True)
            
            output.seek(0)
            return ContentFile(output.read())
            
        except Exception as e:
            logger.error(f"Image optimization failed: {e}")
            return content
    
    def _optimize_svg(self, content: ContentFile) -> ContentFile:
        """Optimize SVG content."""
        try:
            content.seek(0)
            svg_content = content.read()
            
            if isinstance(svg_content, bytes):
                svg_content = svg_content.decode('utf-8')
            
            # Remove comments
            svg_content = re.sub(r'<!--.*?-->', '', svg_content, flags=re.DOTALL)
            
            # Remove unnecessary whitespace
            svg_content = re.sub(r'\s+', ' ', svg_content)
            svg_content = re.sub(r'>\s+<', '><', svg_content)
            
            return ContentFile(svg_content.encode('utf-8'))
            
        except Exception as e:
            logger.error(f"SVG optimization failed: {e}")
            return content


class ImageOptimizer:
    """Advanced image optimization."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.formats = self.config.get('formats', ['webp', 'original'])
        self.sizes = self.config.get('sizes', [
            (320, 'small'),
            (768, 'medium'),
            (1200, 'large'),
            (2400, 'xlarge')
        ])
        
    def optimize(
        self, 
        content: ContentFile,
        quality: int = 85,
        max_size: Optional[Tuple[int, int]] = None
    ) -> ContentFile:
        """Optimize image with size and quality constraints."""
        if not Image:
            return content
        
        try:
            content.seek(0)
            img = Image.open(content)
            
            # Resize if needed
            if max_size and (img.width > max_size[0] or img.height > max_size[1]):
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Convert to RGB if needed
            if img.mode not in ['RGB', 'L']:
                if img.mode == 'RGBA':
                    # Create white background
                    bg = Image.new('RGB', img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[3])
                    img = bg
                else:
                    img = img.convert('RGB')
            
            # Save optimized
            output = io.BytesIO()
            img.save(output, format='JPEG', optimize=True, quality=quality)
            
            output.seek(0)
            return ContentFile(output.read())
            
        except Exception as e:
            logger.error(f"Image optimization failed: {e}")
            return content
    
    def create_responsive_versions(
        self, 
        content: ContentFile,
        base_name: str
    ) -> Dict[str, ContentFile]:
        """Create multiple sizes for responsive images."""
        if not Image:
            return {'original': content}
        
        versions = {}
        
        try:
            content.seek(0)
            img = Image.open(content)
            
            # Original
            content.seek(0)
            versions['original'] = ContentFile(content.read())
            
            # Create different sizes
            for width, label in self.sizes:
                if img.width > width:
                    # Calculate proportional height
                    ratio = width / img.width
                    height = int(img.height * ratio)
                    
                    # Resize
                    resized = img.resize((width, height), Image.Resampling.LANCZOS)
                    
                    # Save
                    output = io.BytesIO()
                    if 'webp' in self.formats:
                        resized.save(output, format='WebP', quality=85)
                        output.seek(0)
                        versions[f'{label}_webp'] = ContentFile(output.read())
                    
                    output = io.BytesIO()
                    resized.save(output, format=img.format, optimize=True, quality=85)
                    output.seek(0)
                    versions[label] = ContentFile(output.read())
            
        except Exception as e:
            logger.error(f"Responsive image creation failed: {e}")
            content.seek(0)
            versions = {'original': ContentFile(content.read())}
        
        return versions


class CSSOptimizer:
    """Advanced CSS optimization."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.inline_small_images = self.config.get('inline_small_images', True)
        self.max_inline_size = self.config.get('max_inline_size', 4096)  # 4KB
        
    def optimize(self, content: ContentFile) -> ContentFile:
        """Optimize CSS with advanced techniques."""
        try:
            content.seek(0)
            css_content = content.read()
            
            if isinstance(css_content, bytes):
                css_content = css_content.decode('utf-8')
            
            # Remove comments
            css_content = self._remove_comments(css_content)
            
            # Minify
            css_content = self._minify(css_content)
            
            # Optimize colors
            css_content = self._optimize_colors(css_content)
            
            # Optimize units
            css_content = self._optimize_units(css_content)
            
            # Inline small images
            if self.inline_small_images:
                css_content = self._inline_images(css_content)
            
            return ContentFile(css_content.encode('utf-8'))
            
        except Exception as e:
            logger.error(f"CSS optimization failed: {e}")
            return content
    
    def _remove_comments(self, css: str) -> str:
        """Remove CSS comments."""
        # Remove /* */ comments
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
        return css
    
    def _minify(self, css: str) -> str:
        """Minify CSS."""
        if csscompressor:
            return csscompressor.compress(css)
        
        # Basic minification
        css = re.sub(r'\s+', ' ', css)
        css = re.sub(r';\s*}', '}', css)
        css = re.sub(r':\s+', ':', css)
        css = re.sub(r'\s*{\s*', '{', css)
        css = re.sub(r'\s*}\s*', '}', css)
        css = re.sub(r'\s*;\s*', ';', css)
        
        return css.strip()
    
    def _optimize_colors(self, css: str) -> str:
        """Optimize color values."""
        # Convert rgb to hex where shorter
        css = re.sub(
            r'rgb\((\d+),\s*(\d+),\s*(\d+)\)',
            lambda m: '#{:02x}{:02x}{:02x}'.format(
                int(m.group(1)), int(m.group(2)), int(m.group(3))
            ),
            css
        )
        
        # Shorten hex colors
        css = re.sub(r'#([0-9a-f])\1([0-9a-f])\2([0-9a-f])\3', r'#\1\2\3', css, flags=re.I)
        
        return css
    
    def _optimize_units(self, css: str) -> str:
        """Optimize unit values."""
        # Remove unit from 0 values
        css = re.sub(r':0(px|em|rem|%)', ':0', css)
        
        # Remove leading zeros
        css = re.sub(r':0\.(\d+)', r':.\1', css)
        
        return css
    
    def _inline_images(self, css: str) -> str:
        """Inline small images as data URIs."""
        # This would require access to the actual image files
        # For now, just return the CSS unchanged
        return css


class JSOptimizer:
    """Advanced JavaScript optimization."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.preserve_comments = self.config.get('preserve_comments', [])
        
    def optimize(self, content: ContentFile) -> ContentFile:
        """Optimize JavaScript with advanced techniques."""
        try:
            content.seek(0)
            js_content = content.read()
            
            if isinstance(js_content, bytes):
                js_content = js_content.decode('utf-8')
            
            # Preserve important comments
            preserved = self._extract_preserved_comments(js_content)
            
            # Minify
            if rjsmin:
                js_content = rjsmin.jsmin(js_content)
            else:
                js_content = self._basic_minify(js_content)
            
            # Re-add preserved comments
            if preserved:
                js_content = preserved + '\n' + js_content
            
            return ContentFile(js_content.encode('utf-8'))
            
        except Exception as e:
            logger.error(f"JS optimization failed: {e}")
            return content
    
    def _extract_preserved_comments(self, js: str) -> str:
        """Extract comments that should be preserved."""
        preserved = []
        
        # Look for license comments and other important comments
        for pattern in self.preserve_comments:
            matches = re.findall(pattern, js, re.MULTILINE | re.DOTALL)
            preserved.extend(matches)
        
        # Always preserve license comments
        license_pattern = r'/\*[!*][\s\S]*?\*/'
        licenses = re.findall(license_pattern, js)
        preserved.extend(licenses)
        
        return '\n'.join(preserved)
    
    def _basic_minify(self, js: str) -> str:
        """Basic JavaScript minification."""
        # Remove single-line comments
        js = re.sub(r'//.*?$', '', js, flags=re.MULTILINE)
        
        # Remove multi-line comments (except preserved)
        js = re.sub(r'/\*[^!*][\s\S]*?\*/', '', js)
        
        # Remove extra whitespace
        js = re.sub(r'\s+', ' ', js)
        js = re.sub(r'\s*([{}();,:])\s*', r'\1', js)
        
        return js.strip()


class CompressionOptimizer:
    """Handle compression for assets."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.compression_level = self.config.get('compression_level', 9)
        self.min_size = self.config.get('min_size', 1024)  # 1KB
        
    def compress(self, content: bytes) -> Tuple[bytes, bool]:
        """Compress content if beneficial."""
        if len(content) < self.min_size:
            return content, False
        
        try:
            compressed = gzip.compress(content, compresslevel=self.compression_level)
            
            # Only use compressed if smaller
            if len(compressed) < len(content) * 0.9:  # 10% savings
                return compressed, True
            
        except Exception as e:
            logger.error(f"Compression failed: {e}")
        
        return content, False
    
    def decompress(self, content: bytes) -> bytes:
        """Decompress content."""
        try:
            return gzip.decompress(content)
        except:
            return content