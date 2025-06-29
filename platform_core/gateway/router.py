"""
Gateway Router

Handles request routing, service discovery, and load balancing.
"""

import re
import random
import logging
from typing import Optional, Dict, List, Tuple
from urllib.parse import urljoin, urlparse
from django.core.cache import cache
from django.http import HttpRequest
from django.utils import timezone

from .models import Route, ServiceRegistry, ServiceInstance
from .exceptions import ServiceUnavailable, RouteNotFound, CircuitBreakerOpen

logger = logging.getLogger(__name__)


class ServiceRouter:
    """
    Routes requests to appropriate backend services.
    """
    
    def __init__(self):
        self._route_cache = {}
        self._service_cache = {}
        self._circuit_breakers = {}
    
    def find_route(self, path: str, method: str) -> Optional[Route]:
        """
        Find matching route for request.
        
        Args:
            path: Request path
            method: HTTP method
            
        Returns:
            Matching Route or None
        """
        cache_key = f"route:{method}:{path}"
        
        # Check cache
        route = self._route_cache.get(cache_key)
        if route is not None:
            return route
        
        # Find active routes
        routes = Route.objects.filter(
            is_active=True
        ).select_related('service').order_by('-priority')
        
        for route in routes:
            if route.matches(path, method):
                self._route_cache[cache_key] = route
                return route
        
        return None
    
    def get_service_instance(self, service: ServiceRegistry) -> ServiceInstance:
        """
        Get healthy service instance using load balancing.
        
        Args:
            service: Service to get instance for
            
        Returns:
            Healthy ServiceInstance
            
        Raises:
            ServiceUnavailable: No healthy instances available
        """
        # Check circuit breaker
        if self._is_circuit_open(service):
            raise CircuitBreakerOpen(f"Circuit breaker open for {service.name}")
        
        # Get healthy instances
        instances = list(ServiceInstance.objects.filter(
            service=service,
            is_healthy=True,
            weight__gt=0
        ))
        
        if not instances:
            # Try to get from service URL directly
            if service.is_active and service.is_healthy:
                # Create temporary instance from service base URL
                parsed = urlparse(service.base_url)
                return ServiceInstance(
                    service=service,
                    instance_id='default',
                    host=parsed.hostname,
                    port=parsed.port or (443 if parsed.scheme == 'https' else 80),
                    is_healthy=True
                )
            
            raise ServiceUnavailable(f"No healthy instances for {service.name}")
        
        # Load balancing: weighted random selection
        total_weight = sum(inst.weight for inst in instances)
        if total_weight == 0:
            return random.choice(instances)
        
        # Weighted selection
        rand = random.uniform(0, total_weight)
        current = 0
        
        for instance in instances:
            current += instance.weight
            if rand <= current:
                return instance
        
        return instances[-1]  # Fallback
    
    def build_service_url(self, route: Route, request_path: str, 
                         instance: Optional[ServiceInstance] = None) -> str:
        """
        Build target service URL.
        
        Args:
            route: Route configuration
            request_path: Original request path
            instance: Service instance (optional)
            
        Returns:
            Target service URL
        """
        # Get base URL
        if instance:
            base_url = instance.get_url()
        else:
            base_url = route.service.base_url
        
        # Determine service path
        if route.service_path:
            # Use explicit service path
            service_path = route.service_path
            
            # Replace path parameters
            path_params = self._extract_path_params(route.path, request_path)
            for param, value in path_params.items():
                service_path = service_path.replace(f"{{{param}}}", value)
        else:
            # Use request path
            service_path = request_path
            
            # Strip prefix if configured
            if route.strip_prefix:
                prefix = route.path.split('{')[0].rstrip('/')
                if service_path.startswith(prefix):
                    service_path = service_path[len(prefix):]
        
        # Clean up path
        service_path = service_path.lstrip('/')
        
        # Append slash if configured
        if route.append_slash and not service_path.endswith('/'):
            service_path += '/'
        
        # Build full URL
        return urljoin(base_url, service_path)
    
    def _extract_path_params(self, pattern: str, path: str) -> Dict[str, str]:
        """
        Extract path parameters from request path.
        
        Args:
            pattern: Route path pattern
            path: Actual request path
            
        Returns:
            Dictionary of parameter names to values
        """
        # Convert pattern to regex
        regex_pattern = pattern
        param_names = []
        
        # Find all parameters in pattern
        for match in re.finditer(r'\{(\w+)\}', pattern):
            param_name = match.group(1)
            param_names.append(param_name)
            regex_pattern = regex_pattern.replace(
                match.group(0),
                f'(?P<{param_name}>[^/]+)'
            )
        
        # Match against path
        regex_pattern = f'^{regex_pattern}$'
        match = re.match(regex_pattern, path)
        
        if match:
            return match.groupdict()
        
        return {}
    
    def _is_circuit_open(self, service: ServiceRegistry) -> bool:
        """
        Check if circuit breaker is open for service.
        
        Args:
            service: Service to check
            
        Returns:
            True if circuit is open
        """
        if not service.circuit_breaker_enabled:
            return False
        
        breaker = self._circuit_breakers.get(service.id)
        if not breaker:
            return False
        
        # Check if circuit is open
        if breaker['state'] == 'open':
            # Check if timeout has passed
            if timezone.now() >= breaker['timeout_until']:
                # Try half-open state
                breaker['state'] = 'half-open'
                return False
            return True
        
        return False
    
    def record_failure(self, service: ServiceRegistry):
        """
        Record service failure for circuit breaker.
        
        Args:
            service: Service that failed
        """
        if not service.circuit_breaker_enabled:
            return
        
        breaker = self._circuit_breakers.setdefault(service.id, {
            'failures': 0,
            'state': 'closed',
            'timeout_until': None
        })
        
        breaker['failures'] += 1
        
        # Check if threshold reached
        if breaker['failures'] >= service.circuit_breaker_threshold:
            breaker['state'] = 'open'
            breaker['timeout_until'] = (
                timezone.now() + 
                timezone.timedelta(seconds=service.circuit_breaker_timeout)
            )
            logger.warning(
                f"Circuit breaker opened for {service.name} "
                f"after {breaker['failures']} failures"
            )
    
    def record_success(self, service: ServiceRegistry):
        """
        Record service success for circuit breaker.
        
        Args:
            service: Service that succeeded
        """
        if not service.circuit_breaker_enabled:
            return
        
        breaker = self._circuit_breakers.get(service.id)
        if breaker:
            if breaker['state'] == 'half-open':
                # Success in half-open state closes circuit
                breaker['state'] = 'closed'
                breaker['failures'] = 0
                logger.info(f"Circuit breaker closed for {service.name}")
            elif breaker['state'] == 'closed':
                # Reset failure count on success
                breaker['failures'] = 0
    
    def clear_cache(self):
        """Clear router caches"""
        self._route_cache.clear()
        self._service_cache.clear()


class LoadBalancer:
    """
    Advanced load balancing strategies.
    """
    
    STRATEGIES = {
        'round_robin': 'round_robin_select',
        'random': 'random_select',
        'weighted_random': 'weighted_random_select',
        'least_connections': 'least_connections_select',
        'ip_hash': 'ip_hash_select',
    }
    
    def __init__(self, strategy: str = 'weighted_random'):
        self.strategy = strategy
        self._round_robin_counters = {}
    
    def select_instance(self, instances: List[ServiceInstance], 
                       request: Optional[HttpRequest] = None) -> ServiceInstance:
        """
        Select instance using configured strategy.
        
        Args:
            instances: Available instances
            request: HTTP request (for IP hash)
            
        Returns:
            Selected instance
        """
        if not instances:
            raise ServiceUnavailable("No instances available")
        
        # Get selection method
        method_name = self.STRATEGIES.get(self.strategy, 'weighted_random_select')
        method = getattr(self, method_name)
        
        return method(instances, request)
    
    def round_robin_select(self, instances: List[ServiceInstance], 
                          request: Optional[HttpRequest] = None) -> ServiceInstance:
        """Round-robin selection"""
        service_id = instances[0].service_id
        counter = self._round_robin_counters.get(service_id, 0)
        
        selected = instances[counter % len(instances)]
        self._round_robin_counters[service_id] = counter + 1
        
        return selected
    
    def random_select(self, instances: List[ServiceInstance], 
                     request: Optional[HttpRequest] = None) -> ServiceInstance:
        """Random selection"""
        return random.choice(instances)
    
    def weighted_random_select(self, instances: List[ServiceInstance], 
                              request: Optional[HttpRequest] = None) -> ServiceInstance:
        """Weighted random selection"""
        total_weight = sum(inst.weight for inst in instances)
        if total_weight == 0:
            return self.random_select(instances, request)
        
        rand = random.uniform(0, total_weight)
        current = 0
        
        for instance in instances:
            current += instance.weight
            if rand <= current:
                return instance
        
        return instances[-1]
    
    def least_connections_select(self, instances: List[ServiceInstance], 
                                request: Optional[HttpRequest] = None) -> ServiceInstance:
        """Select instance with least connections"""
        return min(instances, key=lambda i: i.current_connections)
    
    def ip_hash_select(self, instances: List[ServiceInstance], 
                      request: Optional[HttpRequest] = None) -> ServiceInstance:
        """Select based on client IP hash"""
        if not request:
            return self.random_select(instances, request)
        
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Hash IP to select instance
        ip_hash = hash(client_ip)
        index = ip_hash % len(instances)
        
        return instances[index]
    
    def _get_client_ip(self, request: HttpRequest) -> str:
        """Get client IP from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip