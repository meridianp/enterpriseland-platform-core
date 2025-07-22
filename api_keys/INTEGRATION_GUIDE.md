# API Key Integration Guide

This guide shows how to integrate the API key authentication system with your existing Django REST Framework views.

## Quick Setup

### 1. Add to Django Settings

The API key app is already configured in `settings/base.py`:

```python
# Already added to INSTALLED_APPS
LOCAL_APPS = [
    'api_keys',  # ✓ Added
    # ... other apps
]

# Already added to authentication classes
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'api_keys.authentication.APIKeyAuthentication',  # ✓ Added (first priority)
        'accounts.authentication.CookieJWTAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
}
```

### 2. Add URLs

Already added to `core/urls.py`:

```python
urlpatterns = [
    path('api/', include('api_keys.urls')),  # ✓ Added
    # ... other URLs
]
```

### 3. Run Migrations

```bash
python manage.py migrate api_keys
```

## Basic Integration

### Option 1: Use Existing Permission Classes

For most views, you can use the built-in permission classes:

```python
from rest_framework import viewsets, permissions
from api_keys.permissions import AssessmentsAPIKeyPermission

class AssessmentViewSet(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        AssessmentsAPIKeyPermission,  # Add this line
    ]
    # ... rest of your view
```

### Option 2: Add Required Scopes

For fine-grained control, specify required scopes:

```python
from api_keys.permissions import HasAPIKeyScope

class MyViewSet(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        HasAPIKeyScope,
    ]
    required_scopes = ['read', 'custom:scope']  # Add this line
```

### Option 3: Custom Permission Logic

For complex requirements, create custom permissions:

```python
from api_keys.permissions import HasAPIKeyScope

class CustomAPIKeyPermission(HasAPIKeyScope):
    def has_permission(self, request, view):
        # Always check base API key permissions first
        if not super().has_permission(request, view):
            return True  # Let other auth methods handle it
        
        # Custom logic for API key requests
        if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
            api_key = request.auth
            
            # Example: Different scopes for different methods
            if request.method in ['GET', 'HEAD', 'OPTIONS']:
                return api_key.has_any_scope(['read', 'myapp:read'])
            elif request.method in ['POST', 'PUT', 'PATCH']:
                return api_key.has_any_scope(['write', 'myapp:write'])
            elif request.method == 'DELETE':
                return api_key.has_any_scope(['delete', 'myapp:delete'])
        
        return True  # Let other auth handle non-API-key requests
```

## Available Permission Classes

### General Permissions

```python
from api_keys.permissions import (
    HasAPIKeyScope,      # Base class - checks required_scopes
    ReadOnlyAPIKey,      # Read-only access
    WriteAPIKey,         # Read + write access
    AdminAPIKey,         # Admin access only
)
```

### Resource-Specific Permissions

```python
from api_keys.permissions import (
    AssessmentsAPIKeyPermission,    # For assessments endpoints
    LeadsAPIKeyPermission,          # For leads endpoints  
    MarketIntelAPIKeyPermission,    # For market intelligence
    DealsAPIKeyPermission,          # For deals endpoints
    ContactsAPIKeyPermission,       # For contacts endpoints
    FilesAPIKeyPermission,          # For files endpoints
)
```

## Complete Integration Examples

### Example 1: Assessments ViewSet

```python
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from api_keys.permissions import AssessmentsAPIKeyPermission
from .models import Assessment
from .serializers import AssessmentSerializer

class AssessmentViewSet(viewsets.ModelViewSet):
    queryset = Assessment.objects.all()
    serializer_class = AssessmentSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        AssessmentsAPIKeyPermission,  # Handles API key scope checking
    ]
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Custom action that requires write access."""
        # AssessmentsAPIKeyPermission automatically checks:
        # - GET/HEAD/OPTIONS: requires 'read' or 'assessments:read' scope
        # - POST/PUT/PATCH: requires 'write' or 'assessments:write' scope
        assessment = self.get_object()
        # ... submit logic
        return Response({'status': 'submitted'})
```

### Example 2: Custom Scopes

```python
from api_keys.permissions import HasAPIKeyScope

class ReportsViewSet(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        HasAPIKeyScope,
    ]
    required_scopes = ['reports:read']  # Custom scope
    
    def get_required_scopes(self):
        """Dynamic scope requirements based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return ['reports:write']
        elif self.action == 'destroy':
            return ['reports:delete']
        else:
            return ['reports:read']
```

### Example 3: Function-Based Views

```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from api_keys.permissions import HasAPIKeyScope

@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated, HasAPIKeyScope])
def my_api_view(request):
    # Check API key permissions manually if needed
    if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
        api_key = request.auth
        if request.method == 'POST' and not api_key.has_scope('write'):
            return Response(
                {'error': 'Write scope required'}, 
                status=403
            )
    
    # ... view logic
    return Response({'message': 'success'})
```

## Handling Mixed Authentication

The system works seamlessly with existing JWT authentication:

```python
class MyViewSet(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        HasAPIKeyScope,  # Only applies to API key requests
    ]
    required_scopes = ['read']
    
    def get_permissions(self):
        """Different permissions for different auth methods."""
        permissions = super().get_permissions()
        
        # Add custom logic based on authentication method
        if hasattr(self.request, 'auth'):
            if isinstance(self.request.auth, APIKey):
                # API key authentication
                permissions.append(HasAPIKeyScope())
            elif hasattr(self.request.auth, 'token'):
                # JWT authentication
                permissions.append(permissions.IsAuthenticated())
        
        return permissions
```

## Testing API Key Integration

### Unit Tests

```python
from rest_framework.test import APITestCase
from api_keys.models import APIKey

class MyAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        
        # Create API key for testing
        self.api_key, self.raw_key = APIKey.objects.create_key(
            user=self.user,
            name='Test Key',
            scopes=['read', 'write']
        )
    
    def test_api_key_authentication(self):
        """Test API access with API key."""
        # Use API key in Authorization header
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key}')
        
        response = self.client.get('/api/assessments/')
        self.assertEqual(response.status_code, 200)
    
    def test_insufficient_scope(self):
        """Test access denied with insufficient scope."""
        # Create key with limited scope
        limited_key, limited_raw = APIKey.objects.create_key(
            user=self.user,
            name='Limited Key',
            scopes=['read']  # No write scope
        )
        
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {limited_raw}')
        
        # GET should work
        response = self.client.get('/api/assessments/')
        self.assertEqual(response.status_code, 200)
        
        # POST should fail
        response = self.client.post('/api/assessments/', {})
        self.assertEqual(response.status_code, 403)
```

### Manual Testing with curl

```bash
# Create an API key first
python manage.py create_api_key \
    --user=test@example.com \
    --name="Test Key" \
    --scopes=read,write

# Test with the returned key
curl -H "Authorization: Bearer sk_live_your_key_here" \
     http://localhost:8000/api/assessments/

# Test different endpoints
curl -H "Authorization: Bearer sk_live_your_key_here" \
     http://localhost:8000/api/leads/

# Test insufficient permissions (should return 403)
curl -H "Authorization: Bearer sk_live_read_only_key" \
     -X POST http://localhost:8000/api/assessments/ \
     -H "Content-Type: application/json" \
     -d '{"name": "Test"}'
```

## Monitoring API Key Usage

### Add Usage Tracking Middleware

Already included in the system:

```python
# In settings.py
MIDDLEWARE = [
    # ... other middleware
    'api_keys.middleware.APIKeyUsageMiddleware',  # Add this
    'api_keys.middleware.APIKeySecurityMiddleware',  # Optional security headers
]
```

### View Usage Statistics

```python
from api_keys.models import APIKey, APIKeyUsage

# Get API key usage
api_key = APIKey.objects.get(name='My Key')
usage_logs = api_key.usage_logs.filter(
    timestamp__gte=timezone.now() - timedelta(days=7)
)

# Usage statistics via API
GET /api/api-keys/{key_id}/stats/?days=7
GET /api/api-keys/{key_id}/usage/?start_date=2024-01-01
```

## Common Patterns

### 1. Gradual Migration

Start by adding API key support without changing existing behavior:

```python
class MyViewSet(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        # Don't add API key permissions yet
    ]
    
    def check_permissions(self, request):
        """Custom permission checking during migration."""
        super().check_permissions(request)
        
        # Optional API key validation (warning only)
        if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
            api_key = request.auth
            if not api_key.has_scope('read'):
                logger.warning(f"API key {api_key.id} lacks read scope")
                # Don't block request during migration
```

### 2. Feature Flags

Use different scopes for new features:

```python
class NewFeatureViewSet(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        HasAPIKeyScope,
    ]
    required_scopes = ['beta:new_feature']  # Special scope for beta features
```

### 3. Rate Limiting by Scope

```python
from django.core.cache import cache

def check_api_rate_limit(request):
    if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
        api_key = request.auth
        
        # Different limits based on scope
        if api_key.has_scope('premium'):
            rate_limit = 10000
        elif api_key.has_scope('standard'):
            rate_limit = 1000
        else:
            rate_limit = 100
        
        # Check rate limit logic...
```

## Troubleshooting

### Common Issues

1. **API key not recognized**
   - Check that `APIKeyAuthentication` is in `DEFAULT_AUTHENTICATION_CLASSES`
   - Verify key format: `sk_live_` or `ak_live_` prefix
   - Check that key is active and not expired

2. **Permission denied with valid key**
   - Check that key has required scopes
   - Verify permission class is added to view
   - Check `required_scopes` attribute

3. **Mixed authentication not working**
   - Ensure API key authentication is first in the list
   - Don't override `authentication_classes` unless necessary

### Debug Mode

Add logging to see what's happening:

```python
import logging

logger = logging.getLogger(__name__)

class MyViewSet(viewsets.ModelViewSet):
    def check_permissions(self, request):
        if hasattr(request, 'auth'):
            logger.info(f"Auth type: {type(request.auth)}")
            if isinstance(request.auth, APIKey):
                logger.info(f"API Key scopes: {request.auth.scopes}")
        
        super().check_permissions(request)
```

This integration guide should help you add API key authentication to any existing Django REST Framework views while maintaining compatibility with your current JWT authentication system.