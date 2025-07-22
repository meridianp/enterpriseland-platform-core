"""
Base service class for business logic operations.

Provides common functionality for all service classes including
error handling, logging, and transaction management.
"""

import logging
from typing import Any, Dict, Optional, List, Type, TypeVar, Callable
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.contrib.auth import get_user_model
from django.conf import settings

T = TypeVar('T')


class ServiceError(Exception):
    """Base exception for service errors."""
    pass


class ValidationServiceError(ServiceError):
    """Service error for validation failures."""
    pass


class PermissionServiceError(ServiceError):
    """Service error for permission failures."""
    pass


class NotFoundServiceError(ServiceError):
    """Service error for not found resources."""
    pass


class BaseService:
    """
    Base service class providing common functionality.
    
    All business logic services should inherit from this class to get
    consistent error handling, logging, and transaction management.
    
    This is a platform-level base class that provides:
    - User context management
    - Logging infrastructure
    - Transaction management
    - Error handling
    - Permission checking hooks
    - Response standardization
    """
    
    def __init__(self, user: Optional['User'] = None, context: Optional[Dict[str, Any]] = None):
        """
        Initialize service with user context.
        
        Args:
            user: The user performing the operation
            context: Additional context for the operation (e.g., group, tenant, etc.)
        """
        self.user = user
        self.context = context or {}
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
        
        # Extract common context items
        self.group = self.context.get('group')
        self.tenant = self.context.get('tenant')
        self.request = self.context.get('request')
    
    def _log_operation(self, operation: str, details: Optional[Dict[str, Any]] = None, level: str = 'info'):
        """
        Log service operation.
        
        Args:
            operation: Name of the operation
            details: Additional details to log
            level: Logging level (debug, info, warning, error)
        """
        user_info = f"user={self.user.email if self.user else 'anonymous'}"
        context_info = []
        
        # Add context information
        if self.group:
            context_info.append(f"group={getattr(self.group, 'name', self.group)}")
        if self.tenant:
            context_info.append(f"tenant={getattr(self.tenant, 'name', self.tenant)}")
            
        context_str = ", ".join(context_info) if context_info else "no context"
        details_str = f" details={details}" if details else ""
        
        message = f"{operation} - {user_info}, {context_str}{details_str}"
        
        # Log at appropriate level
        log_method = getattr(self.logger, level, self.logger.info)
        log_method(message)
    
    def _check_permission(self, permission: str, obj: Optional[Any] = None) -> bool:
        """
        Check if user has permission for operation.
        
        This is a hook method that should be overridden by subclasses
        to implement specific permission logic.
        
        Args:
            permission: Permission to check
            obj: Object to check permission against
            
        Returns:
            bool: True if user has permission
            
        Raises:
            PermissionServiceError: If user lacks permission
        """
        if not self.user:
            raise PermissionServiceError("Authentication required")
        
        # Default implementation - override in subclasses
        return True
    
    def _validate_context(self, obj: Any) -> None:
        """
        Validate that object is valid within the current context.
        
        This is a hook method that should be overridden by subclasses
        to implement specific context validation (e.g., multi-tenancy).
        
        Args:
            obj: Object to validate
            
        Raises:
            ValidationServiceError: If context validation fails
        """
        # Default implementation - override in subclasses
        pass
    
    @transaction.atomic
    def _execute_with_transaction(self, operation_func: Callable, *args, **kwargs) -> Any:
        """
        Execute operation within a database transaction.
        
        Args:
            operation_func: Function to execute
            *args: Arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Result of operation_func
            
        Raises:
            ServiceError: If operation fails
        """
        try:
            return operation_func(*args, **kwargs)
        except ValidationError as e:
            self._handle_validation_error(e)
        except PermissionDenied as e:
            raise PermissionServiceError(str(e))
        except ServiceError:
            # Re-raise service errors as-is
            raise
        except Exception as e:
            self.logger.error(f"Transaction failed: {str(e)}", exc_info=True)
            raise ServiceError(f"Operation failed: {str(e)}")
    
    def _handle_validation_error(self, error: ValidationError) -> None:
        """
        Handle Django validation errors.
        
        Args:
            error: ValidationError to handle
            
        Raises:
            ValidationServiceError: Converted service error
        """
        if hasattr(error, 'message_dict'):
            # Form/model validation errors
            raise ValidationServiceError(f"Validation failed: {error.message_dict}")
        elif hasattr(error, 'messages'):
            # Multiple validation messages
            raise ValidationServiceError(f"Validation failed: {'; '.join(error.messages)}")
        else:
            # Single validation message
            raise ValidationServiceError(f"Validation failed: {str(error)}")
    
    def _paginate_queryset(self, queryset, page: int = 1, page_size: Optional[int] = None):
        """
        Paginate a queryset.
        
        Args:
            queryset: QuerySet to paginate
            page: Page number (1-based)
            page_size: Items per page (uses settings default if not provided)
            
        Returns:
            Tuple of (paginated_queryset, pagination_info)
        """
        if page_size is None:
            page_size = getattr(settings, 'DEFAULT_PAGE_SIZE', 100)
        
        total_count = queryset.count()
        start = (page - 1) * page_size
        end = start + page_size
        
        paginated = queryset[start:end]
        
        pagination_info = {
            'page': page,
            'page_size': page_size,
            'total_count': total_count,
            'total_pages': (total_count + page_size - 1) // page_size,
            'has_next': end < total_count,
            'has_previous': page > 1,
        }
        
        return paginated, pagination_info
    
    def create_response(self, 
                       success: bool = True, 
                       data: Optional[Any] = None, 
                       message: Optional[str] = None,
                       errors: Optional[Dict[str, Any]] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Create standardized service response.
        
        Args:
            success: Whether operation was successful
            data: Response data
            message: Optional message
            errors: Optional error details
            metadata: Optional metadata (pagination, etc.)
            
        Returns:
            Standardized response dictionary
        """
        response = {
            'success': success,
        }
        
        if data is not None:
            response['data'] = data
            
        if message:
            response['message'] = message
            
        if errors:
            response['errors'] = errors
            response['success'] = False
            
        if metadata:
            response['metadata'] = metadata
            
        return response
    
    def create_error_response(self, error: Exception, error_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Create standardized error response from exception.
        
        Args:
            error: Exception that occurred
            error_code: Optional error code
            
        Returns:
            Standardized error response
        """
        error_data = {
            'type': error.__class__.__name__,
            'message': str(error),
        }
        
        if error_code:
            error_data['code'] = error_code
            
        return self.create_response(
            success=False,
            errors=error_data,
            message=str(error)
        )
    
    def validate_required_fields(self, data: Dict[str, Any], required_fields: List[str]) -> None:
        """
        Validate that required fields are present in data.
        
        Args:
            data: Data dictionary to validate
            required_fields: List of required field names
            
        Raises:
            ValidationServiceError: If required fields are missing
        """
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            raise ValidationServiceError(
                f"Missing required fields: {', '.join(missing_fields)}"
            )
    
    def get_or_404(self, model_class: Type[T], **kwargs) -> T:
        """
        Get object or raise NotFoundServiceError.
        
        Args:
            model_class: Model class to query
            **kwargs: Query parameters
            
        Returns:
            Model instance
            
        Raises:
            NotFoundServiceError: If object not found
        """
        try:
            return model_class.objects.get(**kwargs)
        except model_class.DoesNotExist:
            model_name = model_class.__name__
            raise NotFoundServiceError(f"{model_name} not found")
        except model_class.MultipleObjectsReturned:
            model_name = model_class.__name__
            raise ValidationServiceError(f"Multiple {model_name} objects found")
    
    def bulk_create_with_validation(self, model_class: Type[T], objects: List[T]) -> List[T]:
        """
        Bulk create objects with validation.
        
        Args:
            model_class: Model class to create
            objects: List of model instances
            
        Returns:
            List of created objects
            
        Raises:
            ValidationServiceError: If validation fails
        """
        # Validate all objects first
        for obj in objects:
            try:
                obj.full_clean()
            except ValidationError as e:
                self._handle_validation_error(e)
        
        # Bulk create
        return model_class.objects.bulk_create(objects)
    
    def safe_update(self, instance: Any, **kwargs) -> Any:
        """
        Safely update model instance with validation.
        
        Args:
            instance: Model instance to update
            **kwargs: Fields to update
            
        Returns:
            Updated instance
            
        Raises:
            ValidationServiceError: If validation fails
        """
        # Update fields
        for field, value in kwargs.items():
            setattr(instance, field, value)
        
        # Validate
        try:
            instance.full_clean()
        except ValidationError as e:
            self._handle_validation_error(e)
        
        # Save
        instance.save()
        return instance