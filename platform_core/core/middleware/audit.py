"""
Audit logging middleware for EnterpriseLand platform.

Provides comprehensive audit logging of user actions, request context,
and system events with minimal performance impact.
"""

import json
import time
import logging
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed
)
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from accounts.models import Group
from platform_core.core.models import AuditLog

User = get_user_model()
logger = logging.getLogger(__name__)

# Thread-local storage for audit context
_audit_context = threading.local()


class AuditContext:
    """
    Thread-local context for audit logging.
    
    Stores request-specific information that can be used
    throughout the request lifecycle for audit logging.
    """
    
    def __init__(self):
        self.user: Optional[User] = None
        self.ip_address: Optional[str] = None
        self.user_agent: Optional[str] = None
        self.group: Optional[Group] = None
        self.request_id: Optional[str] = None
        self.start_time: Optional[float] = None
        self.path: Optional[str] = None
        self.method: Optional[str] = None
        self.status_code: Optional[int] = None
        self.response_time: Optional[float] = None
        self.metadata: Dict[str, Any] = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary for logging."""
        return {
            'user_id': self.user.id if self.user else None,
            'user_email': self.user.email if self.user else None,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'group_id': self.group.id if self.group else None,
            'request_id': self.request_id,
            'path': self.path,
            'method': self.method,
            'status_code': self.status_code,
            'response_time': self.response_time,
            'metadata': self.metadata
        }


def get_audit_context() -> Optional[AuditContext]:
    """Get the current audit context for this thread."""
    return getattr(_audit_context, 'context', None)


def set_audit_context(context: AuditContext) -> None:
    """Set the audit context for this thread."""
    _audit_context.context = context


def clear_audit_context() -> None:
    """Clear the audit context for this thread."""
    if hasattr(_audit_context, 'context'):
        delattr(_audit_context, 'context')


class AuditLoggingMiddleware(MiddlewareMixin):
    """
    Middleware for comprehensive audit logging.
    
    Captures request context, user information, and response details
    for audit trail creation throughout the application.
    """
    
    # Configure which paths to audit
    AUDIT_PATHS = getattr(settings, 'AUDIT_PATHS', ['/api/'])
    EXCLUDE_PATHS = getattr(settings, 'AUDIT_EXCLUDE_PATHS', [
        '/api/health/', '/api/metrics/', '/static/', '/media/',
        '/admin/jsi18n/', '/admin/login/'
    ])
    
    # Configure which methods to audit
    AUDIT_METHODS = getattr(settings, 'AUDIT_METHODS', [
        'POST', 'PUT', 'PATCH', 'DELETE'
    ])
    
    # Performance settings
    AUDIT_ENABLED = getattr(settings, 'AUDIT_LOGGING_ENABLED', True)
    AUDIT_ASYNC = getattr(settings, 'AUDIT_ASYNC_LOGGING', True)
    AUDIT_RESPONSE_TIME_THRESHOLD = getattr(settings, 'AUDIT_RESPONSE_TIME_THRESHOLD', 2.0)
    
    def __init__(self, get_response):
        super().__init__(get_response)
        self.get_response = get_response
        
        # Connect authentication signals
        if self.AUDIT_ENABLED:
            user_logged_in.connect(self._log_user_login, dispatch_uid="audit_login")
            user_logged_out.connect(self._log_user_logout, dispatch_uid="audit_logout")
            user_login_failed.connect(self._log_login_failure, dispatch_uid="audit_login_failed")
    
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Process incoming request and set up audit context."""
        if not self.AUDIT_ENABLED:
            return None
        
        # Check if this request should be audited
        if not self._should_audit_request(request):
            return None
        
        # Create audit context
        context = AuditContext()
        context.user = getattr(request, 'user', None) if hasattr(request, 'user') else None
        context.ip_address = self._get_client_ip(request)
        context.user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]  # Limit length
        context.path = request.path
        context.method = request.method
        context.start_time = time.time()
        context.request_id = self._generate_request_id()
        
        # Get group context
        if context.user and hasattr(context.user, 'groups'):
            context.group = context.user.groups.first()
        
        # Store additional metadata
        context.metadata = {
            'content_type': request.content_type,
            'query_params': dict(request.GET),
            'is_ajax': request.headers.get('X-Requested-With') == 'XMLHttpRequest',
            'is_secure': request.is_secure(),
        }
        
        # Set context for this thread
        set_audit_context(context)
        
        return None
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Process response and log audit information."""
        if not self.AUDIT_ENABLED:
            return response
        
        context = get_audit_context()
        if not context:
            return response
        
        try:
            # Calculate response time
            if context.start_time:
                context.response_time = time.time() - context.start_time
            
            context.status_code = response.status_code
            
            # Log API access for certain conditions
            should_log = (
                context.method in self.AUDIT_METHODS or
                context.status_code >= 400 or
                (context.response_time and context.response_time > self.AUDIT_RESPONSE_TIME_THRESHOLD)
            )
            
            if should_log:
                self._log_api_access(context, response)
        
        except Exception as e:
            logger.error(f"Error in audit logging middleware: {e}")
        
        finally:
            # Clean up context
            clear_audit_context()
        
        return response
    
    def process_exception(self, request: HttpRequest, exception: Exception) -> Optional[HttpResponse]:
        """Log exceptions that occur during request processing."""
        if not self.AUDIT_ENABLED:
            return None
        
        context = get_audit_context()
        if context:
            try:
                self._log_api_error(context, exception)
            except Exception as e:
                logger.error(f"Error logging exception in audit middleware: {e}")
        
        return None
    
    def _should_audit_request(self, request: HttpRequest) -> bool:
        """Determine if a request should be audited."""
        path = request.path
        
        # Check if path is in audit paths
        if self.AUDIT_PATHS:
            if not any(path.startswith(audit_path) for audit_path in self.AUDIT_PATHS):
                return False
        
        # Check if path is excluded
        if any(path.startswith(exclude_path) for exclude_path in self.EXCLUDE_PATHS):
            return False
        
        return True
    
    def _get_client_ip(self, request: HttpRequest) -> Optional[str]:
        """Extract client IP address from request."""
        # Check for forwarded headers (for load balancers/proxies)
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
            return ip
        
        # Check for real IP header
        x_real_ip = request.META.get('HTTP_X_REAL_IP')
        if x_real_ip:
            return x_real_ip.strip()
        
        # Fallback to remote address
        return request.META.get('REMOTE_ADDR')
    
    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def _log_api_access(self, context: AuditContext, response: HttpResponse) -> None:
        """Log API access information."""
        try:
            action = AuditLog.Action.API_ACCESS
            
            # Determine if this was an error
            if context.status_code >= 400:
                action = AuditLog.Action.API_ERROR
            
            metadata = context.to_dict()
            metadata.update({
                'response_size': len(response.content) if hasattr(response, 'content') else 0,
                'content_type': response.get('Content-Type', ''),
            })
            
            if self.AUDIT_ASYNC:
                self._async_create_log(
                    action=action,
                    user=context.user,
                    ip_address=context.ip_address,
                    user_agent=context.user_agent,
                    group=context.group,
                    success=context.status_code < 400,
                    metadata=metadata
                )
            else:
                AuditLog.objects.create_log(
                    action=action,
                    user=context.user,
                    ip_address=context.ip_address,
                    user_agent=context.user_agent,
                    group=context.group,
                    success=context.status_code < 400,
                    metadata=metadata
                )
        
        except Exception as e:
            logger.error(f"Error logging API access: {e}")
    
    def _log_api_error(self, context: AuditContext, exception: Exception) -> None:
        """Log API error information."""
        try:
            metadata = context.to_dict()
            metadata.update({
                'exception_type': exception.__class__.__name__,
                'exception_message': str(exception),
            })
            
            if self.AUDIT_ASYNC:
                self._async_create_log(
                    action=AuditLog.Action.API_ERROR,
                    user=context.user,
                    ip_address=context.ip_address,
                    user_agent=context.user_agent,
                    group=context.group,
                    success=False,
                    error_message=str(exception),
                    metadata=metadata
                )
            else:
                AuditLog.objects.create_log(
                    action=AuditLog.Action.API_ERROR,
                    user=context.user,
                    ip_address=context.ip_address,
                    user_agent=context.user_agent,
                    group=context.group,
                    success=False,
                    error_message=str(exception),
                    metadata=metadata
                )
        
        except Exception as e:
            logger.error(f"Error logging API error: {e}")
    
    def _async_create_log(self, **kwargs) -> None:
        """Create audit log asynchronously using Celery if available."""
        try:
            # Try to use Celery task if available
            from platform_core.core.tasks import create_audit_log_async
            create_audit_log_async.delay(**kwargs)
        except ImportError:
            # Fallback to synchronous logging
            try:
                AuditLog.objects.create_log(**kwargs)
            except Exception as e:
                logger.error(f"Error creating audit log: {e}")
    
    def _log_user_login(self, sender, request, user, **kwargs) -> None:
        """Log successful user login."""
        try:
            context = get_audit_context()
            AuditLog.objects.create_log(
                action=AuditLog.Action.LOGIN,
                user=user,
                ip_address=context.ip_address if context else self._get_client_ip(request),
                user_agent=context.user_agent if context else request.META.get('HTTP_USER_AGENT', ''),
                group=user.groups.first() if user.groups.exists() else None,
                success=True,
                metadata={
                    'login_method': 'django_auth',
                    'session_key': request.session.session_key
                }
            )
        except Exception as e:
            logger.error(f"Error logging user login: {e}")
    
    def _log_user_logout(self, sender, request, user, **kwargs) -> None:
        """Log user logout."""
        try:
            context = get_audit_context()
            AuditLog.objects.create_log(
                action=AuditLog.Action.LOGOUT,
                user=user,
                ip_address=context.ip_address if context else self._get_client_ip(request),
                user_agent=context.user_agent if context else request.META.get('HTTP_USER_AGENT', ''),
                group=user.groups.first() if user.groups.exists() else None,
                success=True,
                metadata={
                    'logout_method': 'django_auth'
                }
            )
        except Exception as e:
            logger.error(f"Error logging user logout: {e}")
    
    def _log_login_failure(self, sender, credentials, request, **kwargs) -> None:
        """Log failed login attempt."""
        try:
            context = get_audit_context()
            # Try to get user by credentials for logging
            user = None
            username = credentials.get('username') or credentials.get('email')
            
            if username:
                try:
                    user = User.objects.get(email=username)
                except User.DoesNotExist:
                    pass
            
            AuditLog.objects.create_log(
                action=AuditLog.Action.LOGIN_FAILED,
                user=user,
                ip_address=context.ip_address if context else self._get_client_ip(request),
                user_agent=context.user_agent if context else request.META.get('HTTP_USER_AGENT', ''),
                group=None,
                success=False,
                metadata={
                    'attempted_username': username,
                    'login_method': 'django_auth',
                    'failure_reason': 'invalid_credentials'
                }
            )
        except Exception as e:
            logger.error(f"Error logging login failure: {e}")


def get_current_user() -> Optional[User]:
    """Get the current user from audit context."""
    context = get_audit_context()
    return context.user if context else None


def get_current_group() -> Optional[Group]:
    """Get the current group from audit context."""
    context = get_audit_context()
    return context.group if context else None


def get_current_ip() -> Optional[str]:
    """Get the current IP address from audit context."""
    context = get_audit_context()
    return context.ip_address if context else None


def log_user_action(
    action: str,
    user: Optional[User] = None,
    content_object: Optional[Any] = None,
    changes: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    **metadata
) -> Optional[AuditLog]:
    """
    Convenience function to log user actions.
    
    Args:
        action: Action that was performed
        user: User who performed the action (defaults to current user)
        content_object: Object that was affected
        changes: Dictionary of changes made
        success: Whether the action was successful
        error_message: Error message if action failed
        **metadata: Additional metadata
        
    Returns:
        Created AuditLog instance or None if logging failed
    """
    try:
        context = get_audit_context()
        
        # Use provided user or get from context
        if not user and context:
            user = context.user
        
        # Get group from context or user
        group = None
        if context:
            group = context.group
        elif user and hasattr(user, 'groups') and user.groups.exists():
            group = user.groups.first()
        
        # Get request context
        ip_address = context.ip_address if context else None
        user_agent = context.user_agent if context else None
        
        # Merge metadata
        full_metadata = {}
        if context:
            full_metadata.update(context.metadata)
        full_metadata.update(metadata)
        
        return AuditLog.objects.create_log(
            action=action,
            user=user,
            content_object=content_object,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent,
            group=group,
            success=success,
            error_message=error_message,
            metadata=full_metadata
        )
    
    except Exception as e:
        logger.error(f"Error logging user action: {e}")
        return None


# Decorator for automatic action logging
def audit_action(action: str, success_message: str = None, error_message: str = None):
    """
    Decorator to automatically log function calls as audit actions.
    
    Args:
        action: Audit action to log
        success_message: Message to log on success
        error_message: Message to log on error
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                log_user_action(
                    action=action,
                    success=True,
                    metadata={
                        'function': func.__name__,
                        'message': success_message or f"{func.__name__} completed successfully"
                    }
                )
                return result
            except Exception as e:
                log_user_action(
                    action=action,
                    success=False,
                    error_message=str(e),
                    metadata={
                        'function': func.__name__,
                        'message': error_message or f"{func.__name__} failed"
                    }
                )
                raise
        return wrapper
    return decorator