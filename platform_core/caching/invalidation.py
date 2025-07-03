"""
Cache Invalidation

Sophisticated cache invalidation patterns and strategies.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Set, Callable
from abc import ABC, abstractmethod
from datetime import datetime
from collections import defaultdict
import threading
from django.core.cache import cache, caches
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver

logger = logging.getLogger(__name__)


class CacheInvalidator(ABC):
    """Base cache invalidator interface."""
    
    @abstractmethod
    def invalidate(self, **kwargs) -> int:
        """Invalidate cache entries. Returns count of invalidated entries."""
        pass
    
    @abstractmethod
    def register_dependency(self, key: str, dependency: Any) -> None:
        """Register a cache key dependency."""
        pass


class TagInvalidator(CacheInvalidator):
    """Invalidate cache entries by tags."""
    
    def __init__(self, cache_alias: str = 'default'):
        self.cache = caches[cache_alias]
        self.tag_registry = defaultdict(set)
        self._lock = threading.Lock()
    
    def invalidate(self, tags: List[str]) -> int:
        """Invalidate all entries with specified tags."""
        invalidated = 0
        
        for tag in tags:
            # Get all keys for this tag
            tag_key = f"_tag_keys:{tag}"
            keys = self.cache.get(tag_key, set())
            
            # Delete all keys
            for key in keys:
                if self.cache.delete(key):
                    invalidated += 1
            
            # Clear tag registry
            self.cache.delete(tag_key)
            
            with self._lock:
                self.tag_registry.pop(tag, None)
        
        logger.info(f"Invalidated {invalidated} cache entries for tags: {tags}")
        return invalidated
    
    def register_dependency(self, key: str, tags: List[str]) -> None:
        """Register cache key with tags."""
        for tag in tags:
            # Update in-memory registry
            with self._lock:
                self.tag_registry[tag].add(key)
            
            # Update cache registry
            tag_key = f"_tag_keys:{tag}"
            keys = self.cache.get(tag_key, set())
            keys.add(key)
            self.cache.set(tag_key, keys, 86400)  # 24 hours
    
    def invalidate_by_pattern(self, tag_pattern: str) -> int:
        """Invalidate tags matching a pattern."""
        matching_tags = []
        pattern = re.compile(tag_pattern)
        
        with self._lock:
            for tag in self.tag_registry:
                if pattern.match(tag):
                    matching_tags.append(tag)
        
        return self.invalidate(matching_tags)


class PatternInvalidator(CacheInvalidator):
    """Invalidate cache entries by key patterns."""
    
    def __init__(self, cache_alias: str = 'default'):
        self.cache = caches[cache_alias]
        self.key_registry = set()
        self._lock = threading.Lock()
    
    def invalidate(self, pattern: str) -> int:
        """Invalidate all entries matching key pattern."""
        invalidated = 0
        regex = re.compile(pattern)
        
        # Get all registered keys
        with self._lock:
            keys_to_check = list(self.key_registry)
        
        # Check each key against pattern
        for key in keys_to_check:
            if regex.match(key):
                if self.cache.delete(key):
                    invalidated += 1
                    with self._lock:
                        self.key_registry.discard(key)
        
        logger.info(f"Invalidated {invalidated} cache entries matching pattern: {pattern}")
        return invalidated
    
    def register_dependency(self, key: str, **kwargs) -> None:
        """Register a cache key."""
        with self._lock:
            self.key_registry.add(key)
        
        # Also store in cache for persistence
        registry_key = "_pattern_registry"
        registry = self.cache.get(registry_key, set())
        registry.add(key)
        self.cache.set(registry_key, registry, 86400)
    
    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all keys with specific prefix."""
        return self.invalidate(f"^{re.escape(prefix)}.*")


class DependencyInvalidator(CacheInvalidator):
    """Invalidate cache based on model dependencies."""
    
    def __init__(self, cache_alias: str = 'default'):
        self.cache = caches[cache_alias]
        self.dependencies = defaultdict(lambda: defaultdict(set))
        self._lock = threading.Lock()
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Set up Django model signal handlers."""
        # These will be connected to specific models
        pass
    
    def invalidate(self, model: str, instance_id: Optional[Any] = None, 
                  operation: str = 'save') -> int:
        """Invalidate cache entries dependent on model changes."""
        invalidated = 0
        
        # Get dependent keys
        with self._lock:
            if instance_id:
                # Specific instance dependencies
                keys = self.dependencies[model][instance_id].copy()
            else:
                # All model dependencies
                keys = set()
                for deps in self.dependencies[model].values():
                    keys.update(deps)
        
        # Invalidate all dependent keys
        for key in keys:
            if self.cache.delete(key):
                invalidated += 1
        
        # Clean up dependencies
        if instance_id:
            with self._lock:
                self.dependencies[model].pop(instance_id, None)
        else:
            with self._lock:
                self.dependencies[model].clear()
        
        logger.info(
            f"Invalidated {invalidated} cache entries for "
            f"{model}:{instance_id or 'all'} on {operation}"
        )
        return invalidated
    
    def register_dependency(self, key: str, model: str, 
                          instance_id: Optional[Any] = None) -> None:
        """Register cache key dependency on model."""
        with self._lock:
            if instance_id:
                self.dependencies[model][instance_id].add(key)
            else:
                self.dependencies[model]['_all'].add(key)
        
        # Store in cache for persistence
        dep_key = f"_deps:{model}:{instance_id or '_all'}"
        deps = self.cache.get(dep_key, set())
        deps.add(key)
        self.cache.set(dep_key, deps, 86400)
    
    def register_model_signals(self, model_class):
        """Register signal handlers for a model."""
        model_name = f"{model_class._meta.app_label}.{model_class._meta.model_name}"
        
        @receiver(post_save, sender=model_class, weak=False)
        def invalidate_on_save(sender, instance, created, **kwargs):
            self.invalidate(model_name, instance.pk, 'save')
        
        @receiver(post_delete, sender=model_class, weak=False)
        def invalidate_on_delete(sender, instance, **kwargs):
            self.invalidate(model_name, instance.pk, 'delete')
            self.invalidate(model_name, None, 'delete')  # Clear model-level cache


class SmartInvalidator:
    """Intelligent cache invalidation coordinator."""
    
    def __init__(self):
        self.tag_invalidator = TagInvalidator()
        self.pattern_invalidator = PatternInvalidator()
        self.dependency_invalidator = DependencyInvalidator()
        self.invalidation_rules = []
        self._lock = threading.Lock()
    
    def add_rule(self, name: str, condition: Callable, 
                 action: Callable) -> None:
        """Add custom invalidation rule."""
        with self._lock:
            self.invalidation_rules.append({
                'name': name,
                'condition': condition,
                'action': action
            })
    
    def invalidate_smart(self, context: Dict[str, Any]) -> Dict[str, int]:
        """Apply smart invalidation based on context."""
        results = {
            'total': 0,
            'by_strategy': {}
        }
        
        # Apply custom rules
        for rule in self.invalidation_rules:
            if rule['condition'](context):
                count = rule['action'](context)
                results['by_strategy'][rule['name']] = count
                results['total'] += count
        
        # Apply standard invalidations
        if 'tags' in context:
            count = self.tag_invalidator.invalidate(context['tags'])
            results['by_strategy']['tags'] = count
            results['total'] += count
        
        if 'pattern' in context:
            count = self.pattern_invalidator.invalidate(context['pattern'])
            results['by_strategy']['pattern'] = count
            results['total'] += count
        
        if 'model' in context:
            count = self.dependency_invalidator.invalidate(
                context['model'],
                context.get('instance_id'),
                context.get('operation', 'save')
            )
            results['by_strategy']['dependency'] = count
            results['total'] += count
        
        return results
    
    def cascade_invalidation(self, initial_keys: List[str]) -> int:
        """Perform cascading invalidation based on relationships."""
        invalidated = set(initial_keys)
        to_process = list(initial_keys)
        
        while to_process:
            key = to_process.pop()
            
            # Find related keys
            related = self._find_related_keys(key)
            
            for related_key in related:
                if related_key not in invalidated:
                    invalidated.add(related_key)
                    to_process.append(related_key)
        
        # Perform actual invalidation
        count = 0
        for key in invalidated:
            if cache.delete(key):
                count += 1
        
        return count
    
    def _find_related_keys(self, key: str) -> Set[str]:
        """Find keys related to the given key."""
        related = set()
        
        # Extract components from key
        parts = key.split(':')
        if len(parts) >= 2:
            base_type = parts[0]
            entity_id = parts[1] if len(parts) > 1 else None
            
            # Add related patterns
            if base_type == 'user' and entity_id:
                related.add(f'profile:{entity_id}')
                related.add(f'permissions:{entity_id}')
                related.add(f'groups:{entity_id}')
            elif base_type == 'assessment' and entity_id:
                related.add(f'assessment_list:*')
                related.add(f'partner:*:{entity_id}')
            # Add more relationship patterns as needed
        
        return related


class InvalidationScheduler:
    """Schedule cache invalidations."""
    
    def __init__(self):
        self.scheduled_invalidations = []
        self._lock = threading.Lock()
        self._timer = None
    
    def schedule_invalidation(self, delay_seconds: int, 
                            invalidator: CacheInvalidator,
                            **kwargs) -> str:
        """Schedule an invalidation to run after delay."""
        import uuid
        
        job_id = str(uuid.uuid4())
        run_at = datetime.now() + timedelta(seconds=delay_seconds)
        
        with self._lock:
            self.scheduled_invalidations.append({
                'id': job_id,
                'run_at': run_at,
                'invalidator': invalidator,
                'kwargs': kwargs
            })
        
        # Start timer if not running
        if not self._timer or not self._timer.is_alive():
            self._start_timer()
        
        return job_id
    
    def _start_timer(self):
        """Start the invalidation timer."""
        def run_scheduled():
            while True:
                now = datetime.now()
                to_run = []
                
                with self._lock:
                    # Find jobs to run
                    self.scheduled_invalidations = [
                        job for job in self.scheduled_invalidations
                        if job['run_at'] > now or to_run.append(job) or False
                    ]
                
                # Run invalidations
                for job in to_run:
                    try:
                        job['invalidator'].invalidate(**job['kwargs'])
                    except Exception as e:
                        logger.error(f"Scheduled invalidation failed: {e}")
                
                # Sleep until next check
                time.sleep(1)
                
                # Stop if no more jobs
                with self._lock:
                    if not self.scheduled_invalidations:
                        self._timer = None
                        break
        
        self._timer = threading.Thread(target=run_scheduled, daemon=True)
        self._timer.start()


from datetime import timedelta
import time
import uuid