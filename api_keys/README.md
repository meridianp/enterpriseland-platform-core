# API Key Management System

A comprehensive API key rotation mechanism for the Django backend that prioritizes both security and functionality.

## Features

### Core Functionality
- **Multiple API keys per user/application** for zero-downtime rotation
- **Scoped permissions** (read-only, specific endpoints, rate limits)
- **User-level and application-level API keys**
- **Gradual key rotation** with overlap period
- **Usage analytics and monitoring**
- **Emergency revocation**

### Security Features
- **Hashed key storage** - Only SHA-256 hashes are stored in the database
- **Cryptographically secure key generation** using Python's `secrets` module
- **Automatic key expiration**
- **IP address restrictions**
- **Rate limiting per API key**
- **Comprehensive audit logging**
- **Timing attack prevention**

### Developer Experience
- **Simple key generation process**
- **Easy integration with existing JWT auth**
- **Management commands for all operations**
- **Django admin interface**
- **RESTful API for key management**
- **Helpful error messages**
- **Testing utilities**

## Quick Start

### 1. Generate an API Key

Using management command:
```bash
python manage.py create_api_key \
    --user=user@example.com \
    --name="My API Key" \
    --scopes=read,write \
    --expires-in-days=365
```

Using the API:
```bash
curl -X POST http://localhost:8000/api/api-keys/ \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My API Key",
    "scopes": ["read", "write"],
    "expires_in_days": 365,
    "rate_limit_per_hour": 1000
  }'
```

### 2. Use the API Key

The API key can be provided in three ways:

**Authorization Header (Recommended):**
```bash
curl -H "Authorization: Bearer sk_live_abcd1234..." http://localhost:8000/api/assessments/
```

**X-API-Key Header:**
```bash
curl -H "X-API-Key: sk_live_abcd1234..." http://localhost:8000/api/assessments/
```

**Query Parameter (Less Secure):**
```bash
curl "http://localhost:8000/api/assessments/?api_key=sk_live_abcd1234..."
```

### 3. Monitor Usage

```bash
# List all your API keys
python manage.py list_api_keys --user=user@example.com

# Check keys expiring soon
python manage.py list_api_keys --expiring-soon

# View usage via API
curl -H "Authorization: Bearer <jwt_token>" \
  http://localhost:8000/api/api-keys/{key_id}/stats/
```

## API Key Types

### User Keys
- Prefixed with `sk_live_` (Secret Key Live)
- Associated with a specific user
- Inherit user's group membership and permissions

### Application Keys
- Prefixed with `ak_live_` (Application Key Live)
- Not tied to a specific user
- Useful for service-to-service communication
- Cannot have admin scope for security

## Scopes

### General Scopes
- `read` - Read access to all resources
- `write` - Write access to all resources  
- `delete` - Delete access to all resources
- `admin` - Full administrative access

### Resource-Specific Scopes
- `assessments:read` / `assessments:write`
- `leads:read` / `leads:write`
- `market_intel:read` / `market_intel:write`
- `deals:read` / `deals:write`
- `contacts:read` / `contacts:write`
- `files:read` / `files:write` / `files:delete`

### Scope Hierarchy
- `admin` scope grants access to all operations
- Resource-specific scopes override general scopes
- More specific scopes take precedence

## Management Commands

### Create API Key
```bash
python manage.py create_api_key --help

# Examples
python manage.py create_api_key \
    --user=user@example.com \
    --name="Production API Key" \
    --scopes=read,assessments:write \
    --rate-limit=5000 \
    --expires-in-days=90

python manage.py create_api_key \
    --application="Analytics Service" \
    --name="Analytics Key" \
    --scopes=read,market_intel:read \
    --allowed-ips=192.168.1.100,192.168.1.101
```

### List API Keys
```bash
python manage.py list_api_keys --help

# Examples
python manage.py list_api_keys
python manage.py list_api_keys --user=user@example.com
python manage.py list_api_keys --expired
python manage.py list_api_keys --expiring-soon
python manage.py list_api_keys --format=json
```

### Rotate API Keys
```bash
python manage.py rotate_api_keys --help

# Examples
python manage.py rotate_api_keys --expiring-in-days=30
python manage.py rotate_api_keys --key-id=<uuid>
python manage.py rotate_api_keys --all --overlap-hours=48
```

### Revoke API Keys
```bash
python manage.py revoke_api_key --help

# Examples
python manage.py revoke_api_key --key-id=<uuid>
python manage.py revoke_api_key --user=user@example.com --all
python manage.py revoke_api_key --expired
```

## API Endpoints

### List API Keys
```http
GET /api/api-keys/
GET /api/api-keys/?is_active=true
GET /api/api-keys/?expires_soon=7
GET /api/api-keys/?key_type=user
```

### Create API Key
```http
POST /api/api-keys/
Content-Type: application/json

{
  "name": "My New Key",
  "scopes": ["read", "write"],
  "expires_in_days": 90,
  "rate_limit_per_hour": 1000,
  "allowed_ips": ["192.168.1.100"]
}
```

### Get API Key Details
```http
GET /api/api-keys/{id}/
```

### Update API Key
```http
PATCH /api/api-keys/{id}/
Content-Type: application/json

{
  "name": "Updated Name",
  "scopes": ["read", "assessments:write"],
  "rate_limit_per_hour": 2000
}
```

### Rotate API Key
```http
POST /api/api-keys/{id}/rotate/
Content-Type: application/json

{
  "overlap_hours": 24,
  "revoke_old_key": false
}
```

### Revoke API Key
```http
DELETE /api/api-keys/{id}/
Content-Type: application/json

{
  "reason": "Security incident"
}
```

### Get Usage Statistics
```http
GET /api/api-keys/{id}/stats/
GET /api/api-keys/{id}/stats/?days=7
```

### Get Usage Logs
```http
GET /api/api-keys/{id}/usage/
GET /api/api-keys/{id}/usage/?start_date=2024-01-01&end_date=2024-01-31
```

## Security Best Practices

### Key Generation
- Keys are generated using `secrets.choice()` for cryptographic security
- 32-character length provides sufficient entropy
- Keys are immediately hashed with SHA-256 before storage

### Storage Security
- Only SHA-256 hashes are stored in the database
- Original keys are never persisted
- Key prefixes (first 8 characters) stored for identification

### Access Control
- IP restrictions can limit key usage to specific networks
- Rate limiting prevents abuse
- Scoped permissions follow principle of least privilege
- Keys can be revoked instantly

### Monitoring
- All API key usage is logged with:
  - Timestamp and endpoint accessed
  - Response time and status code
  - IP address and user agent
  - Error messages for failed requests
- Usage statistics available via API
- Audit logs track all key operations

### Rotation
- Gradual rotation with overlap periods
- Old keys can remain active during transition
- Automated expiration of rotated keys
- Audit trail of all rotations

## Rate Limiting

### Default Limits
- 1000 requests per hour per key (configurable)
- Rate limiting uses sliding window
- Headers indicate current usage:
  - `X-RateLimit-Limit`: Maximum requests per hour
  - `X-RateLimit-Remaining`: Requests remaining

### Configuration
```python
# Per-key rate limit
api_key.rate_limit_per_hour = 5000
api_key.save()

# Global rate limits in settings
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_RATES': {
        'api_key': '1000/hour',
        # ...
    }
}
```

## Integration with Existing Views

### Adding API Key Permissions
```python
from rest_framework import viewsets
from api_keys.permissions import AssessmentsAPIKeyPermission

class AssessmentViewSet(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        AssessmentsAPIKeyPermission,  # Add API key permission
    ]
```

### Custom Scope Requirements
```python
from api_keys.permissions import HasAPIKeyScope

class MyViewSet(viewsets.ModelViewSet):
    permission_classes = [HasAPIKeyScope]
    required_scopes = ['read', 'custom:scope']
```

## Error Handling

### Common Error Responses

**Invalid API Key:**
```json
{
  "detail": "Invalid API key"
}
```

**Rate Limit Exceeded:**
```json
{
  "detail": "Rate limit exceeded. Limit: 1000/hour"
}
```

**Insufficient Scope:**
```json
{
  "detail": "You do not have permission to perform this action."
}
```

**IP Not Allowed:**
```json
{
  "detail": "IP address not allowed"
}
```

## Testing

### Running Tests
```bash
python manage.py test api_keys
python manage.py test api_keys.tests.APIKeyModelTests
python manage.py test api_keys.tests.APIKeyAuthenticationTests
```

### Test Utilities
```python
from api_keys.models import APIKey

# Create test API key
api_key, raw_key = APIKey.objects.create_key(
    user=user,
    name='Test Key',
    scopes=['read', 'write']
)

# Use in API tests
self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {raw_key}')
response = self.client.get('/api/assessments/')
```

## Monitoring and Alerts

### Key Expiration Monitoring
```bash
# Check for keys expiring in 7 days
python manage.py list_api_keys --expiring-soon

# Get expiring keys via API
curl /api/api-keys/expiring/?days=7
```

### Usage Monitoring
```python
# Get usage statistics
from api_keys.models import APIKey, APIKeyUsage

# High usage keys
high_usage = APIKey.objects.filter(
    usage_count__gt=10000,
    last_used_at__gte=timezone.now() - timedelta(days=7)
)

# Error rates
error_count = APIKeyUsage.objects.filter(
    timestamp__gte=timezone.now() - timedelta(hours=1),
    status_code__gte=400
).count()
```

### Setting Up Alerts
Consider setting up monitoring for:
- Keys expiring within 30 days
- High error rates (> 5%)
- Unusual usage patterns
- Rate limit violations
- Keys with no recent usage

## Production Considerations

### Database Performance
- All critical queries use database indexes
- Use database connection pooling
- Consider read replicas for usage analytics

### Redis Rate Limiting
For high-traffic environments, consider using Redis for rate limiting:
```python
# In production, implement Redis-based rate limiting
def check_rate_limit_redis(api_key, window_minutes=60):
    import redis
    r = redis.Redis()
    key = f"rate_limit:{api_key.id}:{window_minutes}"
    # Implementation details...
```

### Logging
- Configure Django logging for API key events
- Consider centralized logging (ELK stack, etc.)
- Monitor for security events

### Backup and Recovery
- Include API key data in regular backups
- Have procedures for emergency key revocation
- Document key rotation processes

## Migration Guide

### From Existing Systems
If migrating from another API key system:

1. **Export existing keys** (if possible)
2. **Create migration script**:
```python
# Example migration script
for old_key in old_system_keys:
    APIKey.objects.create_key(
        user=get_user(old_key.user_id),
        name=old_key.name,
        scopes=convert_permissions(old_key.permissions),
        expires_in_days=calculate_remaining_days(old_key.expires_at)
    )
```
3. **Test thoroughly** in staging environment
4. **Coordinate with API consumers** for key updates
5. **Monitor usage** after migration

### Deployment Checklist
- [ ] Run migrations: `python manage.py migrate`
- [ ] Add to `INSTALLED_APPS`
- [ ] Update `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']`
- [ ] Add URLs to main `urlpatterns`
- [ ] Configure rate limiting
- [ ] Set up monitoring
- [ ] Test key creation and usage
- [ ] Document for your team

## Support

### Debugging
- Check Django logs for authentication errors
- Use `list_api_keys` command to verify key status
- Test keys with curl before application integration
- Monitor usage logs for patterns

### Common Issues
1. **Keys not working**: Check expiration and active status
2. **Permission denied**: Verify scopes match endpoint requirements
3. **Rate limiting**: Check current usage and limits
4. **IP restrictions**: Verify client IP is in allowed list

For additional support, check the test suite for usage examples and patterns.