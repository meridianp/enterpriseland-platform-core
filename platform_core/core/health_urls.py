
from django.http import JsonResponse
from django.urls import path
from django.db import connection
from django.core.cache import cache
import redis
from decouple import config

def health_check(request):
    """Basic health check endpoint"""
    return JsonResponse({
        'status': 'healthy',
        'service': 'CASA Rule Diligence Platform API',
        'version': '1.0.0'
    })

def detailed_health_check(request):
    """Detailed health check with dependency status"""
    health_status = {
        'status': 'healthy',
        'service': 'CASA Rule Diligence Platform API',
        'version': '1.0.0',
        'checks': {}
    }
    
    # Database check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_status['checks']['database'] = 'healthy'
    except Exception as e:
        health_status['checks']['database'] = f'unhealthy: {str(e)}'
        health_status['status'] = 'unhealthy'
    
    # Redis check (if configured)
    try:
        redis_url = config('CELERY_BROKER_URL', default='')
        if redis_url:
            r = redis.from_url(redis_url)
            r.ping()
            health_status['checks']['redis'] = 'healthy'
        else:
            health_status['checks']['redis'] = 'not configured'
    except Exception as e:
        health_status['checks']['redis'] = f'unhealthy: {str(e)}'
    
    return JsonResponse(health_status)

urlpatterns = [
    path('', health_check, name='health_check'),
    path('detailed/', detailed_health_check, name='detailed_health_check'),
]
