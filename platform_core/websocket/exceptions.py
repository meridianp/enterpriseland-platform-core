"""
WebSocket Exceptions
"""


class WebSocketException(Exception):
    """Base exception for WebSocket errors."""
    pass


class WebSocketAuthenticationError(WebSocketException):
    """Authentication error."""
    pass


class WebSocketPermissionError(WebSocketException):
    """Permission denied error."""
    pass


class WebSocketRoomError(WebSocketException):
    """Room-related error."""
    pass


class WebSocketConnectionError(WebSocketException):
    """Connection-related error."""
    pass


class WebSocketMessageError(WebSocketException):
    """Message-related error."""
    pass


class WebSocketRateLimitError(WebSocketException):
    """Rate limit exceeded error."""
    pass