"""
Advanced Cache Backends

Multi-tier, distributed, and edge caching backends.
"""

import time
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from django.core.cache import cache, caches
from django.core.cache.backends.base import BaseCache
from django.conf import settings
import hashlib
import pickle

logger = logging.getLogger(__name__)


class MultiTierCache(BaseCache):
    """
    Multi-tier cache backend with L1 (memory), L2 (Redis), L3 (persistent).
    """
    
    def __init__(self, location, params):
        super().__init__(params)
        
        # Configure tiers
        self.tiers = []
        tier_configs = params.get('OPTIONS', {}).get('TIERS', self._default_tiers())
        
        for tier_config in tier_configs:
            tier = {
                'cache': caches[tier_config['BACKEND']],
                'timeout_factor': tier_config.get('TIMEOUT_FACTOR', 1.0),
                'size_limit': tier_config.get('SIZE_LIMIT', None),
                'name': tier_config.get('NAME', 'unknown')
            }
            self.tiers.append(tier)
    
    def _default_tiers(self):
        """Default tier configuration."""
        return [
            {
                'NAME': 'L1-Memory',
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'TIMEOUT_FACTOR': 0.1,  # 10% of main timeout
                'SIZE_LIMIT': 1000
            },
            {
                'NAME': 'L2-Redis',
                'BACKEND': 'django_redis.cache.RedisCache',
                'TIMEOUT_FACTOR': 1.0,  # Full timeout
                'SIZE_LIMIT': None
            },
            {
                'NAME': 'L3-Database',
                'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
                'TIMEOUT_FACTOR': 10.0,  # 10x timeout
                'SIZE_LIMIT': None
            }
        ]
    
    def get(self, key, default=None, version=None):
        """Get from tiers, promoting on hit."""
        actual_key = self.make_key(key, version)
        
        for i, tier in enumerate(self.tiers):
            try:
                value = tier['cache'].get(actual_key, None)
                
                if value is not None:
                    # Promote to higher tiers
                    for j in range(i):
                        try:
                            higher_tier = self.tiers[j]
                            timeout = self._calculate_timeout(
                                self.default_timeout, 
                                higher_tier['timeout_factor']
                            )
                            higher_tier['cache'].set(actual_key, value, timeout)
                        except Exception as e:
                            logger.warning(f"Failed to promote to {higher_tier['name']}: {e}")
                    
                    return value
                    
            except Exception as e:
                logger.error(f"Error reading from {tier['name']}: {e}")
                continue
        
        return default
    
    def set(self, key, value, timeout=None, version=None):
        """Set in appropriate tiers based on value characteristics."""
        actual_key = self.make_key(key, version)
        timeout = timeout or self.default_timeout
        
        # Determine value size
        try:
            value_size = len(pickle.dumps(value))
        except:
            value_size = len(str(value))
        
        # Set in tiers based on size and timeout
        success = False
        
        for tier in self.tiers:
            # Skip if size exceeds limit
            if tier['size_limit'] and value_size > tier['size_limit']:
                continue
            
            try:
                tier_timeout = self._calculate_timeout(timeout, tier['timeout_factor'])
                tier['cache'].set(actual_key, value, tier_timeout)
                success = True
                
                # Only set in first suitable tier for large values
                if value_size > 10000:  # 10KB
                    break
                    
            except Exception as e:
                logger.error(f"Failed to set in {tier['name']}: {e}")
        
        return success
    
    def delete(self, key, version=None):
        """Delete from all tiers."""
        actual_key = self.make_key(key, version)
        deleted = False
        
        for tier in self.tiers:
            try:
                if tier['cache'].delete(actual_key):
                    deleted = True
            except Exception as e:
                logger.error(f"Failed to delete from {tier['name']}: {e}")
        
        return deleted
    
    def clear(self):
        """Clear all tiers."""
        for tier in self.tiers:
            try:
                tier['cache'].clear()
            except Exception as e:
                logger.error(f"Failed to clear {tier['name']}: {e}")
    
    def _calculate_timeout(self, base_timeout: int, factor: float) -> int:
        """Calculate tier-specific timeout."""
        return int(base_timeout * factor)


class DistributedCache(BaseCache):
    """
    Distributed cache backend with consistent hashing and replication.
    """
    
    def __init__(self, location, params):
        super().__init__(params)
        
        # Configure nodes
        self.nodes = []
        node_configs = params.get('OPTIONS', {}).get('NODES', [])
        
        for node_config in node_configs:
            node = {
                'cache': caches[node_config['BACKEND']],
                'weight': node_config.get('WEIGHT', 1),
                'name': node_config.get('NAME', 'node')
            }
            self.nodes.append(node)
        
        # Replication settings
        self.replication_factor = params.get('OPTIONS', {}).get('REPLICATION_FACTOR', 2)
        
        # Build consistent hash ring
        self._build_hash_ring()
    
    def _build_hash_ring(self):
        """Build consistent hash ring for node distribution."""
        self.ring = {}
        
        for i, node in enumerate(self.nodes):
            # Add multiple virtual nodes based on weight
            for j in range(node['weight'] * 150):  # 150 virtual nodes per weight
                virtual_key = f"{node['name']}:{j}"
                hash_value = self._hash(virtual_key)
                self.ring[hash_value] = i
        
        # Sort ring keys for binary search
        self.sorted_keys = sorted(self.ring.keys())
    
    def _hash(self, key: str) -> int:
        """Generate consistent hash for key."""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)
    
    def _get_nodes_for_key(self, key: str) -> List[int]:
        """Get node indices for key based on consistent hashing."""
        key_hash = self._hash(key)
        
        # Find first node
        primary_node = self._find_node(key_hash)
        nodes = [primary_node]
        
        # Add replica nodes
        for i in range(1, self.replication_factor):
            # Get next node in ring
            next_index = (self.sorted_keys.index(
                next(k for k in self.sorted_keys if self.ring[k] == primary_node)
            ) + i) % len(self.sorted_keys)
            
            next_node = self.ring[self.sorted_keys[next_index]]
            
            # Ensure unique nodes
            if next_node not in nodes:
                nodes.append(next_node)
        
        return nodes[:self.replication_factor]
    
    def _find_node(self, key_hash: int) -> int:
        """Find node for given hash using consistent hashing."""
        # Binary search for first key >= key_hash
        left, right = 0, len(self.sorted_keys) - 1
        
        while left <= right:
            mid = (left + right) // 2
            if self.sorted_keys[mid] < key_hash:
                left = mid + 1
            else:
                right = mid - 1
        
        # Wrap around if necessary
        if left >= len(self.sorted_keys):
            left = 0
        
        return self.ring[self.sorted_keys[left]]
    
    def get(self, key, default=None, version=None):
        """Get from distributed nodes with failover."""
        actual_key = self.make_key(key, version)
        node_indices = self._get_nodes_for_key(actual_key)
        
        # Try each node in order
        for node_idx in node_indices:
            try:
                node = self.nodes[node_idx]
                value = node['cache'].get(actual_key, None)
                
                if value is not None:
                    # Repair missing replicas in background
                    self._repair_replicas(actual_key, value, node_indices, node_idx)
                    return value
                    
            except Exception as e:
                logger.error(f"Failed to get from {node['name']}: {e}")
                continue
        
        return default
    
    def set(self, key, value, timeout=None, version=None):
        """Set on distributed nodes with replication."""
        actual_key = self.make_key(key, version)
        timeout = timeout or self.default_timeout
        node_indices = self._get_nodes_for_key(actual_key)
        
        success_count = 0
        
        for node_idx in node_indices:
            try:
                node = self.nodes[node_idx]
                if node['cache'].set(actual_key, value, timeout):
                    success_count += 1
            except Exception as e:
                logger.error(f"Failed to set on {node['name']}: {e}")
        
        # Consider success if at least one replica was set
        return success_count > 0
    
    def delete(self, key, version=None):
        """Delete from all replica nodes."""
        actual_key = self.make_key(key, version)
        node_indices = self._get_nodes_for_key(actual_key)
        
        deleted = False
        
        for node_idx in node_indices:
            try:
                node = self.nodes[node_idx]
                if node['cache'].delete(actual_key):
                    deleted = True
            except Exception as e:
                logger.error(f"Failed to delete from {node['name']}: {e}")
        
        return deleted
    
    def _repair_replicas(self, key: str, value: Any, 
                        node_indices: List[int], 
                        found_idx: int):
        """Repair missing replicas in background."""
        # This would ideally be async
        for node_idx in node_indices:
            if node_idx != found_idx:
                try:
                    node = self.nodes[node_idx]
                    node['cache'].set(key, value, self.default_timeout)
                except:
                    pass  # Best effort


class EdgeCache(BaseCache):
    """
    Edge cache backend with geographic awareness and origin fallback.
    """
    
    def __init__(self, location, params):
        super().__init__(params)
        
        # Configure edge locations
        self.edges = {}
        edge_configs = params.get('OPTIONS', {}).get('EDGES', {})
        
        for region, edge_config in edge_configs.items():
            self.edges[region] = {
                'cache': caches[edge_config['BACKEND']],
                'latency': edge_config.get('LATENCY', 10),  # ms
                'capacity': edge_config.get('CAPACITY', 1000)
            }
        
        # Origin cache
        origin_config = params.get('OPTIONS', {}).get('ORIGIN', {})
        self.origin = caches[origin_config.get('BACKEND', 'default')]
        
        # Current region (would be determined dynamically in production)
        self.current_region = params.get('OPTIONS', {}).get('REGION', 'us-east-1')
    
    def get(self, key, default=None, version=None):
        """Get from nearest edge, fallback to origin."""
        actual_key = self.make_key(key, version)
        
        # Try local edge first
        if self.current_region in self.edges:
            try:
                edge = self.edges[self.current_region]
                value = edge['cache'].get(actual_key, None)
                
                if value is not None:
                    return value
            except Exception as e:
                logger.error(f"Edge cache error in {self.current_region}: {e}")
        
        # Fallback to origin
        try:
            value = self.origin.get(actual_key, None)
            
            if value is not None:
                # Populate edge cache in background
                self._populate_edge(actual_key, value)
                return value
                
        except Exception as e:
            logger.error(f"Origin cache error: {e}")
        
        return default
    
    def set(self, key, value, timeout=None, version=None):
        """Set in origin and propagate to edges."""
        actual_key = self.make_key(key, version)
        timeout = timeout or self.default_timeout
        
        # Set in origin first
        success = False
        try:
            success = self.origin.set(actual_key, value, timeout)
        except Exception as e:
            logger.error(f"Failed to set in origin: {e}")
            return False
        
        # Propagate to edges based on value characteristics
        if success:
            self._propagate_to_edges(actual_key, value, timeout)
        
        return success
    
    def delete(self, key, version=None):
        """Delete from origin and all edges."""
        actual_key = self.make_key(key, version)
        deleted = False
        
        # Delete from origin
        try:
            if self.origin.delete(actual_key):
                deleted = True
        except Exception as e:
            logger.error(f"Failed to delete from origin: {e}")
        
        # Delete from all edges
        for region, edge in self.edges.items():
            try:
                edge['cache'].delete(actual_key)
            except Exception as e:
                logger.error(f"Failed to delete from edge {region}: {e}")
        
        return deleted
    
    def _populate_edge(self, key: str, value: Any):
        """Populate local edge cache."""
        if self.current_region in self.edges:
            try:
                edge = self.edges[self.current_region]
                edge['cache'].set(key, value, self.default_timeout)
            except:
                pass  # Best effort
    
    def _propagate_to_edges(self, key: str, value: Any, timeout: int):
        """Propagate value to edge caches based on access patterns."""
        # In production, this would be more sophisticated
        # For now, propagate to all edges for frequently accessed keys
        
        # Simple heuristic: propagate if key suggests it's commonly accessed
        if any(pattern in key for pattern in ['home', 'api', 'static', 'user:profile']):
            for region, edge in self.edges.items():
                try:
                    edge['cache'].set(key, value, timeout)
                except Exception as e:
                    logger.warning(f"Failed to propagate to edge {region}: {e}")
    
    def get_edge_stats(self) -> Dict[str, Any]:
        """Get statistics for all edge locations."""
        stats = {}
        
        for region, edge in self.edges.items():
            try:
                # Get cache statistics if available
                cache_backend = edge['cache']
                if hasattr(cache_backend, '_cache'):
                    client = cache_backend._cache.get_client()
                    info = client.info()
                    
                    stats[region] = {
                        'hits': info.get('keyspace_hits', 0),
                        'misses': info.get('keyspace_misses', 0),
                        'memory': info.get('used_memory_human', 'N/A'),
                        'keys': client.dbsize()
                    }
                else:
                    stats[region] = {'status': 'stats not available'}
                    
            except Exception as e:
                stats[region] = {'error': str(e)}
        
        return stats