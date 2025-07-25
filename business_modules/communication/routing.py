"""WebSocket routing for communication module."""

from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r"ws/communication/messages/$",
        consumers.MessageConsumer.as_asgi()
    ),
    re_path(
        r"ws/communication/notifications/$",
        consumers.NotificationConsumer.as_asgi()
    ),
    re_path(
        r"ws/communication/presence/$",
        consumers.PresenceConsumer.as_asgi()
    ),
]