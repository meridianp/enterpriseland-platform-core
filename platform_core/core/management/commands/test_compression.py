"""
Management command to test and monitor compression functionality.

Usage:
    python manage.py test_compression
    python manage.py test_compression --benchmark
    python manage.py test_compression --monitor
"""
import gzip
import json
import time
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.test import RequestFactory
from django.http import HttpResponse
from platform_core.core.middleware.compression import CompressionMiddleware

try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False


class Command(BaseCommand):
    help = 'Test and monitor compression functionality'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--benchmark',
            action='store_true',
            help='Run compression benchmarks',
        )
        parser.add_argument(
            '--monitor',
            action='store_true',
            help='Show compression monitoring information',
        )
        parser.add_argument(
            '--size',
            type=int,
            default=10,
            help='Size in KB for test data (default: 10)',
        )
        parser.add_argument(
            '--iterations',
            type=int,
            default=100,
            help='Number of iterations for benchmarks (default: 100)',
        )
    
    def handle(self, *args, **options):
        """Handle the command execution."""
        if options['benchmark']:
            self.run_benchmarks(options)
        elif options['monitor']:
            self.show_monitoring_info()
        else:
            self.run_basic_tests()
    
    def run_basic_tests(self):
        """Run basic compression functionality tests."""
        self.stdout.write(
            self.style.SUCCESS('Running basic compression tests...')
        )
        
        # Test 1: Basic compression functionality
        self.stdout.write('\n1. Testing basic compression functionality')
        success = self.test_basic_compression()
        self.stdout.write(
            self.style.SUCCESS('✓ Passed') if success else self.style.ERROR('✗ Failed')
        )
        
        # Test 2: Content type filtering
        self.stdout.write('\n2. Testing content type filtering')
        success = self.test_content_type_filtering()
        self.stdout.write(
            self.style.SUCCESS('✓ Passed') if success else self.style.ERROR('✗ Failed')
        )
        
        # Test 3: Security exclusions
        self.stdout.write('\n3. Testing security exclusions')
        success = self.test_security_exclusions()
        self.stdout.write(
            self.style.SUCCESS('✓ Passed') if success else self.style.ERROR('✗ Failed')
        )
        
        # Test 4: Brotli support (if available)
        if BROTLI_AVAILABLE:
            self.stdout.write('\n4. Testing Brotli compression')
            success = self.test_brotli_compression()
            self.stdout.write(
                self.style.SUCCESS('✓ Passed') if success else self.style.ERROR('✗ Failed')
            )
        else:
            self.stdout.write(
                self.style.WARNING('\n4. Brotli compression not available (install brotlipy)')
            )
        
        self.stdout.write(self.style.SUCCESS('\nBasic tests completed!'))
    
    def run_benchmarks(self, options):
        """Run compression performance benchmarks."""
        self.stdout.write(
            self.style.SUCCESS('Running compression benchmarks...')
        )
        
        size_kb = options['size']
        iterations = options['iterations']
        
        # Create test data
        test_data = self.create_test_data(size_kb)
        original_size = len(test_data.encode())
        
        self.stdout.write(f'\nTest data: {size_kb}KB ({original_size:,} bytes)')
        self.stdout.write(f'Iterations: {iterations}')
        
        # Benchmark gzip compression
        self.stdout.write('\nBenchmarking Gzip compression:')
        gzip_time, gzip_size, gzip_ratio = self.benchmark_gzip(test_data, iterations)
        self.stdout.write(f'  Time: {gzip_time:.3f}ms average')
        self.stdout.write(f'  Size: {gzip_size:,} bytes')
        self.stdout.write(f'  Ratio: {gzip_ratio:.2f}x')
        
        # Benchmark brotli compression if available
        if BROTLI_AVAILABLE:
            self.stdout.write('\nBenchmarking Brotli compression:')
            brotli_time, brotli_size, brotli_ratio = self.benchmark_brotli(test_data, iterations)
            self.stdout.write(f'  Time: {brotli_time:.3f}ms average')
            self.stdout.write(f'  Size: {brotli_size:,} bytes')
            self.stdout.write(f'  Ratio: {brotli_ratio:.2f}x')
            
            # Compare compression methods
            self.stdout.write('\nComparison:')
            if brotli_size < gzip_size:
                savings = ((gzip_size - brotli_size) / gzip_size) * 100
                self.stdout.write(f'  Brotli saves {savings:.1f}% more space than Gzip')
            
            if brotli_time < gzip_time:
                speed_diff = ((gzip_time - brotli_time) / gzip_time) * 100
                self.stdout.write(f'  Brotli is {speed_diff:.1f}% faster than Gzip')
            else:
                speed_diff = ((brotli_time - gzip_time) / gzip_time) * 100
                self.stdout.write(f'  Gzip is {speed_diff:.1f}% faster than Brotli')
    
    def show_monitoring_info(self):
        """Show compression monitoring and configuration information."""
        self.stdout.write(
            self.style.SUCCESS('Compression Configuration and Monitoring')
        )
        
        # Show current settings
        compression_settings = getattr(settings, 'COMPRESSION_SETTINGS', {})
        
        self.stdout.write('\nCurrent Settings:')
        self.stdout.write(f'  Enabled: {compression_settings.get("ENABLED", "Not set")}')
        self.stdout.write(f'  Min Size: {compression_settings.get("MIN_SIZE", "Not set")} bytes')
        self.stdout.write(f'  Max Size: {compression_settings.get("MAX_SIZE", "Not set")} bytes')
        self.stdout.write(f'  Compression Level: {compression_settings.get("COMPRESSION_LEVEL", "Not set")}')
        self.stdout.write(f'  Brotli Enabled: {compression_settings.get("BROTLI_ENABLED", "Not set")}')
        
        # Show compressible types
        compressible_types = compression_settings.get('COMPRESSIBLE_TYPES', [])
        self.stdout.write(f'\nCompressible Content Types ({len(compressible_types)}):')
        for content_type in compressible_types[:10]:  # Show first 10
            self.stdout.write(f'  - {content_type}')
        if len(compressible_types) > 10:
            self.stdout.write(f'  ... and {len(compressible_types) - 10} more')
        
        # Show excluded paths
        excluded_paths = compression_settings.get('EXCLUDE_PATHS', [])
        self.stdout.write(f'\nExcluded Paths ({len(excluded_paths)}):')
        for path in excluded_paths[:10]:  # Show first 10
            self.stdout.write(f'  - {path}')
        if len(excluded_paths) > 10:
            self.stdout.write(f'  ... and {len(excluded_paths) - 10} more')
        
        # Show middleware status
        middleware_classes = getattr(settings, 'MIDDLEWARE', [])
        compression_middleware = [
            mw for mw in middleware_classes 
            if 'compression' in mw.lower()
        ]
        
        self.stdout.write(f'\nCompression Middleware ({len(compression_middleware)}):')
        for middleware in compression_middleware:
            self.stdout.write(f'  - {middleware}')
        
        # Show system status
        self.stdout.write('\nSystem Status:')
        self.stdout.write(f'  Brotli Available: {BROTLI_AVAILABLE}')
        
        # Test middleware instantiation
        try:
            def dummy_get_response(request):
                return HttpResponse("test")
            middleware = CompressionMiddleware(dummy_get_response)
            self.stdout.write('  Middleware: ✓ Can instantiate')
        except Exception as e:
            self.stdout.write(f'  Middleware: ✗ Error - {e}')
    
    def test_basic_compression(self):
        """Test basic compression functionality."""
        try:
            factory = RequestFactory()
            request = factory.get('/')
            request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
            
            # Create a response that should be compressed
            data = {'test': 'data', 'items': list(range(100))}
            response = HttpResponse(
                json.dumps(data),
                content_type='application/json'
            )
            
            def dummy_get_response(request):
                return response
            middleware = CompressionMiddleware(dummy_get_response)
            processed_response = middleware.process_response(request, response)
            
            return processed_response.get('Content-Encoding') == 'gzip'
        except Exception as e:
            self.stdout.write(f'    Error: {e}')
            return False
    
    def test_content_type_filtering(self):
        """Test that only compressible content types are compressed."""
        try:
            factory = RequestFactory()
            request = factory.get('/')
            request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
            
            # Test compressible type
            response1 = HttpResponse(
                'x' * 1000,
                content_type='text/plain'
            )
            
            # Test non-compressible type
            response2 = HttpResponse(
                b'\x00' * 1000,
                content_type='image/jpeg'
            )
            
            def dummy_get_response(request):
                return response1
            middleware = CompressionMiddleware(dummy_get_response)
            processed1 = middleware.process_response(request, response1)
            processed2 = middleware.process_response(request, response2)
            
            return (
                processed1.get('Content-Encoding') == 'gzip' and
                processed2.get('Content-Encoding') is None
            )
        except Exception as e:
            self.stdout.write(f'    Error: {e}')
            return False
    
    def test_security_exclusions(self):
        """Test that sensitive paths are excluded from compression."""
        try:
            factory = RequestFactory()
            request = factory.post('/api/auth/login/')
            request.META['HTTP_ACCEPT_ENCODING'] = 'gzip'
            
            response = HttpResponse(
                '{"token": "sensitive_data"}',
                content_type='application/json'
            )
            
            def dummy_get_response(request):
                return response
            middleware = CompressionMiddleware(dummy_get_response)
            processed_response = middleware.process_response(request, response)
            
            return processed_response.get('Content-Encoding') is None
        except Exception as e:
            self.stdout.write(f'    Error: {e}')
            return False
    
    def test_brotli_compression(self):
        """Test Brotli compression functionality."""
        try:
            factory = RequestFactory()
            request = factory.get('/')
            request.META['HTTP_ACCEPT_ENCODING'] = 'br, gzip'
            
            data = {'test': 'data', 'items': list(range(100))}
            response = HttpResponse(
                json.dumps(data),
                content_type='application/json'
            )
            
            def dummy_get_response(request):
                return response
            middleware = CompressionMiddleware(dummy_get_response)
            processed_response = middleware.process_response(request, response)
            
            return processed_response.get('Content-Encoding') == 'br'
        except Exception as e:
            self.stdout.write(f'    Error: {e}')
            return False
    
    def create_test_data(self, size_kb):
        """Create test data of approximately the specified size in KB."""
        # Create JSON data that will be approximately size_kb when serialized
        items_needed = (size_kb * 1024) // 50  # Rough estimate
        data = {
            'items': [
                {
                    'id': i,
                    'name': f'Item {i}',
                    'description': f'This is a description for item number {i}',
                    'category': f'Category {i % 10}',
                    'price': round(i * 1.5, 2),
                    'tags': [f'tag{j}' for j in range(i % 5)],
                    'active': i % 2 == 0,
                }
                for i in range(items_needed)
            ],
            'metadata': {
                'total': items_needed,
                'generated_at': '2024-01-01T00:00:00Z',
                'version': '1.0',
            }
        }
        return json.dumps(data)
    
    def benchmark_gzip(self, data, iterations):
        """Benchmark gzip compression."""
        total_time = 0
        compressed_size = 0
        
        for _ in range(iterations):
            start_time = time.time()
            compressed = gzip.compress(data.encode(), compresslevel=6)
            total_time += (time.time() - start_time) * 1000  # Convert to ms
            compressed_size = len(compressed)
        
        avg_time = total_time / iterations
        compression_ratio = len(data.encode()) / compressed_size
        
        return avg_time, compressed_size, compression_ratio
    
    def benchmark_brotli(self, data, iterations):
        """Benchmark brotli compression."""
        total_time = 0
        compressed_size = 0
        
        for _ in range(iterations):
            start_time = time.time()
            compressed = brotli.compress(data.encode(), quality=6)
            total_time += (time.time() - start_time) * 1000  # Convert to ms
            compressed_size = len(compressed)
        
        avg_time = total_time / iterations
        compression_ratio = len(data.encode()) / compressed_size
        
        return avg_time, compressed_size, compression_ratio