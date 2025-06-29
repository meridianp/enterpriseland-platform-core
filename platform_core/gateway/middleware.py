"""
Gateway Middleware

Intercepts requests and forwards them to backend services.
"""

import json
import logging
import time
from typing import Dict, Any, Optional
from django.http import HttpResponse, JsonResponse, HttpRequest
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from .router import ServiceRouter, LoadBalancer
from .models import GatewayConfig, Route
from .exceptions import GatewayException, ServiceUnavailable, RouteNotFound
from .transformers import RequestTransformer, ResponseTransformer
from .utils import get_client_ip, parse_rate_limit
from platform_core.security.audit.models import APIAccessLog

logger = logging.getLogger(__name__)


class GatewayMiddleware(MiddlewareMixin):
    """
    Main gateway middleware that intercepts and routes requests.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.router = ServiceRouter()
        self.load_balancer = LoadBalancer()
        self.request_transformer = RequestTransformer()
        self.response_transformer = ResponseTransformer()
        
        # HTTP session with retry
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Load configuration
        self.config = self._load_config()
    
    def __call__(self, request):
        # Check if this is a gateway request
        if not self._is_gateway_request(request):
            return self.get_response(request)
        
        # Check maintenance mode
        if self.config.maintenance_mode:
            return JsonResponse({
                'error': 'Service Unavailable',
                'message': self.config.maintenance_message or 'System maintenance in progress'
            }, status=503)
        
        start_time = time.time()
        
        try:
            # Route request
            response = self._handle_gateway_request(request)
            
            # Log access
            if self.config.log_requests:
                self._log_access(request, response, time.time() - start_time)
            
            return response
            
        except GatewayException as e:
            logger.error(f"Gateway error: {e}")
            return JsonResponse({
                'error': e.__class__.__name__,
                'message': str(e)
            }, status=e.status_code)
            
        except Exception as e:
            logger.exception("Unexpected gateway error")
            return JsonResponse({
                'error': 'Internal Server Error',
                'message': 'An unexpected error occurred'
            }, status=500)
    
    def _is_gateway_request(self, request: HttpRequest) -> bool:
        """Check if request should be handled by gateway"""
        # Check if path starts with gateway prefix
        gateway_prefix = getattr(settings, 'GATEWAY_URL_PREFIX', '/api/gateway/')
        return request.path.startswith(gateway_prefix)
    
    def _handle_gateway_request(self, request: HttpRequest) -> HttpResponse:
        """Handle gateway request"""
        # Remove gateway prefix from path
        gateway_prefix = getattr(settings, 'GATEWAY_URL_PREFIX', '/api/gateway/')
        path = request.path[len(gateway_prefix):] if request.path.startswith(gateway_prefix) else request.path
        
        # Find route
        route = self.router.find_route(path, request.method)
        if not route:
            raise RouteNotFound(f"No route found for {request.method} {path}")
        
        # Check authentication if required
        if route.auth_required and not request.user.is_authenticated:
            return JsonResponse({
                'error': 'Unauthorized',
                'message': 'Authentication required'
            }, status=401)
        
        # Get service instance
        instance = self.router.get_service_instance(route.service)
        
        # Build target URL
        target_url = self.router.build_service_url(route, path, instance)
        
        # Transform request
        headers, data = self._prepare_request(request, route)
        
        # Make request to backend service
        try:
            backend_response = self._make_backend_request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=data,
                params=request.GET.dict(),
                timeout=route.service.timeout,
                route=route
            )
            
            # Record success
            self.router.record_success(route.service)
            
            # Transform response
            return self._prepare_response(backend_response, route)
            
        except Exception as e:
            # Record failure
            self.router.record_failure(route.service)
            raise
    
    def _prepare_request(self, request: HttpRequest, route: Route) -> tuple:
        """
        Prepare request for backend service.
        
        Returns:
            Tuple of (headers, data)
        """
        # Copy headers
        headers = {}
        for key, value in request.headers.items():
            # Skip hop-by-hop headers
            if key.lower() not in ['connection', 'keep-alive', 'proxy-authenticate',
                                  'proxy-authorization', 'te', 'trailers',
                                  'transfer-encoding', 'upgrade']:
                headers[key] = value
        
        # Add custom headers
        if route.add_request_headers:
            headers.update(route.add_request_headers)
        
        # Remove specified headers
        for header in route.remove_request_headers:
            headers.pop(header, None)
            headers.pop(header.title(), None)
        
        # Add gateway headers
        headers['X-Forwarded-For'] = get_client_ip(request)
        headers['X-Forwarded-Proto'] = request.scheme
        headers['X-Forwarded-Host'] = request.get_host()
        headers['X-Gateway-Route'] = route.path
        
        # Add service API key if configured
        if route.service.api_key:
            headers['Authorization'] = f'Bearer {route.service.api_key}'
        
        # Get request data
        if request.method in ['POST', 'PUT', 'PATCH']:
            if request.content_type == 'application/json':
                try:
                    data = json.loads(request.body)
                except json.JSONDecodeError:
                    data = request.body
            else:
                data = request.body
        else:
            data = None
        
        # Transform request if configured
        if route.transform_request != 'none':
            data = self.request_transformer.transform(
                data,
                route.transform_request,
                route.transform_config
            )
        
        return headers, data
    
    def _make_backend_request(self, method: str, url: str, headers: dict,
                             data: Any, params: dict, timeout: int,
                             route: Route) -> requests.Response:
        """Make request to backend service"""
        # Prepare request kwargs
        kwargs = {
            'headers': headers,
            'params': params,
            'timeout': timeout,
            'allow_redirects': False,
            'verify': getattr(settings, 'GATEWAY_SSL_VERIFY', True)
        }
        
        # Add data for appropriate methods
        if method in ['POST', 'PUT', 'PATCH']:
            if isinstance(data, dict):
                kwargs['json'] = data
            else:
                kwargs['data'] = data
        
        # Make request
        response = self.session.request(method, url, **kwargs)
        
        # Check response
        if response.status_code >= 500:
            raise ServiceUnavailable(
                f"Backend service returned {response.status_code}"
            )
        
        return response
    
    def _prepare_response(self, backend_response: requests.Response, 
                         route: Route) -> HttpResponse:
        """Prepare response for client"""
        # Create Django response
        response = HttpResponse(
            content=backend_response.content,
            status=backend_response.status_code,
            content_type=backend_response.headers.get('Content-Type', 'text/plain')
        )
        
        # Copy headers
        for key, value in backend_response.headers.items():
            # Skip hop-by-hop headers
            if key.lower() not in ['connection', 'keep-alive', 'proxy-authenticate',
                                  'proxy-authorization', 'te', 'trailers',
                                  'transfer-encoding', 'upgrade', 'content-encoding',
                                  'content-length']:
                response[key] = value
        
        # Add custom response headers
        if route.add_response_headers:
            for key, value in route.add_response_headers.items():
                response[key] = value
        
        # Remove specified headers
        for header in route.remove_response_headers:
            if header in response:
                del response[header]
        
        # Transform response if configured
        if route.transform_response != 'none':
            try:
                content = json.loads(backend_response.text)
                transformed = self.response_transformer.transform(
                    content,
                    route.transform_response,
                    route.transform_config
                )
                response.content = json.dumps(transformed)
                response['Content-Type'] = 'application/json'
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Response transformation failed: {e}")
        
        return response
    
    def _log_access(self, request: HttpRequest, response: HttpResponse,
                   response_time: float):
        """Log API access"""
        try:
            APIAccessLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                method=request.method,
                path=request.path,
                query_params=dict(request.GET),
                request_headers=dict(request.headers),
                request_body=request.body.decode('utf-8', errors='ignore')[:1000] if self.config.log_request_body else None,
                response_status=response.status_code,
                response_headers=dict(response.items()),
                response_body=response.content.decode('utf-8', errors='ignore')[:1000] if self.config.log_response_body else None,
                response_time=int(response_time * 1000),  # Convert to milliseconds
                ip_address=get_client_ip(request),
                user_agent=request.headers.get('User-Agent', ''),
                service='gateway'
            )
        except Exception as e:
            logger.error(f"Failed to log access: {e}")
    
    def _load_config(self) -> GatewayConfig:
        """Load gateway configuration"""
        try:
            return GatewayConfig.objects.filter(is_active=True).first()
        except:
            # Return default config if none exists
            return GatewayConfig(
                global_timeout=60,
                require_auth_default=True,
                log_requests=True
            )