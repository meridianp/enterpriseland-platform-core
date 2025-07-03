"""
Health Check Views
"""
from django.http import JsonResponse
from django.views import View
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator

from .checks import health_check_registry
from .probes import check_readiness, check_liveness


@method_decorator(never_cache, name='dispatch')
class HealthCheckView(View):
    """Comprehensive health check endpoint"""
    
    def get(self, request):
        """Return overall health status"""
        results = health_check_registry.run_all_checks()
        
        # Determine HTTP status code
        status_code = 200
        if results['status'].value in ['critical', 'unhealthy']:
            status_code = 503
        
        # Convert to JSON-serializable format
        response_data = {
            'status': results['status'].value,
            'timestamp': results['timestamp'],
            'critical_failure': results['critical_failure'],
            'checks': {}
        }
        
        for name, check_result in results['checks'].items():
            response_data['checks'][name] = {
                'status': check_result.status.value,
                'message': check_result.message,
                'details': check_result.details,
                'duration_ms': check_result.duration_ms,
                'timestamp': check_result.timestamp
            }
        
        return JsonResponse(response_data, status=status_code)


@method_decorator(never_cache, name='dispatch')
class ReadinessProbeView(View):
    """Kubernetes readiness probe endpoint"""
    
    def get(self, request):
        """Check if service is ready to accept traffic"""
        is_ready, details = check_readiness()
        status_code = 200 if is_ready else 503
        
        return JsonResponse(details, status=status_code)


@method_decorator(never_cache, name='dispatch')
class LivenessProbeView(View):
    """Kubernetes liveness probe endpoint"""
    
    def get(self, request):
        """Check if service is alive"""
        is_alive, details = check_liveness()
        status_code = 200 if is_alive else 503
        
        return JsonResponse(details, status=status_code)


@method_decorator(never_cache, name='dispatch')
class HealthDetailView(View):
    """Detailed health check for specific component"""
    
    def get(self, request, check_name):
        """Run specific health check"""
        result = health_check_registry.run_check(check_name)
        
        if not result:
            return JsonResponse(
                {'error': f'Health check {check_name} not found'},
                status=404
            )
        
        # Determine HTTP status code
        status_code = 200
        if result.status.value in ['critical', 'unhealthy']:
            status_code = 503
        
        response_data = {
            'name': result.name,
            'status': result.status.value,
            'message': result.message,
            'details': result.details,
            'duration_ms': result.duration_ms,
            'timestamp': result.timestamp
        }
        
        return JsonResponse(response_data, status=status_code)