"""
Tests for CDN Integration
"""

import os
import json
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, override_settings
from django.core.files.base import ContentFile
from django.http import HttpRequest, HttpResponse

from platform_core.cdn import (
    CloudflareCDN,
    CloudFrontCDN,
    FastlyCDN,
    MultiCDN,
    CDNStaticStorage,
    CDNMediaStorage,
    CDNMiddleware,
    CDNHeadersMiddleware,
    AssetOptimizer,
    ImageOptimizer,
    CDNManager,
    cdn_manager
)
from platform_core.cdn.utils import (
    should_use_cdn,
    get_asset_version,
    get_cdn_url,
    is_cacheable,
    get_cache_headers
)


class TestCDNProviders(TestCase):
    """Test CDN provider implementations."""
    
    def setUp(self):
        self.cloudflare_config = {
            'base_url': 'https://cdn.example.com/',
            'api_key': 'test-key',
            'zone_id': 'test-zone',
            'enabled': True
        }
        
        self.cloudfront_config = {
            'base_url': 'https://d1234567890.cloudfront.net/',
            'distribution_id': 'E1234567890',
            'aws_access_key': 'test-key',
            'aws_secret_key': 'test-secret',
            'enabled': True
        }
        
        self.fastly_config = {
            'base_url': 'https://test.global.ssl.fastly.net/',
            'service_id': 'test-service',
            'api_key': 'test-key',
            'enabled': True
        }
    
    def test_cloudflare_cdn_get_url(self):
        """Test Cloudflare CDN URL generation."""
        cdn = CloudflareCDN(self.cloudflare_config)
        
        # Test basic URL
        url = cdn.get_url('static/css/style.css')
        self.assertEqual(url, 'https://cdn.example.com/static/css/style.css')
        
        # Test with image optimization
        url = cdn.get_url(
            'images/logo.png',
            optimize_images=True,
            width=300,
            quality=85
        )
        self.assertIn('width=300', url)
        self.assertIn('quality=85', url)
    
    @patch('requests.post')
    def test_cloudflare_cdn_purge(self, mock_post):
        """Test Cloudflare cache purging."""
        mock_post.return_value.status_code = 200
        
        cdn = CloudflareCDN(self.cloudflare_config)
        result = cdn.purge(['static/css/style.css', 'static/js/app.js'])
        
        self.assertTrue(result)
        mock_post.assert_called_once()
        
        # Check API call
        call_args = mock_post.call_args
        self.assertIn('purge_cache', call_args[0][0])
        self.assertEqual(
            call_args[1]['headers']['Authorization'],
            'Bearer test-key'
        )
    
    def test_cloudfront_cdn_get_url(self):
        """Test CloudFront CDN URL generation."""
        cdn = CloudFrontCDN(self.cloudfront_config)
        
        # Test basic URL
        url = cdn.get_url('static/css/style.css')
        self.assertEqual(
            url,
            'https://d1234567890.cloudfront.net/static/css/style.css'
        )
    
    @patch('boto3.client')
    def test_cloudfront_cdn_purge(self, mock_boto3):
        """Test CloudFront invalidation."""
        mock_client = Mock()
        mock_client.create_invalidation.return_value = {
            'ResponseMetadata': {'HTTPStatusCode': 201}
        }
        mock_boto3.return_value = mock_client
        
        cdn = CloudFrontCDN(self.cloudfront_config)
        result = cdn.purge(['/static/*'])
        
        self.assertTrue(result)
        mock_client.create_invalidation.assert_called_once()
    
    def test_fastly_cdn_get_url(self):
        """Test Fastly CDN URL generation."""
        cdn = FastlyCDN(self.fastly_config)
        
        # Test basic URL
        url = cdn.get_url('static/css/style.css')
        self.assertEqual(
            url,
            'https://test.global.ssl.fastly.net/static/css/style.css'
        )
    
    def test_multi_cdn_failover(self):
        """Test Multi-CDN failover strategy."""
        config = {
            'strategy': 'failover',
            'providers': [
                {
                    'type': 'cloudflare',
                    'enabled': False,
                    **self.cloudflare_config
                },
                {
                    'type': 'cloudfront',
                    'enabled': True,
                    **self.cloudfront_config
                }
            ]
        }
        
        cdn = MultiCDN(config)
        url = cdn.get_url('static/css/style.css')
        
        # Should use CloudFront since Cloudflare is disabled
        self.assertIn('cloudfront.net', url)
    
    def test_multi_cdn_round_robin(self):
        """Test Multi-CDN round-robin strategy."""
        config = {
            'strategy': 'round-robin',
            'providers': [
                {'type': 'cloudflare', **self.cloudflare_config},
                {'type': 'fastly', **self.fastly_config}
            ]
        }
        
        cdn = MultiCDN(config)
        
        # First request should use first provider
        url1 = cdn.get_url('test1.css')
        self.assertIn('cdn.example.com', url1)
        
        # Second request should use second provider
        url2 = cdn.get_url('test2.css')
        self.assertIn('fastly.net', url2)
        
        # Third request should wrap around
        url3 = cdn.get_url('test3.css')
        self.assertIn('cdn.example.com', url3)


class TestCDNStorage(TestCase):
    """Test CDN storage backends."""
    
    @override_settings(
        AWS_STORAGE_BUCKET_NAME='test-bucket',
        AWS_S3_REGION_NAME='us-east-1'
    )
    @patch('platform_core.cdn.storage.get_cdn_provider')
    def test_cdn_static_storage_save(self, mock_get_provider):
        """Test CDN static storage save with optimization."""
        mock_provider = Mock()
        mock_provider.is_enabled.return_value = True
        mock_provider.get_url.return_value = 'https://cdn.example.com/test.css'
        mock_get_provider.return_value = mock_provider
        
        storage = CDNStaticStorage()
        storage.optimizer = Mock()
        storage.optimizer.optimize.return_value = ContentFile(b'optimized')
        
        # Mock S3 save
        with patch.object(storage, '_save', return_value='static/test.css'):
            content = ContentFile(b'body { color: red; }')
            name = storage.save('test.css', content)
        
        # Check optimization was called
        storage.optimizer.optimize.assert_called_once()
        
        # Check manifest was updated
        self.assertIn('test.css', storage.manifest)
    
    @patch('platform_core.cdn.storage.get_cdn_provider')
    def test_cdn_static_storage_url(self, mock_get_provider):
        """Test CDN URL generation for static files."""
        mock_provider = Mock()
        mock_provider.is_enabled.return_value = True
        mock_provider.get_url.return_value = 'https://cdn.example.com/test.css'
        mock_get_provider.return_value = mock_provider
        
        storage = CDNStaticStorage()
        url = storage.url('test.css')
        
        self.assertEqual(url, 'https://cdn.example.com/test.css')
        mock_provider.get_url.assert_called_with('test.css')
    
    @patch('platform_core.cdn.storage.get_cdn_provider')
    @patch('platform_core.cdn.storage.Image')
    def test_cdn_media_storage_image_optimization(self, mock_image, mock_get_provider):
        """Test media storage image optimization."""
        mock_provider = Mock()
        mock_get_provider.return_value = mock_provider
        
        # Mock PIL Image
        mock_img = Mock()
        mock_image.open.return_value = mock_img
        
        storage = CDNMediaStorage(optimize_images=True)
        
        # Mock S3 save
        with patch.object(storage, '_save', return_value='media/test.jpg'):
            content = ContentFile(b'fake image data')
            storage.save('test.jpg', content)
        
        # Check image optimization was attempted
        mock_image.open.assert_called_once()


class TestCDNMiddleware(TestCase):
    """Test CDN middleware."""
    
    def setUp(self):
        self.factory = Mock()
        self.mock_provider = Mock()
        self.mock_provider.is_enabled.return_value = True
        self.mock_provider.get_url.side_effect = lambda path: f'https://cdn.example.com/{path}'
    
    @patch('platform_core.cdn.middleware.get_cdn_provider')
    def test_cdn_middleware_url_rewriting(self, mock_get_provider):
        """Test CDN middleware URL rewriting."""
        mock_get_provider.return_value = self.mock_provider
        
        middleware = CDNMiddleware(Mock())
        
        # Create request
        request = HttpRequest()
        request.path = '/page/'
        request.cdn_enabled = True
        
        # Create response with static URLs
        response = HttpResponse(
            b'<img src="/static/img/logo.png">'
            b'<link href="/static/css/style.css">'
        )
        response['Content-Type'] = 'text/html'
        
        # Process response
        processed = middleware.process_response(request, response)
        
        content = processed.content.decode()
        self.assertIn('https://cdn.example.com/img/logo.png', content)
        self.assertIn('https://cdn.example.com/css/style.css', content)
    
    def test_cdn_headers_middleware(self):
        """Test CDN headers middleware."""
        middleware = CDNHeadersMiddleware(Mock())
        
        request = HttpRequest()
        request.path = '/static/css/style.css'
        
        response = HttpResponse()
        processed = middleware.process_response(request, response)
        
        # Check cache headers
        self.assertIn('Cache-Control', processed)
        self.assertIn('max-age=31536000', processed['Cache-Control'])
        self.assertIn('Vary', processed)
        
        # Check security headers
        self.assertEqual(processed['X-Content-Type-Options'], 'nosniff')


class TestCDNOptimization(TestCase):
    """Test asset optimization."""
    
    def test_asset_optimizer_css(self):
        """Test CSS optimization."""
        optimizer = AssetOptimizer()
        
        # Mock csscompressor
        with patch('platform_core.cdn.optimization.csscompressor') as mock_css:
            mock_css.compress.return_value = 'body{color:red}'
            
            content = ContentFile(b'body { color: red; }')
            optimized = optimizer.optimize('style.css', content)
            
            optimized.seek(0)
            self.assertEqual(optimized.read(), b'body{color:red}')
    
    def test_asset_optimizer_js(self):
        """Test JavaScript optimization."""
        optimizer = AssetOptimizer()
        
        # Mock rjsmin
        with patch('platform_core.cdn.optimization.rjsmin') as mock_js:
            mock_js.jsmin.return_value = 'function test(){return true}'
            
            content = ContentFile(b'function test() { return true; }')
            optimized = optimizer.optimize('app.js', content)
            
            optimized.seek(0)
            self.assertEqual(optimized.read(), b'function test(){return true}')
    
    @patch('platform_core.cdn.optimization.Image')
    def test_image_optimizer(self, mock_image):
        """Test image optimization."""
        optimizer = ImageOptimizer()
        
        # Mock PIL Image
        mock_img = Mock()
        mock_img.width = 2000
        mock_img.height = 1500
        mock_img.mode = 'RGB'
        mock_img.format = 'JPEG'
        mock_image.open.return_value = mock_img
        
        content = ContentFile(b'fake image data')
        optimized = optimizer.optimize(content, quality=85, max_size=(1200, 1200))
        
        # Check that thumbnail was called with max size
        mock_img.thumbnail.assert_called_with((1200, 1200), mock_image.Resampling.LANCZOS)
    
    @patch('platform_core.cdn.optimization.Image')
    def test_responsive_image_creation(self, mock_image):
        """Test responsive image version creation."""
        optimizer = ImageOptimizer()
        
        # Mock PIL Image
        mock_img = Mock()
        mock_img.width = 2400
        mock_img.height = 1600
        mock_img.format = 'JPEG'
        mock_image.open.return_value = mock_img
        
        # Mock resize
        mock_img.resize.return_value = mock_img
        
        content = ContentFile(b'fake image data')
        versions = optimizer.create_responsive_versions(content, 'test.jpg')
        
        # Should create multiple versions
        self.assertIn('original', versions)
        self.assertIn('small', versions)
        self.assertIn('medium', versions)
        self.assertIn('large', versions)


class TestCDNManager(TestCase):
    """Test CDN manager."""
    
    def setUp(self):
        self.mock_provider = Mock()
        self.mock_provider.is_enabled.return_value = True
        self.mock_provider.get_url.return_value = 'https://cdn.example.com/test.css'
    
    @patch('platform_core.cdn.manager.get_cdn_provider')
    def test_cdn_manager_get_url(self, mock_get_provider):
        """Test CDN manager URL generation."""
        mock_get_provider.return_value = self.mock_provider
        
        manager = CDNManager()
        url = manager.get_url('static/test.css')
        
        self.assertEqual(url, 'https://cdn.example.com/test.css')
        self.mock_provider.get_url.assert_called_with('static/test.css')
    
    @patch('platform_core.cdn.manager.get_cdn_provider')
    def test_cdn_manager_purge(self, mock_get_provider):
        """Test CDN manager cache purging."""
        self.mock_provider.purge.return_value = True
        mock_get_provider.return_value = self.mock_provider
        
        manager = CDNManager()
        result = manager.purge(['path1', 'path2'])
        
        self.assertTrue(result)
        self.mock_provider.purge.assert_called_with(['path1', 'path2'])
    
    @patch('platform_core.cdn.manager.get_cdn_provider')
    def test_cdn_manager_health_check(self, mock_get_provider):
        """Test CDN manager health check."""
        self.mock_provider.get_stats.return_value = {'requests': 1000}
        mock_get_provider.return_value = self.mock_provider
        
        manager = CDNManager()
        health = manager.health_check()
        
        self.assertEqual(health['status'], 'healthy')
        self.assertTrue(health['provider_enabled'])
        self.assertEqual(health['checks']['url_generation'], 'passed')


class TestCDNUtils(TestCase):
    """Test CDN utilities."""
    
    @override_settings(
        CDN_ENABLED=True,
        CDN_ALLOWED_EXTENSIONS=['.css', '.js', '.jpg']
    )
    def test_should_use_cdn(self):
        """Test CDN usage detection."""
        self.assertTrue(should_use_cdn('/static/css/style.css'))
        self.assertTrue(should_use_cdn('/static/js/app.js'))
        self.assertFalse(should_use_cdn('/api/users/'))
        self.assertFalse(should_use_cdn('/static/data.json'))
    
    def test_get_asset_version(self):
        """Test asset version generation."""
        version = get_asset_version('/static/css/style.css')
        self.assertIsNotNone(version)
        self.assertEqual(len(version), 8)  # Should be 8 character hash
    
    def test_is_cacheable(self):
        """Test cacheable resource detection."""
        self.assertTrue(is_cacheable('/static/css/style.css'))
        self.assertTrue(is_cacheable('/static/img/logo.png'))
        self.assertFalse(is_cacheable('/api/data.json'))
        
        # Test with headers
        headers = {'Cache-Control': 'no-cache'}
        self.assertFalse(is_cacheable('/static/css/style.css', headers))
    
    def test_get_cache_headers(self):
        """Test cache header generation."""
        # CSS should have long cache
        headers = get_cache_headers('/static/css/style.css')
        self.assertIn('max-age=31536000', headers['Cache-Control'])
        
        # PDF should have shorter cache
        headers = get_cache_headers('/docs/report.pdf')
        self.assertIn('max-age=86400', headers['Cache-Control'])


class TestCDNIntegration(TestCase):
    """Test CDN integration scenarios."""
    
    @override_settings(
        CDN_ENABLED=True,
        CDN_PROVIDER_CONFIG={
            'class': 'platform_core.cdn.providers.CloudflareCDN',
            'base_url': 'https://cdn.example.com/',
            'api_key': 'test-key',
            'zone_id': 'test-zone',
            'enabled': True
        }
    )
    @patch('requests.post')
    def test_end_to_end_cdn_workflow(self, mock_post):
        """Test complete CDN workflow."""
        mock_post.return_value.status_code = 200
        
        # Get CDN URL
        url = get_cdn_url('static/css/style.css')
        self.assertEqual(url, 'https://cdn.example.com/static/css/style.css')
        
        # Purge cache
        from platform_core.cdn import purge_cdn_cache
        result = purge_cdn_cache(['static/css/style.css'])
        self.assertTrue(result)
        
        # Check manager stats
        stats = cdn_manager.get_stats()
        self.assertIn('usage', stats)