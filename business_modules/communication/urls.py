"""Communication module URL configuration."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ChannelViewSet, MessageViewSet, NotificationViewSet,
    NotificationPreferenceViewSet, MeetingViewSet,
    TypingIndicatorView, PresenceView
)

app_name = "communication"

# Create router
router = DefaultRouter()

# Register viewsets
router.register(r"channels", ChannelViewSet, basename="channel")
router.register(r"messages", MessageViewSet, basename="message")
router.register(r"notifications", NotificationViewSet, basename="notification")
router.register(r"preferences", NotificationPreferenceViewSet, basename="preference")
router.register(r"meetings", MeetingViewSet, basename="meeting")
router.register(r"typing", TypingIndicatorView, basename="typing")
router.register(r"presence", PresenceView, basename="presence")

# URL patterns
urlpatterns = [
    path("", include(router.urls)),
    
    # WebSocket endpoints (handled by ASGI)
    # These are documented here but implemented in routing.py
    # ws/communication/messages/ - Real-time messaging
    # ws/communication/notifications/ - Real-time notifications
    # ws/communication/presence/ - User presence updates
]

# API endpoint documentation
"""
Communication API Endpoints:

Channels:
- GET    /api/communication/channels/                 - List channels
- POST   /api/communication/channels/                 - Create channel
- GET    /api/communication/channels/{id}/            - Get channel
- PUT    /api/communication/channels/{id}/            - Update channel
- DELETE /api/communication/channels/{id}/            - Delete channel
- POST   /api/communication/channels/{id}/add_members/ - Add members
- POST   /api/communication/channels/{id}/remove_member/ - Remove member
- POST   /api/communication/channels/{id}/leave/      - Leave channel
- POST   /api/communication/channels/{id}/mark_read/  - Mark as read
- POST   /api/communication/channels/{id}/archive/    - Archive channel
- GET    /api/communication/channels/{id}/statistics/ - Get statistics
- POST   /api/communication/channels/create_direct/   - Create DM channel

Messages:
- GET    /api/communication/messages/                 - List messages
- POST   /api/communication/messages/                 - Send message
- GET    /api/communication/messages/{id}/            - Get message
- PUT    /api/communication/messages/{id}/            - Edit message
- DELETE /api/communication/messages/{id}/            - Delete message
- POST   /api/communication/messages/search/          - Search messages
- POST   /api/communication/messages/bulk_action/     - Bulk actions
- POST   /api/communication/messages/{id}/add_reaction/ - Add reaction
- DELETE /api/communication/messages/{id}/remove_reaction/ - Remove reaction
- POST   /api/communication/messages/{id}/create_thread/ - Create thread

Notifications:
- GET    /api/communication/notifications/            - List notifications
- GET    /api/communication/notifications/{id}/       - Get notification
- GET    /api/communication/notifications/unread_count/ - Unread count
- POST   /api/communication/notifications/mark_all_read/ - Mark all read
- POST   /api/communication/notifications/{id}/mark_read/ - Mark as read
- POST   /api/communication/notifications/bulk_mark_read/ - Bulk mark read
- POST   /api/communication/notifications/{id}/archive/ - Archive

Preferences:
- GET    /api/communication/preferences/me/           - Get preferences
- PUT    /api/communication/preferences/me/           - Update preferences
- PATCH  /api/communication/preferences/me/           - Partial update

Meetings:
- GET    /api/communication/meetings/                 - List meetings
- POST   /api/communication/meetings/                 - Schedule meeting
- GET    /api/communication/meetings/{id}/            - Get meeting
- PUT    /api/communication/meetings/{id}/            - Update meeting
- DELETE /api/communication/meetings/{id}/            - Cancel meeting
- POST   /api/communication/meetings/{id}/join/       - Join meeting
- POST   /api/communication/meetings/{id}/end/        - End meeting
- POST   /api/communication/meetings/{id}/update_response/ - RSVP
- POST   /api/communication/meetings/instant/         - Start instant call

Real-time:
- POST   /api/communication/typing/update/            - Update typing status
- POST   /api/communication/presence/update/          - Update presence
- GET    /api/communication/presence/online_users/    - Get online users

WebSocket Endpoints:
- ws://   /ws/communication/messages/                 - Real-time messaging
- ws://   /ws/communication/notifications/            - Real-time notifications
- ws://   /ws/communication/presence/                 - Presence updates
"""