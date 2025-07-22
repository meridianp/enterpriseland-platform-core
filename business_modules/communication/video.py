"""Video conferencing provider abstraction."""

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class BaseVideoProvider(ABC):
    """Base class for video conferencing providers."""
    
    @abstractmethod
    def create_room(self, room_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Create a video room."""
        pass
    
    @abstractmethod
    def generate_access_token(self, room_id: str, user_id: str, role: str) -> str:
        """Generate access token for a user."""
        pass
    
    @abstractmethod
    def get_recording(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Get recording information."""
        pass
    
    @abstractmethod
    def end_room(self, room_id: str) -> bool:
        """End a video room."""
        pass


class AgoraProvider(BaseVideoProvider):
    """Agora.io video provider."""
    
    def __init__(self):
        """Initialize Agora provider."""
        self.app_id = getattr(settings, "AGORA_APP_ID", "")
        self.app_certificate = getattr(settings, "AGORA_APP_CERTIFICATE", "")
    
    def create_room(self, room_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Create an Agora room."""
        # Agora doesn't require explicit room creation
        # Rooms are created automatically when users join
        return {
            "room_id": room_id,
            "url": f"https://app.example.com/video/{room_id}",
            "provider": "agora",
            "app_id": self.app_id,
        }
    
    def generate_access_token(self, room_id: str, user_id: str, role: str) -> str:
        """Generate Agora RTC token."""
        try:
            from agora_token_builder import RtcTokenBuilder
            
            # Token expiration time (24 hours)
            expiration_time_in_seconds = 86400
            current_timestamp = int(time.time())
            privilege_expired_ts = current_timestamp + expiration_time_in_seconds
            
            # Role mapping
            agora_role = 1 if role in ["host", "co_host"] else 2
            
            token = RtcTokenBuilder.buildTokenWithUid(
                self.app_id,
                self.app_certificate,
                room_id,
                user_id,
                agora_role,
                privilege_expired_ts
            )
            
            return token
        
        except ImportError:
            logger.error("agora-token-builder not installed")
            return ""
        except Exception as e:
            logger.error(f"Failed to generate Agora token: {e}")
            return ""
    
    def get_recording(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Get Agora recording."""
        # This would integrate with Agora Cloud Recording API
        # For now, return None
        return None
    
    def end_room(self, room_id: str) -> bool:
        """End Agora room."""
        # Agora rooms end automatically when all users leave
        return True


class TwilioVideoProvider(BaseVideoProvider):
    """Twilio Video provider."""
    
    def __init__(self):
        """Initialize Twilio provider."""
        self.account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
        self.api_key = getattr(settings, "TWILIO_API_KEY", "")
        self.api_secret = getattr(settings, "TWILIO_API_SECRET", "")
    
    def create_room(self, room_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Twilio room."""
        try:
            from twilio.rest import Client
            
            client = Client(self.api_key, self.api_secret, self.account_sid)
            
            room = client.video.rooms.create(
                unique_name=room_id,
                type=settings.get("type", "group"),
                record_participants_on_connect=settings.get("recording", False),
                max_participants=settings.get("max_participants", 50)
            )
            
            return {
                "room_id": room.unique_name,
                "sid": room.sid,
                "url": f"https://app.example.com/video/{room_id}",
                "provider": "twilio",
            }
        
        except ImportError:
            logger.error("twilio not installed")
            return {"room_id": room_id, "url": "", "provider": "twilio"}
        except Exception as e:
            logger.error(f"Failed to create Twilio room: {e}")
            return {"room_id": room_id, "url": "", "provider": "twilio"}
    
    def generate_access_token(self, room_id: str, user_id: str, role: str) -> str:
        """Generate Twilio access token."""
        try:
            from twilio.jwt.access_token import AccessToken
            from twilio.jwt.access_token.grants import VideoGrant
            
            token = AccessToken(
                self.account_sid,
                self.api_key,
                self.api_secret,
                identity=user_id
            )
            
            grant = VideoGrant(room=room_id)
            token.add_grant(grant)
            
            return token.to_jwt().decode()
        
        except ImportError:
            logger.error("twilio not installed")
            return ""
        except Exception as e:
            logger.error(f"Failed to generate Twilio token: {e}")
            return ""
    
    def get_recording(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Get Twilio recording."""
        try:
            from twilio.rest import Client
            
            client = Client(self.api_key, self.api_secret, self.account_sid)
            
            # Get room
            rooms = client.video.rooms.list(unique_name=room_id, limit=1)
            if not rooms:
                return None
            
            room = rooms[0]
            
            # Get recordings
            recordings = room.recordings.list(limit=1)
            if not recordings:
                return None
            
            recording = recordings[0]
            
            return {
                "url": recording.url,
                "duration": recording.duration,
                "size": recording.size,
                "status": recording.status,
            }
        
        except Exception as e:
            logger.error(f"Failed to get Twilio recording: {e}")
            return None
    
    def end_room(self, room_id: str) -> bool:
        """End Twilio room."""
        try:
            from twilio.rest import Client
            
            client = Client(self.api_key, self.api_secret, self.account_sid)
            
            # Get room
            rooms = client.video.rooms.list(unique_name=room_id, limit=1)
            if not rooms:
                return False
            
            room = rooms[0]
            room.update(status="completed")
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to end Twilio room: {e}")
            return False


class JitsiProvider(BaseVideoProvider):
    """Jitsi Meet provider (self-hosted or cloud)."""
    
    def __init__(self):
        """Initialize Jitsi provider."""
        self.server_url = getattr(settings, "JITSI_SERVER_URL", "https://meet.jit.si")
        self.jwt_secret = getattr(settings, "JITSI_JWT_SECRET", "")
    
    def create_room(self, room_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Jitsi room."""
        # Jitsi rooms are created automatically
        return {
            "room_id": room_id,
            "url": f"{self.server_url}/{room_id}",
            "provider": "jitsi",
        }
    
    def generate_access_token(self, room_id: str, user_id: str, role: str) -> str:
        """Generate Jitsi JWT token."""
        if not self.jwt_secret:
            # No authentication required
            return ""
        
        try:
            import jwt
            import time
            
            payload = {
                "context": {
                    "user": {
                        "id": user_id,
                        "moderator": role in ["host", "co_host"],
                    }
                },
                "aud": "jitsi",
                "iss": "enterpriseland",
                "sub": self.server_url,
                "room": room_id,
                "exp": int(time.time()) + 86400,  # 24 hours
            }
            
            token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")
            return token
        
        except Exception as e:
            logger.error(f"Failed to generate Jitsi token: {e}")
            return ""
    
    def get_recording(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Get Jitsi recording."""
        # This depends on your Jitsi recording setup
        return None
    
    def end_room(self, room_id: str) -> bool:
        """End Jitsi room."""
        # Jitsi rooms end automatically
        return True


class VideoProvider:
    """Video provider factory."""
    
    def __init__(self):
        """Initialize video provider based on settings."""
        provider_name = getattr(settings, "VIDEO_PROVIDER", "jitsi").lower()
        
        if provider_name == "agora":
            self.provider = AgoraProvider()
        elif provider_name == "twilio":
            self.provider = TwilioVideoProvider()
        elif provider_name == "jitsi":
            self.provider = JitsiProvider()
        else:
            # Default to Jitsi
            self.provider = JitsiProvider()
    
    def create_room(self, room_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Create a video room."""
        return self.provider.create_room(room_id, settings)
    
    def generate_access_token(self, room_id: str, user_id: str, role: str) -> str:
        """Generate access token."""
        return self.provider.generate_access_token(room_id, user_id, role)
    
    def get_recording(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Get recording information."""
        return self.provider.get_recording(room_id)
    
    def end_room(self, room_id: str) -> bool:
        """End a video room."""
        return self.provider.end_room(room_id)