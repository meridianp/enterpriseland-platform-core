"""
Comprehensive tests for compression middleware functionality.

Tests cover:
- Basic gzip and brotli compression
- Content type filtering
- Security exclusions
- Performance thresholds
- Conditional compression
- Streaming compression
"""
import gzip
import json
import zlib
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest
from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import override_settings

from platform_core.core.middleware.compression import (
    CompressionMiddleware,
    StreamingCompressionMiddleware,
    ConditionalCompressionMiddleware
)

try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False


class CompressionMiddlewareTestCase(TestCase):
    """Test cases for the main compression middleware."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CompressionMiddleware()
    
    def test_gzip_compression_enabled(self):
        """Test that gzip compression works for compressible content."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip, deflate'
        
        # Create a large JSON response
        data = {'items': [{'id': i, 'name': f'Item {i}'} for i in range(100)]}
        response = HttpResponse(
            json.dumps(data),
            content_type='application/json'
        )
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was applied
        self.assertEqual(processed_response.get('Content-Encoding'), 'gzip')
        self.assertIn('Accept-Encoding', processed_response.get('Vary', ''))
        
        # Verify the content can be decompressed
        compressed_content = processed_response.content
        decompressed_content = gzip.decompress(compressed_content)
        self.assertEqual(decompressed_content.decode(), json.dumps(data))
    
    @pytest.mark.skipif(not BROTLI_AVAILABLE, reason="Brotli not available")
    def test_brotli_compression_preferred(self):
        """Test that brotli is preferred over gzip when available."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip, br'
        
        # Create a large text response
        content = 'This is a test response ' * 50
        response = HttpResponse(content, content_type='text/plain')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that brotli compression was applied
        self.assertEqual(processed_response.get('Content-Encoding'), 'br')
        
        # Verify the content can be decompressed
        compressed_content = processed_response.content
        decompressed_content = brotli.decompress(compressed_content)
        self.assertEqual(decompressed_content.decode(), content)
    
    def test_compression_disabled_for_small_content(self):
        """Test that small content is not compressed."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        # Create a small response
        response = HttpResponse('Small', content_type='text/plain')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))
    
    def test_compression_disabled_for_non_compressible_types(self):
        """Test that non-compressible content types are not compressed."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        # Create a large binary response
        content = b'\x00' * 1000
        response = HttpResponse(content, content_type='image/jpeg')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))
    
    def test_compression_excluded_for_sensitive_paths(self):
        """Test that sensitive paths are excluded from compression."""
        # Test authentication endpoint
        request = self.factory.post('/api/auth/login/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        # Create a large JSON response
        data = {'token': 'sensitive_token_data', 'user': {'id': 1, 'name': 'Test User'}}
        response = HttpResponse(
            json.dumps(data),
            content_type='application/json'
        )
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))
    
    def test_compression_skipped_for_already_compressed(self):
        """Test that already compressed responses are not re-compressed."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        response = HttpResponse('Test content', content_type='text/plain')
        response['Content-Encoding'] = 'gzip'
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied again
        self.assertEqual(processed_response.get('Content-Encoding'), 'gzip')
        self.assertEqual(processed_response.content, b'Test content')
    
    def test_compression_skipped_for_error_responses(self):
        """Test that error responses are not compressed."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        response = HttpResponse('Not Found', status=404, content_type='text/plain')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))
    
    def test_compression_skipped_without_accept_encoding(self):
        """Test that compression is skipped if client doesn't support it."""
        request = self.factory.get('/')
        # No Accept-Encoding header
        
        # Create a large response
        content = 'This is a test response ' * 50
        response = HttpResponse(content, content_type='text/plain')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))
    
    @override_settings(COMPRESSION_SETTINGS={'ENABLED': False})
    def test_compression_disabled_globally(self):
        """Test that compression can be disabled globally."""
        middleware = CompressionMiddleware()
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        # Create a large response
        content = 'This is a test response ' * 50
        response = HttpResponse(content, content_type='text/plain')
        
        # Process the response
        processed_response = middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))


class StreamingCompressionMiddlewareTestCase(TestCase):
    """Test cases for streaming compression middleware."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = StreamingCompressionMiddleware()
    
    def test_streaming_compression_enabled(self):
        """Test that streaming compression works for streaming responses."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        # Create a streaming response
        def generate_content():
            for i in range(10):
                yield f'Line {i}\n'.encode()
        
        response = StreamingHttpResponse(
            generate_content(),
            content_type='text/plain'
        )
        
        # Enable streaming compression for this test
        with override_settings(STREAMING_COMPRESSION_SETTINGS={'ENABLED': True}):
            middleware = StreamingCompressionMiddleware()
            processed_response = middleware.process_response(request, response)
        
        # Check that compression was applied
        self.assertEqual(processed_response.get('Content-Encoding'), 'gzip')
        self.assertIn('Accept-Encoding', processed_response.get('Vary', ''))
        
        # Content-Length should be removed for streaming
        self.assertNotIn('Content-Length', processed_response)
    
    def test_streaming_compression_skipped_for_non_streaming(self):
        """Test that non-streaming responses are not processed."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        response = HttpResponse('Regular response', content_type='text/plain')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))


class ConditionalCompressionMiddlewareTestCase(TestCase):
    """Test cases for conditional compression middleware."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ConditionalCompressionMiddleware()
    
    def test_client_type_detection_mobile(self):
        """Test mobile client detection."""
        request = self.factory.get('/')
        request.META['HTTP_USER_AGENT'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)'
        
        client_type = self.middleware._detect_client_type(request)
        self.assertEqual(client_type, 'mobile')
    
    def test_client_type_detection_bot(self):
        """Test bot client detection."""
        request = self.factory.get('/')
        request.META['HTTP_USER_AGENT'] = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
        
        client_type = self.middleware._detect_client_type(request)
        self.assertEqual(client_type, 'bot')
    
    def test_client_type_detection_desktop(self):
        """Test desktop client detection."""
        request = self.factory.get('/')
        request.META['HTTP_USER_AGENT'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        
        client_type = self.middleware._detect_client_type(request)
        self.assertEqual(client_type, 'desktop')
    
    def test_compression_disabled_for_bots(self):
        """Test that compression can be disabled for bots."""
        request = self.factory.get('/')
        request.META['HTTP_USER_AGENT'] = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
        
        response = HttpResponse('Bot content', content_type='text/html')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that response is unchanged (bot compression disabled by default)
        self.assertEqual(processed_response, response)


class CompressionSecurityTestCase(TestCase):
    """Test cases for compression security features."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CompressionMiddleware()
    
    def test_sensitive_auth_endpoints_excluded(self):
        """Test that authentication endpoints are excluded."""
        sensitive_paths = [
            '/api/auth/login/',
            '/api/auth/register/',
            '/api/auth/password/reset/',
            '/api/users/123/password/',
        ]
        
        for path in sensitive_paths:
            with self.subTest(path=path):
                request = self.factory.post(path)
                request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
                
                response = HttpResponse(
                    '{"sensitive": "data"}',
                    content_type='application/json'
                )
                
                processed_response = self.middleware.process_response(request, response)
                
                # Check that compression was not applied
                self.assertIsNone(processed_response.get('Content-Encoding'))
    
    def test_file_upload_endpoints_excluded(self):
        """Test that file upload endpoints are excluded."""
        request = self.factory.post('/api/files/upload/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        response = HttpResponse(
            '{"file_id": "uploaded_file"}',
            content_type='application/json'
        )
        
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))
    
    def test_admin_endpoints_excluded(self):
        """Test that admin endpoints are excluded."""
        request = self.factory.post('/admin/login/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        response = HttpResponse(
            '<html><body>Admin login</body></html>',
            content_type='text/html'
        )
        
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied
        self.assertIsNone(processed_response.get('Content-Encoding'))


class CompressionPerformanceTestCase(TestCase):
    """Test cases for compression performance features."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CompressionMiddleware()
    
    def test_large_content_compression_limit(self):
        """Test that extremely large content is not compressed."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        # Create content larger than max size (10MB)
        large_content = 'x' * (11 * 1024 * 1024)  # 11MB
        response = HttpResponse(large_content, content_type='text/plain')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # Check that compression was not applied due to size limit
        self.assertIsNone(processed_response.get('Content-Encoding'))
    
    def test_compression_only_for_compressible_content(self):
        """Test that compression is only applied when beneficial."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        # Create content that doesn't compress well (random data)
        import random
        random_content = ''.join(random.choices('0123456789abcdef', k=1000))
        response = HttpResponse(random_content, content_type='text/plain')
        
        # Process the response
        processed_response = self.middleware.process_response(request, response)
        
        # The middleware should only compress if it actually reduces size
        # This test verifies the compression logic includes size checks
        if processed_response.get('Content-Encoding'):
            # If compressed, verify it's actually smaller
            original_size = len(random_content.encode())
            compressed_size = len(processed_response.content)
            self.assertLess(compressed_size, original_size)


class CompressionIntegrationTestCase(TestCase):
    """Integration tests for compression with other middleware."""
    
    def setUp(self):
        self.factory = RequestFactory()
    
    def test_compression_with_cors_headers(self):
        """Test that compression works with CORS headers."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        request.META['HTTP_ORIGIN'] = 'https://example.com'
        
        response = HttpResponse(
            '{"message": "CORS response"}',
            content_type='application/json'
        )
        response['Access-Control-Allow-Origin'] = '*'
        
        middleware = CompressionMiddleware()
        processed_response = middleware.process_response(request, response)
        
        # Check that both compression and CORS headers are present
        self.assertEqual(processed_response.get('Content-Encoding'), 'gzip')
        self.assertEqual(processed_response.get('Access-Control-Allow-Origin'), '*')
    
    def test_compression_preserves_cache_headers(self):
        """Test that compression preserves cache headers."""
        request = self.factory.get('/')
        request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
        
        response = HttpResponse(
            '{"data": "cacheable"}',
            content_type='application/json'
        )
        response['Cache-Control'] = 'max-age=3600'
        response['ETag'] = '"abc123"'
        
        middleware = CompressionMiddleware()
        processed_response = middleware.process_response(request, response)
        
        # Check that compression and cache headers coexist
        self.assertEqual(processed_response.get('Content-Encoding'), 'gzip')
        self.assertEqual(processed_response.get('Cache-Control'), 'max-age=3600')
        self.assertEqual(processed_response.get('ETag'), '"abc123"')


# Helper functions for tests
def create_large_json_response(size_kb=10):
    """Create a large JSON response for testing compression."""
    # Create data that will be approximately size_kb when serialized
    items_needed = (size_kb * 1024) // 50  # Rough estimate
    data = {
        'items': [
            {
                'id': i,
                'name': f'Item {i}',
                'description': f'Description for item {i}',
                'value': i * 1.5
            }
            for i in range(items_needed)
        ]
    }
    return HttpResponse(json.dumps(data), content_type='application/json')


def decompress_gzip(data):
    """Helper to decompress gzip data."""
    return gzip.decompress(data)


def decompress_brotli(data):
    """Helper to decompress brotli data."""
    if not BROTLI_AVAILABLE:
        raise ImportError("Brotli not available")
    return brotli.decompress(data)