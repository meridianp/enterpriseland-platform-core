"""
Core views for the CASA platform.
"""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def csrf_failure(request, reason=""):
    """
    Custom CSRF failure view that returns JSON response.
    
    Args:
        request: The HTTP request
        reason: The reason for CSRF failure
        
    Returns:
        JsonResponse with error details
    """
    return JsonResponse({
        'error': 'CSRF verification failed',
        'reason': reason,
        'detail': 'CSRF token missing or incorrect. Please refresh and try again.'
    }, status=403)