
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import authenticate
from django.utils import timezone
from datetime import timedelta
import secrets

from .models import User, Group, GroupMembership, GuestAccess
from .serializers import (
    UserSerializer, UserCreateSerializer, GroupSerializer,
    GroupMembershipSerializer, LoginSerializer, TokenSerializer,
    GuestAccessSerializer
)
from .permissions import IsAdminOrReadOnly, RoleBasedPermission
from core.mixins import AuthenticationThrottleMixin

class CustomTokenObtainPairView(AuthenticationThrottleMixin, TokenObtainPairView):
    """Custom JWT token view with user data and strict rate limiting"""
    
    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            
            # Update last login
            user.last_login_at = timezone.now()
            user.save()
            
            # Generate tokens
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for user management"""
    queryset = User.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        """Get current user profile"""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['patch'], permission_classes=[permissions.IsAuthenticated])
    def update_profile(self, request):
        """Update current user profile"""
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class GroupViewSet(viewsets.ModelViewSet):
    """ViewSet for group management"""
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
    
    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        """Get group members"""
        group = self.get_object()
        memberships = GroupMembership.objects.filter(group=group)
        serializer = GroupMembershipSerializer(memberships, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def add_member(self, request, pk=None):
        """Add user to group"""
        group = self.get_object()
        user_id = request.data.get('user_id')
        is_admin = request.data.get('is_admin', False)
        
        try:
            user = User.objects.get(id=user_id)
            membership, created = GroupMembership.objects.get_or_create(
                user=user,
                group=group,
                defaults={'is_admin': is_admin}
            )
            
            if not created:
                return Response(
                    {'error': 'User is already a member of this group'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            serializer = GroupMembershipSerializer(membership)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['delete'])
    def remove_member(self, request, pk=None):
        """Remove user from group"""
        group = self.get_object()
        user_id = request.data.get('user_id')
        
        try:
            membership = GroupMembership.objects.get(user_id=user_id, group=group)
            membership.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        except GroupMembership.DoesNotExist:
            return Response(
                {'error': 'User is not a member of this group'},
                status=status.HTTP_404_NOT_FOUND
            )

class GuestAccessViewSet(viewsets.ModelViewSet):
    """ViewSet for guest access management"""
    queryset = GuestAccess.objects.all()
    serializer_class = GuestAccessSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]
    
    def get_queryset(self):
        """Filter by user's groups"""
        user = self.request.user
        if user.role == User.Role.ADMIN:
            return GuestAccess.objects.all()
        
        user_groups = user.groups.all()
        return GuestAccess.objects.filter(assessment__group__in=user_groups)
    
    def perform_create(self, serializer):
        """Create guest access token"""
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(days=30)  # Default 30 days
        
        serializer.save(
            token=token,
            created_by=self.request.user,
            expires_at=expires_at
        )

@api_view(['POST'])
@permission_classes([])
def guest_login(request):
    """Login with guest token"""
    token = request.data.get('token')
    
    if not token:
        return Response(
            {'error': 'Token is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        guest_access = GuestAccess.objects.get(token=token)
        
        if not guest_access.is_valid:
            return Response(
                {'error': 'Token is invalid or expired'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Update access tracking
        guest_access.accessed_count += 1
        guest_access.last_accessed_at = timezone.now()
        guest_access.save()
        
        # Return assessment data
        from assessments.serializers import AssessmentSerializer
        assessment_data = AssessmentSerializer(guest_access.assessment).data
        
        return Response({
            'assessment': assessment_data,
            'guest_access': GuestAccessSerializer(guest_access).data
        })
    
    except GuestAccess.DoesNotExist:
        return Response(
            {'error': 'Invalid token'},
            status=status.HTTP_401_UNAUTHORIZED
        )

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def logout(request):
    """Logout user"""
    try:
        refresh_token = request.data.get('refresh')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        
        return Response({'message': 'Successfully logged out'})
    except Exception:
        return Response({'message': 'Successfully logged out'})
