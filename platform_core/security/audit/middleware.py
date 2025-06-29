"""
Audit Logging Middleware

Middleware for automatic audit logging of requests and changes.
"""

import time
import uuid
import json
from typing import Dict, Any, Optional
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from django.db.models import Model
from django.contrib.auth.models import AnonymousUser

from .models import APIAccessLog, AuditLog
from .signals import audit_log_created
from ..auth.authentication import get_client_ip


class AuditLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log API access and track request context.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Paths to exclude from logging
        self.exclude_paths = getattr(
            settings, 
            'AUDIT_EXCLUDE_PATHS', 
            ['/health/', '/metrics/', '/static/', '/media/']
        )
        
        # Whether to log request/response bodies
        self.log_request_body = getattr(settings, 'AUDIT_LOG_REQUEST_BODY', False)
        self.log_response_body = getattr(settings, 'AUDIT_LOG_RESPONSE_BODY', False)
        
        # Maximum body size to log (to prevent huge logs)
        self.max_body_size = getattr(settings, 'AUDIT_MAX_BODY_SIZE', 10000)
    
    def process_request(self, request):
        """Process incoming request"""
        # Skip excluded paths
        if any(request.path.startswith(path) for path in self.exclude_paths):
            return None
        
        # Generate request ID for correlation
        request.audit_request_id = str(uuid.uuid4())
        
        # Track request start time
        request.audit_start_time = time.time()
        
        # Store request body if needed
        if self.log_request_body and hasattr(request, 'body'):
            try:
                request.audit_request_body = request.body[:self.max_body_size]
            except:
                request.audit_request_body = b''
        
        return None
    
    def process_response(self, request, response):
        """Process outgoing response and log access"""
        # Skip if no audit context
        if not hasattr(request, 'audit_request_id'):
            return response
        
        # Skip excluded paths
        if any(request.path.startswith(path) for path in self.exclude_paths):
            return response
        
        # Calculate response time
        response_time_ms = int((time.time() - request.audit_start_time) * 1000)
        
        # Get response size
        response_size = len(response.content) if hasattr(response, 'content') else 0
        
        # Create API access log
        try:
            self._create_api_access_log(
                request=request,
                response=response,
                response_time_ms=response_time_ms,
                response_size=response_size
            )
        except Exception as e:
            # Don't let logging errors break the response
            import logging
            logging.error(f"Failed to create API access log: {e}")
        
        return response
    
    def process_exception(self, request, exception):
        """Log exceptions"""
        if hasattr(request, 'audit_request_id'):
            # Log the error
            try:
                self._create_api_access_log(
                    request=request,
                    response=None,
                    response_time_ms=int((time.time() - request.audit_start_time) * 1000),
                    response_size=0,
                    error_message=str(exception)
                )
            except:
                pass
        
        return None
    
    def _create_api_access_log(
        self,
        request,
        response,
        response_time_ms: int,
        response_size: int,
        error_message: str = ''
    ):
        """Create API access log entry"""
        # Get user
        user = None
        if hasattr(request, 'user') and not isinstance(request.user, AnonymousUser):
            user = request.user
        
        # Get authentication method
        auth_method = 'none'
        if user:
            if hasattr(request, 'auth'):
                auth_method = 'jwt'
            elif request.session.get('_auth_user_id'):
                auth_method = 'session'
        
        # Get query params (sanitized)
        query_params = dict(request.GET)
        
        # Remove sensitive params
        sensitive_params = ['password', 'token', 'secret', 'key']
        for param in sensitive_params:
            if param in query_params:
                query_params[param] = '***'
        
        # Create log entry
        APIAccessLog.objects.create(
            method=request.method,
            path=request.path,
            query_params=query_params,
            request_body_size=len(getattr(request, 'audit_request_body', b'')),
            user=user,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            status_code=response.status_code if response else 500,
            response_size=response_size,
            response_time_ms=response_time_ms,
            authentication_method=auth_method,
            rate_limited=getattr(request, 'rate_limited', False),
            error_message=error_message
        )


class ModelAuditMiddleware(MiddlewareMixin):
    """
    Middleware to track model changes in the current request context.
    """
    
    def process_request(self, request):
        """Set up audit context for the request"""
        # Store request context in thread-local storage
        from .utils import set_audit_context
        
        context = {
            'request_id': getattr(request, 'audit_request_id', None),
            'user': getattr(request, 'user', None),
            'ip_address': get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'session_key': request.session.session_key if hasattr(request, 'session') else None
        }
        
        set_audit_context(context)
        
        return None
    
    def process_response(self, request, response):
        """Clear audit context after request"""
        from .utils import clear_audit_context
        clear_audit_context()
        return response
    
    def process_exception(self, request, exception):
        """Clear audit context on exception"""
        from .utils import clear_audit_context
        clear_audit_context()
        return None


class ComplianceLoggingMiddleware(MiddlewareMixin):
    """
    Specialized middleware for compliance-related logging.
    
    Tracks access to sensitive data and ensures compliance requirements.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Models that contain sensitive data
        self.sensitive_models = getattr(
            settings,
            'AUDIT_SENSITIVE_MODELS',
            ['User', 'Contact', 'Assessment']
        )
        
        # Fields that are considered sensitive
        self.sensitive_fields = getattr(
            settings,
            'AUDIT_SENSITIVE_FIELDS',
            ['email', 'phone', 'ssn', 'tax_id', 'bank_account']
        )
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        """Track which view is being accessed"""
        # Store view information for later use
        request.audit_view_name = f"{view_func.__module__}.{view_func.__name__}"
        return None
    
    def process_template_response(self, request, response):
        """Track sensitive data in template context"""
        if hasattr(response, 'context_data'):
            self._check_sensitive_data_access(request, response.context_data)
        
        return response
    
    def _check_sensitive_data_access(self, request, context_data: Dict[str, Any]):
        """Check if sensitive data is being accessed"""
        from .models import DataAccessLog
        
        # Skip if no user
        if not hasattr(request, 'user') or request.user.is_anonymous:
            return
        
        # Check for sensitive model instances in context
        for key, value in context_data.items():
            if isinstance(value, Model):
                model_name = value.__class__.__name__
                
                if model_name in self.sensitive_models:
                    # Log sensitive data access
                    fields_accessed = []
                    
                    # Check which fields are being accessed
                    # This is simplified - in production, use field tracking
                    for field in value._meta.fields:
                        if field.name in self.sensitive_fields:
                            fields_accessed.append(field.name)
                    
                    if fields_accessed:
                        DataAccessLog.objects.create(
                            user=request.user,
                            model_name=model_name,
                            record_id=str(value.pk),
                            fields_accessed=fields_accessed,
                            access_type='view',
                            ip_address=get_client_ip(request),
                            group=getattr(request.user, 'group', None)
                        )