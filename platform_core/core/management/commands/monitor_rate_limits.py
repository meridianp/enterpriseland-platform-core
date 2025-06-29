"""
Management command to monitor rate limiting status and usage.
"""

import json
from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Count
from tabulate import tabulate

from accounts.models import Group

User = get_user_model()


class Command(BaseCommand):
    help = 'Monitor rate limiting status and usage patterns'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--scope',
            type=str,
            help='Specific scope to monitor (e.g., user, tenant, ai_agent)',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Monitor specific user by ID',
        )
        parser.add_argument(
            '--group-id',
            type=str,
            help='Monitor specific tenant/group by ID',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear rate limits for specified scope/user/group',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output in JSON format',
        )
    
    def handle(self, *args, **options):
        scope = options.get('scope')
        user_id = options.get('user_id')
        group_id = options.get('group_id')
        clear = options.get('clear')
        json_output = options.get('json')
        
        if clear:
            self.clear_rate_limits(scope, user_id, group_id)
            return
        
        # Collect rate limit data
        data = self.collect_rate_limit_data(scope, user_id, group_id)
        
        if json_output:
            self.stdout.write(json.dumps(data, indent=2))
        else:
            self.display_rate_limit_data(data)
    
    def collect_rate_limit_data(self, scope=None, user_id=None, group_id=None):
        """Collect current rate limit usage data."""
        data = {
            'timestamp': timezone.now().isoformat(),
            'scopes': {},
            'users': {},
            'groups': {},
            'ai_tokens': {},
            'upload_sizes': {}
        }
        
        # Get all cache keys
        cache_keys = []
        if hasattr(cache, '_cache'):
            # For Redis cache backend
            try:
                cache_keys = cache._cache.get_client().keys('*')
            except:
                pass
        
        # Parse rate limit keys
        for key in cache_keys:
            if isinstance(key, bytes):
                key = key.decode('utf-8')
            
            # Skip if filtering by scope
            if scope and scope not in key:
                continue
            
            # User rate limits
            if 'throttle_user_' in key:
                user_pk = key.split('throttle_user_')[-1]
                if user_id and str(user_id) != user_pk:
                    continue
                
                try:
                    user = User.objects.get(pk=user_pk)
                    history = cache.get(key, [])
                    data['users'][user.email] = {
                        'id': user.id,
                        'requests': len(history),
                        'scope': 'user'
                    }
                except User.DoesNotExist:
                    pass
            
            # Group/tenant rate limits
            elif 'throttle_tenant_' in key:
                tenant_id = key.split('throttle_tenant_')[-1]
                if group_id and str(group_id) != tenant_id:
                    continue
                
                try:
                    group = Group.objects.get(id=tenant_id)
                    history = cache.get(key, [])
                    data['groups'][group.name] = {
                        'id': str(group.id),
                        'requests': len(history),
                        'scope': 'tenant'
                    }
                except Group.DoesNotExist:
                    pass
            
            # AI token usage
            elif 'ai_tokens:' in key:
                user_pk = key.split('ai_tokens:')[-1]
                if user_id and str(user_id) != user_pk:
                    continue
                
                try:
                    user = User.objects.get(pk=user_pk)
                    tokens = cache.get(key, 0)
                    data['ai_tokens'][user.email] = {
                        'id': user.id,
                        'tokens_used': tokens
                    }
                except User.DoesNotExist:
                    pass
            
            # Upload sizes
            elif 'upload_size:' in key:
                ident = key.split('upload_size:')[-1]
                size = cache.get(key, 0)
                data['upload_sizes'][ident] = {
                    'size_bytes': size,
                    'size_mb': round(size / 1024 / 1024, 2)
                }
        
        # Add scope summaries
        for scope_name in ['user', 'anon', 'tenant', 'authentication', 'ai_agent']:
            if scope and scope != scope_name:
                continue
            
            scope_data = self.get_scope_summary(scope_name, cache_keys)
            if scope_data:
                data['scopes'][scope_name] = scope_data
        
        return data
    
    def get_scope_summary(self, scope_name, cache_keys):
        """Get summary for a specific scope."""
        count = 0
        for key in cache_keys:
            if isinstance(key, bytes):
                key = key.decode('utf-8')
            if f'throttle_{scope_name}_' in key:
                count += 1
        
        return {
            'active_limiters': count,
            'scope': scope_name
        }
    
    def display_rate_limit_data(self, data):
        """Display rate limit data in a formatted table."""
        self.stdout.write(f"\n=== Rate Limit Monitor Report ===")
        self.stdout.write(f"Timestamp: {data['timestamp']}\n")
        
        # Display scope summary
        if data['scopes']:
            self.stdout.write("\n--- Scope Summary ---")
            scope_table = []
            for scope, info in data['scopes'].items():
                scope_table.append([
                    scope,
                    info['active_limiters']
                ])
            
            if scope_table:
                headers = ['Scope', 'Active Limiters']
                self.stdout.write(tabulate(scope_table, headers=headers))
        
        # Display user rate limits
        if data['users']:
            self.stdout.write("\n\n--- User Rate Limits ---")
            user_table = []
            for email, info in data['users'].items():
                user_table.append([
                    info['id'],
                    email,
                    info['requests'],
                    info['scope']
                ])
            
            headers = ['ID', 'Email', 'Requests', 'Scope']
            self.stdout.write(tabulate(user_table, headers=headers))
        
        # Display group rate limits
        if data['groups']:
            self.stdout.write("\n\n--- Group/Tenant Rate Limits ---")
            group_table = []
            for name, info in data['groups'].items():
                group_table.append([
                    info['id'],
                    name,
                    info['requests'],
                    info['scope']
                ])
            
            headers = ['ID', 'Name', 'Requests', 'Scope']
            self.stdout.write(tabulate(group_table, headers=headers))
        
        # Display AI token usage
        if data['ai_tokens']:
            self.stdout.write("\n\n--- AI Token Usage ---")
            token_table = []
            for email, info in data['ai_tokens'].items():
                token_table.append([
                    info['id'],
                    email,
                    info['tokens_used']
                ])
            
            headers = ['ID', 'Email', 'Tokens Used']
            self.stdout.write(tabulate(token_table, headers=headers))
        
        # Display upload sizes
        if data['upload_sizes']:
            self.stdout.write("\n\n--- Upload Size Tracking ---")
            upload_table = []
            for ident, info in data['upload_sizes'].items():
                upload_table.append([
                    ident,
                    f"{info['size_mb']} MB",
                    info['size_bytes']
                ])
            
            headers = ['Identity', 'Size', 'Bytes']
            self.stdout.write(tabulate(upload_table, headers=headers))
        
        self.stdout.write("\n")
    
    def clear_rate_limits(self, scope=None, user_id=None, group_id=None):
        """Clear rate limits for specified criteria."""
        cleared_count = 0
        
        if user_id:
            # Clear specific user's limits
            user = User.objects.get(pk=user_id)
            patterns = [
                f'throttle_user_{user_id}',
                f'ai_tokens:{user_id}',
                f'upload_size:*'  # May include user's IP
            ]
            
            for pattern in patterns:
                keys = self.get_matching_keys(pattern)
                for key in keys:
                    cache.delete(key)
                    cleared_count += 1
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Cleared {cleared_count} rate limit entries for user {user.email}'
                )
            )
        
        elif group_id:
            # Clear specific group's limits
            group = Group.objects.get(id=group_id)
            key = f'throttle_tenant_{group_id}'
            if cache.delete(key):
                cleared_count = 1
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Cleared rate limits for group {group.name}'
                )
            )
        
        elif scope:
            # Clear all limits for a scope
            pattern = f'throttle_{scope}_*'
            keys = self.get_matching_keys(pattern)
            
            for key in keys:
                cache.delete(key)
                cleared_count += 1
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Cleared {cleared_count} rate limit entries for scope {scope}'
                )
            )
        
        else:
            # Clear all rate limits (use with caution!)
            if input("Clear ALL rate limits? This cannot be undone. (yes/no): ").lower() == 'yes':
                cache.clear()
                self.stdout.write(
                    self.style.SUCCESS('Cleared all cache entries including rate limits')
                )
            else:
                self.stdout.write('Operation cancelled')
    
    def get_matching_keys(self, pattern):
        """Get cache keys matching a pattern."""
        if hasattr(cache, '_cache'):
            try:
                # For Redis backend
                return cache._cache.get_client().keys(pattern)
            except:
                pass
        return []