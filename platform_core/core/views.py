"""
Core views for the CASA platform.
"""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response


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


class PlatformViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet for platform models with common functionality.
    """
    def get_serializer_context(self):
        """Add request and group to serializer context."""
        context = super().get_serializer_context()
        if hasattr(self.request, 'user') and self.request.user.is_authenticated:
            context['group'] = getattr(self.request.user, 'group', None)
        return context