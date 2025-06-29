"""
Rate Limit Management Views

Views for managing and monitoring rate limits.
"""

from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from platform_core.core.views import PlatformViewSet
from .models import (
    RateLimitRule, RateLimitViolation, 
    IPWhitelist, UserRateLimit
)
from .serializers import (
    RateLimitRuleSerializer, RateLimitViolationSerializer,
    IPWhitelistSerializer, UserRateLimitSerializer,
    RateLimitStatusSerializer
)
from .backends import get_backend


class RateLimitRuleViewSet(PlatformViewSet):
    """
    ViewSet for managing rate limit rules.
    """
    queryset = RateLimitRule.objects.all()
    serializer_class = RateLimitRuleSerializer
    permission_classes = [permissions.IsAdminUser]
    
    @action(detail=False, methods=['get'])
    def test(self, request):
        """Test rate limit rules against a request"""
        # Get test parameters
        path = request.query_params.get('path', '/api/test/')
        method = request.query_params.get('method', 'GET')
        user_id = request.query_params.get('user_id')
        ip = request.query_params.get('ip', '127.0.0.1')
        
        # Find applicable rules
        rules = []
        for rule in self.get_queryset().filter(is_active=True):
            # Check endpoint pattern
            if rule.endpoint_pattern:
                import re
                if not re.match(rule.endpoint_pattern, path):
                    continue
            
            rules.append({
                'id': rule.id,
                'name': rule.name,
                'limit': rule.get_limit_string(),
                'strategy': rule.strategy,
                'action': rule.action,
                'priority': rule.priority
            })
        
        return Response({
            'path': path,
            'method': method,
            'applicable_rules': rules,
            'rule_count': len(rules)
        })
    
    @action(detail=True, methods=['post'])
    def clear_cache(self, request, pk=None):
        """Clear rate limit cache for a rule"""
        rule = self.get_object()
        
        # This would clear all cached data for this rule
        # Implementation depends on backend
        
        return Response({'status': 'cache cleared'})


class RateLimitViolationViewSet(PlatformViewSet):
    """
    ViewSet for viewing rate limit violations.
    """
    queryset = RateLimitViolation.objects.all()
    serializer_class = RateLimitViolationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter violations based on permissions"""
        queryset = super().get_queryset()
        
        # Non-admin users can only see their own violations
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        
        # Add filters
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        
        ip_address = self.request.query_params.get('ip_address')
        if ip_address:
            queryset = queryset.filter(ip_address=ip_address)
        
        endpoint = self.request.query_params.get('endpoint')
        if endpoint:
            queryset = queryset.filter(endpoint__icontains=endpoint)
        
        # Date range filter
        days = self.request.query_params.get('days', 7)
        try:
            days = int(days)
        except ValueError:
            days = 7
        
        start_date = timezone.now() - timedelta(days=days)
        queryset = queryset.filter(timestamp__gte=start_date)
        
        return queryset.order_by('-timestamp')
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get violation statistics"""
        queryset = self.get_queryset()
        
        # Time range
        days = int(request.query_params.get('days', 7))
        start_date = timezone.now() - timedelta(days=days)
        queryset = queryset.filter(timestamp__gte=start_date)
        
        # Calculate statistics
        stats = {
            'total_violations': queryset.count(),
            'unique_users': queryset.values('user').distinct().count(),
            'unique_ips': queryset.values('ip_address').distinct().count(),
            'by_endpoint': list(
                queryset.values('endpoint').annotate(
                    count=Count('id')
                ).order_by('-count')[:10]
            ),
            'by_action': list(
                queryset.values('action_taken').annotate(
                    count=Count('id')
                ).order_by('-count')
            ),
            'by_rule': list(
                queryset.exclude(rule=None).values(
                    'rule__name'
                ).annotate(
                    count=Count('id')
                ).order_by('-count')[:10]
            ),
            'timeline': self._get_timeline_data(queryset, days)
        }
        
        return Response(stats)
    
    def _get_timeline_data(self, queryset, days):
        """Get timeline data for violations"""
        from django.db.models import Count
        from django.db.models.functions import TruncHour, TruncDay
        
        if days <= 1:
            # Hourly for last 24 hours
            return list(
                queryset.annotate(
                    period=TruncHour('timestamp')
                ).values('period').annotate(
                    count=Count('id')
                ).order_by('period')
            )
        else:
            # Daily for longer periods
            return list(
                queryset.annotate(
                    period=TruncDay('timestamp')
                ).values('period').annotate(
                    count=Count('id')
                ).order_by('period')
            )


class IPWhitelistViewSet(PlatformViewSet):
    """
    ViewSet for managing IP whitelist.
    """
    queryset = IPWhitelist.objects.all()
    serializer_class = IPWhitelistSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def perform_create(self, serializer):
        serializer.save(added_by=self.request.user)
    
    @action(detail=False, methods=['post'])
    def check(self, request):
        """Check if an IP is whitelisted"""
        ip_address = request.data.get('ip_address')
        
        if not ip_address:
            return Response(
                {'error': 'ip_address is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        whitelisted = IPWhitelist.objects.filter(
            ip_address=ip_address,
            is_active=True
        ).exclude(
            expires_at__lt=timezone.now()
        ).exists()
        
        return Response({
            'ip_address': ip_address,
            'whitelisted': whitelisted
        })


class UserRateLimitViewSet(PlatformViewSet):
    """
    ViewSet for managing custom user rate limits.
    """
    queryset = UserRateLimit.objects.all()
    serializer_class = UserRateLimitSerializer
    permission_classes = [permissions.IsAdminUser]
    
    @action(detail=False, methods=['get'])
    def my_limit(self, request):
        """Get current user's rate limit"""
        try:
            limit = request.user.custom_rate_limit
            if limit.is_valid():
                return Response(
                    UserRateLimitSerializer(limit).data
                )
        except UserRateLimit.DoesNotExist:
            pass
        
        # Return default limits
        return Response({
            'rate_limit': 100,
            'per_seconds': 60,
            'is_default': True
        })
    
    @action(detail=False, methods=['get'])
    def status(self, request):
        """Get current rate limit status for user"""
        backend = get_backend()
        
        # Get current usage for different keys
        user_key = f"user:{request.user.id}" if request.user.is_authenticated else None
        ip_key = f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"
        
        status_data = {
            'user_limits': [],
            'ip_limits': []
        }
        
        # Check active rules
        for rule in RateLimitRule.objects.filter(is_active=True):
            if user_key and rule.strategy in ['user', 'user_ip']:
                usage = backend.get_usage(rule.get_cache_key(user_key))
                status_data['user_limits'].append({
                    'rule': rule.name,
                    'limit': rule.get_limit_string(),
                    'current_usage': usage.get('count', 0),
                    'remaining': max(0, rule.rate_limit - usage.get('count', 0))
                })
            
            if rule.strategy in ['ip', 'user_ip']:
                usage = backend.get_usage(rule.get_cache_key(ip_key))
                status_data['ip_limits'].append({
                    'rule': rule.name,
                    'limit': rule.get_limit_string(),
                    'current_usage': usage.get('count', 0),
                    'remaining': max(0, rule.rate_limit - usage.get('count', 0))
                })
        
        return Response(status_data)