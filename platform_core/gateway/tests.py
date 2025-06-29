"""
Tests for API Gateway

Tests gateway routing, transformation, and aggregation features.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from unittest.mock import Mock, patch
import json

from .models import ServiceRegistry, Route, GatewayConfig, APIAggregation
from .router import ServiceRouter, LoadBalancer
from .middleware import GatewayMiddleware
from .transformers import RequestTransformer, ResponseTransformer
from .aggregator import APIAggregator
from .utils import parse_rate_limit, match_path_pattern

User = get_user_model()


class ServiceRouterTests(TestCase):
    """Test service router"""
    
    def setUp(self):
        self.router = ServiceRouter()
        
        # Create test service
        self.service = ServiceRegistry.objects.create(
            name='test-service',
            display_name='Test Service',
            service_type='rest',
            base_url='http://localhost:8001',
            is_active=True,
            is_healthy=True
        )
        
        # Create test routes
        self.route1 = Route.objects.create(
            path='/users/{id}',
            method='GET',
            service=self.service,
            priority=100,
            is_active=True
        )
        
        self.route2 = Route.objects.create(
            path='/users',
            method='POST',
            service=self.service,
            priority=90,
            is_active=True
        )
    
    def test_find_route(self):
        """Test route finding"""
        # Test exact match
        route = self.router.find_route('/users/123', 'GET')
        self.assertEqual(route.id, self.route1.id)
        
        # Test method matching
        route = self.router.find_route('/users', 'POST')
        self.assertEqual(route.id, self.route2.id)
        
        # Test no match
        route = self.router.find_route('/posts', 'GET')
        self.assertIsNone(route)
    
    def test_build_service_url(self):
        """Test service URL building"""
        # Test with path parameter
        url = self.router.build_service_url(self.route1, '/users/123')
        self.assertEqual(url, 'http://localhost:8001/users/123')
        
        # Test with service path
        self.route1.service_path = '/api/v1/users/{id}'
        url = self.router.build_service_url(self.route1, '/users/456')
        self.assertEqual(url, 'http://localhost:8001/api/v1/users/456')
        
        # Test strip prefix
        self.route1.strip_prefix = True
        self.route1.service_path = ''
        url = self.router.build_service_url(self.route1, '/users/789')
        self.assertEqual(url, 'http://localhost:8001/789')
    
    def test_circuit_breaker(self):
        """Test circuit breaker functionality"""
        self.service.circuit_breaker_enabled = True
        self.service.circuit_breaker_threshold = 3
        self.service.save()
        
        # Record failures
        for i in range(3):
            self.router.record_failure(self.service)
        
        # Circuit should be open
        self.assertTrue(self.router._is_circuit_open(self.service))
        
        # Record success
        self.router.record_success(self.service)
        
        # Circuit should still be open (need timeout)
        self.assertTrue(self.router._is_circuit_open(self.service))


class LoadBalancerTests(TestCase):
    """Test load balancer"""
    
    def setUp(self):
        self.service = ServiceRegistry.objects.create(
            name='test-service',
            display_name='Test Service',
            service_type='rest',
            base_url='http://localhost:8001'
        )
        
        # Create test instances
        from .models import ServiceInstance
        self.instances = []
        for i in range(3):
            instance = ServiceInstance.objects.create(
                service=self.service,
                instance_id=f'instance-{i}',
                host=f'host{i}',
                port=8000 + i,
                weight=100 * (i + 1),  # Different weights
                is_healthy=True
            )
            self.instances.append(instance)
    
    def test_round_robin(self):
        """Test round-robin selection"""
        balancer = LoadBalancer('round_robin')
        
        # Should cycle through instances
        selected = []
        for _ in range(6):
            instance = balancer.select_instance(self.instances)
            selected.append(instance.instance_id)
        
        # Check distribution
        self.assertEqual(selected.count('instance-0'), 2)
        self.assertEqual(selected.count('instance-1'), 2)
        self.assertEqual(selected.count('instance-2'), 2)
    
    def test_weighted_random(self):
        """Test weighted random selection"""
        balancer = LoadBalancer('weighted_random')
        
        # Run many selections
        selections = {}
        for _ in range(1000):
            instance = balancer.select_instance(self.instances)
            selections[instance.instance_id] = selections.get(instance.instance_id, 0) + 1
        
        # Higher weight instances should be selected more
        self.assertGreater(
            selections.get('instance-2', 0),
            selections.get('instance-0', 0)
        )
    
    def test_least_connections(self):
        """Test least connections selection"""
        balancer = LoadBalancer('least_connections')
        
        # Set connection counts
        self.instances[0].current_connections = 10
        self.instances[1].current_connections = 5
        self.instances[2].current_connections = 15
        
        # Should select instance with least connections
        instance = balancer.select_instance(self.instances)
        self.assertEqual(instance.instance_id, 'instance-1')


class TransformerTests(TestCase):
    """Test request/response transformers"""
    
    def test_request_json_transform(self):
        """Test JSON request transformation"""
        transformer = RequestTransformer()
        
        # Test field mapping
        data = {'old_field': 'value', 'nested': {'field': 'data'}}
        config = {
            'mapping': {
                'old_field': 'new_field',
                'nested.field': 'flat_field'
            }
        }
        
        result = transformer.transform(data, 'json', config)
        self.assertEqual(result['new_field'], 'value')
        self.assertEqual(result['flat_field'], 'data')
    
    def test_response_json_transform(self):
        """Test JSON response transformation"""
        transformer = ResponseTransformer()
        
        # Test field filtering
        data = {
            'id': 123,
            'name': 'Test',
            'secret': 'hidden',
            'internal': 'private'
        }
        config = {
            'include_fields': ['id', 'name']
        }
        
        result = transformer.transform(data, 'json', config)
        self.assertEqual(result, {'id': 123, 'name': 'Test'})
    
    def test_xml_transform(self):
        """Test XML transformation"""
        transformer = RequestTransformer()
        
        # Test JSON to XML
        data = {'user': {'name': 'Test', 'age': 25}}
        config = {'root_element': 'request'}
        
        result = transformer.transform(data, 'xml', config)
        self.assertIn('<user>', result)
        self.assertIn('<name>Test</name>', result)


class GatewayMiddlewareTests(TestCase):
    """Test gateway middleware"""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = GatewayMiddleware(lambda r: HttpResponse('OK'))
        
        # Create test data
        self.service = ServiceRegistry.objects.create(
            name='api',
            display_name='API Service',
            base_url='http://api:8000',
            is_active=True,
            is_healthy=True
        )
        
        self.route = Route.objects.create(
            path='/test',
            method='GET',
            service=self.service,
            is_active=True
        )
        
        # Create config
        self.config = GatewayConfig.objects.create(
            is_active=True,
            log_requests=True
        )
    
    @patch('requests.Session.request')
    def test_request_forwarding(self, mock_request):
        """Test request forwarding to backend"""
        # Mock backend response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "success"}'
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.text = '{"result": "success"}'
        mock_request.return_value = mock_response
        
        # Make request
        request = self.factory.get('/api/gateway/test')
        request.user = Mock(is_authenticated=True)
        
        response = self.middleware(request)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'success', response.content)
        
        # Check backend was called
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args[0][0], 'GET')
        self.assertEqual(call_args[0][1], 'http://api:8000/test')
    
    def test_authentication_required(self):
        """Test authentication requirement"""
        request = self.factory.get('/api/gateway/test')
        request.user = Mock(is_authenticated=False)
        
        response = self.middleware(request)
        
        self.assertEqual(response.status_code, 401)
    
    def test_maintenance_mode(self):
        """Test maintenance mode"""
        self.config.maintenance_mode = True
        self.config.maintenance_message = 'Under maintenance'
        self.config.save()
        
        request = self.factory.get('/api/gateway/test')
        request.user = Mock(is_authenticated=True)
        
        response = self.middleware(request)
        
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'Under maintenance', response.content)


class APIAggregatorTests(TestCase):
    """Test API aggregator"""
    
    def setUp(self):
        self.aggregator = APIAggregator()
        
        # Create test services
        self.user_service = ServiceRegistry.objects.create(
            name='users',
            display_name='User Service',
            base_url='http://users:8000'
        )
        
        self.order_service = ServiceRegistry.objects.create(
            name='orders',
            display_name='Order Service',
            base_url='http://orders:8000'
        )
        
        # Create aggregation
        self.aggregation = APIAggregation.objects.create(
            name='user-orders',
            aggregation_type='parallel',
            request_path='/user/{user_id}/dashboard',
            request_method='GET',
            service_calls={
                'calls': [
                    {
                        'name': 'user_info',
                        'service': 'users',
                        'path': '/users/{user_id}',
                        'method': 'GET'
                    },
                    {
                        'name': 'user_orders',
                        'service': 'orders',
                        'path': '/orders?user_id={user_id}',
                        'method': 'GET'
                    }
                ]
            },
            merge_responses=True
        )
    
    @patch('requests.Session.request')
    def test_parallel_aggregation(self, mock_request):
        """Test parallel aggregation"""
        # Mock responses
        def side_effect(*args, **kwargs):
            response = Mock()
            if 'users' in args[1]:
                response.json.return_value = {'id': 123, 'name': 'Test User'}
            else:
                response.json.return_value = {'orders': [{'id': 1}, {'id': 2}]}
            response.status_code = 200
            return response
        
        mock_request.side_effect = side_effect
        
        # Create request
        request = Mock()
        request.method = 'GET'
        request.headers = {}
        request.GET = {}
        request.path = '/user/123/dashboard'
        
        # Execute aggregation
        result, status = self.aggregator.execute_aggregation(
            self.aggregation,
            request
        )
        
        # Check result
        self.assertEqual(status, 200)
        self.assertIn('user_info', result['data'])
        self.assertIn('user_orders', result['data'])


class UtilsTests(TestCase):
    """Test utility functions"""
    
    def test_parse_rate_limit(self):
        """Test rate limit parsing"""
        # Test various formats
        self.assertEqual(parse_rate_limit('100/hour'), (100, 3600))
        self.assertEqual(parse_rate_limit('10/minute'), (10, 60))
        self.assertEqual(parse_rate_limit('1000/day'), (1000, 86400))
        
        # Test invalid format
        with self.assertRaises(ValueError):
            parse_rate_limit('invalid')
    
    def test_match_path_pattern(self):
        """Test path pattern matching"""
        # Test simple pattern
        params = match_path_pattern('/users/{id}', '/users/123')
        self.assertEqual(params, {'id': '123'})
        
        # Test multiple parameters
        params = match_path_pattern(
            '/users/{user_id}/posts/{post_id}',
            '/users/456/posts/789'
        )
        self.assertEqual(params, {'user_id': '456', 'post_id': '789'})
        
        # Test no match
        params = match_path_pattern('/users/{id}', '/posts/123')
        self.assertIsNone(params)