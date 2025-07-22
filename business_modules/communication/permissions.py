"""Communication module permissions."""

from rest_framework import permissions


class CanManageChannel(permissions.BasePermission):
    """Permission to manage channel (archive, add/remove members)."""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can manage channel."""
        # Check if user is member
        member = obj.members.filter(user=request.user).first()
        if not member:
            return False
        
        # Only owners and admins can manage
        return member.role in ["OWNER", "ADMIN"]


class CanSendMessage(permissions.BasePermission):
    """Permission to send messages in a channel."""
    
    def has_permission(self, request, view):
        """Check general permission."""
        # For list and create actions
        if view.action in ["list", "retrieve"]:
            return True
        
        if view.action == "create":
            # Will check channel membership in has_object_permission
            return True
        
        return True
    
    def has_object_permission(self, request, view, obj):
        """Check if user can interact with message."""
        if view.action in ["retrieve", "list"]:
            # Can view if member of channel
            return obj.channel.is_member(request.user)
        
        if view.action in ["update", "partial_update"]:
            # Can only edit own messages
            return obj.sender == request.user
        
        if view.action == "destroy":
            # Can delete own messages or if has permission
            return obj.sender == request.user or request.user.has_perm("communication.delete_message")
        
        # For reactions and other actions
        return obj.channel.is_member(request.user)


class CanDeleteMessage(permissions.BasePermission):
    """Permission to delete messages."""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can delete message."""
        # Can delete own messages
        if obj.sender == request.user:
            return True
        
        # Check channel role
        member = obj.channel.members.filter(user=request.user).first()
        if member and member.role in ["OWNER", "ADMIN", "MODERATOR"]:
            return True
        
        # Check Django permission
        return request.user.has_perm("communication.delete_message")


class CanManageMeeting(permissions.BasePermission):
    """Permission to manage meetings."""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can manage meeting."""
        # Organizer can always manage
        if obj.organizer == request.user:
            return True
        
        # Check if user is host/co-host
        participant = obj.meeting_participants.filter(
            user=request.user,
            role__in=["HOST", "CO_HOST"]
        ).first()
        
        return participant is not None


class CanViewNotification(permissions.BasePermission):
    """Permission to view notifications."""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can view notification."""
        # Can only view own notifications
        return obj.recipient == request.user


class IsChannelMember(permissions.BasePermission):
    """Permission requiring channel membership."""
    
    def has_permission(self, request, view):
        """Check general permission."""
        # Check channel_id in request data for create actions
        if view.action == "create":
            channel_id = request.data.get("channel")
            if channel_id:
                from .models import Channel
                try:
                    channel = Channel.objects.get(id=channel_id)
                    return channel.is_member(request.user)
                except Channel.DoesNotExist:
                    return False
        return True
    
    def has_object_permission(self, request, view, obj):
        """Check if user is member of related channel."""
        # Get channel from object
        channel = None
        if hasattr(obj, "channel"):
            channel = obj.channel
        elif hasattr(obj, "channels"):
            # For objects that might relate to multiple channels
            return any(ch.is_member(request.user) for ch in obj.channels.all())
        
        if channel:
            return channel.is_member(request.user)
        
        return False