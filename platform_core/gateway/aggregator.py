"""
API Aggregator

Handles complex API aggregation patterns like scatter-gather,
sequential calls, and conditional execution.
"""

import asyncio
import concurrent.futures
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from django.http import HttpRequest
import requests

from .models import APIAggregation, ServiceRegistry
from .router import ServiceRouter
from .transformers import AggregationTransformer
from .exceptions import AggregationError, ServiceUnavailable

logger = logging.getLogger(__name__)


class APIAggregator:
    """
    Orchestrates multiple API calls and aggregates responses.
    """
    
    def __init__(self):
        self.router = ServiceRouter()
        self.transformer = AggregationTransformer()
        self.session = requests.Session()
        
        # Thread pool for parallel execution
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=10
        )
    
    def execute_aggregation(self, aggregation: APIAggregation, 
                           request: HttpRequest) -> Tuple[Dict[str, Any], int]:
        """
        Execute API aggregation.
        
        Args:
            aggregation: Aggregation configuration
            request: Original HTTP request
            
        Returns:
            Tuple of (response_data, status_code)
        """
        try:
            # Extract parameters from request
            params = self._extract_params(request, aggregation)
            
            # Execute based on aggregation type
            if aggregation.aggregation_type == 'parallel':
                responses = self._execute_parallel(
                    aggregation.service_calls,
                    params,
                    request
                )
            elif aggregation.aggregation_type == 'sequential':
                responses = self._execute_sequential(
                    aggregation.service_calls,
                    params,
                    request
                )
            elif aggregation.aggregation_type == 'conditional':
                responses = self._execute_conditional(
                    aggregation.service_calls,
                    params,
                    request
                )
            elif aggregation.aggregation_type == 'scatter_gather':
                responses = self._execute_scatter_gather(
                    aggregation.service_calls,
                    params,
                    request
                )
            else:
                raise AggregationError(
                    f"Unknown aggregation type: {aggregation.aggregation_type}"
                )
            
            # Check for failures
            failed_calls = [
                name for name, resp in responses.items()
                if isinstance(resp, dict) and resp.get('error')
            ]
            
            if failed_calls and aggregation.fail_fast:
                return {
                    'error': 'Aggregation failed',
                    'failed_services': failed_calls,
                    'details': responses
                }, 500
            
            # Merge responses
            if aggregation.merge_responses:
                result = self.transformer.merge_responses(
                    responses,
                    aggregation.response_template
                )
            else:
                result = responses
            
            # Determine status code
            status_code = 200
            if failed_calls:
                status_code = 207  # Multi-Status
                if not aggregation.partial_response_allowed:
                    status_code = 500
            
            return result, status_code
            
        except Exception as e:
            logger.exception(f"Aggregation error: {e}")
            return {
                'error': 'Aggregation failed',
                'message': str(e)
            }, 500
    
    def _extract_params(self, request: HttpRequest, 
                       aggregation: APIAggregation) -> Dict[str, Any]:
        """Extract parameters from request"""
        params = {
            'method': request.method,
            'headers': dict(request.headers),
            'query': dict(request.GET),
            'body': None,
            'path_params': {}
        }
        
        # Extract body
        if request.method in ['POST', 'PUT', 'PATCH']:
            if request.content_type == 'application/json':
                try:
                    params['body'] = json.loads(request.body)
                except:
                    params['body'] = request.body.decode('utf-8')
            else:
                params['body'] = request.body.decode('utf-8')
        
        # Extract path parameters
        # This would be enhanced with proper path matching
        import re
        pattern = aggregation.request_path.replace('{', '(?P<').replace('}', '>[^/]+)')
        match = re.match(f'^{pattern}$', request.path)
        if match:
            params['path_params'] = match.groupdict()
        
        return params
    
    def _execute_parallel(self, service_calls: Dict[str, Any], 
                         params: Dict[str, Any],
                         request: HttpRequest) -> Dict[str, Any]:
        """Execute service calls in parallel"""
        calls = service_calls.get('calls', [])
        futures = {}
        
        # Submit all calls
        for call_config in calls:
            name = call_config['name']
            future = self.executor.submit(
                self._make_service_call,
                call_config,
                params,
                request,
                {}  # No previous responses in parallel mode
            )
            futures[name] = future
        
        # Collect results
        responses = {}
        for name, future in futures.items():
            try:
                responses[name] = future.result(timeout=30)
            except Exception as e:
                logger.error(f"Service call {name} failed: {e}")
                responses[name] = {
                    'error': str(e),
                    'service': name
                }
        
        return responses
    
    def _execute_sequential(self, service_calls: Dict[str, Any], 
                           params: Dict[str, Any],
                           request: HttpRequest) -> Dict[str, Any]:
        """Execute service calls sequentially"""
        calls = service_calls.get('calls', [])
        responses = {}
        
        for call_config in calls:
            name = call_config['name']
            
            # Check dependencies
            depends_on = call_config.get('depends_on', [])
            for dep in depends_on:
                if dep not in responses or responses[dep].get('error'):
                    responses[name] = {
                        'error': f'Dependency {dep} failed',
                        'service': name
                    }
                    continue
            
            try:
                responses[name] = self._make_service_call(
                    call_config,
                    params,
                    request,
                    responses
                )
            except Exception as e:
                logger.error(f"Service call {name} failed: {e}")
                responses[name] = {
                    'error': str(e),
                    'service': name
                }
                
                # Stop on error if fail_fast
                if call_config.get('fail_fast', True):
                    break
        
        return responses
    
    def _execute_conditional(self, service_calls: Dict[str, Any], 
                            params: Dict[str, Any],
                            request: HttpRequest) -> Dict[str, Any]:
        """Execute service calls conditionally"""
        calls = service_calls.get('calls', [])
        responses = {}
        
        for call_config in calls:
            name = call_config['name']
            
            # Check condition
            condition = call_config.get('condition')
            if condition:
                if not self._evaluate_condition(condition, params, responses):
                    responses[name] = {
                        'skipped': True,
                        'reason': 'Condition not met'
                    }
                    continue
            
            try:
                responses[name] = self._make_service_call(
                    call_config,
                    params,
                    request,
                    responses
                )
            except Exception as e:
                logger.error(f"Service call {name} failed: {e}")
                responses[name] = {
                    'error': str(e),
                    'service': name
                }
        
        return responses
    
    def _execute_scatter_gather(self, service_calls: Dict[str, Any], 
                               params: Dict[str, Any],
                               request: HttpRequest) -> Dict[str, Any]:
        """
        Execute scatter-gather pattern.
        
        Broadcasts request to multiple services and gathers responses.
        """
        scatter_config = service_calls.get('scatter', {})
        gather_config = service_calls.get('gather', {})
        
        # Scatter phase - parallel calls to multiple services
        scatter_services = scatter_config.get('services', [])
        futures = {}
        
        for service_name in scatter_services:
            # Build call config
            call_config = {
                'name': service_name,
                'service': service_name,
                'path': scatter_config.get('path', params.get('path')),
                'method': scatter_config.get('method', params['method']),
                'transform': scatter_config.get('transform', {})
            }
            
            future = self.executor.submit(
                self._make_service_call,
                call_config,
                params,
                request,
                {}
            )
            futures[service_name] = future
        
        # Collect scatter results
        scatter_responses = {}
        for name, future in futures.items():
            try:
                scatter_responses[name] = future.result(timeout=30)
            except Exception as e:
                logger.error(f"Scatter call to {name} failed: {e}")
                scatter_responses[name] = {
                    'error': str(e),
                    'service': name
                }
        
        # Gather phase - aggregate results
        if gather_config:
            gather_method = gather_config.get('method', 'merge')
            
            if gather_method == 'merge':
                # Simple merge
                return scatter_responses
            elif gather_method == 'reduce':
                # Custom reduction
                reducer = gather_config.get('reducer')
                if reducer:
                    return self._apply_reducer(scatter_responses, reducer)
            elif gather_method == 'select':
                # Select best response
                selector = gather_config.get('selector')
                if selector:
                    return self._apply_selector(scatter_responses, selector)
        
        return scatter_responses
    
    def _make_service_call(self, call_config: Dict[str, Any],
                          params: Dict[str, Any],
                          request: HttpRequest,
                          previous_responses: Dict[str, Any]) -> Any:
        """Make a single service call"""
        # Get service
        service_name = call_config['service']
        try:
            service = ServiceRegistry.objects.get(
                name=service_name,
                is_active=True
            )
        except ServiceRegistry.DoesNotExist:
            raise ServiceUnavailable(f"Service {service_name} not found")
        
        # Build URL
        path = call_config.get('path', '')
        
        # Replace placeholders with params
        for key, value in params['path_params'].items():
            path = path.replace(f'{{{key}}}', str(value))
        
        # Replace references to previous responses
        for match in re.finditer(r'\$\{([^}]+)\}', path):
            ref = match.group(1)
            value = self._resolve_reference(ref, previous_responses)
            if value is not None:
                path = path.replace(match.group(0), str(value))
        
        url = service.get_full_url(path)
        
        # Prepare request
        method = call_config.get('method', params['method'])
        headers = params['headers'].copy()
        
        # Add service API key
        if service.api_key:
            headers['Authorization'] = f'Bearer {service.api_key}'
        
        # Prepare body
        body = params.get('body')
        if 'transform' in call_config and body:
            # Apply transformation
            # This would use the transformer
            pass
        
        # Make request
        kwargs = {
            'headers': headers,
            'timeout': service.timeout,
            'allow_redirects': False
        }
        
        if method in ['POST', 'PUT', 'PATCH'] and body:
            if isinstance(body, dict):
                kwargs['json'] = body
            else:
                kwargs['data'] = body
        
        response = self.session.request(method, url, **kwargs)
        
        # Parse response
        if response.headers.get('Content-Type', '').startswith('application/json'):
            try:
                return response.json()
            except:
                return {'status': response.status_code, 'body': response.text}
        else:
            return {'status': response.status_code, 'body': response.text}
    
    def _evaluate_condition(self, condition: Dict[str, Any],
                           params: Dict[str, Any],
                           responses: Dict[str, Any]) -> bool:
        """Evaluate condition for conditional execution"""
        condition_type = condition.get('type', 'simple')
        
        if condition_type == 'simple':
            # Simple field comparison
            field = condition.get('field')
            operator = condition.get('operator', '==')
            value = condition.get('value')
            
            # Get field value
            field_value = None
            if field.startswith('$'):
                # Reference to response
                field_value = self._resolve_reference(field[1:], responses)
            elif field.startswith('@'):
                # Reference to param
                field_value = params.get(field[1:])
            
            # Compare
            if operator == '==':
                return field_value == value
            elif operator == '!=':
                return field_value != value
            elif operator == '>':
                return field_value > value
            elif operator == '<':
                return field_value < value
            elif operator == 'in':
                return field_value in value
            elif operator == 'not_in':
                return field_value not in value
        
        return True
    
    def _resolve_reference(self, ref: str, responses: Dict[str, Any]) -> Any:
        """Resolve reference to previous response"""
        parts = ref.split('.')
        current = responses
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    
    def _apply_reducer(self, responses: Dict[str, Any],
                      reducer: Dict[str, Any]) -> Any:
        """Apply reducer to aggregate responses"""
        reducer_type = reducer.get('type', 'custom')
        
        if reducer_type == 'sum':
            # Sum numeric fields
            field = reducer.get('field')
            total = 0
            for resp in responses.values():
                if isinstance(resp, dict) and field in resp:
                    total += resp[field]
            return {'total': total, 'field': field}
        
        elif reducer_type == 'average':
            # Average numeric fields
            field = reducer.get('field')
            values = []
            for resp in responses.values():
                if isinstance(resp, dict) and field in resp:
                    values.append(resp[field])
            
            if values:
                return {
                    'average': sum(values) / len(values),
                    'field': field,
                    'count': len(values)
                }
        
        elif reducer_type == 'custom':
            # Custom reducer code
            # This would execute custom code safely
            pass
        
        return responses
    
    def _apply_selector(self, responses: Dict[str, Any],
                       selector: Dict[str, Any]) -> Any:
        """Apply selector to choose best response"""
        selector_type = selector.get('type', 'first')
        
        if selector_type == 'first':
            # Return first successful response
            for name, resp in responses.items():
                if isinstance(resp, dict) and not resp.get('error'):
                    return {name: resp}
        
        elif selector_type == 'fastest':
            # Return fastest response (would need timing info)
            pass
        
        elif selector_type == 'custom':
            # Custom selector logic
            pass
        
        return responses