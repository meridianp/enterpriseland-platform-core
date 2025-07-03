"""
WebSocket Support System

Provides real-time bidirectional communication with:
- Django Channels integration
- Authentication and authorization
- Channel-based messaging
- Presence tracking
- Auto-reconnection support
- Scaling with Redis pub/sub
- Room/topic management
- Message history
"""

default_app_config = 'platform_core.websocket.apps.WebSocketConfig'