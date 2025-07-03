"""
WebSocket Views

REST API views for WebSocket management.
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Count, Q
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from platform_core.common.views import BaseViewSet
from .models import (
    WebSocketConnection,
    WebSocketRoom,
    WebSocketMessage,
    WebSocketPresence
)
from .serializers import (
    WebSocketConnectionSerializer,
    WebSocketRoomSerializer,
    MessageSerializer,
    WebSocketPresenceSerializer,
    SendMessageSerializer,
    BroadcastMessageSerializer
)


class WebSocketConnectionViewSet(BaseViewSet):
    """ViewSet for WebSocket connections."""
    
    queryset = WebSocketConnection.objects.all()
    serializer_class = WebSocketConnectionSerializer
    filterset_fields = ['user', 'state', 'protocol']
    search_fields = ['user__username', 'ip_address', 'channel_name']
    ordering_fields = ['connected_at', 'last_seen_at']
    ordering = ['-connected_at']
    
    def get_queryset(self):
        """Filter by user permissions."""
        queryset = super().get_queryset()
        
        # Non-admin users can only see their own connections
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get active connections."""
        connections = self.filter_queryset(
            self.get_queryset().filter(state='open')
        )
        
        serializer = self.get_serializer(connections, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get connection statistics."""
        queryset = self.get_queryset()
        
        stats = {
            'total_connections': queryset.count(),
            'active_connections': queryset.filter(state='open').count(),
            'unique_users': queryset.values('user').distinct().count(),
            'by_protocol': dict(
                queryset.values('protocol').annotate(count=Count('id')).values_list('protocol', 'count')
            ),
            'by_state': dict(
                queryset.values('state').annotate(count=Count('id')).values_list('state', 'count')
            )
        }
        
        return Response(stats)
    
    @action(detail=True, methods=['post'])
    def disconnect(self, request, pk=None):
        """Force disconnect a connection."""
        connection = self.get_object()
        
        if connection.state != 'open':
            return Response(
                {'error': 'Connection is not open'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Send disconnect message via channel layer
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.send)(
            connection.channel_name,
            {
                'type': 'websocket.close',
                'code': 4000,
                'reason': 'Disconnected by admin'
            }
        )
        
        # Update connection state
        connection.close()
        
        return Response({'status': 'disconnected'})


class WebSocketRoomViewSet(BaseViewSet):
    """ViewSet for WebSocket rooms."""
    
    queryset = WebSocketRoom.objects.all()
    serializer_class = WebSocketRoomSerializer
    filterset_fields = ['room_type', 'is_active', 'owner']
    search_fields = ['name', 'display_name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    
    def get_queryset(self):
        """Filter rooms by user access."""
        queryset = super().get_queryset()
        
        if not self.request.user.is_staff:
            # Show public rooms and rooms user has access to
            queryset = queryset.filter(
                Q(require_authentication=False) |
                Q(owner=self.request.user) |
                Q(allowed_users=self.request.user)
            ).distinct()
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        """Get room members (active connections)."""
        room = self.get_object()
        
        connections = room.get_active_connections().select_related('user')
        users = [
            {
                'id': str(conn.user.id),
                'username': conn.user.username,
                'connected_at': conn.connected_at
            }
            for conn in connections
        ]
        
        return Response({
            'room': room.name,
            'member_count': len(users),
            'members': users
        })
    
    @action(detail=True, methods=['get'])
    def presence(self, request, pk=None):
        """Get room presence information."""
        room = self.get_object()
        
        if not room.enable_presence:
            return Response({'error': 'Presence not enabled for this room'})
        
        presence_records = WebSocketPresence.objects.filter(
            room=room,
            status__in=['online', 'away', 'busy']
        ).select_related('user')
        
        serializer = WebSocketPresenceSerializer(presence_records, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get room message history."""
        room = self.get_object()
        
        if not room.enable_history:
            return Response({'error': 'History not enabled for this room'})
        
        # Check user can access room
        if not room.can_join(request.user):
            return Response(
                {'error': 'Access denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get messages
        limit = int(request.query_params.get('limit', 50))
        before = request.query_params.get('before')
        
        messages = WebSocketMessage.objects.filter(room=room)
        
        if before:
            messages = messages.filter(created_at__lt=before)
        
        messages = messages.order_by('-created_at')[:limit]
        
        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def clear_history(self, request, pk=None):
        """Clear room message history."""
        room = self.get_object()
        
        # Check permission
        if room.owner != request.user and not request.user.is_staff:
            return Response(
                {'error': 'Only room owner can clear history'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Delete messages
        count = WebSocketMessage.objects.filter(room=room).delete()[0]
        
        return Response({'deleted_count': count})


class WebSocketMessageViewSet(BaseViewSet):
    """ViewSet for WebSocket messages."""
    
    queryset = WebSocketMessage.objects.all()
    serializer_class = MessageSerializer
    filterset_fields = ['message_type', 'delivery_status', 'sender', 'room']
    search_fields = ['content', 'sender__username']
    ordering_fields = ['created_at']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Filter messages by user access."""
        queryset = super().get_queryset()
        
        if not self.request.user.is_staff:
            # Only show messages from rooms user has access to
            accessible_rooms = WebSocketRoom.objects.filter(
                Q(require_authentication=False) |
                Q(owner=self.request.user) |
                Q(allowed_users=self.request.user)
            ).values_list('id', flat=True)
            
            queryset = queryset.filter(
                Q(sender=self.request.user) |
                Q(recipient=self.request.user) |
                Q(room__in=accessible_rooms)
            ).distinct()
        
        return queryset
    
    @action(detail=False, methods=['post'])
    def send(self, request):
        """Send a message to a room via API."""
        serializer = SendMessageSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        
        # Get room
        room = WebSocketRoom.objects.get(name=serializer.validated_data['room'])
        
        # Create message
        message = WebSocketMessage.objects.create(
            sender=request.user,
            room=room,
            message_type=serializer.validated_data['message_type'],
            content=serializer.validated_data['content'],
            metadata=serializer.validated_data.get('metadata', {}),
            delivery_status='delivered'
        )
        
        # Broadcast via channel layer
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            room.name,
            {
                'type': 'message.new',
                'message': MessageSerializer(message).data
            }
        )
        
        return Response(
            MessageSerializer(message).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=False, methods=['post'])
    def broadcast(self, request):
        """Broadcast a message to multiple targets."""
        if not request.user.is_staff:
            return Response(
                {'error': 'Admin access required'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = BroadcastMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        channel_layer = get_channel_layer()
        message_data = {
            'type': 'broadcast.message',
            'content': serializer.validated_data['content'],
            'message_type': serializer.validated_data['message_type'],
            'priority': serializer.validated_data['priority'],
            'metadata': serializer.validated_data.get('metadata', {}),
            'timestamp': timezone.now().isoformat()
        }
        
        targets = []
        
        # Broadcast to rooms
        for room_name in serializer.validated_data.get('rooms', []):
            async_to_sync(channel_layer.group_send)(room_name, message_data)
            targets.append(f'room:{room_name}')
        
        # Broadcast to users
        for user_id in serializer.validated_data.get('users', []):
            user_channel = f"notifications.user.{user_id}"
            async_to_sync(channel_layer.group_send)(user_channel, message_data)
            targets.append(f'user:{user_id}')
        
        return Response({
            'status': 'broadcast_sent',
            'targets': targets,
            'message': message_data
        })


class WebSocketStatusView(APIView):
    """WebSocket system status."""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get WebSocket system status."""
        # Get connection stats
        active_connections = WebSocketConnection.objects.filter(
            state='open'
        ).count()
        
        # Get room stats
        active_rooms = WebSocketRoom.objects.filter(
            is_active=True
        ).annotate(
            member_count=Count('websocketconnection', 
                              filter=Q(websocketconnection__state='open'))
        ).filter(member_count__gt=0).count()
        
        # Get message stats
        recent_messages = WebSocketMessage.objects.filter(
            created_at__gte=timezone.now() - timezone.timedelta(minutes=5)
        ).count()
        
        return Response({
            'status': 'operational',
            'stats': {
                'active_connections': active_connections,
                'active_rooms': active_rooms,
                'recent_messages': recent_messages,
                'channel_layer': {
                    'backend': get_channel_layer().__class__.__name__,
                    'available': True
                }
            }
        })