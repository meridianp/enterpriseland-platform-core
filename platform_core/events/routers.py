"""
Event Routers

Provides advanced event routing and filtering capabilities.
"""

import re
import logging
from typing import Dict, Any, List, Optional, Callable, Set
from dataclasses import dataclass
from enum import Enum

from django.conf import settings

from .models import EventSubscription
from .brokers import Message
from .exceptions import EventRouterError

logger = logging.getLogger(__name__)


class MatchType(Enum):
    """Event matching types."""
    EXACT = "exact"
    PREFIX = "prefix"
    PATTERN = "pattern"
    REGEX = "regex"


@dataclass
class RouteRule:
    """Represents a routing rule."""
    
    event_types: List[str]
    match_type: MatchType
    target: str  # Queue/topic name
    filter_func: Optional[Callable[[Message], bool]] = None
    transform_func: Optional[Callable[[Message], Message]] = None
    priority: int = 0
    
    def matches(self, event_type: str) -> bool:
        """Check if event type matches this rule."""
        if self.match_type == MatchType.EXACT:
            return event_type in self.event_types
        
        elif self.match_type == MatchType.PREFIX:
            return any(
                event_type.startswith(prefix) 
                for prefix in self.event_types
            )
        
        elif self.match_type == MatchType.PATTERN:
            # Use wildcard patterns (e.g., "user.*", "*.created")
            for pattern in self.event_types:
                regex_pattern = pattern.replace('.', r'\.').replace('*', '.*')
                if re.match(f"^{regex_pattern}$", event_type):
                    return True
            return False
        
        elif self.match_type == MatchType.REGEX:
            return any(
                re.match(pattern, event_type) 
                for pattern in self.event_types
            )
        
        return False
    
    def should_route(self, message: Message) -> bool:
        """Check if message should be routed by this rule."""
        # Check event type match
        if not self.matches(message.event_type):
            return False
        
        # Apply filter function if provided
        if self.filter_func:
            try:
                return self.filter_func(message)
            except Exception as e:
                logger.error(f"Filter function error: {e}")
                return False
        
        return True
    
    def transform_message(self, message: Message) -> Message:
        """Transform message if transform function provided."""
        if self.transform_func:
            try:
                return self.transform_func(message)
            except Exception as e:
                logger.error(f"Transform function error: {e}")
        
        return message


class EventRouter:
    """Routes events to appropriate destinations."""
    
    def __init__(self):
        self.rules: List[RouteRule] = []
        self._load_default_rules()
    
    def _load_default_rules(self):
        """Load default routing rules from settings."""
        default_rules = getattr(settings, 'EVENT_ROUTING_RULES', [])
        
        for rule_config in default_rules:
            self.add_rule(
                event_types=rule_config['event_types'],
                match_type=MatchType(rule_config.get('match_type', 'exact')),
                target=rule_config['target'],
                priority=rule_config.get('priority', 0)
            )
    
    def add_rule(self,
                 event_types: List[str],
                 target: str,
                 match_type: MatchType = MatchType.EXACT,
                 filter_func: Optional[Callable] = None,
                 transform_func: Optional[Callable] = None,
                 priority: int = 0) -> RouteRule:
        """Add a routing rule."""
        rule = RouteRule(
            event_types=event_types,
            match_type=match_type,
            target=target,
            filter_func=filter_func,
            transform_func=transform_func,
            priority=priority
        )
        
        self.rules.append(rule)
        
        # Sort rules by priority (highest first)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        
        return rule
    
    def remove_rule(self, rule: RouteRule):
        """Remove a routing rule."""
        if rule in self.rules:
            self.rules.remove(rule)
    
    def route(self, message: Message) -> List[str]:
        """
        Route message and return list of targets.
        
        Args:
            message: Message to route
            
        Returns:
            List of target queues/topics
        """
        targets = []
        
        for rule in self.rules:
            if rule.should_route(message):
                # Transform message if needed
                transformed = rule.transform_message(message)
                
                # Add target if not already added
                if rule.target not in targets:
                    targets.append(rule.target)
                
                logger.debug(
                    f"Message {message.id} matched rule for {rule.target}"
                )
        
        # If no rules matched, use default routing
        if not targets:
            targets = self._get_default_targets(message)
        
        return targets
    
    def _get_default_targets(self, message: Message) -> List[str]:
        """Get default targets for unmatched messages."""
        # Check for active subscriptions
        subscriptions = EventSubscription.objects.filter(
            event_types__contains=[message.event_type],
            is_active=True,
            is_paused=False
        )
        
        targets = [sub.endpoint for sub in subscriptions]
        
        # Add default queue if configured
        default_queue = getattr(settings, 'EVENT_DEFAULT_QUEUE', None)
        if default_queue and default_queue not in targets:
            targets.append(default_queue)
        
        return targets


class ContentBasedRouter(EventRouter):
    """Routes events based on message content."""
    
    def add_content_rule(self,
                         field_path: str,
                         operator: str,
                         value: Any,
                         target: str,
                         priority: int = 0):
        """
        Add content-based routing rule.
        
        Args:
            field_path: Path to field in message data (e.g., "user.role")
            operator: Comparison operator (eq, ne, gt, lt, gte, lte, in, contains)
            value: Value to compare against
            target: Target queue/topic
            priority: Rule priority
        """
        def content_filter(message: Message) -> bool:
            try:
                # Navigate to field value
                field_value = self._get_field_value(message.data, field_path)
                
                # Apply operator
                if operator == 'eq':
                    return field_value == value
                elif operator == 'ne':
                    return field_value != value
                elif operator == 'gt':
                    return field_value > value
                elif operator == 'lt':
                    return field_value < value
                elif operator == 'gte':
                    return field_value >= value
                elif operator == 'lte':
                    return field_value <= value
                elif operator == 'in':
                    return field_value in value
                elif operator == 'contains':
                    return value in field_value
                else:
                    logger.warning(f"Unknown operator: {operator}")
                    return False
                    
            except Exception as e:
                logger.error(f"Content filter error: {e}")
                return False
        
        # Add rule with content filter
        self.add_rule(
            event_types=['*'],  # Apply to all events
            target=target,
            match_type=MatchType.PATTERN,
            filter_func=content_filter,
            priority=priority
        )
    
    def _get_field_value(self, data: Dict[str, Any], path: str) -> Any:
        """Get nested field value from data."""
        parts = path.split('.')
        value = data
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        
        return value


class TopicRouter(EventRouter):
    """Routes events to topic exchanges with pattern matching."""
    
    def __init__(self):
        super().__init__()
        self.topic_patterns: Dict[str, Set[str]] = {}
    
    def add_topic_binding(self, pattern: str, queue: str):
        """
        Add topic binding pattern.
        
        Args:
            pattern: Topic pattern (e.g., "order.*.shipped", "#.error")
            queue: Target queue
        """
        if pattern not in self.topic_patterns:
            self.topic_patterns[pattern] = set()
        
        self.topic_patterns[pattern].add(queue)
        
        # Convert topic pattern to regex
        regex_pattern = pattern.replace('.', r'\.').replace('*', '[^.]+').replace('#', '.*')
        
        # Add as routing rule
        self.add_rule(
            event_types=[f"^{regex_pattern}$"],
            target=queue,
            match_type=MatchType.REGEX
        )
    
    def remove_topic_binding(self, pattern: str, queue: str):
        """Remove topic binding."""
        if pattern in self.topic_patterns:
            self.topic_patterns[pattern].discard(queue)
            
            if not self.topic_patterns[pattern]:
                del self.topic_patterns[pattern]


class FanoutRouter(EventRouter):
    """Routes events to all subscribers (fanout pattern)."""
    
    def __init__(self):
        super().__init__()
        self.fanout_groups: Dict[str, Set[str]] = {}
    
    def add_to_fanout_group(self, group: str, queue: str):
        """Add queue to fanout group."""
        if group not in self.fanout_groups:
            self.fanout_groups[group] = set()
        
        self.fanout_groups[group].add(queue)
    
    def remove_from_fanout_group(self, group: str, queue: str):
        """Remove queue from fanout group."""
        if group in self.fanout_groups:
            self.fanout_groups[group].discard(queue)
            
            if not self.fanout_groups[group]:
                del self.fanout_groups[group]
    
    def fanout_to_group(self, message: Message, group: str) -> List[str]:
        """Get all queues in fanout group."""
        return list(self.fanout_groups.get(group, []))


class CompositeRouter:
    """Combines multiple routers for complex routing scenarios."""
    
    def __init__(self):
        self.routers: List[EventRouter] = []
    
    def add_router(self, router: EventRouter):
        """Add a router to the composite."""
        self.routers.append(router)
    
    def remove_router(self, router: EventRouter):
        """Remove a router from the composite."""
        if router in self.routers:
            self.routers.remove(router)
    
    def route(self, message: Message) -> List[str]:
        """Route message through all routers and combine results."""
        all_targets = set()
        
        for router in self.routers:
            targets = router.route(message)
            all_targets.update(targets)
        
        return list(all_targets)


# Example usage patterns
def create_application_router() -> CompositeRouter:
    """Create a composite router for the application."""
    composite = CompositeRouter()
    
    # Basic event router
    basic_router = EventRouter()
    basic_router.add_rule(
        event_types=['user.created', 'user.updated'],
        target='user-events-queue'
    )
    basic_router.add_rule(
        event_types=['order.*'],
        target='order-events-queue',
        match_type=MatchType.PATTERN
    )
    
    # Content-based router
    content_router = ContentBasedRouter()
    content_router.add_content_rule(
        field_path='priority',
        operator='eq',
        value='high',
        target='high-priority-queue'
    )
    content_router.add_content_rule(
        field_path='amount',
        operator='gt',
        value=1000,
        target='large-transactions-queue'
    )
    
    # Topic router
    topic_router = TopicRouter()
    topic_router.add_topic_binding('*.error', 'error-queue')
    topic_router.add_topic_binding('payment.#', 'payment-queue')
    
    # Add all routers to composite
    composite.add_router(basic_router)
    composite.add_router(content_router)
    composite.add_router(topic_router)
    
    return composite