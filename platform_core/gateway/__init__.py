"""
API Gateway Module

Provides a unified entry point for all API requests with:
- Request routing and forwarding
- Request/response transformation
- Service aggregation
- Protocol translation
- Authentication and authorization
- Rate limiting and throttling
- Caching and optimization
- Monitoring and analytics
"""

default_app_config = 'platform_core.gateway.apps.GatewayConfig'