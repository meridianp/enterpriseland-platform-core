"""
Views for API Key management.

Provides REST API endpoints for creating, viewing, rotating, and revoking API keys.
"""

from datetime import timedelta
from typing import Dict, Any

from django.contrib.auth import get_user_model
from django.db.models import Count, Avg, Q, F
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models import AuditLog
from .models import APIKey, APIKeyUsage
from .serializers import (
    APIKeyCreateSerializer,
    APIKeySerializer,
    APIKeyListSerializer,
    APIKeyUpdateSerializer,
    APIKeyRotateSerializer,
    APIKeyUsageSerializer,
    APIKeyUsageStatsSerializer,
    APIKeyResponseSerializer
)

User = get_user_model()


class APIKeyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing API keys.
    
    Supports:
    - Creating new API keys
    - Listing user's API keys
    - Viewing key details
    - Updating key settings
    - Rotating keys
    - Revoking keys
    - Viewing usage statistics
    """
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter keys based on user permissions."""
        user = self.request.user
        
        # Admin can see all keys
        if user.role == User.Role.ADMIN:
            queryset = APIKey.objects.all()
        else:
            # Users can only see their own keys
            queryset = APIKey.objects.filter(user=user)
        
        # Apply filters
        if self.action == 'list':
            # Filter by status
            is_active = self.request.query_params.get('is_active')
            if is_active is not None:
                queryset = queryset.filter(is_active=is_active.lower() == 'true')
            
            # Filter by expiration
            expires_soon = self.request.query_params.get('expires_soon')
            if expires_soon:
                days = int(expires_soon)
                queryset = queryset.expiring_soon(days=days)
            
            # Filter by type
            key_type = self.request.query_params.get('key_type')
            if key_type == 'user':
                queryset = queryset.filter(application_name='')
            elif key_type == 'application':
                queryset = queryset.exclude(application_name='')
        
        return queryset.select_related('user', 'group', 'replaced_by')
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'create':
            return APIKeyCreateSerializer
        elif self.action == 'list':
            return APIKeyListSerializer
        elif self.action in ['update', 'partial_update']:
            return APIKeyUpdateSerializer
        elif self.action == 'rotate':
            return APIKeyRotateSerializer
        elif self.action == 'usage':
            return APIKeyUsageSerializer
        elif self.action == 'stats':
            return APIKeyUsageStatsSerializer
        else:
            return APIKeySerializer
    
    def create(self, request, *args, **kwargs):
        """Create a new API key."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get the user's group (assuming single group membership)
        group = None
        if request.user.groups.exists():
            group = request.user.groups.first()
        
        # Create the API key
        api_key, raw_key = APIKey.objects.create_key(
            user=request.user,
            group=group,
            **serializer.validated_data
        )
        
        # Prepare response
        response_data = {
            'api_key': APIKeySerializer(api_key).data,
            'key': raw_key,
            'message': (
                "API key created successfully. "
                "Please store the key securely - it won't be shown again."
            )
        }
        
        return Response(
            APIKeyResponseSerializer(response_data).data,
            status=status.HTTP_201_CREATED
        )
    
    def update(self, request, *args, **kwargs):
        """Update API key settings."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # Check ownership
        if instance.user != request.user and request.user.role != User.Role.ADMIN:
            raise PermissionDenied("You can only update your own API keys")
        
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        # Log the update
        old_values = {
            field: getattr(instance, field)
            for field in serializer.validated_data.keys()
        }
        
        self.perform_update(serializer)
        
        # Create audit log
        changes = {
            field: {'old': old_values[field], 'new': value}
            for field, value in serializer.validated_data.items()
            if old_values[field] != value
        }
        
        if changes:
            AuditLog.objects.create_log(
                action=AuditLog.Action.UPDATE,
                user=request.user,
                content_object=instance,
                changes=changes
            )
        
        return Response(APIKeySerializer(instance).data)
    
    def destroy(self, request, *args, **kwargs):
        """Revoke an API key."""
        instance = self.get_object()
        
        # Check ownership
        if instance.user != request.user and request.user.role != User.Role.ADMIN:
            raise PermissionDenied("You can only revoke your own API keys")
        
        # Don't actually delete, just revoke
        reason = request.data.get('reason', 'User requested revocation')
        instance.revoke(user=request.user, reason=reason)
        
        return Response(
            {'message': 'API key revoked successfully'},
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['post'])
    def rotate(self, request, pk=None):
        """
        Rotate an API key.
        
        Creates a new key with the same settings and optionally revokes the old one.
        """
        instance = self.get_object()
        
        # Check ownership
        if instance.user != request.user and request.user.role != User.Role.ADMIN:
            raise PermissionDenied("You can only rotate your own API keys")
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create new key
        new_key, raw_key = instance.rotate(user=request.user)
        
        # Handle old key based on settings
        overlap_hours = serializer.validated_data.get('overlap_hours', 24)
        revoke_immediately = serializer.validated_data.get('revoke_old_key', False)
        
        if revoke_immediately:
            instance.revoke(user=request.user, reason='Rotated')
        elif overlap_hours > 0:
            # Schedule revocation for later
            instance.expires_at = timezone.now() + timedelta(hours=overlap_hours)
            instance.save(update_fields=['expires_at'])
        
        # Prepare response
        response_data = {
            'api_key': APIKeySerializer(new_key).data,
            'key': raw_key,
            'message': (
                f"API key rotated successfully. "
                f"Old key will remain active for {overlap_hours} hours. "
                "Please store the new key securely."
            )
        }
        
        return Response(
            APIKeyResponseSerializer(response_data).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['get'])
    def usage(self, request, pk=None):
        """Get usage logs for an API key."""
        instance = self.get_object()
        
        # Check ownership
        if instance.user != request.user and request.user.role != User.Role.ADMIN:
            raise PermissionDenied("You can only view usage for your own API keys")
        
        # Get usage logs with filters
        queryset = instance.usage_logs.all()
        
        # Filter by date range
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        
        # Filter by status
        status_code = request.query_params.get('status_code')
        if status_code:
            queryset = queryset.filter(status_code=status_code)
        
        # Paginate
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Get usage statistics for an API key."""
        instance = self.get_object()
        
        # Check ownership
        if instance.user != request.user and request.user.role != User.Role.ADMIN:
            raise PermissionDenied("You can only view stats for your own API keys")
        
        # Get date range
        days = int(request.query_params.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        # Get usage logs
        usage_logs = instance.usage_logs.filter(timestamp__gte=start_date)
        
        # Calculate statistics
        total_requests = usage_logs.count()
        successful_requests = usage_logs.filter(
            status_code__gte=200, status_code__lt=300
        ).count()
        failed_requests = total_requests - successful_requests
        
        # Average response time
        avg_response_time = usage_logs.aggregate(
            avg=Avg('response_time_ms')
        )['avg'] or 0
        
        # Unique IPs
        unique_ips = usage_logs.values('ip_address').distinct().count()
        
        # Top endpoints
        top_endpoints = usage_logs.values('endpoint', 'method').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        # Requests by hour (last 24 hours)
        last_24h = timezone.now() - timedelta(hours=24)
        hourly_stats = []
        
        for i in range(24):
            hour_start = last_24h + timedelta(hours=i)
            hour_end = hour_start + timedelta(hours=1)
            count = usage_logs.filter(
                timestamp__gte=hour_start,
                timestamp__lt=hour_end
            ).count()
            hourly_stats.append({
                'hour': hour_start.strftime('%Y-%m-%d %H:00'),
                'requests': count
            })
        
        # Error rate
        error_rate = (failed_requests / total_requests * 100) if total_requests > 0 else 0
        
        stats = {
            'total_requests': total_requests,
            'successful_requests': successful_requests,
            'failed_requests': failed_requests,
            'average_response_time_ms': avg_response_time,
            'unique_ips': unique_ips,
            'top_endpoints': list(top_endpoints),
            'requests_by_hour': hourly_stats,
            'error_rate': error_rate
        }
        
        serializer = self.get_serializer(stats)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def expiring(self, request):
        """Get API keys expiring soon."""
        days = int(request.query_params.get('days', 7))
        
        queryset = self.get_queryset().expiring_soon(days=days)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = APIKeyListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = APIKeyListSerializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get active API keys."""
        queryset = self.get_queryset().active()
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = APIKeyListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = APIKeyListSerializer(queryset, many=True)
        return Response(serializer.data)
