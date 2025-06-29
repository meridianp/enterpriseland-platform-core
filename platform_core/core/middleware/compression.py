"""
Advanced compression middleware for Django with security considerations.

This middleware provides:
- Gzip and Brotli compression support
- Configurable compression for different content types
- Security best practices (avoiding compression for sensitive data)
- Performance optimization with size thresholds
- ETags and cache headers compatibility
"""
import gzip
import re
import zlib
from io import BytesIO
from django.conf import settings
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin
from django.utils.regex_helper import _lazy_re_compile

try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    try:
        import brotlipy as brotli
        BROTLI_AVAILABLE = True
    except ImportError:
        BROTLI_AVAILABLE = False


class CompressionMiddleware(MiddlewareMixin):
    """
    Advanced compression middleware with security considerations.
    
    Features:
    - Supports gzip and brotli compression
    - Configurable minimum size threshold
    - Content-type filtering
    - Security: avoids compressing sensitive endpoints
    - Performance: skips already compressed content
    - Cache-friendly: preserves ETags and cache headers
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        
        # Get compression settings from Django settings
        self.compression_settings = getattr(settings, 'COMPRESSION_SETTINGS', {})
        
        # Default settings
        self.enabled = self.compression_settings.get('ENABLED', True)
        self.min_size = self.compression_settings.get('MIN_SIZE', 200)
        self.max_size = self.compression_settings.get('MAX_SIZE', 10 * 1024 * 1024)  # 10MB
        self.compression_level = self.compression_settings.get('COMPRESSION_LEVEL', 6)
        self.brotli_enabled = self.compression_settings.get('BROTLI_ENABLED', BROTLI_AVAILABLE)
        
        # Content types to compress
        self.compressible_types = self.compression_settings.get('COMPRESSIBLE_TYPES', [
            'text/html',
            'text/css',
            'text/javascript',
            'text/plain',
            'text/xml',
            'application/json',
            'application/javascript',
            'application/xml',
            'application/xhtml+xml',
            'application/rss+xml',
            'application/atom+xml',
            'image/svg+xml',
        ])
        
        # Paths to exclude from compression (security-sensitive)
        self.exclude_paths = self.compression_settings.get('EXCLUDE_PATHS', [
            r'^/api/auth/login/$',
            r'^/api/auth/register/$',
            r'^/api/auth/password/',
            r'^/api/users/.*/password/',
            r'^/admin/login/',
            r'^/api/files/upload/',  # Large file uploads
        ])
        
        # Content encodings that are already compressed
        self.compressed_encodings = ['gzip', 'br', 'compress', 'deflate']
        
        # Compile regex patterns
        self.exclude_patterns = [_lazy_re_compile(pattern) for pattern in self.exclude_paths]
    
    def process_response(self, request, response):
        """Process response and apply compression if appropriate."""
        
        # Skip if compression is disabled
        if not self.enabled:
            return response
        
        # Skip if already compressed
        if response.get('Content-Encoding'):
            return response
        
        # Skip if not a successful response
        if response.status_code != 200:
            return response
        
        # Skip if response is too small or too large
        content_length = len(response.content)
        if content_length < self.min_size or content_length > self.max_size:
            return response
        
        # Skip if content type is not compressible
        content_type = response.get('Content-Type', '').split(';')[0].strip().lower()
        if not self._is_compressible_type(content_type):
            return response
        
        # Skip sensitive endpoints
        if self._is_excluded_path(request.path):
            return response
        
        # Skip if client doesn't accept compression
        accept_encoding = request.META.get('HTTP_ACCEPT_ENCODING', '')
        
        # Try brotli first (better compression ratio)
        if self.brotli_enabled and 'br' in accept_encoding:
            compressed_content = self._compress_brotli(response.content)
            if compressed_content:
                response.content = compressed_content
                response['Content-Encoding'] = 'br'
                response['Content-Length'] = str(len(compressed_content))
                patch_vary_headers(response, ('Accept-Encoding',))
                return response
        
        # Fall back to gzip
        if 'gzip' in accept_encoding:
            compressed_content = self._compress_gzip(response.content)
            if compressed_content:
                response.content = compressed_content
                response['Content-Encoding'] = 'gzip'
                response['Content-Length'] = str(len(compressed_content))
                patch_vary_headers(response, ('Accept-Encoding',))
        
        return response
    
    def _is_compressible_type(self, content_type):
        """Check if content type should be compressed."""
        return any(
            content_type.startswith(compressible_type)
            for compressible_type in self.compressible_types
        )
    
    def _is_excluded_path(self, path):
        """Check if path should be excluded from compression."""
        return any(pattern.match(path) for pattern in self.exclude_patterns)
    
    def _compress_gzip(self, content):
        """Compress content using gzip."""
        try:
            buffer = BytesIO()
            with gzip.GzipFile(fileobj=buffer, mode='wb', compresslevel=self.compression_level) as gz_file:
                gz_file.write(content)
            compressed = buffer.getvalue()
            
            # Only return compressed content if it's actually smaller
            if len(compressed) < len(content):
                return compressed
            return None
        except Exception:
            # If compression fails, return None to skip compression
            return None
    
    def _compress_brotli(self, content):
        """Compress content using brotli."""
        if not BROTLI_AVAILABLE:
            return None
        
        try:
            # Brotli compression levels: 0-11 (higher = better compression, slower)
            # Convert gzip level (1-9) to brotli level (0-11)
            brotli_level = min(11, max(0, self.compression_level + 2))
            compressed = brotli.compress(content, quality=brotli_level)
            
            # Only return compressed content if it's actually smaller
            if len(compressed) < len(content):
                return compressed
            return None
        except Exception:
            # If compression fails, return None to skip compression
            return None


class StreamingCompressionMiddleware(MiddlewareMixin):
    """
    Streaming compression middleware for large responses.
    
    This middleware is designed for responses that might be too large
    to compress in memory all at once.
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        
        # Get settings
        self.compression_settings = getattr(settings, 'STREAMING_COMPRESSION_SETTINGS', {})
        self.enabled = self.compression_settings.get('ENABLED', False)  # Disabled by default
        self.chunk_size = self.compression_settings.get('CHUNK_SIZE', 8192)
        self.buffer_size = self.compression_settings.get('BUFFER_SIZE', 64 * 1024)  # 64KB
    
    def process_response(self, request, response):
        """Process streaming response for compression."""
        
        if not self.enabled:
            return response
        
        # Only compress streaming responses
        if not response.streaming:
            return response
        
        # Check if client accepts gzip
        accept_encoding = request.META.get('HTTP_ACCEPT_ENCODING', '')
        if 'gzip' not in accept_encoding:
            return response
        
        # Skip if already compressed
        if response.get('Content-Encoding'):
            return response
        
        # Apply streaming compression
        response.streaming_content = self._compress_streaming(response.streaming_content)
        response['Content-Encoding'] = 'gzip'
        patch_vary_headers(response, ('Accept-Encoding',))
        
        # Remove Content-Length as it's no longer accurate for streaming
        if 'Content-Length' in response:
            del response['Content-Length']
        
        return response
    
    def _compress_streaming(self, streaming_content):
        """Compress streaming content in chunks."""
        compressor = zlib.compressobj(
            level=6,
            method=zlib.DEFLATED,
            wbits=16 + zlib.MAX_WBITS,  # gzip format
            memLevel=8,
            strategy=zlib.Z_DEFAULT_STRATEGY
        )
        
        # Yield gzip header
        yield compressor.compress(b'')
        yield compressor.flush(zlib.Z_SYNC_FLUSH)
        
        # Compress content in chunks
        for chunk in streaming_content:
            if chunk:
                compressed_chunk = compressor.compress(chunk)
                if compressed_chunk:
                    yield compressed_chunk
        
        # Finalize compression
        final_chunk = compressor.flush()
        if final_chunk:
            yield final_chunk


class ConditionalCompressionMiddleware(MiddlewareMixin):
    """
    Conditional compression middleware that respects client preferences
    and server capabilities.
    
    This middleware adds intelligent compression decisions based on:
    - Client capabilities (Accept-Encoding header)
    - Content characteristics (size, type, compressibility)
    - Server load and performance metrics
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        
        self.settings = getattr(settings, 'CONDITIONAL_COMPRESSION_SETTINGS', {})
        self.enabled = self.settings.get('ENABLED', True)
        
        # Performance thresholds
        self.cpu_threshold = self.settings.get('CPU_THRESHOLD', 80)  # Don't compress if CPU > 80%
        self.memory_threshold = self.settings.get('MEMORY_THRESHOLD', 85)  # Don't compress if memory > 85%
        
        # Quality settings based on client
        self.quality_settings = self.settings.get('QUALITY_SETTINGS', {
            'mobile': {'level': 4, 'enabled': True},  # Faster compression for mobile
            'desktop': {'level': 6, 'enabled': True},  # Standard compression
            'bot': {'level': 9, 'enabled': False},     # No compression for bots
        })
    
    def process_response(self, request, response):
        """Apply conditional compression logic."""
        
        if not self.enabled:
            return response
        
        # Detect client type
        client_type = self._detect_client_type(request)
        quality_config = self.quality_settings.get(client_type, self.quality_settings['desktop'])
        
        # Skip compression for bots or if disabled for client type
        if not quality_config.get('enabled', True):
            return response
        
        # Check system resources (simplified - in production you'd use actual metrics)
        if self._should_skip_due_to_load():
            response['X-Compression-Skipped'] = 'High server load'
            return response
        
        # Apply compression with client-specific settings
        compression_level = quality_config.get('level', 6)
        
        # Set compression level in request for other middleware
        request._compression_level = compression_level
        
        return response
    
    def _detect_client_type(self, request):
        """Detect client type from User-Agent."""
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        # Simple client detection
        if any(bot in user_agent for bot in ['bot', 'spider', 'crawler']):
            return 'bot'
        elif any(mobile in user_agent for mobile in ['mobile', 'android', 'iphone']):
            return 'mobile'
        else:
            return 'desktop'
    
    def _should_skip_due_to_load(self):
        """Check if compression should be skipped due to server load."""
        # In a real implementation, you would check actual system metrics
        # For now, this is a placeholder that always returns False
        # You could integrate with monitoring tools like Prometheus, CloudWatch, etc.
        return False